"""Inline find / replace bar embedded under the editor tabs.

Not a dock widget -- it sits in the central layout, opens with Ctrl+F
(replace row with Ctrl+H) and closes with Escape, the way every modern
editor's find bar behaves.  Highlights all matches live and shows a
match count.
"""

from PyQt6 import QtCore, QtGui, QtWidgets


class FindBar(QtWidgets.QFrame):
    """Slim incremental find/replace bar bound to the active editor."""

    def __init__(self, parent=None, host=None):
        super().__init__(parent)
        self.setObjectName("findBar")
        # The window that owns the editor area; it repositions this
        # floating overlay (see EditorWindow._position_find_bar).
        self._host = host
        self._editor = None
        self._idx = -1

        # Debounce live re-search so typing in a big file stays smooth.
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._run_search)

        self._build()
        self.hide()

        esc = QtGui.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key.Key_Escape), self)
        esc.activated.connect(self.close_bar)

    # ── construction ─────────────────────────────────────────────────
    def _build(self):
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        # Left chevron toggles the replace row inline (VS Code style),
        # so one Ctrl+F bar does both find and replace.
        self._expand = QtWidgets.QToolButton()
        self._expand.setObjectName("findExpand")
        self._expand.setCheckable(True)
        self._expand.setText("›")
        self._expand.setToolTip("Toggle Replace")
        self._expand.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._expand.toggled.connect(self._set_replace_visible)

        # Field widths are design pixels; zoom_px keeps them in step with the
        # font the QSS grows, so the bar does not squeeze its own inputs.
        from frontEnd.theme_utils import zoom_px
        self._find_edit = QtWidgets.QLineEdit()
        self._find_edit.setPlaceholderText("Find")
        self._find_edit.setClearButtonEnabled(True)
        self._find_edit.setMinimumWidth(zoom_px(240))
        self._find_edit.textChanged.connect(self._search_timer.start)
        # Enter = next, Shift+Enter = previous (VS Code).
        self._find_edit.returnPressed.connect(self._on_find_return)

        self._count = QtWidgets.QLabel("")
        self._count.setObjectName("findCount")
        self._count.setMinimumWidth(zoom_px(80))
        self._count.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self._case = self._toggle("Aa", "Match case (Alt+C)")
        self._word = self._toggle("W", "Whole word (Alt+W)")
        self._regex = self._toggle(".*", "Regular expression (Alt+R)")
        for box in (self._case, self._word, self._regex):
            box.toggled.connect(self._update)

        prev_btn = self._tool("↑", "Previous (Shift+Enter)",
                              self.find_prev)
        next_btn = self._tool("↓", "Next (Enter)", self.find_next)
        close_btn = self._tool("✕", "Close (Esc)", self.close_bar)
        close_btn.setObjectName("findClose")

        self._replace_edit = QtWidgets.QLineEdit()
        self._replace_edit.setPlaceholderText("Replace")
        self._replace_edit.setClearButtonEnabled(True)
        self._replace_edit.setMinimumWidth(zoom_px(240))
        # Enter = replace this match, Ctrl+Enter = replace all (VS Code).
        self._replace_edit.returnPressed.connect(self._on_replace_return)
        self._rep_btn = QtWidgets.QPushButton("Replace")
        self._rep_btn.setToolTip("Replace this match (Enter)")
        self._rep_btn.clicked.connect(self.replace_one)
        self._rep_all_btn = QtWidgets.QPushButton("All")
        self._rep_all_btn.setToolTip("Replace all matches (Ctrl+Enter)")
        self._rep_all_btn.clicked.connect(self.replace_all)

        # chevron spans both rows so it sits beside find + replace
        grid.addWidget(self._expand, 0, 0, 2, 1)
        grid.addWidget(self._find_edit, 0, 1)
        grid.addWidget(self._count, 0, 2)
        grid.addWidget(self._case, 0, 3)
        grid.addWidget(self._word, 0, 4)
        grid.addWidget(self._regex, 0, 5)
        grid.addWidget(prev_btn, 0, 6)
        grid.addWidget(next_btn, 0, 7)
        grid.addWidget(close_btn, 0, 8)
        grid.addWidget(self._replace_edit, 1, 1)
        grid.addWidget(self._rep_btn, 1, 3, 1, 3)
        grid.addWidget(self._rep_all_btn, 1, 6, 1, 3)
        grid.setColumnStretch(1, 1)

        self._replace_widgets = (
            self._replace_edit, self._rep_btn, self._rep_all_btn)
        self._set_replace_visible(False)        # collapsed by default

        # Tab walks Find → Replace → option toggles, like VS Code.
        self.setTabOrder(self._find_edit, self._replace_edit)
        self.setTabOrder(self._replace_edit, self._case)
        self.setTabOrder(self._case, self._word)
        self.setTabOrder(self._word, self._regex)

        # Option-toggle and select-all-matches accelerators (active only
        # while the find bar has focus), matching VS Code's bindings.
        self._shortcut("Alt+C", self._case.toggle)
        self._shortcut("Alt+W", self._word.toggle)
        self._shortcut("Alt+R", self._regex.toggle)
        self._shortcut("Alt+Return", self._select_all_matches)
        self._shortcut("Alt+Enter", self._select_all_matches)
        # Down/Up step through matches too (the find field is one line,
        # so the arrows are otherwise unused) -- discoverable nav next to
        # Enter/Shift+Enter and F3/Shift+F3.
        self._shortcut("Down", self.find_next)
        self._shortcut("Up", self.find_prev)

    def _shortcut(self, sequence, slot):
        sc = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
        sc.setContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(slot)
        return sc

    def _toggle(self, text, tip):
        btn = QtWidgets.QToolButton()
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setCheckable(True)
        btn.setObjectName("findToggle")
        return btn

    def _tool(self, text, tip, slot):
        btn = QtWidgets.QToolButton()
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setObjectName("findTool")
        btn.clicked.connect(slot)
        return btn

    # ── public API (driven by EditorWindow) ──────────────────────────
    def _active(self):
        """The editor if it supports search (QScintilla), else None."""
        if self._editor is not None and hasattr(self._editor, "search_all"):
            return self._editor
        return None

    def set_editor(self, editor):
        if self._active() is not None and self._editor is not editor:
            self._editor.clear_search()
        self._editor = editor
        if self.isVisible():
            self._update()

    def open_find(self):
        # Keep whatever replace state the chevron is in (VS Code style).
        self._reveal()

    def open_replace(self):
        self._expand.setChecked(True)        # reveals the replace row
        self._reveal()
        self._replace_edit.setFocus()

    def close_bar(self):
        if self._active() is not None:
            self._editor.clear_search()
        if self._editor is not None:
            self._editor.setFocus()
        self.hide()

    # ── behaviour ────────────────────────────────────────────────────
    def _reveal(self):
        self.show()
        seed = self._selected_seed()
        if seed:
            self._find_edit.setText(seed)
        self._reposition()
        self._find_edit.setFocus()
        self._find_edit.selectAll()
        self._update()

    def _reposition(self):
        """Ask the host to re-pin the overlay (size may have changed)."""
        if self._host is not None:
            self._host._position_find_bar()

    def _set_replace_visible(self, visible):
        self._expand.setText("⌄" if visible else "›")
        if self._expand.isChecked() != visible:
            self._expand.setChecked(visible)
        for widget in self._replace_widgets:
            widget.setVisible(visible)
        # Height changed; re-pin so the overlay stays in the corner.
        self._reposition()

    def _selected_seed(self):
        if self._editor is None or not self._editor.hasSelectedText():
            return ""
        text = self._editor.selectedText()
        return text if "\n" not in text else ""

    def _flags(self):
        return (self._regex.isChecked(), self._case.isChecked(),
                self._word.isChecked())

    def _run_search(self):
        """Debounced live search (fired by the typing timer)."""
        self._update()

    def _update(self):
        self._search_timer.stop()
        if self._active() is None:
            self._count.setText("")
            return
        query = self._find_edit.text()
        regex, case, word = self._flags()
        count = self._editor.search_all(query, regex, case, word)
        if not query:
            self._idx = -1
            self._count.setText("")
            self._set_no_match(False)
        elif count == 0:
            self._idx = -1
            self._count.setText("No results")
            self._set_no_match(True)
        else:
            self._idx = self._editor.nearest_match_index()
            self._editor.select_match(self._idx)
            self._show_position()
            self._set_no_match(False)

    def _set_no_match(self, no_match):
        """Flag the find box red when the query has no matches."""
        if self._find_edit.property("noMatch") == no_match:
            return
        self._find_edit.setProperty("noMatch", no_match)
        self._find_edit.style().unpolish(self._find_edit)
        self._find_edit.style().polish(self._find_edit)

    def _show_position(self):
        total = self._editor.match_count()
        if total:
            self._count.setText("%d of %d" % (self._idx + 1, total))

    def find_next(self):
        self._step(1)

    def find_prev(self):
        self._step(-1)

    def _step(self, delta):
        if self._active() is None:
            return
        if self._editor.match_count() == 0:
            self._update()
            return
        self._idx = (self._idx + delta) % self._editor.match_count()
        self._editor.select_match(self._idx)
        self._show_position()

    def _on_find_return(self):
        shift = (QtWidgets.QApplication.keyboardModifiers()
                 & QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.find_prev() if shift else self.find_next()

    def _on_replace_return(self):
        ctrl = (QtWidgets.QApplication.keyboardModifiers()
                & QtCore.Qt.KeyboardModifier.ControlModifier)
        self.replace_all() if ctrl else self.replace_one()

    def _select_all_matches(self):
        if self._active() is None or self._editor.match_count() == 0:
            return
        self._editor.select_all_matches()

    def replace_one(self):
        if self._active() is None or self._editor.isReadOnly():
            return
        # Only replace when the selection is the current match; a stray
        # manual selection should not be clobbered.
        if self._editor.hasSelectedText() and self._selection_is_match():
            self._editor.replace(self._replace_edit.text())
        self._update()    # re-search; selects the next match after caret

    def _selection_is_match(self):
        """True if the live selection equals the search query."""
        regex, case, _word = self._flags()
        if regex:
            return True            # can't cheaply verify a regex match
        selected = self._editor.selectedText()
        query = self._find_edit.text()
        if case:
            return selected == query
        return selected.lower() == query.lower()

    def replace_all(self):
        if self._active() is None or self._editor.isReadOnly():
            return
        if not self._find_edit.text():
            return
        # search_all has already populated the match set with the same
        # (Python-regex) engine the count is shown for, so the replaced
        # total always matches the displayed count.
        self._update()
        count = self._editor.replace_all_matches(self._replace_edit.text())
        self._update()
        self._count.setText("Replaced %d" % count)
