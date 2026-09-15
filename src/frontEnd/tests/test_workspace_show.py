"""The main window is maximized when the workspace flow reveals it, not
in Application.__init__ (which runs behind the splash and is then hidden).

Pins that _finish_workspace_change maximizes the captured view exactly once, so
the maximized layout+paint isn't built and thrown away during startup.
"""
from frontEnd.Workspace import Workspace


class _StubView:
    def __init__(self):
        self.splash = None
        self.maximized = 0
        self.shown = 0

    def showMaximized(self):
        self.maximized += 1

    def show(self):
        self.shown += 1


def test_finish_workspace_change_maximizes_view(qapp):
    ws = Workspace()
    try:
        view = _StubView()
        ws.returnWhetherClickedOrNot(view)
        ws._finish_workspace_change()
        assert view.maximized == 1
        assert view.shown == 0        # must maximize, not plain show
    finally:
        ws.deleteLater()


def test_finish_workspace_change_without_view_is_safe(qapp):
    ws = Workspace()
    try:
        ws._app_view = None
        ws._finish_workspace_change()   # must not raise
    finally:
        ws.deleteLater()
