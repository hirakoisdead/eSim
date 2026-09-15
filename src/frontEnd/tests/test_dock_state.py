"""Regression tests for dock state persistence and restoration.

F9(a): the dock registry + naming counter are per-instance state, not module
globals -- two DockAreas no longer share one ``dock`` dict / ``count``.

F10: a tab is matched to its dock by an *exact* windowTitle, so closing
``Simulation-RLC-2`` can never take out ``Simulation-RLC-21`` (the old
``startswith`` prefix match) and tab text is never elided.

Plus: the tab strip's close-X stays wired after a garbage collection.
"""
import gc

from PyQt6 import QtCore, QtWidgets, sip

from frontEnd.DockArea import DockArea


class _RecordingDock(QtWidgets.QDockWidget):
    def __init__(self, title):
        super().__init__(title)
        self.setObjectName(title)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.close_events = 0

    def closeEvent(self, event):
        self.close_events += 1
        super().closeEvent(event)


def test_dock_registry_and_counter_are_per_instance(qapp):
    a = DockArea()
    b = DockArea()
    try:
        # Independent registries -- each seeded only with its own Welcome dock.
        assert a._docks is not b._docks
        assert 'Welcome' in a._docks and 'Welcome' in b._docks
        assert a._docks['Welcome'] is not b._docks['Welcome']

        # Mutating one instance's counter must not touch the other's.
        a._count = 99
        assert b._count == 1
    finally:
        a.deleteLater()
        b.deleteLater()
        qapp.processEvents()


def test_tab_close_matches_exact_title_not_prefix(qapp):
    da = DockArea()
    try:
        # handle_tab_close only considers VISIBLE docks; children of a hidden
        # top-level are never visible, so the area itself must be shown for
        # this test to exercise the match at all (offscreen platform is fine).
        da.show()
        # Two docks whose titles share a prefix -- the classic wrong-close case.
        short = _RecordingDock('Simulation-RLC-2')
        long = _RecordingDock('Simulation-RLC-21')
        for d in (short, long):
            da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, d)
            d.setVisible(True)

        # Build a tab bar whose tab 0 reads the *shorter* title.
        tab_bar = QtWidgets.QTabBar()
        tab_bar.addTab('Simulation-RLC-2')

        da.handle_tab_close(0, tab_bar)

        # Only the exact-title dock is destroyed; the prefix sibling survives.
        assert short.close_events == 1
        assert long.close_events == 0
        assert long.windowTitle() == 'Simulation-RLC-21'
    finally:
        da.deleteLater()
        qapp.processEvents()


def _dock_tab_bars(da):
    return [tb for tb in da.findChildren(QtWidgets.QTabBar)
            if not isinstance(tb.parent(), QtWidgets.QTabWidget)]


def test_tab_close_survives_garbage_collection(qapp):
    """The close-X keeps working after Python's cyclic collector runs.

    The wiring used to be ``connect(lambda index, tab_bar=tb: ...)``. Nothing
    but PyQt's connection proxy referenced that lambda, and the lambda
    referenced the tab bar wrapper that owned the proxy -- an unreachable
    cycle. One gc pass (any tool import is enough to trigger one) collected
    it: Qt still counted the connection but the Python callable was gone, so
    every dock tab's X silently did nothing for the rest of the session.
    """
    da = DockArea()
    try:
        da.show()
        d = _RecordingDock('Simulation-RLC-1')
        da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, d)
        da.tabifyDockWidget(da._docks['Welcome'], d)
        qapp.processEvents()

        bars = _dock_tab_bars(da)
        assert bars, "tabifying two docks must create a dock-area tab bar"
        assert bars[0].tabsClosable()
        # The DockArea holds the bar itself, so the wiring cannot be collected.
        assert sip.unwrapinstance(bars[0]) in da._armed_tab_bars

        # Drop every local handle, then collect -- this is what killed it.
        del bars
        for _ in range(3):
            gc.collect()
        qapp.processEvents()
        gc.collect(2)

        tab_bar = _dock_tab_bars(da)[0]
        index = next(i for i in range(tab_bar.count())
                     if tab_bar.tabText(i).replace('&', '').strip()
                     == 'Simulation-RLC-1')
        tab_bar.tabCloseRequested.emit(index)
        qapp.processEvents()

        assert d.close_events == 1, \
            "close-X did nothing after gc: the slot was collected"
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_repeated_arming_does_not_stack_connections(qapp):
    """Every dock open re-arms the tab bar; the slot must connect only once,
    or one X click would close N docks."""
    da = DockArea()
    try:
        da.show()
        first = _RecordingDock('Tool-A-1')
        second = _RecordingDock('Tool-B-2')
        for dock in (first, second):
            da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, dock)
            da.tabifyDockWidget(da._docks['Welcome'], dock)
        qapp.processEvents()

        tab_bar = _dock_tab_bars(da)[0]
        before = tab_bar.receivers(tab_bar.tabCloseRequested)
        for _ in range(5):
            da.enable_tab_close_buttons()
        assert tab_bar.receivers(tab_bar.tabCloseRequested) == before

        index = next(i for i in range(tab_bar.count())
                     if tab_bar.tabText(i).replace('&', '').strip()
                     == 'Tool-A-1')
        tab_bar.tabCloseRequested.emit(index)
        qapp.processEvents()

        assert first.close_events == 1
        assert second.close_events == 0
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_tab_bars_do_not_elide(qapp):
    da = DockArea()
    try:
        # Tabify two docks so a dock-area tab bar exists, then arm close buttons.
        d = _RecordingDock('Simulation-Long-Name-1')
        da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, d)
        da.tabifyDockWidget(da._docks['Welcome'], d)

        for tb in da.findChildren(QtWidgets.QTabBar):
            if isinstance(tb.parent(), QtWidgets.QTabWidget):
                continue
            assert tb.elideMode() == QtCore.Qt.TextElideMode.ElideNone
    finally:
        da.deleteLater()
        qapp.processEvents()
