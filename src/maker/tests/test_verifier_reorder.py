"""Verify-stage reordering: draggable editor tabs + a draggable hierarchy.

Pins the contract the two reorder surfaces have to keep:

* design tabs move, the testbench tab stays last, and ``design_views`` follows
  the on-screen order (it feeds ``design_views[-1]`` and the compile order);
* the hierarchy is reordered through one entry point (arrows, drag, Ctrl+Up /
  Ctrl+Down all land in ``apply_hierarchy_order``), keeps its item widgets, and
  greys out the arrow that has nowhere to go.

Ungated -- headless widgets, no iverilog needed.
"""
import pytest

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtTest import QTest

LEFT = QtCore.Qt.MouseButton.LeftButton


@pytest.fixture
def verifier(qapp):
    from maker.VerilogVerifier import VerilogVerifier
    w = VerilogVerifier()
    w.unlock_ui()
    # Shown: the drag paints from real tab geometry, which only exists once the
    # bar has been laid out.
    w.resize(900, 300)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()


def _press_and_move(bar, index, dx, steps=6):
    """Press a tab and carry it dx pixels right (or left), without releasing."""
    start = bar.tabRect(index).center()
    QTest.mousePress(bar, LEFT, pos=start)
    x = start.x()
    for step in range(1, steps + 1):
        # Interpolate to the exact endpoint rather than adding dx // steps each
        # time: the floor lost up to `steps` pixels, so a drag calculated to
        # just clear the neighbour's centre could fall a few pixels short.
        x = start.x() + round(dx * step / steps)
        QTest.mouseMove(bar, QtCore.QPoint(x, start.y()))
    return QtCore.QPoint(x, start.y())


def _drag_tab(bar, index, dx, steps=6):
    end = _press_and_move(bar, index, dx, steps)
    QTest.mouseRelease(bar, LEFT, pos=end)


def _past_neighbour(bar, a, b):
    """Drag distance that carries tab ``a``'s leading edge past tab ``b``'s
    midpoint -- the swap threshold, computed from real geometry.

    Derived rather than assumed from a tab width: the old
    ``bar.tabRect(1).width()`` only cleared the threshold while the two labels
    happened to be about equally wide, so it broke the moment a label got
    longer."""
    a_rect, b_rect = bar.tabRect(a), bar.tabRect(b)
    target = b_rect.x() + b_rect.width() // 2
    lead = a_rect.x() + a_rect.width()
    return (target - lead) + 4


def _tab_labels(w):
    return [w.editor_tabs.tabText(i) for i in range(w.editor_tabs.count())]


def _hierarchy_names(w):
    return w.hierarchy_list.names()


def _row_buttons(w, row):
    item = w.hierarchy_list.item(row)
    widget = w.hierarchy_list.itemWidget(item)
    return widget.findChildren(QtWidgets.QPushButton)


# --------------------------------------------------------------- tab bar ----

def test_the_drag_is_painted_by_the_bar_not_by_qt(verifier):
    # Qt's own movable-tab drag cannot be used under an application stylesheet
    # (paintWithOffsets goes false, so only the close button moves). The bar
    # carries the tab itself; these are the pieces that has to have.
    bar = verifier.editor_tabs.tabBar()
    assert not bar.isMovable()
    assert not bar.drawBase()

    verifier.add_module_tab("second.v", "module second; endmodule")
    end = _press_and_move(bar, 0, bar.tabRect(0).width())

    assert bar._drag_index >= 0            # a tab is being carried
    assert bar._drag_pix is not None       # ...as a pixmap the bar draws
    assert bar._gap_color.alpha() == 255   # ...over an opaque, filled-in slot
    carried = bar.tabButton(bar._drag_index, QtWidgets.QTabBar.ButtonPosition.RightSide)
    # The live close button would otherwise sit in the vacated slot; it rides
    # along inside the pixmap instead.
    assert carried is not None and not carried.isVisible()

    QTest.mouseRelease(bar, LEFT, pos=end)
    QTest.qWait(bar._SETTLE_MS + 60)
    assert bar._drag_index == -1
    assert carried.isVisible()


