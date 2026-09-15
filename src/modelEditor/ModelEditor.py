from PyQt6 import QtWidgets, QtCore
from configuration import Dialogs
from configuration import paths
from PyQt6.QtWidgets import QTableWidgetItem
import xml.etree.ElementTree as ET
from configuration.Appconfig import Appconfig
import os


class ParameterEditDelegate(QtWidgets.QStyledItemDelegate):
    '''
    - Editor delegate for the parameter table.
    - The default in-cell editor was a short, inset pill: its text was clipped
      top-and-bottom and the teal "selected cell" fill showed all around it, so
      the value being edited looked like an unreadable blue box.
    - This makes the editor fill the whole cell (room for the text, and it
      covers the teal underneath), paints an opaque themed background, and opens
      showing the value with the caret at the end — no select-all block over it.
    '''

    def _is_dark(self):
        from PyQt6 import QtGui
        try:
            from frontEnd import theme_utils
            mode = theme_utils.get_preferences().get(
                'theme_mode', 'System')
            if mode == 'Dark':
                return True
            if mode == 'Light':
                return False
        except Exception:
            pass
        try:
            from frontEnd.theme_utils import system_is_dark
            return system_is_dark()
        except Exception:
            return False

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QtWidgets.QLineEdit):
            if self._is_dark():
                bg, fg, border = "#0E1728", "#F8FBFF", "#53D7FF"
                sel_bg, sel_fg = "#0E7490", "#FFFFFF"
            else:
                bg, fg, border = "#FFFFFF", "#142033", "#0077A8"
                sel_bg, sel_fg = "#0077A8", "#FFFFFF"
            editor.setStyleSheet(
                "QLineEdit{{margin:0;padding:0 8px;border:2px solid %(b)s;"
                "border-radius:8px;background:%(bg)s;color:%(fg)s;"
                "selection-background-color:%(sb)s;selection-color:%(sf)s;}}"
                % {"b": border, "bg": bg, "fg": fg,
                   "sb": sel_bg, "sf": sel_fg}
            )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        # Fill the whole cell: gives the text vertical room (no clipping) and
        # fully hides the teal selection fill behind the editor.
        editor.setGeometry(option.rect)

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        if isinstance(editor, QtWidgets.QLineEdit):
            # Runs after Qt's built-in select-all, clearing it.
            QtCore.QTimer.singleShot(
                0, lambda: (editor.deselect(), editor.end(False)))


