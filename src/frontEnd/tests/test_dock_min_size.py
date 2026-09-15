"""A tool panel must never be able to force the eSim window off-screen.

QMainWindow cannot be resized below the sum of its docks' layout minimums.
That makes every panel's minimum a hard floor on the whole application: mount
one tall fixed-metric page and the window grows past the bottom of the desktop,
where the last rows are unreachable AND the window cannot be dragged back --
there is no smaller size for Qt to go to. That is exactly what the NGHDL VHDL
builder (min 720x385) did once it became a Flow Navigator stage: opening it
pushed the main window's minimum height to 682 logical pixels, more than the
672 a 1920x1080 laptop at 150% Windows scaling actually has.

The fix is structural, not a set of hand-tuned pixel values: dock content is
mounted behind a resizable scroll viewport (DockArea._scrollable), so a panel
that does not fit scrolls instead of pushing the window. These tests pin that
property against the worst case a future panel could present.

Budget below is the smallest workspace eSim claims to support -- 1280x720
logical minus a 48px taskbar -- with room left for the title bar and frame.
"""
from PyQt6 import QtCore, QtWidgets

from frontEnd.DockArea import DockArea

# Logical pixels of desktop on a 1920x1080 panel at 150% Windows scaling,
# minus the taskbar. Anything the window demands beyond this is off-screen.
WORKSPACE_H = 672
WORKSPACE_W = 1280
# Windows title bar + resize frame, which the workspace budget must also cover.
FRAME_H = 40


def _tall_panel(width=1200, height=1400):
    """Stand-in for a fixed-metric page (NGHDL's builder, a wide form...).

    A real panel is used only where the toolchain it needs is guaranteed
    present; this reproduces the property that matters -- a large layout
    minimum -- on every machine.
    """
    panel = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(panel)
    inner = QtWidgets.QWidget()
    inner.setMinimumSize(width, height)
    lay.addWidget(inner)
    return panel


def test_scrollable_absorbs_a_panels_minimum(qapp):
    panel = _tall_panel()
    assert panel.minimumSizeHint().height() >= 1400   # the hazard is real

    area = DockArea._scrollable(panel)
    # Behind a viewport the panel no longer dictates a floor.
    assert area.minimumSizeHint().height() < 300
    assert area.minimumSizeHint().width() < 300
    # ...and it still fills the viewport when there IS room, so nothing
    # changes on a large display.
    assert area.widgetResizable()
    area.resize(1600, 1600)
    qapp.processEvents()
    assert panel.width() >= 1200


def test_mounted_dock_fits_a_small_workspace(qapp):
    """The end-to-end property: a tall tool panel mounted the normal way
    leaves the main window shrinkable to a laptop workspace."""
    da = DockArea()
    try:
        dock = QtWidgets.QDockWidget('Tool-1')
        da.apply_fullscreen_feature(dock, _tall_panel())
        da.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, dock)
        qapp.processEvents()

        floor = da.minimumSizeHint()
        assert floor.height() + FRAME_H <= WORKSPACE_H, (
            f"a dock forces a {floor.height()}px-tall window; a small laptop "
            f"workspace is {WORKSPACE_H}px")
        assert floor.width() <= WORKSPACE_W
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_panel_survives_the_mount(qapp):
    """The scroll viewport is invisible to the rest of the dock machinery:
    the panel is still a live descendant of the dock, so FullScreenToggle's
    reparenting and the tool-dock registry keep working."""
    da = DockArea()
    try:
        dock = QtWidgets.QDockWidget('Tool-1')
        panel = _tall_panel()
        da.apply_fullscreen_feature(dock, panel)
        qapp.processEvents()

        holder = dock.widget()
        assert holder is not None
        assert panel.isAncestorOf is not None
        assert holder.isAncestorOf(panel)
        # The card is still the holder's direct child (the Aurora look and the
        # fullscreen hand-off both depend on that shape).
        card = holder.findChild(QtWidgets.QFrame, "dockCard")
        assert card is not None and card.parent() is holder
    finally:
        da.deleteLater()
        qapp.processEvents()


def test_nghdl_stage_is_scrolled(qapp, monkeypatch):
    """The VHDL stage specifically: the Flow Navigator must wrap it, the way
    it wraps Author and Convert. Uses a stand-in page so the test does not
    need a working GHDL toolchain."""
    from maker import FlowNavigator as FN

    flow = FN.FlowNavigator(0)
    try:
        monkeypatch.setattr(FN.FlowNavigator, "_make_nghdl",
                            lambda self: _tall_panel(720, 900))
        flow._select_mode("vhdl")
        qapp.processEvents()

        assert flow.stack.currentWidget().minimumSizeHint().height() < 300
        assert flow.minimumSizeHint().height() < 300
    finally:
        flow.deleteLater()
        qapp.processEvents()
