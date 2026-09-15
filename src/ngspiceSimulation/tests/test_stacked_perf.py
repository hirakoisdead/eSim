"""Performance-path regression tests for the plotting module.

Covers the three stacked-view optimisations:

1. minmax_decimate — peak-preserving draw-time decimation of long traces.
2. The incremental stacked refresh — a visibility toggle must reuse the
   surviving panes' Axes objects instead of fig.clear()-rebuilding the stack.
3. The per-trace stats cache — the p-p/DC/RMS overlay is O(points) to
   compute and must not be recomputed on every rebuild.
"""
import os
import pathlib

import numpy as np
import pytest

from ngspiceSimulation.constants import MAX_STACKED_GAP_RATIO
from ngspiceSimulation.math_utils import minmax_decimate
from ngspiceSimulation.plot_window import plotWindow


@pytest.fixture(autouse=True)
def isolated_plot_config(tmp_path, monkeypatch):
    """Point ~/.pythonPlotting at a per-test dir.

    plotWindow.save_config() runs on close and persists stacked pane order /
    stats visibility by trace NAME; with the shared real config each test
    would hydrate the previous test's layout (same net0..netN names) and the
    assertions would see polluted pane state.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setattr(pathlib.Path, "home",
                        classmethod(lambda cls: fake_home))


# ── minmax_decimate ──────────────────────────────────────────────────────

def test_decimate_small_input_passthrough():
    x = np.linspace(0, 1, 100)
    y = np.sin(x)
    xd, yd = minmax_decimate(x, y, 2000)
    assert len(xd) == 100 and len(yd) == 100
    assert np.array_equal(xd, x) and np.array_equal(yd, y)


def test_decimate_reduces_and_preserves_envelope():
    rng = np.random.default_rng(42)
    n = 100_000
    x = np.linspace(0, 1e-3, n)
    y = np.sin(2 * np.pi * 5e4 * x) + 0.01 * rng.standard_normal(n)
    # Bury a single-sample glitch — the whole point of min/max decimation
    # is that this spike must survive.
    y[31_337] = 50.0
    y[62_000] = -50.0
    xd, yd = minmax_decimate(x, y, 2000)
    assert len(xd) < n // 10
    assert float(np.max(yd)) == 50.0
    assert float(np.min(yd)) == -50.0
    # True endpoints kept so the drawn x-span matches the raw data.
    assert xd[0] == x[0]
    assert xd[-1] == x[-1]
    # Monotonic x stays monotonic (points emitted in sample order).
    assert np.all(np.diff(xd) >= 0)


def test_decimate_constant_signal():
    x = np.arange(50_000, dtype=float)
    y = np.full(50_000, 3.3)
    xd, yd = minmax_decimate(x, y, 1000)
    assert len(xd) < 10_000
    assert np.all(yd == 3.3)


# ── plotWindow integration fixtures ──────────────────────────────────────

def _write_tran_project(d: str, npts: int, nnodes: int) -> None:
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


@pytest.fixture
def stacked_window(qapp, tmp_path):
    """Six-signal transient project switched into stacked view."""
    _write_tran_project(str(tmp_path), npts=64, nnodes=6)
    w = plotWindow(str(tmp_path), "proj")
    for t in w.traces.values():
        t.visible = True
    w.radio_stacked.setChecked(True)
    w.refresh_plot()
    yield w
    w.close()


# ── incremental stacked refresh ──────────────────────────────────────────

def test_stacked_hide_reuses_surviving_axes(stacked_window):
    w = stacked_window
    assert len(w.panes) == 6
    assert w._stacked_pane_keys == [('t', i) for i in range(6)]
    survivors = {k: ax for k, ax in zip(w._stacked_pane_keys, w.panes)}

    w.traces[2].visible = False
    w.refresh_plot()

    assert len(w.panes) == 5
    assert ('t', 2) not in w._stacked_pane_keys
    # Every surviving pane must be the SAME Axes object as before the toggle.
    for k, ax in zip(w._stacked_pane_keys, w.panes):
        assert ax is survivors[k]


def test_stacked_show_adds_only_new_pane(stacked_window):
    w = stacked_window
    w.traces[5].visible = False
    w.refresh_plot()
    before = {k: ax for k, ax in zip(w._stacked_pane_keys, w.panes)}
    assert len(w.panes) == 5

    w.traces[5].visible = True
    w.refresh_plot()

    assert len(w.panes) == 6
    assert ('t', 5) in w._stacked_pane_keys
    for k, ax in zip(w._stacked_pane_keys, w.panes):
        if k in before:
            assert ax is before[k]
    # The re-shown trace got a fresh line on a fresh pane.
    assert w.traces[5].line_object is not None
    assert w.traces[5].line_object.axes is w.panes[-1]


def test_stacked_hidden_trace_line_cleared(stacked_window):
    w = stacked_window
    w.traces[0].visible = False
    w.refresh_plot()
    assert w.traces[0].line_object is None


def test_stacked_incremental_declines_on_stats_toggle(stacked_window):
    w = stacked_window
    old_panes = list(w.panes)
    w.stats_check.setChecked(True)
    w.traces[1].visible = False
    w._force_full_refresh = True  # what the stats handler path implies
    w.refresh_plot()
    # Full rebuild: all axes are new objects.
    assert all(ax not in old_panes for ax in w.panes)


def test_stacked_incremental_keeps_bottom_xlabel(stacked_window):
    w = stacked_window
    assert w.panes[-1].get_xlabel() != ''
    label = w.panes[-1].get_xlabel()
    # Hide the bottom signal: a kept pane becomes the new bottom row.
    w.traces[5].visible = False
    w.refresh_plot()
    assert w.panes[-1].get_xlabel() == label
    for ax in w.panes[:-1]:
        assert ax.get_xlabel() == ''


def test_stacked_pane_reorder_still_full_refresh(stacked_window):
    """_move_pane sets _force_full_refresh; the incremental path must not
    swallow it (the signature can't see order changes)."""
    w = stacked_window
    old0 = w.panes[0]
    w._move_pane(0, +1)
    assert w._stacked_pane_keys[0] == ('t', 1)
    assert w._stacked_pane_keys[1] == ('t', 0)
    assert w.panes[0] is not old0


def _pane_geometry_px(w):
    """(smallest pane height, largest inter-pane gap) in device pixels."""
    fig_h = w.fig.get_size_inches()[1] * w.fig.dpi
    pos = [ax.get_position() for ax in w.panes]
    panes = [(p.y1 - p.y0) * fig_h for p in pos]
    gaps = [(pos[i].y0 - pos[i + 1].y1) * fig_h for i in range(len(pos) - 1)]
    return min(panes), (max(gaps) if gaps else 0.0)


def test_stacked_incremental_adds_keep_pane_height(qapp, tmp_path):
    """Adding waveforms one at a time must not starve the panes.

    The incremental path reuses the inter-pane gap solved for the previous
    (smaller) pane count. Left unbounded that gap keeps its absolute size
    while the panes it separates shrink, so the stack degenerates into mostly
    whitespace — panes at ~40% of a fresh layout by N=12, which users worked
    around by toggling view mode (a full rebuild) to reset it.
    """
    _write_tran_project(str(tmp_path), npts=64, nnodes=12)
    w = plotWindow(str(tmp_path), "proj")
    w.resize(1400, 900)
    w.show()
    qapp.processEvents()
    try:
        for i, t in w.traces.items():
            t.visible = i < 2
        w.radio_stacked.setChecked(True)
        w.refresh_plot()
        w.canvas.draw()

        for n in range(3, 13):           # incremental adds only
            w.traces[n - 1].visible = True
            w.refresh_plot()
            w.canvas.draw()
        assert len(w.panes) == 12
        incr_pane, incr_gap = _pane_geometry_px(w)

        w._force_full_refresh = True     # the mode-toggle workaround
        w.refresh_plot()
        w.canvas.draw()
        full_pane, _ = _pane_geometry_px(w)

        assert incr_pane >= 0.8 * full_pane, (
            f"incremental panes {incr_pane:.1f}px vs {full_pane:.1f}px fresh")
        assert incr_gap <= MAX_STACKED_GAP_RATIO * incr_pane
    finally:
        w.close()


def _stacked_margins_px(w):
    """(margin above the top pane, smallest inter-pane gap) in device pixels."""
    fig_h = w.fig.get_size_inches()[1] * w.fig.dpi
    pos = [ax.get_position() for ax in w.panes]
    gaps = [(pos[i].y0 - pos[i + 1].y1) * fig_h for i in range(len(pos) - 1)]
    return (1.0 - pos[0].y1) * fig_h, (min(gaps) if gaps else 0.0)


def test_stacked_burst_removal_keeps_title_room(qapp, tmp_path):
    """Select-all, then untick down to 4 faster than Qt applies the resize.

    Every pane carries its name and stats in the margin above it. The canvas
    minimum height shrinks with the pane count, but Qt applies it on a later
    layout pass, so a click burst places all its geometry against the old,
    taller canvas — and when the resize finally lands, the frozen fractions
    scale down and take the title room with them: titles collide with the pane
    above and the top one clips against the canvas edge.
    """
    _write_tran_project(str(tmp_path), npts=64, nnodes=14)
    w = plotWindow(str(tmp_path), "proj")
    w.resize(1400, 900)
    w.show()
    qapp.processEvents()
    try:
        for t in w.traces.values():
            t.visible = True
        w.radio_stacked.setChecked(True)
        w.refresh_plot()
        w.canvas.draw()
        qapp.processEvents()

        for k in range(13, 3, -1):       # burst — no event processing between
            w.traces[k].visible = False
            w.refresh_plot()
            w.canvas.draw()
        qapp.processEvents()             # resize finally lands
        w.canvas.draw()
        assert len(w.panes) == 4
        burst_top, burst_gap = _stacked_margins_px(w)

        w._force_full_refresh = True     # reference layout at the same N
        w.refresh_plot()
        w.canvas.draw()
        qapp.processEvents()
        full_top, full_gap = _stacked_margins_px(w)

        assert burst_top >= 0.9 * full_top, (
            f"title margin {burst_top:.1f}px vs {full_top:.1f}px fresh")
        assert burst_gap >= 0.7 * full_gap, (
            f"pane gap {burst_gap:.1f}px vs {full_gap:.1f}px fresh")
    finally:
        w.close()


# ── decimation integration ───────────────────────────────────────────────

@pytest.fixture
def long_window(qapp, tmp_path):
    """Two long (60k-sample) traces — above the decimation threshold."""
    _write_tran_project(str(tmp_path), npts=60_000, nnodes=2)
    w = plotWindow(str(tmp_path), "proj")
    for t in w.traces.values():
        t.visible = True
    yield w
    w.close()


def test_long_traces_drawn_decimated(long_window):
    w = long_window
    w.refresh_plot()
    for t in w.traces.values():
        assert t.line_object is not None
        assert len(t.line_object.get_xdata()) < 60_000
    assert len(w._decim_registry) == 2


def test_zoom_redecimates_from_raw(long_window):
    w = long_window
    w.refresh_plot()
    line = w.traces[0].line_object
    full_span = line._esim_decim_span
    # Zoom into 1% of the x range, then run the deferred re-decimation.
    x = np.asarray(w.obj_dataext.x, dtype=float)
    w.axes.set_xlim(float(x[0]), float(x[len(x) // 100]))
    w._redecimate_visible()
    assert line._esim_decim_span != full_span
    # The zoomed window has < DECIMATION threshold raw samples, so the line
    # now carries full-resolution data for that window.
    i0, i1 = line._esim_decim_span
    assert i1 - i0 <= len(x) // 100 + 4
    assert len(line.get_xdata()) == i1 - i0


def test_stacked_registry_pruned_on_hide(long_window):
    w = long_window
    w.radio_stacked.setChecked(True)
    w.refresh_plot()
    assert len(w._decim_registry) == 2
    w.traces[1].visible = False
    w.refresh_plot()   # incremental path prunes the deleted pane's line
    live = [ln for ln in w._decim_registry if ln.axes in w.fig.axes]
    assert len(live) == len(w._decim_registry) == 1


# ── stats cache ──────────────────────────────────────────────────────────

def test_stats_cached_across_rebuilds(stacked_window, monkeypatch):
    w = stacked_window
    calls = {"n": 0}
    orig = plotWindow._compute_trace_stats_row

    def counting(self, trace_idx, x_arr):
        calls["n"] += 1
        return orig(self, trace_idx, x_arr)

    monkeypatch.setattr(plotWindow, "_compute_trace_stats_row", counting)
    # stats_check defaults ON, so the fixture's refresh already cached the
    # rows; start from a cold cache to observe the compute count.
    w._stats_cache.clear()
    assert w.stats_check.isChecked()
    w._force_full_refresh = True
    w.refresh_plot()
    assert calls["n"] == 6          # one compute per visible trace
    w._force_full_refresh = True
    w.refresh_plot()                # second full rebuild: all cache hits
    assert calls["n"] == 6
