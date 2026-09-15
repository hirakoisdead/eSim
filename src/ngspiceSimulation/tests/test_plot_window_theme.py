"""Regression tests for the apply_theme re-entrancy guard.

setStyleSheet() synchronously dispatches a QEvent.PaletteChange. Before the
guard, changeEvent re-called apply_theme on that event, which called
setStyleSheet again — an unbounded recursion that blew Python's recursion
limit (surfacing as a RecursionError deep in a canvas sizeHint/numpy
reduction) or, with cheaper frames, spun long enough to freeze the GUI.
Constructing the widget at all exercises the loop, since __init__ calls
apply_theme.
"""
import os
import time

import numpy as np
import pytest

from matplotlib.colors import to_rgba

from PyQt6.QtCore import QEvent, QEventLoop

from ngspiceSimulation import plot_window as pw_mod
from ngspiceSimulation._palette import _DARK_DEFAULTS, _LIGHT_DEFAULTS
from ngspiceSimulation.plot_window import plotWindow


def _write_tran_project(d: str, npts: int = 32, nnodes: int = 2) -> None:
    with open(os.path.join(d, "analysis"), "w") as f:
        f.write(".tran 1e-6 1e-3 0\n")
    t = np.linspace(0, 1e-3, npts)
    cols = [np.sin(2 * np.pi * (50 + 10 * k) * t) for k in range(nnodes)]
    names = [f"net{k}" for k in range(nnodes)]
    with open(os.path.join(d, "plot_data_v.txt"), "w") as f:
        f.write("Index   time   " + "   ".join(names) + "\n")
        f.write("-" * 40 + "\n")
        M = np.column_stack([np.arange(npts), t] + cols)
        np.savetxt(f, M, fmt=["%d"] + ["%.9g"] * (nnodes + 1), delimiter="\t")
    open(os.path.join(d, "plot_data_i.txt"), "w").close()


def _repaint(qapp, plot_window, ms=250):
    """Deliver a PaletteChange and let the DEFERRED restyle run.

    The handler no longer re-themes inline: doing that from inside the app-wide
    repolish re-entered Qt's style engine and was crashing eSim natively
    (theme_utils.defer_restyle). The work is queued to the next event-loop tick
    instead, so the tests have to turn the loop before asserting.
    """
    qapp.sendEvent(plot_window, QEvent(QEvent.Type.PaletteChange))
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


@pytest.fixture
def plot_window(qapp, tmp_path):
    _write_tran_project(str(tmp_path))
    w = plotWindow(str(tmp_path), "proj")
    yield w
    w.close()


def test_construction_does_not_recurse(plot_window):
    # Reaching here means __init__ -> apply_theme -> setStyleSheet ->
    # PaletteChange -> ... did not recurse into a RecursionError.
    assert plot_window._applying_theme is False


def test_palette_change_reapplies_theme_once(qapp, plot_window, monkeypatch):
    """A single PaletteChange must run the theme body exactly once.

    Without the guard the self-induced PaletteChange from setStyleSheet would
    re-enter the body cascade-style; the guard collapses it to one pass.
    """
    calls = {"n": 0}
    orig = plotWindow._apply_theme_impl

    def counting_impl(self):
        calls["n"] += 1
        return orig(self)

    monkeypatch.setattr(plotWindow, "_apply_theme_impl", counting_impl)
    _repaint(qapp, plot_window)
    assert calls["n"] == 1
    assert plot_window._applying_theme is False


def test_palette_change_restyle_is_deferred(qapp, plot_window, monkeypatch):
    """The native-crash fix: the restyle must NOT run inside the handler.

    A PaletteChange is delivered from inside the app-wide repolish that
    QApplication.setStyleSheet() runs. Re-theming there (our own setStyleSheet,
    the nav toolbar's setPalette, a canvas redraw) re-enters Qt's style engine
    while it is still walking a snapshot of the widget tree -- the window eSim
    was dying in with a 0xC0000005 on a zoom change. The work has to land one
    event-loop tick later instead.
    """
    calls = {"n": 0}
    orig = plotWindow._apply_theme_impl

    def counting_impl(self):
        calls["n"] += 1
        return orig(self)

    monkeypatch.setattr(plotWindow, "_apply_theme_impl", counting_impl)
    qapp.sendEvent(plot_window, QEvent(QEvent.Type.PaletteChange))
    assert calls["n"] == 0, "re-themed INSIDE the polish that delivered the event"

    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    assert calls["n"] == 1, "deferred restyle never ran"


def test_palette_change_storm_collapses_to_one_restyle(qapp, plot_window,
                                                       monkeypatch):
    """A burst of palette events (what holding the zoom pill produces) must
    coalesce into a single restyle, not one repolish per event."""
    calls = {"n": 0}
    orig = plotWindow._apply_theme_impl

    def counting_impl(self):
        calls["n"] += 1
        return orig(self)

    monkeypatch.setattr(plotWindow, "_apply_theme_impl", counting_impl)
    for _ in range(8):
        qapp.sendEvent(plot_window, QEvent(QEvent.Type.PaletteChange))
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    assert calls["n"] == 1, f"8 palette events ran {calls['n']} restyles"


