"""HiDPI regression tests for the embedded matplotlib canvas.

Guards the fix in plot_window.FigureCanvas.showEvent.

matplotlib's FigureCanvasQT.showEvent stopped performing the initial
device-pixel-ratio sync on Qt >= 6.6: that branch only installs a
DevicePixelRatioChange event filter, and the filter fires solely when the ratio
*changes*. A plot window opened on a HiDPI screen whose ratio never changes is
therefore never synced -- device_pixel_ratio stays 1 and figure.dpi keeps its
construction value, so Agg renders the buffer at logical resolution and Qt
stretches it to physical size. The result is a soft, pixelated plot surrounded
by perfectly sharp Qt chrome, and it survives every redraw, resize, view-mode
toggle and re-simulation because each of those re-renders at the same stale
ratio.

These tests must stay meaningful on a 1.0-ratio machine (CI, and any non-HiDPI
dev box), where a genuine sync is a no-op and would assert nothing. So the
canvas subclass below reports a fixed 1.75 ratio, which reproduces the HiDPI
condition deterministically anywhere. Without the showEvent override these
tests fail on every platform; with it they pass.
"""

import pytest
from PyQt6 import QtWidgets
from matplotlib.figure import Figure

from ngspiceSimulation.plot_window import FigureCanvas

FAKE_RATIO = 1.75
BASE_DPI = 100
WIN_W, WIN_H = 900, 600


class _HiDpiCanvas(FigureCanvas):
    """eSim's canvas, pinned to a HiDPI ratio regardless of the real screen."""

    def devicePixelRatioF(self) -> float:
        return FAKE_RATIO


def _show(canvas):
    """Put the canvas in a shown top-level window and settle the event queue.

    A real window is required: matplotlib's showEvent reaches through
    self.window().windowHandle(), which is None until the widget is shown.
    """
    win = QtWidgets.QMainWindow()
    win.setCentralWidget(canvas)
    win.resize(WIN_W, WIN_H)
    win.show()
    QtWidgets.QApplication.processEvents()
    return win


def test_show_syncs_device_pixel_ratio(qapp):
    """Showing the canvas must adopt the screen's ratio and scale figure.dpi."""
    fig = Figure(figsize=(10, 8), dpi=BASE_DPI)
    canvas = _HiDpiCanvas(fig)
    win = _show(canvas)
    try:
        assert canvas.device_pixel_ratio == pytest.approx(FAKE_RATIO), (
            "canvas kept device_pixel_ratio=1 on a HiDPI screen -- the initial "
            "sync matplotlib skips on Qt>=6.6 did not run"
        )
        assert fig.dpi == pytest.approx(BASE_DPI * FAKE_RATIO), (
            "figure.dpi was not scaled by the device pixel ratio"
        )
    finally:
        win.close()


def test_agg_buffer_matches_physical_pixels(qapp):
    """The crispness invariant: the Agg buffer must equal the physical pixels.

    When the buffer is smaller, Qt stretches it to fill the widget and the plot
    renders blurry. Comparing the two is the objective form of "looks sharp".
    """
    fig = Figure(figsize=(10, 8), dpi=BASE_DPI)
    canvas = _HiDpiCanvas(fig)
    win = _show(canvas)
    try:
        expected_w = round(canvas.width() * FAKE_RATIO)
        expected_h = round(canvas.height() * FAKE_RATIO)
        assert round(fig.bbox.width) == expected_w, (
            f"Agg buffer is {round(fig.bbox.width)}px wide but the canvas "
            f"occupies {expected_w} physical px -- Qt will stretch it "
            f"{expected_w / max(round(fig.bbox.width), 1):.2f}x (blurry plot)"
        )
        assert round(fig.bbox.height) == expected_h
    finally:
        win.close()


def test_sync_is_noop_at_ratio_one(qapp):
    """On a normal-DPI display the fix must change nothing."""
    fig = Figure(figsize=(10, 8), dpi=BASE_DPI)

    class _StdCanvas(FigureCanvas):
        def devicePixelRatioF(self) -> float:
            return 1.0

    canvas = _StdCanvas(fig)
    win = _show(canvas)
    try:
        assert canvas.device_pixel_ratio == pytest.approx(1.0)
        assert fig.dpi == pytest.approx(BASE_DPI)
    finally:
        win.close()
