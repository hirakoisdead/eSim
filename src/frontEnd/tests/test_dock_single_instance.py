"""Single-instance tool docks.

Clicking a tool launcher used to mount a brand-new dock every time -- ten
clicks on Plotting meant ten live matplotlib canvases tabified side by side.
DockArea now keeps a (tool kind, project key) -> dock registry: a re-click
raises the existing tab instead of stacking another heavy widget tree, and
the registry entry dies with the dock (tab close, Close Project, Qt-side
deletion) so a later click builds a fresh one.
"""
from PyQt6 import QtCore, QtWidgets, sip

from frontEnd.DockArea import DockArea


def _tool_dock_count(da, prefix):
    return sum(1 for k in da._docks if k.startswith(prefix))


def test_registry_hit_returns_live_dock(qapp):
    da = DockArea()
    try:
        d = QtWidgets.QDockWidget('Tool-1')
        w = QtWidgets.QWidget()
        da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, d)
        da._register_tool_dock('tool', '/proj/a', d, w)

        assert da._live_tool_dock('tool', '/proj/a') is d
        assert d._tool_widget is w
        # A different project key is a different instance.
        assert da._live_tool_dock('tool', '/proj/b') is None
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_destroyed_dock_leaves_registry(qapp):
    da = DockArea()
    try:
        d = QtWidgets.QDockWidget('Tool-1')
        d.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, d)
        da._register_tool_dock('tool', '/proj/a', d, QtWidgets.QWidget())

        # _destroy_dock -> _forget_dock purges the single-instance entry too.
        assert da._destroy_dock(d)
        assert da._live_tool_dock('tool', '/proj/a') is None
        assert ('tool', '/proj/a') not in da._tool_docks
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_qt_side_deletion_is_detected(qapp):
    da = DockArea()
    try:
        d = QtWidgets.QDockWidget('Tool-1')
        da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, d)
        da._register_tool_dock('tool', None, d, QtWidgets.QWidget())

        # Kill the dock behind the registry's back (models WA_DeleteOnClose
        # paths that never route through _forget_dock).
        sip.delete(d)

        assert da._live_tool_dock('tool') is None
        # The stale entry is dropped on lookup, not left to rot.
        assert ('tool', None) not in da._tool_docks
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_usermanual_mounts_no_dock():
    # Help hands the manual to the system viewer/browser, so it has no in-app
    # surface: the old dock was an always-empty tab. Nothing may mount one.
    assert not hasattr(DockArea, 'usermanual')


def test_esim_converter_is_single_instance(qapp):
    da = DockArea()
    try:
        da.eSimConverter()
        first = da._live_tool_dock('esim-converter')
        assert first is not None
        assert _tool_dock_count(da, 'Schematic Converter-') == 1

        da.eSimConverter()
        assert da._live_tool_dock('esim-converter') is first
        assert _tool_dock_count(da, 'Schematic Converter-') == 1
    finally:
        da.deleteLater()
        qapp.processEvents()