def _render_with_grid(w):
    """Put a couple of traces on screen with the grid on so the retheme walk
    has live gridline / tick / spine artists to recolor."""
    w.grid_check.setChecked(True)
    w.select_all_waveforms()
    w.refresh_plot()


def test_palette_change_rethemes_live_artists(qapp, plot_window, monkeypatch):
    """The reported bug: after a live dark<->light toggle the already-drawn
    matplotlib artists (grid, ticks, labels) and the nav-toolbar icons kept the
    old theme. _retheme_canvas must walk them in place on PaletteChange."""
    _render_with_grid(plot_window)
    ax = plot_window.fig.axes[0]
    assert ax.get_xgridlines(), "no gridlines rendered — test setup failed"

    # Capture a toolbar icon identity before the flip so we can prove it was
    # rebuilt (mpl tints icons once at construction and never re-tints).
    home = plot_window.nav_toolbar._actions.get("home")
    key_before = home.icon().cacheKey() if home is not None else None

    # Flip the palette the widget will read on the next PaletteChange.
    dark = dict(_DARK_DEFAULTS)
    monkeypatch.setattr(pw_mod, "current_palette", lambda *a, **k: dark)
    _repaint(qapp, plot_window)

    gl = plot_window.fig.axes[0].get_xgridlines()[0]
    assert to_rgba(gl.get_color()) == to_rgba(dark["grid_color"])
    tick = plot_window.fig.axes[0].get_yticklabels()[0]
    assert to_rgba(tick.get_color()) == to_rgba(dark["tick_color"])
    assert to_rgba(plot_window.fig.get_facecolor()) == to_rgba(dark["bg"])

    if home is not None:
        assert not home.icon().isNull()
        assert home.icon().cacheKey() != key_before  # icon was rebuilt


def test_fresh_dark_render_uses_palette_tokens(qapp, tmp_path, monkeypatch):
    """The _render_mixin literal fixes: a FRESH render under dark theme must use
    palette tokens, not the old baked light literals (white legend / #444444
    stats), so the surface is right even with no toggle."""
    dark = dict(_DARK_DEFAULTS)
    monkeypatch.setattr(pw_mod, "current_palette", lambda *a, **k: dark)
    _write_tran_project(str(tmp_path))
    w = plotWindow(str(tmp_path), "proj")
    try:
        w.legend_check.setChecked(True)
        w.stats_check.setChecked(True)
        w.select_all_waveforms()
        w.refresh_plot()

        leg = w.fig.axes[0].get_legend()
        if leg is not None:  # normal view draws a combined legend
            # RGB only — framealpha=0.95 sets the 4th channel, not the color.
            assert to_rgba(leg.get_frame().get_facecolor())[:3] == to_rgba(dark["legend_face"])[:3]
            assert to_rgba(leg.get_frame().get_edgecolor())[:3] == to_rgba(dark["legend_edge"])[:3]
    finally:
        w.close()


def _mean_glyph_lum(icon, size=24):
    """Mean luminance of the icon's opaque glyph pixels (edges excluded)."""
    img = icon.pixmap(size, size).toImage()
    lums = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                lums.append(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
    assert lums, "icon has no opaque pixels — glyph missing"
    return sum(lums) / len(lums)


def test_toggle_retints_toolbar_glyphs(qapp, plot_window, monkeypatch):
    """Pixel-truth regression for the invisible-icons bug. cacheKey()-changed
    was not enough: mpl's _icon() tints from the TOOLBAR's palette, which mid-
    repolish still held the OLD theme, so the rebuilt icons came out the old
    color (white on white after dark->light). The fix forces the toolbar
    palette from self._palette before tinting; assert the actual glyph color
    flips both ways."""
    _render_with_grid(plot_window)
    home = plot_window.nav_toolbar._actions.get("home")
    assert home is not None

    dark = dict(_DARK_DEFAULTS)
    monkeypatch.setattr(pw_mod, "current_palette", lambda *a, **k: dark)
    _repaint(qapp, plot_window)
    assert _mean_glyph_lum(home.icon()) > 150, "dark theme glyph not light"

    light = dict(_LIGHT_DEFAULTS)
    monkeypatch.setattr(pw_mod, "current_palette", lambda *a, **k: light)
    _repaint(qapp, plot_window)
    assert _mean_glyph_lum(home.icon()) < 100, "light theme glyph not dark"

    # Figure-options button: _icon() needs the '.png' extension; extensionless
    # resolved to a nonexistent path and a null pixmap.
    assert not plot_window._fig_btn.icon().isNull()
    _mean_glyph_lum(plot_window._fig_btn.icon())


def test_light_first_then_dark_toolbar_visible(qapp, plot_window, monkeypatch):
    """Symmetry: build light, toggle dark — every nav-toolbar action keeps a
    non-null (rebuilt) icon, i.e. glyphs never vanish across a toggle."""
    _render_with_grid(plot_window)
    dark = dict(_DARK_DEFAULTS)
    monkeypatch.setattr(pw_mod, "current_palette", lambda *a, **k: dark)
    _repaint(qapp, plot_window)
    for name, act in plot_window.nav_toolbar._actions.items():
        assert not act.icon().isNull(), f"toolbar icon {name!r} went null"
