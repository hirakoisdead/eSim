# =========================================================================
#          FILE: Dialogs.py
#
#         USAGE: from configuration import Dialogs
#                Dialogs.warning(self, "Title", "Message")
#
#   DESCRIPTION: Centralized, parent-aware message-popup helpers for eSim.
#
#   WHY THIS EXISTS
#   ---------------
#   A QMessageBox / QErrorMessage created with parent=None becomes its own
#   top-level window with no owner / transient-for relationship to the main
#   window. When such a dialog runs modally via .exec() it blocks input to the
#   main window, but because the window manager doesn't know the dialog belongs
#   to the main window it frequently stacks the dialog *behind* it (very common
#   on X11/Wayland; also happens on Windows through the missing owner link).
#   The user then sees a "frozen" main window with the real dialog hidden
#   behind it and assumes eSim has crashed.
#
#   Passing a real parent fixes stacking + centering on every platform. These
#   helpers resolve a sensible parent automatically (falling back to the active
#   / main window) so call sites cannot reintroduce the bug, set the dialog
#   application-modal, and raise/activate it as a cross-platform belt-and-
#   suspenders for uncooperative window managers.
#
#   RULE: Do NOT construct QMessageBox / QErrorMessage directly anywhere else
#   in eSim -- always go through this module. A unit test
#   (configuration/tests/test_dialog_hygiene.py) enforces this.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

from PyQt6 import QtCore, QtWidgets

# Short aliases for the PyQt6 scoped enums used at call sites.
Icon = QtWidgets.QMessageBox.Icon
Button = QtWidgets.QMessageBox.StandardButton


def _resolve_parent(parent):
    """Return a usable parent QWidget for a dialog.

    Uses the explicit ``parent`` only when its top-level window is actually
    on screen. Many eSim "widgets" are invisible controllers (e.g.
    ``OpenProjectInfo``, ``ModelGeneration``) that subclass QWidget but are
    never shown -- parenting a dialog to one gives the dialog a transient
    parent that the window manager doesn't associate with the real main
    window, so the dialog still ends up *behind* it. In that case (and when no
    parent is given) we fall back to the application's active window, then to
    the first visible top-level QMainWindow. Returns ``None`` only when there
    is no GUI to attach to (e.g. headless unit tests), which is harmless.
    """
    if isinstance(parent, QtWidgets.QWidget):
        win = parent.window()
        if win is not None and win.isVisible():
            return parent
        # else: invisible/un-shown controller widget -- fall through.

    app = QtWidgets.QApplication.instance()
    if app is None:
        return None

    active = app.activeWindow()
    if isinstance(active, QtWidgets.QWidget) and active.isVisible():
        return active

    for widget in app.topLevelWidgets():
        if isinstance(widget, QtWidgets.QMainWindow) and widget.isVisible():
            return widget
    return None


def resolve_parent(parent=None):
    """Public: best on-screen parent window for a dialog that can't use the
    helpers below (``QFileDialog`` / ``QInputDialog`` static methods). Pass the
    calling widget; if it is an invisible controller this returns the real main
    window instead so the native/Qt dialog isn't stranded behind it.
    """
    return _resolve_parent(parent)


def make_message_box(parent=None, icon=Icon.NoIcon, title="", text="",
                     informative_text="", buttons=Button.Ok,
                     default_button=Button.NoButton):
    """Build a fully-configured, parent-attached, application-modal QMessageBox
    *without* executing it.

    Use this when the caller needs to customise the box further (rich text,
    custom buttons, ``addButton`` …) before showing it; finish with
    :func:`show_modal`. For the common cases prefer the convenience helpers
    (:func:`information`, :func:`warning`, :func:`critical`, :func:`question`).
    """
    box = QtWidgets.QMessageBox(_resolve_parent(parent))
    box.setIcon(icon)
    if title:
        box.setWindowTitle(title)
    if text:
        box.setText(text)
    if informative_text:
        box.setInformativeText(informative_text)
    if buttons is not None:
        box.setStandardButtons(buttons)
    if default_button is not None:
        box.setDefaultButton(default_button)
    box.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    return box


def show_modal(box):
    """Show ``box`` modally with the cross-platform stacking workaround.

    ``show()`` + ``raise_()`` + ``activateWindow()`` forces the dialog above
    the main window on X11/Wayland/Windows even when the WM is uncooperative;
    ``exec()`` then runs the modal loop. Returns the clicked StandardButton.
    """
    box.show()
    box.raise_()
    box.activateWindow()
    return box.exec()


def information(parent, title, text, buttons=Button.Ok,
                default=Button.NoButton, informative_text=""):
    return show_modal(make_message_box(
        parent, Icon.Information, title, text, informative_text,
        buttons, default))


def warning(parent, title, text, buttons=Button.Ok,
            default=Button.NoButton, informative_text=""):
    return show_modal(make_message_box(
        parent, Icon.Warning, title, text, informative_text,
        buttons, default))


def critical(parent, title, text, buttons=Button.Ok,
             default=Button.NoButton, informative_text=""):
    return show_modal(make_message_box(
        parent, Icon.Critical, title, text, informative_text,
        buttons, default))


def question(parent, title, text, buttons=Button.Yes | Button.No,
             default=Button.NoButton, informative_text=""):
    return show_modal(make_message_box(
        parent, Icon.Question, title, text, informative_text,
        buttons, default))


def make_error_message(parent=None):
    """Drop-in, parent-attached replacement for ``QtWidgets.QErrorMessage()``.

    QErrorMessage is itself a top-level window and suffers the same
    parentless-stacking problem. This returns one attached to a resolved
    parent; the caller keeps using it (``setWindowTitle`` / ``showMessage``).
    """
    return QtWidgets.QErrorMessage(_resolve_parent(parent))
