# =========================================================================
#             FILE: RemoveItemsDialog.py
#
#      DESCRIPTION: A reusable, searchable, multi-select removal dialog.
#                   Replaces the old "pick one item from a giant unscrollable
#                   QComboBox" pattern used by the NgVeri tab to delete Verilog
#                   models and lint_off entries.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

from PyQt6 import QtCore, QtGui, QtWidgets
# Dual-layout import so this file is byte-identical in both homes (a drift test
# enforces it). eSim runs it as part of the ``maker`` package and resolves the
# ``configuration`` package; NGHDL is packaged standalone with a flat module
# namespace and a vendored, byte-identical ``Dialogs.py`` sitting beside this
# copy, so the package import fails there and the flat import takes over.
try:
    from configuration import Dialogs
except ImportError:                       # NGHDL standalone / vendored layout
    import Dialogs


# Backend badge colours (NgVeri tab). Kept here so the legend and the per-row
# dots can never drift apart.
BADGE_COLOURS = {
    "NgVeri": "#2e7d32",    # green   -- legacy Verilator -> Ngveri.cm
    "d_cosim": "#1565c0",   # blue    -- Icarus -> eSim_NgVeriCosim
    "Nghdl": "#e65100",     # orange  -- GHDL/NGHDL -> ghdl.cm
}
_DEFAULT_BADGE_COLOUR = "#616161"


class RemoveItemsDialog(QtWidgets.QDialog):
    """A modal "remove these items" picker.

    Solves the three problems of the old QComboBox approach:
      * a real scrollbar (a QListWidget, never the stylesheet-crippled combo
        popup that rendered the whole list with no scroll),
      * a live search box to find an item in a long list, and
      * multi-select, so several models can be torn down in one pass.

    Usage::

        dlg = RemoveItemsDialog("Remove Verilog Models", names,
                                badges={name: "NgVeri"/"d_cosim", ...},
                                item_noun="model", parent=self)
        if dlg.exec():
            for name in dlg.selected_items():
                ...

    The caller owns the actual teardown; this dialog only collects the choice.
    """

    def __init__(self, title, items, badges=None, item_noun="item",
                 parent=None):
        super().__init__(parent)
        self._item_noun = item_noun
        self._badges = badges or {}

        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(420, 460)

        layout = QtWidgets.QVBoxLayout(self)

        # --- search box ---------------------------------------------------
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search " + item_noun + "s…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        # --- optional backend legend -------------------------------------
        distinct = sorted({self._badges[k] for k in self._badges})
        if len(distinct) > 1:
            legend = QtWidgets.QHBoxLayout()
            legend.setSpacing(12)
            for label in distinct:
                dot = QtWidgets.QLabel()
                dot.setPixmap(self._dot(self._colour(label)).pixmap(12, 12))
                legend.addWidget(dot)
                legend.addWidget(QtWidgets.QLabel(label))
            legend.addStretch(1)
            layout.addLayout(legend)

        # --- the list itself ---------------------------------------------
        self.listw = QtWidgets.QListWidget()
        self.listw.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listw.setAlternatingRowColors(True)
        self.listw.setUniformItemSizes(True)
        self.listw.itemSelectionChanged.connect(self._update_state)
        layout.addWidget(self.listw, 1)

        for name in sorted(items, key=lambda s: s.lower()):
            item = QtWidgets.QListWidgetItem(name)
            badge = self._badges.get(name)
            if badge:
                item.setIcon(self._dot(self._colour(badge)))
                item.setToolTip(badge + " model")
            self.listw.addItem(item)

        if self.listw.count() == 0:
            empty = QtWidgets.QListWidgetItem(
                "(no " + item_noun + "s to remove)")
            empty.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.listw.addItem(empty)

        # --- footer: count + buttons -------------------------------------
        self.status = QtWidgets.QLabel("0 selected")
        layout.addWidget(self.status)

        self.buttons = QtWidgets.QDialogButtonBox()
        self.remove_btn = self.buttons.addButton(
            "Remove Selected",
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        # Destructive action → Aurora danger button (themed red), instead of
        # red text fighting the global cyan-gradient button background.
        self.remove_btn.setProperty("cssClass", "danger")
        self.buttons.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._update_state()
        self.search.setFocus()

    # ------------------------------------------------------------------ #
    #  Pure helpers (unit-tested without a QApplication where possible)
    # ------------------------------------------------------------------ #
    @staticmethod
    def matches(name, query):
        """Case-insensitive substring match; an empty query matches all."""
        q = (query or "").strip().lower()
        return q in (name or "").lower()

    def _colour(self, badge):
        return BADGE_COLOURS.get(badge, _DEFAULT_BADGE_COLOUR)

    @staticmethod
    def _dot(colour):
        """A small round colour swatch used as a row icon / legend marker."""
        pix = QtGui.QPixmap(12, 12)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor(colour))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        return QtGui.QIcon(pix)

    # ------------------------------------------------------------------ #
    #  Behaviour
    # ------------------------------------------------------------------ #
    def _apply_filter(self, text):
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            self.listw.setRowHidden(i, not self.matches(item.text(), text))

    def _update_state(self):
        n = len(self.listw.selectedItems())
        self.status.setText(str(n) + " selected")
        self.remove_btn.setEnabled(n > 0)

    def selected_items(self):
        """Names the user chose to remove (empty if cancelled)."""
        return [it.text() for it in self.listw.selectedItems()]

    def _on_accept(self):
        names = self.listw.selectedItems()
        if not names:
            return
        ret = Dialogs.warning(
            self, "Confirm removal",
            "<b>Remove " + str(len(names)) + " " + self._item_noun +
            ("s" if len(names) != 1 else "") + "?</b><br>"
            "This cannot be undone.",
            QtWidgets.QMessageBox.StandardButton.Ok |
            QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel)
        if ret == QtWidgets.QMessageBox.StandardButton.Ok:
            self.accept()
