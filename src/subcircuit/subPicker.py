# ==============================================================================
#          FILE: subPicker.py
#
#   DESCRIPTION: The "which subcircuit?" dialog behind the Edit button.
#
#                Edit used to open a bare OS folder dialog rooted at
#                ``library/SubcircuitLibrary``. That library ships over seven
#                hundred folders, so choosing one meant scrolling an
#                alphabetical wall of names with nothing to distinguish them --
#                no search, no way to see which subcircuit a folder actually
#                holds (119 of them are named differently from their ``.sub``),
#                and no way to tell a finished model from a schematic somebody
#                started and never converted.
#
#                This lists the same folders with the facts that decide the
#                choice, filters as you type, and reports the subcircuit's
#                identity rather than the folder's name. The folder dialog is
#                still one click away as "Browse..." so nothing that worked
#                before stops working -- a subcircuit living outside the
#                library is still reachable exactly as it was.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

from PyQt6 import QtCore, QtWidgets

from subcircuit import subPaths


class SubcircuitPicker(QtWidgets.QDialog):
    """Searchable list of the Subcircuit Library.

    ``chosen`` holds ``(folder, stem)`` after an accepted dialog. ``browse`` is
    True instead when the user asked for the plain folder dialog, which the
    caller then runs -- keeping this dialog free of any file-dialog behaviour
    of its own.
    """

    #: Column layout. Kept as data so the header, the row builder and the
    #: tests all agree on what is shown.
    COLUMNS = ('Subcircuit', 'Ports', 'Netlist', 'Model', 'Folder')

    def __init__(self, library_root, parent=None):
        super(SubcircuitPicker, self).__init__(parent)
        self.setWindowTitle("Open Subcircuit")
        self.chosen = None
        self.browse = False
        self._rows = []

        layout = QtWidgets.QVBoxLayout(self)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search subcircuits…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._applyFilter)
        layout.addWidget(self.search)

        self.table = QtWidgets.QTreeWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHeaderLabels(list(self.COLUMNS))
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemDoubleClicked.connect(lambda *_: self._accept())
        self.table.itemSelectionChanged.connect(self._syncOpenButton)
        layout.addWidget(self.table, 1)

        self.summary = QtWidgets.QLabel()
        self.summary.setProperty("cssClass", "muted")
        layout.addWidget(self.summary)

        buttons = QtWidgets.QDialogButtonBox()
        self.open_btn = buttons.addButton(
            "Open", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.browse_btn = buttons.addButton(
            "Browse…", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.open_btn.clicked.connect(self._accept)
        self.browse_btn.clicked.connect(self._browse)
        self.browse_btn.setToolTip(
            "Pick a folder anywhere on disk, the way Edit always has")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(760, 460)
        self._load(library_root)

    # -- population ----------------------------------------------------------

    def _load(self, library_root):
        """Fill the list from the library, most useful information first."""
        self._rows = subPaths.scan_library(library_root)
        for row in self._rows:
            # A folder whose identity cannot be resolved still gets a line --
            # hiding it would make a subcircuit that exists look like one that
            # does not. It simply cannot be opened without choosing a stem.
            stem = row['stem'] or row['name']
            item = QtWidgets.QTreeWidgetItem([
                stem,
                self._portText(row),
                'yes' if row['has_netlist'] else '—',
                'yes' if row['has_model'] else '—',
                row['name'],
            ])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, row)
            if row['status'] == 'ambiguous':
                item.setToolTip(0, 'This folder holds several subcircuits; '
                                   'eSim cannot tell which one is its own.')
            elif not row['has_schematic']:
                item.setToolTip(0, 'No schematic in this folder — it holds a '
                                   'model file only.')
            self.table.addTopLevelItem(item)
        for col in range(len(self.COLUMNS)):
            self.table.resizeColumnToContents(col)
        self._applyFilter('')

    def _portText(self, row):
        """Port count read off the ``.sub`` header, or a dash when unbuilt."""
        if not row['has_model']:
            return '—'
        ports = subPaths.subckt_ports(
            subPaths.model_path(row['path'], row['stem']))
        return '—' if ports is None else str(len(ports))

    # -- filtering -----------------------------------------------------------

    def _applyFilter(self, text):
        """Match on both the subcircuit name and its folder.

        Both matter: users look for the part number they know, and that may be
        either the folder (``74HC123``) or the model inside it
        (``multivibrator``).
        """
        needle = text.strip().lower()
        shown = 0
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i)
            haystack = (item.text(0) + ' ' + item.text(4)).lower()
            hidden = bool(needle) and needle not in haystack
            item.setHidden(hidden)
            shown += 0 if hidden else 1
        self.summary.setText(
            '%d of %d subcircuits' % (shown, len(self._rows)))
        self._selectFirstVisible()
        self._syncOpenButton()

    def _selectFirstVisible(self):
        if self.table.selectedItems():
            if not self.table.selectedItems()[0].isHidden():
                return
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i)
            if not item.isHidden():
                self.table.setCurrentItem(item)
                return
        self.table.clearSelection()

    # -- result --------------------------------------------------------------

    def selectedRow(self):
        items = self.table.selectedItems()
        if not items or items[0].isHidden():
            return None
        return items[0].data(0, QtCore.Qt.ItemDataRole.UserRole)

    def _syncOpenButton(self):
        """Open stays disabled for a row eSim cannot identify, with the reason
        on the button rather than in an error dialog after the click."""
        row = self.selectedRow()
        ok = bool(row and row['stem'])
        self.open_btn.setEnabled(ok)
        if row and not row['stem']:
            self.open_btn.setToolTip(
                'This folder holds several subcircuits and none is named '
                'after it — open it with Browse… to choose one.')
        else:
            self.open_btn.setToolTip('')

    def _accept(self):
        row = self.selectedRow()
        if not row or not row['stem']:
            return
        self.chosen = (row['path'], row['stem'])
        self.accept()

    def _browse(self):
        """Hand back to the folder dialog Edit always used."""
        self.browse = True
        self.accept()
