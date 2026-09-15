"""Release regressions: editor icons, flow chrome and popup ownership."""
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from PyQt6 import QtCore, QtGui, QtSvg, QtTest, QtWidgets


@pytest.fixture
def qt_messages():
    messages = []
    previous = QtCore.qInstallMessageHandler(
        lambda kind, context, message: messages.append(message))
    yield messages
    QtCore.qInstallMessageHandler(previous)


@pytest.mark.parametrize("dark", [False, True])
def test_editor_close_icons_resolve_outside_source_directory(
        qapp, tmp_path, monkeypatch, qt_messages, dark):
    from codeEditor import EditorWindow as module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module.theme, "is_dark_theme", lambda: dark)
    settings_class = QtCore.QSettings
    monkeypatch.setattr(QtCore, "QSettings", lambda *args: settings_class(
        str(tmp_path / "editor.ini"), settings_class.Format.IniFormat))
    file_path = tmp_path / "test.cir"
    file_path.write_text("* test circuit\n.end\n", encoding="utf-8")
    window = module.EditorWindow()
    try:
        window.open(str(file_path))
        qapp.processEvents()
        paths = re.findall(r'url\("([^"]+\.svg)"\)', window.styleSheet())
        assert len(paths) == 2
        for path in paths:
            assert Path(path).is_absolute(), path
            assert Path(path).is_file(), path
            assert QtSvg.QSvgRenderer(path).isValid(), path
        assert not any("Cannot open file" in message for message in qt_messages)
        bar = window.tabs.tabBar()
        button = (bar.tabButton(0, QtWidgets.QTabBar.ButtonPosition.RightSide)
                  or bar.tabButton(0, QtWidgets.QTabBar.ButtonPosition.LeftSide))
        assert button is not None and button.isVisible()
        assert button.width() > 0 and button.height() > 0
        QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
        assert window.tabs.count() == 0
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("dark", [False, True])
def test_flow_stylesheet_parses_in_both_themes(qapp, qt_messages, dark):
    from maker.FlowNavigator import FlowNavigator

    bar = QtWidgets.QWidget()
    bar.setObjectName("flowTabBar")
    target = SimpleNamespace(tabbar=bar, _is_dark=lambda: dark)
    target._pill_tokens = lambda: FlowNavigator._pill_tokens(target)
    try:
        bar.show()
        for _ in range(3):
            FlowNavigator._apply_pill_theme(target)
            qapp.processEvents()
        assert not any("Could not parse" in message for message in qt_messages)
        assert bar.styleSheet().count("{") == bar.styleSheet().count("}")
    finally:
        bar.close()
        bar.deleteLater()


def test_tooltip_has_transient_parent_before_show_and_tracks_owner(
        qapp, monkeypatch, qt_messages):
    from frontEnd.tooltips import AuroraToolTip, install_tooltips

    filt = install_tooltips(qapp)
    parents_at_show = []
    original_show = AuroraToolTip.show

    def record_show(tip):
        handle = tip.windowHandle()
        parents_at_show.append(handle.transientParent() if handle else None)
        original_show(tip)

    monkeypatch.setattr(AuroraToolTip, "show", record_show)
    windows = [QtWidgets.QWidget(), QtWidgets.QWidget()]
    try:
        for index, window in enumerate(windows):
            window.setToolTip("Window %s" % index)
            window.resize(200, 120)
            window.move(20 + index * 250, 30)
            window.show()
            qapp.processEvents()
            point = window.rect().center()
            event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, point,
                                    window.mapToGlobal(point))
            assert filt.eventFilter(window, event)
            assert parents_at_show[-1] is window.windowHandle()
            assert filt._tip.windowHandle().transientParent() is window.windowHandle()
            assert filt._tip.isVisible()
            filt._hide()
        assert not any("Failed to create popup" in message for message in qt_messages)
    finally:
        filt._hide()
        for window in windows:
            window.close()
            window.deleteLater()
        qapp.processEvents()
