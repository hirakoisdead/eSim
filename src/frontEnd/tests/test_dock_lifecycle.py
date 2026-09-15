"""Regression tests for dock creation, replacement, and teardown.

Close Project must *destroy* a project's docks, not merely hide them: hiding
left plot canvases + refresh timers, QWebEngineViews, QScintilla editors and
the verifier's DesignBus watchdog thread alive (and still registered) for the
whole session. These pin:

  * ``closeDock`` runs each registered dock's ``closeEvent`` and drops it,
  * the per-project bucket is popped afterwards,
  * a missing bucket does not raise (seeding is no longer an implicit invariant),
  * a dock that vetoes its close (unsaved-editor case) survives, and
  * ``_forget_dock`` unregisters a dock from every bucket it belonged to.
"""
import pytest

from PyQt6 import QtCore, QtWidgets

from frontEnd.DockArea import DockArea


class _RecordingDock(QtWidgets.QDockWidget):
    """A dock that records whether its closeEvent ran (deletes on close)."""

    def __init__(self, title):
        super().__init__(title)
        self.setObjectName(title)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.close_events = 0

    def closeEvent(self, event):
        self.close_events += 1
        super().closeEvent(event)


class _VetoDock(QtWidgets.QDockWidget):
    """A dock that refuses to close -- models an editor with unsaved changes."""

    def __init__(self, title):
        super().__init__(title)
        self.setObjectName(title)

    def closeEvent(self, event):
        event.ignore()


@pytest.fixture
def dockarea(qapp):
    da = DockArea()
    # Start every test from a clean per-project registry.
    da.obj_appconfig.dock_dict.clear()
    yield da
    da.obj_appconfig.dock_dict.clear()
    da.deleteLater()


def _register(da, project, dock):
    da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, dock)
    da.obj_appconfig.dock_dict.setdefault(project, []).append(dock)


def _set_current(da, project):
    da.obj_appconfig.current_project['ProjectName'] = project


def test_close_project_destroys_and_forgets_docks(qapp, dockarea):
    _set_current(dockarea, 'ProjA')
    d1 = _RecordingDock('Simulation-ProjA-1')
    d2 = _RecordingDock('Plotting-ProjA-2')
    _register(dockarea, 'ProjA', d1)
    _register(dockarea, 'ProjA', d2)

    dockarea.closeDock()

    # Each dock's own teardown ran (so matplotlib figures/timers, watchdog
    # threads and tmpdirs get reaped via their closeEvent).
    assert d1.close_events == 1
    assert d2.close_events == 1
    # The bucket is gone -- nothing lingers registered.
    assert 'ProjA' not in dockarea.obj_appconfig.dock_dict
    # deleteLater was scheduled; draining it must not fault (idempotent teardown).
    qapp.processEvents()


def test_close_project_with_no_docks_does_not_raise(qapp, dockarea):
    # A project that was never seeded in dock_dict (implicit-invariant bug).
    _set_current(dockarea, 'NeverSeeded')
    dockarea.closeDock()  # must not KeyError
    assert 'NeverSeeded' not in dockarea.obj_appconfig.dock_dict


def test_vetoed_dock_survives_and_bucket_retained(qapp, dockarea):
    _set_current(dockarea, 'ProjB')
    keep = _VetoDock('Editor-ProjB-1')
    _register(dockarea, 'ProjB', keep)

    dockarea.closeDock()

    # The dock refused to close, so it must still be alive and registered.
    assert keep.windowTitle() == 'Editor-ProjB-1'
    assert keep in dockarea.obj_appconfig.dock_dict.get('ProjB', [])


def test_destroy_dock_reports_torn_down(qapp, dockarea):
    _set_current(dockarea, 'ProjC')
    gone = _RecordingDock('Simulation-ProjC-1')
    kept = _VetoDock('Editor-ProjC-2')
    _register(dockarea, 'ProjC', gone)
    _register(dockarea, 'ProjC', kept)

    assert dockarea._destroy_dock(gone) is True
    assert dockarea._destroy_dock(kept) is False


def test_forget_dock_unregisters_from_all_buckets(qapp, dockarea):
    _set_current(dockarea, 'ProjD')
    shared = _RecordingDock('Simulation-ProjD-1')
    # Deliberately place it in two buckets to prove _forget_dock sweeps all.
    _register(dockarea, 'ProjD', shared)
    dockarea.obj_appconfig.dock_dict.setdefault('OtherProj', []).append(shared)

    dockarea._forget_dock(shared)

    assert shared not in dockarea.obj_appconfig.dock_dict.get('ProjD', [])
    assert shared not in dockarea.obj_appconfig.dock_dict.get('OtherProj', [])