class ModelEditorclass(QtWidgets.QWidget):
    '''
    - Initialise the layout for dockarea
    - Use QVBoxLayout, QSplitter, QGridLayout to define the layout
    - Initalise directory to save new models,
      savepathtest = 'library/deviceModelLibrary'
    - Initialise buttons and options ====>
        - Name            Function Called
    ========================================
        - New             opennew
        - Edit            openedit
        - Save            savemodelfile
        - Upload          converttoxml
        - Add             addparameters
        - Remove          removeparameter
        - Diode           diode_click
        - BJT             bjt_click
        - MOS             mos_click
        - JFET            jfet_click
        - IGBT            igbt_click
        - Magnetic Core   magnetic_click
    '''

    def __init__(self):
        QtWidgets.QWidget.__init__(self)

        self.savepathtest = paths.library_path('deviceModelLibrary')
        self.obj_appconfig = Appconfig()
        self.newflag = 0

        # ── Root: a full-bleed column that fills the whole dock. The old
        # QGridLayout pinned the device radios to column 1 and floated a fixed
        # 200px table in a mid-panel island, so the editor sat as a small clump
        # with dead margins on every side. Here a header sits on top and a body
        # row (slim device rail + a parameter editor that grows) stretches all
        # the way down to the dock floor.
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # ── Header ───────────────────────────────────────────────────────
        title = QtWidgets.QLabel("Model Editor")
        title.setProperty("cssClass", "title")
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Create, edit and import SPICE device-model libraries — diodes, "
            "transistors, MOSFETs, JFETs, IGBTs and magnetic cores — then save "
            "them into your project's model library."
        )
        subtitle.setProperty("cssClass", "muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # ── File actions (full-width toolbar) ────────────────────────────
        # New / Edit / Upload are quiet ghost buttons; Save is the accent CTA,
        # pushed to the right edge and disabled until there's something to save.
        file_group = QtWidgets.QGroupBox("Library")
        file_group.setProperty("cssClass", "themedGroupBox")
        file_row = QtWidgets.QHBoxLayout(file_group)
        file_row.setSpacing(10)

        self.newbtn = QtWidgets.QPushButton('New')
        self.newbtn.setProperty("cssClass", "secondary")
        self.newbtn.setMinimumHeight(38)
        self.newbtn.setToolTip('<b>Create a new model library</b>')
        self.newbtn.clicked.connect(self.opennew)

        self.editbtn = QtWidgets.QPushButton('Edit')
        self.editbtn.setProperty("cssClass", "secondary")
        self.editbtn.setMinimumHeight(38)
        self.editbtn.setToolTip('<b>Edit an existing model library</b>')
        self.editbtn.clicked.connect(self.openedit)

        self.uploadbtn = QtWidgets.QPushButton('Upload .lib')
        self.uploadbtn.setProperty("cssClass", "secondary")
        self.uploadbtn.setMinimumHeight(38)
        self.uploadbtn.setToolTip(
            '<b>Import an external .lib file into eSim</b>')
        self.uploadbtn.clicked.connect(self.converttoxml)

        self.savebtn = QtWidgets.QPushButton('Save')
        # Commit action — the primary accent button of this toolbar.
        self.savebtn.setProperty("cssClass", "primary")
        self.savebtn.setMinimumHeight(38)
        self.savebtn.setToolTip('<b>Save the model library</b>')
        self.savebtn.setDisabled(True)
        self.savebtn.clicked.connect(self.savemodelfile)

        file_row.addWidget(self.newbtn)
        file_row.addWidget(self.editbtn)
        file_row.addWidget(self.uploadbtn)
        file_row.addStretch(1)
        file_row.addWidget(self.savebtn)
        root.addWidget(file_group)

        # ── Device rail (left of the body) ───────────────────────────────
        # The six device types stacked as a slim rail; disabled until New is
        # clicked, exactly as before, but now grouped and legible.
        device_group = QtWidgets.QGroupBox("Device type")
        device_group.setProperty("cssClass", "themedGroupBox")
        device_group.setMaximumWidth(220)
        device_col = QtWidgets.QVBoxLayout(device_group)
        device_col.setSpacing(12)

        self.radiobtnbox = QtWidgets.QButtonGroup()
        self.diode = QtWidgets.QRadioButton('Diode')
        self.bjt = QtWidgets.QRadioButton('BJT')
        self.mos = QtWidgets.QRadioButton('MOS')
        self.jfet = QtWidgets.QRadioButton('JFET')
        self.igbt = QtWidgets.QRadioButton('IGBT')
        self.magnetic = QtWidgets.QRadioButton('Magnetic Core')
        for rb in (self.diode, self.bjt, self.mos,
                   self.jfet, self.igbt, self.magnetic):
            rb.setDisabled(True)
            self.radiobtnbox.addButton(rb)
            device_col.addWidget(rb)
        device_col.addStretch(1)

        self.diode.clicked.connect(self.diode_click)
        self.bjt.clicked.connect(self.bjt_click)
        self.mos.clicked.connect(self.mos_click)
        self.jfet.clicked.connect(self.jfet_click)
        self.igbt.clicked.connect(self.igbt_click)
        self.magnetic.clicked.connect(self.magnetic_click)

        # ── Parameter editor (right of the body, grows to fill) ──────────
        param_group = QtWidgets.QGroupBox("Parameters")
        param_group.setProperty("cssClass", "themedGroupBox")
        param_col = QtWidgets.QVBoxLayout(param_group)
        param_col.setSpacing(12)

        # Dropdown for the sub-types of a device (e.g. BJT → NPN / PNP).
        self.types = QtWidgets.QComboBox()
        self.types.setMinimumHeight(34)
        self.types.setHidden(True)
        param_col.addWidget(self.types)

        # Holder: an empty-state hint until a model is loaded, then the
        # parameter table is mounted in its place by createtable().
        self.table_holder = QtWidgets.QVBoxLayout()
        self.placeholder = QtWidgets.QLabel(
            "Pick a device type after New, or open a library with Edit, "
            "to view and edit its parameters."
        )
        self.placeholder.setProperty("cssClass", "muted")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter)
        self.table_holder.addWidget(self.placeholder)
        param_col.addLayout(self.table_holder, 1)

        # Kept as an unmounted stub so early setHidden() calls (opennew,
        # converttoxml) are safe before any real table exists.
        self.modeltable = QtWidgets.QTableWidget()

        # Add / Remove row beneath the table.
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(10)
        self.addbtn = QtWidgets.QPushButton('Add parameter')
        self.addbtn.setMinimumHeight(34)
        self.addbtn.setHidden(True)
        self.addbtn.clicked.connect(self.addparameters)
        self.removebtn = QtWidgets.QPushButton('Remove')
        # Destructive — flat red danger styling.
        self.removebtn.setProperty("cssClass", "danger")
        self.removebtn.setMinimumHeight(34)
        self.removebtn.setHidden(True)
        self.removebtn.clicked.connect(self.removeparameter)
        action_row.addStretch(1)
        action_row.addWidget(self.addbtn)
        action_row.addWidget(self.removebtn)
        param_col.addLayout(action_row)

        # ── Body row: slim device rail + growing editor, stretched to floor.
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(device_group, 0)
        body.addWidget(param_group, 1)
        root.addLayout(body, 1)

    def _mount_table(self, table):
        '''
        - Swap the placeholder / any previous table out of the holder and drop
          the freshly built `table` in, so the editor body always fills the
          Parameters group instead of floating in a fixed-size island.
        '''
        self.placeholder.setHidden(True)
        for i in reversed(range(self.table_holder.count())):
            w = self.table_holder.itemAt(i).widget()
            if w is not None and w is not self.placeholder:
                self.table_holder.takeAt(i)
                w.setParent(None)
        table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.table_holder.addWidget(table, 1)

    def _show_placeholder(self):
        '''
        - Tear any mounted table back out and restore the empty-state hint,
          used when a flow resets the editor (New, Upload).
        '''
        for i in reversed(range(self.table_holder.count())):
            w = self.table_holder.itemAt(i).widget()
            if w is not None and w is not self.placeholder:
                self.table_holder.takeAt(i)
                w.setParent(None)
        self.placeholder.setHidden(False)

    def opennew(self):
        '''
        - To create New Model file
        - Change state of other buttons accordingly, ex. enable diode, bjt, ...
        - Validate filename created, to check if one already exists
        '''
        self.addbtn.setHidden(True)
        try:
            self.removebtn.setHidden(True)
            self._show_placeholder()
        except BaseException:
            pass

        # Opens new dialog box
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'New Model', 'Enter Model Name:'
        )

        if ok:
            if not text:
                print("Model name cannot be empty")
                print("==================")
                Dialogs.critical(
                    self, "Error Message", 'The model name cannot be empty')
                return

            self.newflag = 1
            self.diode.setDisabled(False)
            self.bjt.setDisabled(False)
            self.mos.setDisabled(False)
            self.jfet.setDisabled(False)
            self.igbt.setDisabled(False)
            self.magnetic.setDisabled(False)
            self.modelname = (str(text))
        else:
            return

        # Validate if the file created exists already or not
        # Show error accordingly
        self.validation(text)

    def diode_click(self):
        '''
        - Call function, openfiletype, which opens the table view\
            for Diode specs
        - Set states for other elements
        - Diode has no types, so hide that
        '''
        self.openfiletype('Diode')
        self.types.setHidden(True)

    def bjt_click(self):
        '''
        - Set states for other elements
        - Initialise types combo box elements
        - - NPN
        - - PNP
        - Open the default type in the table
        - Add an event listener for type-selection event
        '''
        self.types.setHidden(False)
        self.types.clear()
        self.types.addItem('NPN')
        self.types.addItem('PNP')
        # Open in table default
        filetype = str(self.types.currentText())
        self.openfiletype(filetype)
        # When element selected from combo box, call setfiletype
        self.types.currentTextChanged.connect(self.setfiletype)

    def mos_click(self):
        '''
        - Set states for other elements
        - Initialise types combo box elements
        - - NMOS(Level-1 5um)
        - - NMOS(Level-3 0.5um)
        - - ...
        - Open the default type in the table
        - Add an event listener for type-selection event
        '''
        self.types.setHidden(False)
        self.types.clear()
        self.types.addItem('NMOS(Level-1 5um)')
        self.types.addItem('NMOS(Level-3 0.5um)')
        self.types.addItem('NMOS(Level-8 180um)')
        self.types.addItem('PMOS(Level-1 5um)')
        self.types.addItem('PMOS(Level-3 0.5um)')
        self.types.addItem('PMOS(Level-8 180um)')
        filetype = str(self.types.currentText())
        self.openfiletype(filetype)
        self.types.currentTextChanged.connect(self.setfiletype)

    def jfet_click(self):
        '''
        - Set states for other elements
        - Initialise types combo box elements
        - - N-JFET
        - - P-JFET
        - Open the default type in the table
        - Add an event listener for type-selection event
        '''
        self.types.setHidden(False)
        self.types.clear()
        self.types.addItem('N-JFET')
        self.types.addItem('P-JFET')
        filetype = str(self.types.currentText())
        self.openfiletype(filetype)
        self.types.currentTextChanged.connect(self.setfiletype)

    def igbt_click(self):
        '''
        - Set states for other elements
        - Initialise types combo box elements
        - - N-IGBT
        - - P-IGBT
        - Open the default type in the table
        - Add an event listener for type-selection event
        '''
        self.types.setHidden(False)
        self.types.clear()
        self.types.addItem('N-IGBT')
        self.types.addItem('P-IGBT')
        filetype = str(self.types.currentText())
        self.openfiletype(filetype)
        self.types.currentTextChanged.connect(self.setfiletype)

    def magnetic_click(self):
        '''
        - Set states for other elements
        - Initialise types combo box elements
        - Open the default type in the table
        - Add an event listener for type-selection event
        - No types here, only one view
        '''
        self.openfiletype('Magnetic Core')
        self.types.setHidden(True)

    def setfiletype(self, text):
        '''
        - Triggered when each type selected
        - Get the type clicked, from text
        - Open appropriate table using openfiletype(filetype)
        '''
        self.filetype = str(text)
        self.openfiletype(self.filetype)

    def openfiletype(self, filetype):
        '''
        - Select path for the filetype passed
        - Accordingly call `createtable(path)` to draw tables usingg QTable
        - Check for the state of button before rendering
        '''
        self.path = paths.library_path('deviceModelLibrary/Templates')
        if self.diode.isChecked():
            if filetype == 'Diode':
                path = os.path.join(self.path, 'D.xml')
                self.createtable(path)
        if self.bjt.isChecked():
            if filetype == 'NPN':
                path = os.path.join(self.path, 'NPN.xml')
                self.createtable(path)
            elif filetype == 'PNP':
                path = os.path.join(self.path, 'PNP.xml')
                self.createtable(path)
        if self.mos.isChecked():
            if filetype == 'NMOS(Level-1 5um)':
                path = os.path.join(self.path, 'NMOS-5um.xml')
                self.createtable(path)
            elif filetype == 'NMOS(Level-3 0.5um)':
                path = os.path.join(self.path, 'NMOS-0.5um.xml')
                self.createtable(path)
            elif filetype == 'NMOS(Level-8 180um)':
                path = os.path.join(self.path, 'NMOS-180nm.xml')
                self.createtable(path)
            elif filetype == 'PMOS(Level-1 5um)':
                path = os.path.join(self.path, 'PMOS-5um.xml')
                self.createtable(path)
            elif filetype == 'PMOS(Level-3 0.5um)':
                path = os.path.join(self.path, 'PMOS-0.5um.xml')
                self.createtable(path)
            elif filetype == 'PMOS(Level-8 180um)':
                path = os.path.join(self.path, 'PMOS-180nm.xml')
                self.createtable(path)
        if self.jfet.isChecked():
            if filetype == 'N-JFET':
                path = os.path.join(self.path, 'NJF.xml')
                self.createtable(path)
            elif filetype == 'P-JFET':
                path = os.path.join(self.path, 'PJF.xml')
                self.createtable(path)
        if self.igbt.isChecked():
            if filetype == 'N-IGBT':
                path = os.path.join(self.path, 'NIGBT.xml')
                self.createtable(path)
            elif filetype == 'P-IGBT':
                path = os.path.join(self.path, 'PIGBT.xml')
                self.createtable(path)
        if self.magnetic.isChecked():
            if filetype == 'Magnetic Core':
                path = os.path.join(self.path, 'CORE.xml')
                self.createtable(path)

    def openedit(self):
        '''
        - When `Edit` button clicked, this function called
        - Set states for other buttons accordingly
        - Open the file selector box with path as deviceModelLibrary
        and filetype set as .lib, save it in `self.editfile`
        - Create table for the selected .lib file using\
            `self.createtable(path)`
        - Handle exception of no file selected
        '''
        self.newflag = 0
        self.addbtn.setHidden(True)
        self.types.setHidden(True)
        self.diode.setDisabled(True)
        self.mos.setDisabled(True)
        self.jfet.setDisabled(True)
        self.igbt.setDisabled(True)
        self.bjt.setDisabled(True)
        self.magnetic.setDisabled(True)
        try:
            self.editfile = QtCore.QDir.toNativeSeparators(
                QtWidgets.QFileDialog.getOpenFileName(
                    self, "Open Library Directory",
                    paths.library_path("deviceModelLibrary"), "*.lib"
                )[0]
            )

            if self.editfile:
                self.createtable(self.editfile)
        except BaseException:
            print("No File selected for edit")

    def createtable(self, modelfile):
        '''
        - Set states for other components
        - Initialise QTable widget
        - Set options for QTable widget
        - Mount QTable widget into the Parameters holder via `_mount_table`
        - Select the `.xml` file from the modelfile passed as `.lib`
        - Use ET (xml.etree.ElementTree) to parse the xml file
        - Extract data from the XML and store it in `modeldict`
        - Show the extracted data in QTableWidget
        - Can edit QTable inplace, connect `edit_modeltable`\
            function for editing
        '''
        self.savebtn.setDisabled(False)
        self.addbtn.setHidden(False)
        self.removebtn.setHidden(False)
        self.modelfile = modelfile
        self.modeldict = {}
        self.modeltable = QtWidgets.QTableWidget()
        self.modeltable.setColumnCount(2)
        self.modeltable.setItemDelegate(ParameterEditDelegate(self.modeltable))
        vh = self.modeltable.verticalHeader()
        vh.setVisible(False)
        # Taller rows so the inline editor has room and its text isn't clipped.
        vh.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(40)
        header = self.modeltable.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._mount_table(self.modeltable)
        filepath, filename = os.path.split(self.modelfile)
        base, ext = os.path.splitext(filename)
        self.modelfile = os.path.join(filepath, base + '.xml')
        print("Model File used for creating table : ", self.modelfile)
        self.tree = ET.parse(self.modelfile)
        self.root = self.tree.getroot()
        # Default so a library whose XML omits these tags doesn't fall back to
        # a STALE value from a previously opened model (or, for ref_model, an
        # AttributeError in savethefile when it was never set at all).
        self.ref_model = None
        self.model_name = None
        for elem in self.tree.iter(tag='ref_model'):
            self.ref_model = elem.text
        for elem in self.tree.iter(tag='model_name'):
            self.model_name = elem.text
        row = 0
        # get data from XML and store to dictionary (self.modeldict)
        for params in self.tree.findall('param'):
            for paramlist in params:
                self.modeldict[paramlist.tag] = paramlist.text
                row = row + 1
        self.modeltable.setRowCount(row)
        count = 0
        # setItem in modeltable, for each item in modeldict
        for tags, values in list(self.modeldict.items()):
            self.modeltable.setItem(count, 0, QTableWidgetItem(tags))
            try:
                valueitem = QTableWidgetItem(values)
            except BaseException:
                pass
            self.modeltable.setItem(count, 1, valueitem)
            count = count + 1
        self.modeltable.setHorizontalHeaderLabels(
            ("Parameters;Values").split(";")
        )
        self.modeltable.show()
        self.modeltable.itemChanged.connect(self.edit_modeltable)

    def edit_modeltable(self):
        '''
        - Called when a cell is edited in-place in the QTableWidget.
        - Only flags the file dirty. The authoritative parameter→value map is
          rebuilt from the table at save time (_rebuild_modeldict_from_table),
          so an edit to EITHER column is captured correctly. The old handler
          wrote ``modeldict[val] = name`` unconditionally; when the parameter
          *name* column was edited it produced ``modeldict[newname] = newname``,
          dropping the real value and leaking the old key (silent corruption).
        '''
        self.savebtn.setDisabled(False)

    def _rebuild_modeldict_from_table(self):
        '''Rebuild self.modeldict from the current table contents so the table
        is the single source of truth. Skips empty/blank parameter names.'''
        rebuilt = {}
        for r in range(self.modeltable.rowCount()):
            keyitem = self.modeltable.item(r, 0)
            if keyitem is None:
                continue
            key = keyitem.text().strip()
            if not key:
                continue
            valitem = self.modeltable.item(r, 1)
            rebuilt[key] = valitem.text() if valitem is not None else ''
        self.modeldict = rebuilt

    def addparameters(self):
        '''
        - Called when `Add` button clicked beside QTableWidget
        - Open up dialog box to enter parameter and value accordingly
        - Validate if parameter already in list of parameters
        - Accordingly add parameter and value in modeldict as well as table
        - text1 => parameter, text2 => value
        '''
        text1, ok = QtWidgets.QInputDialog.getText(
            self, 'Parameter', 'Enter Parameter'
        )
        if ok:
            if not text1:
                print("Parameter name cannot be empty")
                print("==================")
                Dialogs.critical(
                    self, "Error Message",
                    'The parameter name cannot be empty')
                return
            elif text1 in {
                self.modeltable.item(r, 0).text().strip()
                for r in range(self.modeltable.rowCount())
                if self.modeltable.item(r, 0) is not None
            }:
                Dialogs.critical(
                    self, "Error Message",
                    "The paramaeter " + text1 + " is already in the list")
                return
            text2, ok = QtWidgets.QInputDialog.getText(
                self, 'Value', 'Enter Value'
            )
            if ok:
                if not text2:
                    print("Value cannot be empty")
                    print("==================")
                    Dialogs.critical(
                        self, "Error Message", 'Value cannot be empty')
                    return

                currentRowCount = self.modeltable.rowCount()
                self.modeltable.insertRow(currentRowCount)
                self.modeltable.setItem(
                    currentRowCount, 0, QTableWidgetItem(text1)
                )
                self.modeltable.setItem(
                    currentRowCount, 1, QTableWidgetItem(text2)
                )
                self.modeldict[str(text1)] = str(text2)

    def savemodelfile(self):
        '''
        - Called when save functon clicked
        - If new file created, call `createXML` file
        - Else call `savethefile`
        '''
        # The table is the source of truth — rebuild the map from it before
        # writing so an in-place parameter-name edit is captured, not corrupted.
        self._rebuild_modeldict_from_table()
        if self.newflag == 1:
            self.createXML(self.model_name)
        else:
            # A cancelled Edit file-picker leaves editfile empty; writing would
            # produce a nameless ".lib"/".xml" in the process CWD.
            editfile = getattr(self, 'editfile', '')
            if not editfile:
                Dialogs.critical(
                    self, "Error Message",
                    'No model file is open. Use New or Edit first.')
                return
            self.savethefile(editfile)

    def createXML(self, model_name):
        '''
        - Create .xml and .lib file if new model is being created
        - Save it in the corresponding component directory,\
            example Diode, IGBT..
        - For each component, separate folder is there
        - Check the contents of .lib and .xml file to\
            understand their structure
        '''
        # Map each device radio to its library sub-folder. Exactly one radio is
        # expected to be checked; reaching Save with none selected (Edit, then
        # New without picking a device type) used to fall through every branch
        # and hit ``txtfile.close()`` on an unbound name (UnboundLocalError).
        device_folders = [
            (self.diode, 'Diode'),
            (self.mos, 'MOS'),
            (self.jfet, 'JFET'),
            (self.igbt, 'IGBT'),
            (self.magnetic, 'Misc'),
            (self.bjt, 'Transistor'),
        ]
        folder = next(
            (sub for rb, sub in device_folders if rb.isChecked()), None)
        if folder is None:
            Dialogs.critical(
                self, "Error Message",
                'Select a device type before saving the model.')
            return

        self.savepath = paths.library_path('deviceModelLibrary')
        savedir = os.path.join(self.savepath, folder)
        libpath = os.path.join(savedir, self.modelname + '.lib')
        xmlpath = os.path.join(savedir, self.modelname + '.xml')

        # Absolute paths only — no os.chdir. The library tree may be read-only
        # (a Program Files / system install), where a mid-write exception used
        # to strand the whole process CWD inside the library folder. The
        # read-only case and an invalid parameter name (bad XML tag) now both
        # surface as one dialog and leave the CWD untouched.
        try:
            root = ET.Element("library")
            ET.SubElement(root, "model_name").text = model_name
            ET.SubElement(root, "ref_model").text = self.modelname
            param = ET.SubElement(root, "param")
            for tags, text in list(self.modeldict.items()):
                ET.SubElement(param, tags).text = text
            tree = ET.ElementTree(root)

            os.makedirs(savedir, exist_ok=True)
            with open(libpath, 'w') as txtfile:
                txtfile.write(
                    '.MODEL ' + self.modelname + ' ' + self.model_name + '(')
                for tags, text in list(self.modeldict.items()):
                    txtfile.write(' ' + tags + '=' + text)
                txtfile.write(' )\n')
            tree.write(xmlpath)
        except (OSError, ValueError) as e:
            Dialogs.critical(
                self, "Error Message",
                'Could not save the model into the library folder:\n' +
                savedir + '\n\nThe library may be read-only (a Program Files '
                'or system install), or a parameter name is not a valid XML '
                'tag.\n\n' + str(e))
            return

        self.obj_appconfig.print_info(
            'New ' + self.modelname + ' ' + self.model_name +
            ' library created at ' + savedir)

        msg = "Model saved successfully!"
        Dialogs.information(
            self, "Information", msg, QtWidgets.QMessageBox.StandardButton.Ok
        )

    def validation(self, text):
        '''
        - This function checks if the file (xml type) with the name\
            already exists
        - Accordingly show error message
        '''
        newfilename = text + '.xml'

        all_dir = [x[0] for x in os.walk(self.savepathtest)]
        for each_dir in all_dir:
            all_files = os.listdir(each_dir)
            if newfilename in all_files:
                Dialogs.critical(
                    self, "Error Message",
                    'The file with name ' + text + ' already exists.')

    def savethefile(self, editfile):
        '''
        - This function save the editing in the model table
        - Create .lib and .xml file for the editfile path and replace them
        - Also print Updated Library with libpath in the command window
        '''
        xmlpath, file = os.path.split(editfile)
        filename = os.path.splitext(file)[0]
        # The sibling .xml may lack <ref_model>/<model_name> (hand-made or an
        # older-format library); fall back to the file stem instead of raising
        # AttributeError when the attribute was never set.
        ref_model = getattr(self, 'ref_model', None) or filename
        model_name = getattr(self, 'model_name', None) or filename
        libpath = os.path.join(xmlpath, filename + '.lib')
        # Absolute paths, guarded: a read-only library folder or an invalid
        # parameter name (bad XML tag) surfaces as a dialog, never a raw crash.
        try:
            with open(libpath, 'w') as libfile:
                libfile.write('.MODEL ' + ref_model + ' ' + model_name + '(')
                for tags, text in list(self.modeldict.items()):
                    libfile.write(' ' + tags + '=' + text)
                libfile.write(' )\n')

            root = ET.Element("library")
            ET.SubElement(root, "model_name").text = model_name
            ET.SubElement(root, "ref_model").text = ref_model
            param = ET.SubElement(root, "param")
            for tags, text in list(self.modeldict.items()):
                ET.SubElement(param, tags).text = text
            tree = ET.ElementTree(root)
            tree.write(os.path.join(xmlpath, filename + ".xml"))
        except (OSError, ValueError) as e:
            Dialogs.critical(
                self, "Error Message",
                'Could not save the model file:\n' + libpath +
                '\n\nThe folder may be read-only, or a parameter name is not '
                'a valid XML tag.\n\n' + str(e))
            return

        self.obj_appconfig.print_info('Updated library ' + libpath)

        msg = "Model saved successfully!"
        Dialogs.information(
            self, "Information", msg, QtWidgets.QMessageBox.StandardButton.Ok
        )

    def removeparameter(self):
        '''
        - Get the index of the current selected item
        - Remove the whole row from QTable Widget
        - Remove the param,value pair from modeldict
        '''
        self.savebtn.setDisabled(False)
        index = self.modeltable.currentIndex()
        remove_item = self.modeltable.item(index.row(), 0)

        if remove_item:
            remove_item = remove_item.text()
            self.modeltable.removeRow(index.row())
            # pop-not-del: the key may be stale after a name edit (the map is
            # rebuilt from the table on save anyway), so never raise KeyError.
            self.modeldict.pop(str(remove_item), None)
        else:
            print("No parameter selected to remove")
            print("==================")
            Dialogs.critical(
                self, "Error Message", 'No parameter selected to remove')

    def converttoxml(self):
        '''
        - Called when upload button clicked
        - Used to read file form a certain location for .lib extension
        - Accordingly parse it and extract modelname and modelref
        - Also extract param value pairs
        - Take input the name of the library you want to save it as
        - Save it in `User Libraries` with the given name,
        and input from uploaded file
        '''
        self.addbtn.setHidden(True)
        self.removebtn.setHidden(True)
        self._show_placeholder()
        model_dict = {}
        stringof = []

        self.libfile = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                self, "Open Library Directory",
                paths.library_path("deviceModelLibrary"), "*.lib"
            )[0]
        )

        if not self.libfile:
            return

        try:
            with open(self.libfile) as libopen:
                content = libopen.read()
        except OSError as e:
            Dialogs.critical(
                self, "Error Message",
                'Could not read the selected .lib file:\n' + str(e))
            return

        filedata = content.split()
        modelcount = 0
        found = False
        for words in filedata:
            modelcount = modelcount + 1
            if words.lower() == '.model':
                found = True
                break
        # Need the two tokens after '.model' (ref_model, model_name). A file
        # with no '.model' line, an empty file, or '.model' as the last token
        # used to IndexError here.
        if not found or modelcount + 1 >= len(filedata):
            Dialogs.critical(
                self, "Error Message",
                'The selected file has no valid ".model" definition.')
            return
        ref_model = filedata[modelcount]
        model_name = filedata[modelcount + 1]
        model_name = list(model_name)
        modelnamecnt = 0
        flag = 0
        for chars in model_name:
            modelnamecnt = modelnamecnt + 1
            if chars == '(':
                flag = 1
                break
        if flag == 1:
            model_name = ''.join(model_name[0:modelnamecnt - 1])
        else:
            model_name = ''.join(model_name)

        stringof = list(content)

        count = 0
        for chars in stringof:
            count = count + 1
            if chars == '(':
                break
        count1 = 0
        for chars in stringof:
            count1 = count1 + 1
            if chars == ')':
                break
        stringof = stringof[count:count1 - 1]
        stopcount = []
        listofname = []
        stopcount.append(0)
        count = 0
        for chars in stringof:
            count = count + 1
            if chars == '=':
                stopcount.append(count)
        stopcount.append(count)

        i = 0
        for no in stopcount:
            try:
                listofname.append(
                    ''.join(stringof[int(stopcount[i]):int(stopcount[i + 1])]))
                i = i + 1
            except BaseException:
                pass
        listoflist = []
        listofname2 = [
            el.replace(
                '\t',
                '').replace(
                '\n',
                ' ').replace(
                '+',
                '').replace(
                    ')',
                    '').replace(
                        '=',
                '') for el in listofname]
        listofname = []
        for item in listofname2:
            listofname.append(item.rstrip().lstrip())
        for values in listofname:
            valuelist = values.split(' ')
            listoflist.append(valuelist)
        for i in range(1, len(listoflist)):
            model_dict[listoflist[0][0]] = listoflist[1][0]
            try:
                model_dict[listoflist[i][-1]] = listoflist[i + 1][0]
            except BaseException:
                pass
        # Write into the user library with absolute paths — no os.chdir, so a
        # failed write (illegal filename characters, read-only library) can no
        # longer strand the process CWD inside the library folder.
        savepath = os.path.join(self.savepathtest, 'User Libraries')
        text, ok1 = QtWidgets.QInputDialog.getText(
            self, 'Model Name', 'Enter Model Library Name'
        )
        if ok1:
            if not text:
                print("Model library name cannot be empty")
                print("==================")
                Dialogs.critical(
                    self, "Error Message",
                    'The model library name cannot be empty')
            else:
                try:
                    root = ET.Element("library")
                    ET.SubElement(root, "model_name").text = model_name
                    ET.SubElement(root, "ref_model").text = ref_model
                    param = ET.SubElement(root, "param")
                    for tags, txt in list(model_dict.items()):
                        ET.SubElement(param, tags).text = txt
                    tree = ET.ElementTree(root)
                    os.makedirs(savepath, exist_ok=True)
                    tree.write(os.path.join(savepath, text + ".xml"))
                    with open(os.path.join(savepath, text + ".lib"),
                              'w') as fileopen:
                        fileopen.write(content)
                except (OSError, ValueError) as e:
                    Dialogs.critical(
                        self, "Error Message",
                        'Could not save the model library into:\n' +
                        savepath + '\n\nThe name may contain characters not '
                        'allowed in a filename, or the library folder is '
                        'read-only.\n\n' + str(e))
