"""_app_teardown quiesces animation/timer/figure state at exit.

The recurring 0xc0000005 in sip at teardown is a use-after-free: animations and
timers tick against graphics effects/canvases Qt is freeing. _app_teardown stops
them first, in order, and must be crash-proof (every step guarded).

Full validation is live (5 launch/exit cycles with no new WER entry); this pins
the crash-proof contract and that widget timers are actually stopped.
"""
import os
import sys

from PyQt6 import QtCore, QtWidgets

# Application.py does a bare `import pathmagic` (frontEnd/pathmagic.py) at module
# load, so its own directory must be importable.
_FE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FE not in sys.path:
    sys.path.insert(0, _FE)

from frontEnd.Application import _app_teardown


def test_teardown_stops_widget_timers(qapp):
    w = QtWidgets.QWidget()
    t = QtCore.QTimer(w)
    t.start(1000)
    assert t.isActive()
    _app_teardown()
    assert not t.isActive()
    w.deleteLater()


def test_teardown_is_crash_proof_without_matplotlib(qapp):
    # matplotlib may not be loaded; teardown must not force the import or raise.
    _app_teardown(apply_theme_slot=None)


def test_teardown_tolerates_a_bad_theme_slot(qapp):
    # Disconnecting a slot that was never connected must be swallowed.
    def never_connected(*_):
        pass
    _app_teardown(apply_theme_slot=never_connected)