def test_dragging_with_the_mouse_reorders_the_tabs(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    bar = verifier.editor_tabs.tabBar()
    assert _tab_labels(verifier)[:2] == ["counter.v", "second.v"]

    _drag_tab(bar, 0, _past_neighbour(bar, 0, 1))

    assert _tab_labels(verifier)[:2] == ["second.v", "counter.v"]


def test_a_drag_does_not_thrash_back_and_forth(verifier):
    # The swap fires on centre-crosses-centre. Hit-testing the pointer instead
    # would swap the pair again on every move once they had traded places.
    verifier.add_module_tab("second.v", "module second; endmodule")
    bar = verifier.editor_tabs.tabBar()
    moves = []
    bar.tabMoved.connect(lambda f, t: moves.append((f, t)))

    _drag_tab(bar, 0, _past_neighbour(bar, 0, 1), steps=12)

    assert len(moves) == 1
    assert _tab_labels(verifier)[:2] == ["second.v", "counter.v"]


def test_a_drag_to_the_far_right_stops_at_the_testbench(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    bar = verifier.editor_tabs.tabBar()

    _drag_tab(bar, 0, bar.width(), steps=16)

    assert _tab_labels(verifier)[-1].startswith("Testbench")
    assert verifier.editor_tabs.indexOf(verifier.tb_view) == verifier.editor_tabs.count() - 1


def test_dragging_a_design_tab_reorders_tabs_and_design_views(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    before = _tab_labels(verifier)
    assert before[:2] == ["counter.v", "second.v"]

    verifier.editor_tabs.tabBar().moveTab(0, 1)

    assert _tab_labels(verifier)[:2] == ["second.v", "counter.v"]
    # design_views mirrors the bar: last-added is no longer last on screen.
    assert [verifier.editor_tabs.indexOf(v) for v in verifier.design_views] == [0, 1]
    assert verifier.editor_tabs.tabText(
        verifier.editor_tabs.indexOf(verifier.design_views[-1])) == "counter.v"


def test_testbench_tab_is_re_pinned_last(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    tb_index = verifier.editor_tabs.indexOf(verifier.tb_view)

    # Whatever route a drag took, the testbench must come back to the end.
    verifier.editor_tabs.tabBar().moveTab(tb_index, 0)

    last = verifier.editor_tabs.count() - 1
    assert verifier.editor_tabs.indexOf(verifier.tb_view) == last
    assert verifier.tb_view not in verifier.design_views


def test_pinned_tab_refuses_to_start_a_drag(verifier):
    bar = verifier.editor_tabs.tabBar()
    pinned = bar.count() - 1
    press = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(bar.tabRect(pinned).center()),
        QtCore.QPointF(bar.tabRect(pinned).center()),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier)
    bar.mousePressEvent(press)
    assert bar._drag_locked is True

    release = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QtCore.QPointF(bar.tabRect(pinned).center()),
        QtCore.QPointF(bar.tabRect(pinned).center()),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier)
    bar.mouseReleaseEvent(release)
    assert bar._drag_locked is False


# ------------------------------------------------------------- hierarchy ----

def test_move_arrows_reorder_the_hierarchy(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    verifier.add_module_tab("third.v", "module third; endmodule")
    assert _hierarchy_names(verifier) == ["counter.v", "second.v", "third.v"]

    verifier.move_hierarchy_item(verifier.hierarchy_list.item(2), "up")
    assert _hierarchy_names(verifier) == ["counter.v", "third.v", "second.v"]
    # Selection follows the row that moved, so the next click continues it.
    assert verifier.hierarchy_list.currentRow() == 1

    verifier.move_hierarchy_item(verifier.hierarchy_list.item(1), "down")
    assert _hierarchy_names(verifier) == ["counter.v", "second.v", "third.v"]


def test_move_at_the_ends_is_a_no_op(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    names = _hierarchy_names(verifier)

    verifier.move_hierarchy_item(verifier.hierarchy_list.item(0), "up")
    verifier.move_hierarchy_item(verifier.hierarchy_list.item(1), "down")

    assert _hierarchy_names(verifier) == names


def test_boundary_arrows_are_disabled(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    first_up, first_down = _row_buttons(verifier, 0)
    last_up, last_down = _row_buttons(verifier, 1)

    assert not first_up.isEnabled()      # nothing above the first row
    assert first_down.isEnabled()
    assert last_up.isEnabled()
    assert not last_down.isEnabled()     # nothing below the last row


def test_rows_keep_their_item_widgets_after_a_reorder(verifier):
    # The whole reason the drop is intercepted: a model-level move would have
    # destroyed these widgets and left blank rows.
    verifier.add_module_tab("second.v", "module second; endmodule")
    verifier.apply_hierarchy_order(["second.v", "counter.v"], 0)

    for row in range(verifier.hierarchy_list.count()):
        widget = verifier.hierarchy_list.itemWidget(
            verifier.hierarchy_list.item(row))
        assert widget is not None
        assert len(widget.findChildren(QtWidgets.QPushButton)) == 2


def test_ctrl_arrow_keys_reorder(verifier):
    verifier.add_module_tab("second.v", "module second; endmodule")
    verifier.hierarchy_list.setCurrentRow(1)

    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Up,
        QtCore.Qt.KeyboardModifier.ControlModifier)
    verifier.hierarchy_list.keyPressEvent(event)

    assert _hierarchy_names(verifier) == ["second.v", "counter.v"]


def test_drop_row_math():
    from maker.VerilogVerifier import HierarchyList
    # Dragging row 0 down over row 2's lower half (gap 3) lands it last.
    assert HierarchyList.drop_row(0, 3, 3) == 2
    # Dropping into the gap directly below itself changes nothing.
    assert HierarchyList.drop_row(1, 2, 3) == 1
    # Dragging upward: the gap index is the destination as-is.
    assert HierarchyList.drop_row(2, 0, 3) == 0
    # Past the end / before the start is clamped into the list.
    assert HierarchyList.drop_row(1, 9, 3) == 2
    assert HierarchyList.drop_row(1, 0, 3) == 0


def test_reorder_survives_a_hidden_panel(verifier):
    # The slide snapshots grabbed rows; an unmapped widget grabs empty. Make
    # sure the reorder itself still lands when the panel is not on screen.
    verifier.add_module_tab("second.v", "module second; endmodule")
    verifier.hide()
    assert not verifier.hierarchy_list.isVisible()

    verifier.apply_hierarchy_order(["second.v", "counter.v"], 0)

    assert _hierarchy_names(verifier) == ["second.v", "counter.v"]
    assert verifier._hierarchy_anim is None
