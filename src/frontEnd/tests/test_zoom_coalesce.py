"""Zoom must not repolish the whole app once per click.

``change_zoom`` used to call ``theme_utils.apply_theme`` -- a full
``QApplication.setStyleSheet()`` repolish of every widget in the process --
synchronously, from inside the zoom button's own ``clicked`` handler. Clicking
the pill repeatedly stacked repolish on repolish: each new pass re-entered Qt's
style engine while the previous pass's deferred work (graphics-effect refresh,
palette-change handlers, queued repaints) was still in flight, and any widget
pointer the outer pass still held could be freed underneath it.

That is the window eSim was dying in: ``~/.esim/crash.log``, session
2026-07-25, a 0xC0000005 with no Python frame deeper than

    theme_utils._apply_theme_impl -> app.setStyleSheet
    Application.change_zoom
    <lambda>   (the zoom button)

and a WER record of an execute fault on a heap address -- a call through a
freed C++ object's vtable.

The fix keeps the label instant and lands the expensive restyle once, on the
trailing edge of the click burst.
"""
import os
import sys
import time

import pytest

from PyQt6 import QtCore, QtWidgets

# Application.py does a bare ``import pathmagic``, so its own directory has to
# be importable -- the launcher gets this for free by chdir'ing into frontEnd.
_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)


class _Zoomer(QtWidgets.QWidget):
    """Only the surface the zoom path touches, borrowed off Application so the
    test drives the real methods without building the whole main window."""

    def __init__(self):
        super().__init__()
        from frontEnd.Application import Application
        self.change_zoom = Application.change_zoom.__get__(self)
        self._schedule_zoom_apply = Application._schedule_zoom_apply.__get__(self)
        self._apply_zoom_now = Application._apply_zoom_now.__get__(self)
        self.zoom_label = QtWidgets.QLabel()
        self.metrics_calls = 0

    def _apply_view_control_metrics(self, zoom_level):
        self.metrics_calls += 1


@pytest.fixture
def zoomer(qapp):
    z = _Zoomer()
    yield z
    z.deleteLater()


def _settle(qapp, ms=400):
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 10)


@pytest.fixture
def applies(monkeypatch):
    """Count app-wide repolishes without actually running one."""
    from frontEnd import theme_utils
    calls = {"n": 0}
    monkeypatch.setattr(theme_utils, "apply_theme",
                        lambda *_a, **_k: calls.__setitem__("n", calls["n"] + 1))
    return calls


def test_single_click_does_not_repolish_inline(qapp, zoomer, applies):
    zoomer.change_zoom(-10)
    assert applies["n"] == 0, "repolished from inside the click handler"
    # The readout is what the user watches, so it must already be right.
    assert zoomer.zoom_label.text().strip() == "90%"
    _settle(qapp)
    assert applies["n"] == 1
    assert zoomer.metrics_calls == 1


def test_click_burst_collapses_to_one_repolish(qapp, zoomer, applies):
    for _ in range(10):
        zoomer.change_zoom(-10)
    assert applies["n"] == 0
    assert zoomer.zoom_label.text().strip() == "50%"   # clamped floor
    _settle(qapp)
    assert applies["n"] == 1, f"10 clicks ran {applies['n']} repolishes"


def test_zoom_stays_within_bounds(qapp, zoomer, applies):
    for _ in range(40):
        zoomer.change_zoom(10)
    _settle(qapp)
    from frontEnd.theme_utils import get_preferences
    assert get_preferences()["zoom_level"] == 300
    for _ in range(60):
        zoomer.change_zoom(-10)
    _settle(qapp)
    assert get_preferences()["zoom_level"] == 50


def test_no_op_zoom_schedules_nothing(qapp, zoomer, applies):
    """At the ceiling, another + is not a theme change."""
    for _ in range(40):
        zoomer.change_zoom(10)
    _settle(qapp)
    before = applies["n"]
    zoomer.change_zoom(10)
    _settle(qapp)
    assert applies["n"] == before
