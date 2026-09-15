"""The Aurora tooltip must claim sub-widget tips, not only widget tips.

Tab / item / header / menu tooltips are painted by Qt's own handlers as the
native square box; the filter has to answer their ToolTip event itself or the
ugly box comes back on those surfaces (the dock strip at the bottom being the
one users hit every session).
"""
from PyQt6 import QtCore, QtGui, QtWidgets

from frontEnd.tooltips import install_tooltips

TOP = QtCore.Qt.DockWidgetArea.TopDockWidgetArea


def _help_event(widget, point):
    return QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, point,
                            widget.mapToGlobal(point))


def _filter(qapp):
    filt = install_tooltips(qapp)
    filt._hide()
    return filt


def test_dock_tab_strip_gets_aurora_card(qapp):
    win = QtWidgets.QMainWindow()
    first = QtWidgets.QDockWidget('Welcome', win)
    second = QtWidgets.QDockWidget('Simulation-RLC-1', win)
    win.addDockWidget(TOP, first)
    win.addDockWidget(TOP, second)
    win.tabifyDockWidget(first, second)
    win.resize(800, 600)
    win.show()
    qapp.processEvents()

    bar = win.findChildren(QtWidgets.QTabBar)[0]
    filt = _filter(qapp)
    point = bar.tabRect(1).center()

    assert filt.eventFilter(bar, _help_event(bar, point)) is True, \
        'native square tooltip was left to paint the dock tab'
    assert filt._tip.isVisible()
    assert filt._tip._label.text() == 'Simulation-RLC-1'
    filt._hide()


def test_header_section_tip(qapp):
    table = QtWidgets.QTableWidget(2, 2)
    table.setHorizontalHeaderLabels(['a', 'b'])
    table.horizontalHeaderItem(0).setToolTip('col a tip')
    table.resize(300, 200)
    table.show()
    qapp.processEvents()

    header = table.horizontalHeader()
    point = QtCore.QPoint(header.sectionPosition(0) + 5, header.height() // 2)
    filt = _filter(qapp)
    assert filt._header_tip(header.viewport().mapToGlobal(point)) == 'col a tip'


def test_menu_tip_only_when_qt_would_show_one(qapp):
    menu = QtWidgets.QMenu()
    action = menu.addAction('Run')
    action.setToolTip('Run the netlist')
    menu.show()
    qapp.processEvents()
    menu.setActiveAction(action)

    filt = _filter(qapp)
    centre = menu.mapToGlobal(menu.rect().center())
    assert filt._menu_tip(centre) == ''  # toolTipsVisible() is off by default
    menu.setToolTipsVisible(True)
    assert filt._menu_tip(centre) == 'Run the netlist'
    menu.hide()
