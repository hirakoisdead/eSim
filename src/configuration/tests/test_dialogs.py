"""Tests for the parent-aware popup helpers in ``configuration.Dialogs``.

These cover parent resolution and message-box construction. The convenience
wrappers (information/warning/critical/question) and ``show_modal`` call
``QMessageBox.exec()`` which blocks on a modal loop, so they are exercised only
indirectly via ``make_message_box`` here.
"""
from PyQt6 import QtCore, QtWidgets

from configuration import Dialogs


# ── _resolve_parent ────────────────────────────────────────────────────────

def test_resolve_parent_returns_visible_widget(qapp):
    w = QtWidgets.QWidget()
    w.show()
    try:
        assert Dialogs._resolve_parent(w) is w
    finally:
        w.close()


def test_resolve_parent_skips_invisible_controller_widget(qapp):
    """An invisible/never-shown controller widget (e.g. OpenProjectInfo,
    ModelGeneration subclass QWidget but are never shown) must NOT be used as
    the parent -- doing so is the bug where the dialog ends up behind the real
    main window. It must resolve to the visible main window instead."""
    main = QtWidgets.QMainWindow()
    main.show()
    invisible_controller = QtWidgets.QWidget()  # never shown
    try:
        assert not invisible_controller.isVisible()
        assert Dialogs._resolve_parent(invisible_controller) is main
    finally:
        main.close()


def test_resolve_parent_falls_back_to_main_window(qapp):
    win = QtWidgets.QMainWindow()
    win.show()
    try:
        # A non-widget (e.g. converter/controller classes pass self, which may
        # not be a QWidget) must still resolve to the visible main window.
        assert Dialogs._resolve_parent(object()) is win
        assert Dialogs._resolve_parent(None) is win
    finally:
        win.close()


# ── make_message_box ───────────────────────────────────────────────────────

def test_make_message_box_attaches_parent_and_is_modal(qapp):
    parent = QtWidgets.QWidget()
    parent.show()
    try:
        box = Dialogs.make_message_box(
            parent, Dialogs.Icon.Warning, "Title", "Body")
        assert box.parent() is parent
        assert (box.windowModality()
                == QtCore.Qt.WindowModality.ApplicationModal)
        assert box.icon() == Dialogs.Icon.Warning
        assert box.windowTitle() == "Title"
        assert box.text() == "Body"
    finally:
        parent.close()


def test_make_message_box_sets_standard_buttons(qapp):
    parent = QtWidgets.QWidget()
    parent.show()
    try:
        box = Dialogs.make_message_box(
            parent, Dialogs.Icon.Question, "T", "B",
            buttons=Dialogs.Button.Yes | Dialogs.Button.No)
        assert (box.standardButtons()
                == (Dialogs.Button.Yes | Dialogs.Button.No))
    finally:
        parent.close()
