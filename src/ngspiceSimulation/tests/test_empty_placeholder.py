"""Empty-state placeholder lifecycle in normal view.

The "Please select a waveform to plot" text is drawn by a full rebuild that
saw zero visible traces. Because the normal-mode composition signature
deliberately excludes the visible set, the very next visibility toggle takes
the incremental path — which never calls fig.clear(). The placeholder must
therefore be removed explicitly there, or it survives on top of the plotted
waveforms until an unrelated full rebuild (e.g. a view-mode switch) wipes it.
"""
import os

import numpy as np
import pytest

from ngspiceSimulation.plot_window import plotWindow

PLACEHOLDER = 'Please select a waveform to plot'


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


def _placeholder_texts(w):
    return [t for t in w.axes.texts if t.get_text() == PLACEHOLDER]


@pytest.fixture
def empty_window(qapp, tmp_path):
    """Freshly-opened transient project: traces default to not-visible."""
    _write_tran_project(str(tmp_path), npts=64, nnodes=3)
    w = plotWindow(str(tmp_path), "proj")
    w.refresh_plot()
    yield w
    w.close()


def test_placeholder_shown_when_nothing_visible(empty_window):
    w = empty_window
    assert not w.visible_traces
    assert w._empty_placeholder is not None
    assert len(_placeholder_texts(w)) == 1


def test_placeholder_cleared_on_first_selection(empty_window):
    """The regression: selecting a waveform must remove the empty-state text."""
    w = empty_window
    axes_before = w.axes

    w.traces[0].visible = True
    w.refresh_plot()

    # Incremental path was taken — same Axes object, no fig.clear().
    assert w.axes is axes_before
    assert w._empty_placeholder is None
    assert _placeholder_texts(w) == []
    assert w.traces[0].line_object is not None


def test_placeholder_returns_after_deselecting_all(empty_window):
    w = empty_window
    w.traces[0].visible = True
    w.refresh_plot()
    assert _placeholder_texts(w) == []

    w.traces[0].visible = False
    w.refresh_plot()

    assert w._empty_placeholder is not None
    assert len(_placeholder_texts(w)) == 1


def test_placeholder_not_duplicated_across_rebuilds(empty_window):
    w = empty_window
    for _ in range(3):
        w._force_full_refresh = True
        w.refresh_plot()
    assert len(_placeholder_texts(w)) == 1


def test_placeholder_survives_view_mode_round_trip(empty_window):
    """Stacked → normal with a trace visible must not resurrect the text."""
    w = empty_window
    w.traces[1].visible = True
    w.refresh_plot()

    w.radio_stacked.setChecked(True)
    w.refresh_plot()
    w.radio_stacked.setChecked(False)
    w.refresh_plot()

    assert w._empty_placeholder is None
    assert _placeholder_texts(w) == []
