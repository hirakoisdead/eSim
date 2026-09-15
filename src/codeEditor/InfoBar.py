"""GNOME-style inline notification strip pinned to an editor's top.

Mirrors the GNOME Text Editor / gedit "File Has Changed on Disk" bar:
instead of a modal dialog that steals focus and hides the document, a
coloured strip slides in at the top of the affected tab, pushes the text
down (so nothing is covered) and carries an action button plus a dismiss
"X".

Both :class:`CodeEditor` and :class:`PlainEditor` derive from
``QAbstractScrollArea``, so the strip reserves its height with
``setViewportMargins`` -- the same mechanism Qt's own widgets use to dock
chrome above a scroll viewport -- and tracks the editor's width on resize.
"""

from PyQt6 import QtCore, QtWidgets


class InfoBar(QtWidgets.QFrame):
    """A dismissible notification docked to the top of *editor*.

    Only one bar lives on an editor at a time: constructing a new one
    replaces any bar already attached (stored as ``editor._info_bar``).
    """

    def __init__(self, editor, title, message, action_text, on_action):
        super().__init__(editor)
        # Replace any existing bar so repeated disk changes don't stack.
        old = getattr(editor, "_info_bar", None)
        if old is not None:
            old.dismiss()
        editor._info_bar = self

        self._editor = editor
        self.setObjectName("infoBar")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(12)

        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("infoTitle")
        msg_lbl = QtWidgets.QLabel(message)
        msg_lbl.setObjectName("infoMessage")
        text.addWidget(title_lbl)
        text.addWidget(msg_lbl)
        layout.addLayout(text)
        layout.addStretch(1)

        action = QtWidgets.QPushButton(action_text)
        action.setObjectName("infoAction")
        action.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        action.clicked.connect(lambda: self._run(on_action))
        layout.addWidget(action, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        close = QtWidgets.QToolButton()
        close.setObjectName("infoClose")
        close.setText("✕")                       # ✕
        close.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        editor.installEventFilter(self)
        self._reposition()
        self.show()

    # ------------------------------------------------------------------
    def _run(self, on_action):
        # Dismiss first so the action (e.g. reload, which resets the
        # viewport margins itself) sees a clean editor.
        self.dismiss()
        on_action()

    def eventFilter(self, obj, event):
        if obj is self._editor and event.type() in (
                QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show):
            self._reposition()
        return False

    def _reposition(self):
        height = self.sizeHint().height()
        self.setGeometry(0, 0, self._editor.width(), height)
        # Push the text viewport down so the strip never covers content.
        self._editor.setViewportMargins(0, height, 0, 0)

    def dismiss(self):
        if self._editor is None:
            return
        self._editor.setViewportMargins(0, 0, 0, 0)
        self._editor.removeEventFilter(self)
        if getattr(self._editor, "_info_bar", None) is self:
            self._editor._info_bar = None
        self._editor = None
        self.deleteLater()
