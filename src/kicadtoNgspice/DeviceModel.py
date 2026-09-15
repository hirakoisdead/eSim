from PyQt6 import QtWidgets, QtCore
from configuration import Dialogs
from configuration import paths
import os
from xml.etree import ElementTree as ET
from . import TrackWidget
from . import ModelGrouping
from .ModelGroupWidget import (ModelGroupWidget, InstanceRow,
                               finish_group_layout)
from projManagement import modelCache
from projManagement.projectPaths import previous_values_path
from frontEnd.theme_utils import zoom_px


class DeviceModel(QtWidgets.QWidget):
    """
    - This class creates Device Library Tab in KicadtoNgspice Window
      It dynamically creates the widget for device like diode,mosfet,
      transistor and jfet.
    - Same function as the subCircuit file, except for
      this takes different parameters in the if block
        - q   TRANSISTOR
        - d   DIODE
        - j   JFET
        - m   MOSFET
        - s   SWITCH
        - tx  single lossy transmission line
    - Other 2 functions same as the ones in subCircuit
        - trackLibrary
        - trackLibraryWithoutButton
    """

    def __init__(self, schematicInfo, clarg1, track=None):

        self.clarg1 = clarg1
        kicadFile = self.clarg1
        self.root = []
        try:
            f = open(
                previous_values_path(kicadFile),
                'r')
            tree = ET.parse(f)
            parent_self = tree.getroot()
            for child in parent_self:
                if child.tag == "devicemodel":
                    self.root = child
        except Exception:
            print("Device Model Previous XML is Empty")

        QtWidgets.QWidget.__init__(self)

        # Shared per-conversion data bus, injected by the converter window; a
        # standalone construction falls back to its own instance.
        self.obj_trac = track if track is not None else \
            TrackWidget.TrackWidget()

        # Row and column count
        self.row = 0
        self.count = 1  # Entry count
        self.entry_var = {}

        # For MOSFET
        self.widthLabel = {}
        self.lengthLabel = {}
        self.parameterLabel = {}
        self.multifactorLable = {}
        self.devicemodel_dict_beg = {}
        self.devicemodel_dict_end = {}
        # List to hold information about device
        self.deviceDetail = {}
        # (model_name, ModelGroupWidget) per group built by eSim_general_libs;
        # used for cross-project model_cache hints. Empty for sky130/ihp.
        self._groups = []

        # Set Layout
        self.grid = QtWidgets.QGridLayout()
        self.setLayout(self.grid)
        # print("Reading Device model details from Schematic")
        # Check for IHP SG13G2 PDK first - be specific to avoid false matches
        # Look for component lines starting with 'ihp' or models containing 'sg13_'
        has_ihp = False
        for line in schematicInfo:
            words = line.split()
            if len(words) >= 2:
                # Check if reference starts with 'ihp' (ihp1, ihp2, etc.)
                if words[0].startswith('ihp'):
                    has_ihp = True
                    break
                # Check if model name contains 'sg13_' (sg13_lv_nmos, etc.)
                if 'sg13_' in words[-1].lower():
                    has_ihp = True
                    break
        
        if has_ihp:
            self.eSim_ihp(schematicInfo)
        elif "sky130" in " ".join(schematicInfo):
            self.eSim_sky130(schematicInfo)
        else:
            self.eSim_general_libs(schematicInfo)

    def eSim_sky130(self, schematicInfo):
        sky130box = QtWidgets.QGroupBox()
        sky130grid = QtWidgets.QGridLayout()
        self.count = self.count+1
        self.row = self.row + 1
        self.devicemodel_dict_beg["scmode1"] = self.count
        beg = self.count
        self.deviceDetail[self.count] = "scmode1"
        sky130box.setTitle("Add parameters of SKY130 library ")
        # +
        # " : " +
        # words[6])
        self.parameterLabel[self.count] = QtWidgets.QLabel("Enter the path ")
        self.row = self.row + 1
        sky130grid.addWidget(self.parameterLabel[self.count], self.row, 0)
        self.entry_var[self.count] = QtWidgets.QLineEdit()
        self.entry_var[self.count].setReadOnly(True)

        for child in self.root:
            if child.tag == "scmode1":
                # An empty <scmode1/> prevvalues node (no children) used to
                # IndexError at child[0]. Treat a missing or
                # non-existent stored path as "use the default library path".
                try:
                    stored_path = child[0].text
                except (IndexError, AttributeError):
                    stored_path = None
                if stored_path and os.path.exists(stored_path):
                    self.entry_var[self.count] \
                        .setText(stored_path)
                    path_name = stored_path
                else:
                    if os.name == 'nt':
                        path_name = paths.library_path(
                            "sky130_fd_pr/models/sky130.lib.spice"
                        )
                    else:
                        path_name = os.path.abspath(
                            "/usr/share/local/" +
                            "sky130_fd_pr/models/sky130.lib.spice"
                        )
                    self.entry_var[self.count].setText(path_name)
        # self.trackLibraryWithoutButton(self.count, path_name)

        sky130grid.addWidget(self.entry_var[self.count], self.row, 1)
        self.addbtn = QtWidgets.QPushButton("Add")
        self.addbtn.setObjectName("%d" % beg)
        self.addbtn.clicked.connect(self.trackLibrary)
        sky130grid.addWidget(self.addbtn, self.row, 2)
        # self.count = self.count + 1
        self.adddefaultbtn = QtWidgets.QPushButton("Add Default")
        self.adddefaultbtn.setObjectName("%d" % beg)
        self.adddefaultbtn.clicked.connect(self.trackDefaultLib)
        sky130grid.addWidget(self.adddefaultbtn, self.row, 3)
        self.count = self.count + 1
        self.parameterLabel[self.count] = QtWidgets.QLabel(
            "Enter the corner e.g. tt")
        self.row = self.row + 1
        sky130grid.addWidget(self.parameterLabel[self.count], self.row, 0)
        self.entry_var[self.count] = QtWidgets.QLineEdit()
        self.entry_var[self.count].setText("")
        self.entry_var[self.count].setMaximumWidth(zoom_px(150))
        self.entry_var[self.count].setObjectName("%d" % beg)
        path_name = ''
        for child in self.root:
            if child.tag == "scmode1":
                # child[1] is the stored corner, child[0] its library path.
                # A scmode1 node with fewer children used to IndexError
                # here. Fall back to a blank corner field.
                try:
                    stored_corner = child[1].text
                    stored_path = child[0].text
                except (IndexError, AttributeError):
                    stored_corner = stored_path = None
                if stored_corner:
                    self.entry_var[self.count] \
                        .setText(stored_corner)
                    path_name = stored_path
                else:
                    self.entry_var[self.count].setText("")

        sky130grid.addWidget(self.entry_var[self.count], self.row, 1)
        self.entry_var[self.count].textChanged.connect(self.textChange)
        self.trackLibraryWithoutButton(beg, path_name)

        sky130box.setLayout(sky130grid)
        sky130box.setProperty("cssClass", "themedGroupBox")
        self.grid.addWidget(sky130box)
        # if self.entry_var[self.count-3].text() == "":
        #    pass
        # else:
        #   self.trackLibraryWithoutButton(self.count-3, path_name)

        self.row = self.row + 1
        self.devicemodel_dict_end["scmode1"] = self.count
        self.count = self.count + 1

        for eachline in schematicInfo:
            print("=========================================")
            print(eachline)
            words = eachline.split()
            # A blank schematicInfo line makes eachline[0] IndexError in the
            # designator test below; skip it.
            if not eachline.strip():
                continue
            # supporteddesignator = ['sc', 'u', 'x', 'v', 'i', 'a']
            if eachline[0:2] != 'sc' and eachline[0] != 'u' \
                    and eachline[0] != 'x' and eachline[0] != '*'\
                    and eachline[0] != 'v' and eachline[0] != 'i'\
                    and eachline[0] != 'a':
                print("Only components with designators 'sc', 'u', \
'x', 'v', 'i', 'a'\
                     can be used with SKY130 mode")
                print("Please remove other components")
                self.msg = Dialogs.make_error_message(self)
                self.msg.setModal(True)
                self.msg.setWindowTitle("Invalid components")
                self.content = "Only components with designators " + \
                               "'sc', 'u' and 'x' can be used \
                               with SKY130 mode. " + \
                               "Please edit the schematic and \
                               generate netlist again"
                self.msg.showMessage(self.content)
                self.msg.exec()
                return

            elif eachline[0:2] == 'sc' and eachline[0:6] != 'scmode':
                self.devicemodel_dict_beg[words[0]] = self.count
                self.deviceDetail[self.count] = words[0]
                sky130box = QtWidgets.QGroupBox()
                sky130grid = QtWidgets.QGridLayout()
                beg = self.count
                sky130box.setTitle(
                    "Add parameters for " +
                    words[0] + " : " + words[-1])
                path_name = ''

                # Adding to get SKY130 dimension
                self.parameterLabel[self.count] = QtWidgets.QLabel(
                    "Enter the parameters of SKY130 component " + words[0])
                sky130grid.addWidget(
                    self.parameterLabel[self.count], self.row, 0)
                self.entry_var[self.count] = QtWidgets.QLineEdit()
                self.entry_var[self.count].setText("")
                self.entry_var[self.count].setMaximumWidth(zoom_px(1000))
                self.entry_var[self.count].setObjectName("%d" % beg)
                sky130grid.addWidget(self.entry_var[self.count], self.row, 1)
                self.entry_var[self.count].textChanged.connect(self.textChange)
                sky130box.setLayout(sky130grid)
                sky130box.setProperty("cssClass", "themedGroupBox")
                try:
                    for child in self.root:
                        if child.tag == words[0]:
                            # print("DEVICE MODEL MATCHING---", \
                            #       child.tag, words[0])
                            try:
                                if child[0].text:
                                    self.entry_var[self.count] \
                                        .setText(child[0].text)
                                    path_name = child[0].text
                                else:
                                    self.entry_var[self.count].setText("")
                                    path_name = ""
                            except Exception as e:
                                print("Error when set text of Device " +
                                      "SKY130 Component :", str(e))
                except Exception:
                    pass
                self.trackLibraryWithoutButton(self.count, path_name)
                self.grid.addWidget(sky130box)

                # Adding Device Details #

                # Increment row and widget count
                self.row = self.row + 1
                self.devicemodel_dict_end[words[0]] = self.count
                self.count = self.count + 1


    def eSim_ihp(self, schematicInfo):
        """
        Handle IHP SG13G2 PDK components.
        Each IHP device gets its own library selection UI with:
        - Library path + Add/Add Default buttons
        - Corner selection dropdown
        - Device parameters (W, L, nf)
        """
        # IHP Corner options for different device types
        self.ihp_corner_options = {
            'mos': ['mos_tt', 'mos_ff', 'mos_ss', 'mos_sf', 'mos_fs'],
            'res': ['res_typ', 'res_bcs', 'res_wcs'],
            'cap': ['cap_typ', 'cap_bcs', 'cap_wcs'],
            'dio': ['dio_tt', 'dio_ss', 'dio_ff'],
            'hbt': ['hbt_typ', 'hbt_bcs', 'hbt_wcs'],
        }
        
        # Map model names to (corner_file, corner_type)
        # This enables auto-detection of the correct corner library
        self.ihp_model_to_corner = {
            # MOS Low-Voltage
            'sg13_lv_nmos': ('cornerMOSlv.lib', 'mos'),
            'sg13_lv_pmos': ('cornerMOSlv.lib', 'mos'),
            'nmoscl_2': ('cornerMOSlv.lib', 'mos'),
            'nmoscl_4': ('cornerMOSlv.lib', 'mos'),
            # MOS High-Voltage
            'sg13_hv_nmos': ('cornerMOShv.lib', 'mos'),
            'sg13_hv_pmos': ('cornerMOShv.lib', 'mos'),
            # Resistors
            'rppd': ('cornerRES.lib', 'res'),
            'rhigh': ('cornerRES.lib', 'res'),
            'rsil': ('cornerRES.lib', 'res'),
            'ptap1': ('cornerRES.lib', 'res'),
            'ntap1': ('cornerRES.lib', 'res'),
            'rparasitic': ('cornerRES.lib', 'res'),
            # Capacitors
            'cap_cmim': ('cornerCAP.lib', 'cap'),
            'cap_rfcmim': ('cornerCAP.lib', 'cap'),
            'cparasitic': ('cornerCAP.lib', 'cap'),
            # Diodes
            'dantenna': ('cornerDIO.lib', 'dio'),
            'dpantenna': ('cornerDIO.lib', 'dio'),
            'dpwdnw': ('cornerDIO.lib', 'dio'),
            'ddnwpsub': ('cornerDIO.lib', 'dio'),
            'isolbox': ('cornerDIO.lib', 'dio'),
            # HBT (Bipolar)
            'npn13g2': ('cornerHBT.lib', 'hbt'),
            'npn13g2_5t': ('cornerHBT.lib', 'hbt'),
            'npn13g2l': ('cornerHBT.lib', 'hbt'),
            'npn13g2l_5t': ('cornerHBT.lib', 'hbt'),
            'npn13g2v': ('cornerHBT.lib', 'hbt'),
            'npn13g2v_5t': ('cornerHBT.lib', 'hbt'),
            'pnpmpa': ('cornerHBT.lib', 'hbt'),
        }
        
        # Process each IHP component
        for eachline in schematicInfo:
            words = eachline.split()
            if len(words) < 2:
                continue
                
            # Skip non-IHP components and comments
            if eachline[0] == '*' or eachline[0] == '.':
                continue
            
            # Check if this is an IHP device
            # Detection methods:
            # 1. Reference starts with 'ihp' prefix
            # 2. Model name is in our mapping dictionary
            # 3. Model contains 'sg13' or 'npn13' or known IHP names
            model_name = words[-1].lower() if len(words) > 1 else ""
            is_ihp_device = (
                eachline[0:3] == 'ihp' or  # Reference prefix
                model_name in self.ihp_model_to_corner or  # Known model
                'sg13' in model_name or  # SG13 MOS
                'npn13' in model_name or  # HBT
                model_name.startswith('cap_') or  # Capacitors
                model_name in ['rppd', 'rhigh', 'rsil', 'ptap1', 'ntap1', 
                              'dantenna', 'dpantenna', 'isolbox', 'pnpmpa']
            )
            
            # Skip ihpmode marker lines (legacy support)
            if eachline[0:7] == 'ihpmode':
                continue
                
            if not is_ihp_device:
                continue
                
            print("=========================================")
            print("IHP Device found:", eachline)
            
            device_ref = words[0]  # e.g., ihp1
            device_model = words[-1]  # e.g., sg13_lv_pmos
            
            # Determine corner file based on model
            corner_file, corner_type = self.ihp_model_to_corner.get(
                device_model.lower(), ('cornerMOSlv.lib', 'mos'))
            
            # Create device panel
            self.devicemodel_dict_beg[device_ref] = self.count
            self.deviceDetail[self.count] = device_ref
            
            ihpbox = QtWidgets.QGroupBox()
            ihpgrid = QtWidgets.QGridLayout()
            beg = self.count
            
            ihpbox.setTitle(f"IHP Device: {device_ref} ({device_model})")
            
            row = 0
            
            # Row 1: Library Path with Add and Add Default buttons
            self.parameterLabel[self.count] = QtWidgets.QLabel("Library Path:")
            ihpgrid.addWidget(self.parameterLabel[self.count], row, 0)
            
            self.entry_var[self.count] = QtWidgets.QLineEdit()
            self.entry_var[self.count].setReadOnly(True)
            self.entry_var[self.count].setObjectName(f"{beg}")
            
            # Store corner file info for this device
            self.entry_var[self.count].setProperty("corner_file", corner_file)
            self.entry_var[self.count].setProperty("device_ref", device_ref)
            
            # Load previous value OR set default
            lib_path_set = False
            for child in self.root:
                if child.tag == device_ref:
                    try:
                        if child[0].text and os.path.exists(child[0].text):
                            self.entry_var[self.count].setText(child[0].text)
                            lib_path_set = True
                    except (IndexError, AttributeError):
                        pass
            
            # If no previous value, auto-fill with default path
            if not lib_path_set:
                pdk_root = os.environ.get('PDK_ROOT',
                    os.path.expanduser('~/ihp/IHP-Open-PDK'))
                default_lib_path = os.path.join(pdk_root,
                    "ihp-sg13g2/libs.tech/ngspice/models", corner_file)
                if os.path.exists(default_lib_path):
                    self.entry_var[self.count].setText(default_lib_path)
            
            ihpgrid.addWidget(self.entry_var[self.count], row, 1)
            
            # Add button
            addbtn = QtWidgets.QPushButton("Add")
            addbtn.setObjectName(f"{beg}")
            addbtn.clicked.connect(self.trackIHPDeviceLibrary)
            ihpgrid.addWidget(addbtn, row, 2)
            
            # Add Default button
            adddefaultbtn = QtWidgets.QPushButton("Default")
            adddefaultbtn.setObjectName(f"{beg}")
            adddefaultbtn.setProperty("corner_file", corner_file)
            adddefaultbtn.clicked.connect(self.trackDefaultIHPDeviceLib)
            ihpgrid.addWidget(adddefaultbtn, row, 3)
            
            self.count += 1
            row += 1
            
            # Row 2: Corner Selection Dropdown
            self.parameterLabel[self.count] = QtWidgets.QLabel("Corner:")
            ihpgrid.addWidget(self.parameterLabel[self.count], row, 0)
            
            corner_combo = QtWidgets.QComboBox()
            corner_combo.setObjectName(f"{beg}")
            corner_combo.addItems(self.ihp_corner_options.get(corner_type, ['mos_tt']))
            corner_combo.setCurrentIndex(0)  # Default to first (typ/tt)
            
            # Load previous corner if exists
            for child in self.root:
                if child.tag == device_ref:
                    try:
                        if child[1].text:
                            idx = corner_combo.findText(child[1].text)
                            if idx >= 0:
                                corner_combo.setCurrentIndex(idx)
                    except (IndexError, AttributeError):
                        pass
            
            corner_combo.currentTextChanged.connect(self.ihpCornerChanged)
            self.entry_var[self.count] = corner_combo
            ihpgrid.addWidget(corner_combo, row, 1)
            
            self.count += 1
            row += 1
            
            # Row 3: Device Parameters (W, L, nf)
            self.parameterLabel[self.count] = QtWidgets.QLabel("Parameters:")
            ihpgrid.addWidget(self.parameterLabel[self.count], row, 0)
            
            param_entry = QtWidgets.QLineEdit()
            param_entry.setPlaceholderText("e.g., W=1u L=130n nf=1")
            param_entry.setObjectName(f"{beg}")
            
            # Load previous parameters if exists
            for child in self.root:
                if child.tag == device_ref:
                    try:
                        if child[2].text:
                            param_entry.setText(child[2].text)
                    except (IndexError, AttributeError):
                        pass
            
            param_entry.textChanged.connect(self.ihpParamChanged)
            self.entry_var[self.count] = param_entry
            ihpgrid.addWidget(param_entry, row, 1, 1, 3)
            
            # Track this device with default values
            lib_path = self.entry_var[beg].text()
            corner = corner_combo.currentText()
            params = param_entry.text()
            if lib_path:
                self.obj_trac.deviceModelTrack[device_ref] = f"{lib_path}:{corner}:{params}"
            
            ihpbox.setLayout(ihpgrid)
            ihpbox.setProperty("cssClass", "ihpGroup")
            self.grid.addWidget(ihpbox)
            
            self.row += 1
            self.devicemodel_dict_end[device_ref] = self.count
            self.count += 1
            

    def trackDefaultIHPDeviceLib(self):
        """Set default IHP PDK library path for a specific device."""
        sending_btn = self.sender()
        self.widgetObjCount = int(sending_btn.objectName())
        corner_file = sending_btn.property("corner_file")
        
        # Build default path
        pdk_root = os.environ.get('PDK_ROOT',
            os.path.expanduser('~/ihp/IHP-Open-PDK'))
        lib_path = os.path.join(pdk_root,
            "ihp-sg13g2/libs.tech/ngspice/models", corner_file)
        
        self.entry_var[self.widgetObjCount].setText(lib_path)
        self.deviceName = self.deviceDetail[self.widgetObjCount]
        
        # Get corner from combo (next widget)
        corner = self.entry_var[self.widgetObjCount + 1].currentText()
        # Get params (next next widget)
        params = self.entry_var[self.widgetObjCount + 2].text()
        
        self.obj_trac.deviceModelTrack[self.deviceName] = f"{lib_path}:{corner}:{params}"
        print(f"IHP Default set: {self.deviceName} -> {self.obj_trac.deviceModelTrack[self.deviceName]}")

    def trackIHPDeviceLibrary(self):
        """Browse for IHP PDK library file for a specific device."""
        sending_btn = self.sender()
        self.widgetObjCount = int(sending_btn.objectName())
        
        self.libfile = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                self, "Select IHP Corner Library File",
                os.path.expanduser("~/ihp"),
                "Library Files (*.lib);;All Files (*)"
            )[0]
        )
        
        if not self.libfile:
            return
        
        self.entry_var[self.widgetObjCount].setText(self.libfile)
        self.deviceName = self.deviceDetail[self.widgetObjCount]
        
        # Get corner and params
        corner = self.entry_var[self.widgetObjCount + 1].currentText()
        params = self.entry_var[self.widgetObjCount + 2].text()
        
        self.obj_trac.deviceModelTrack[self.deviceName] = f"{self.libfile}:{corner}:{params}"
        print(f"IHP Library set: {self.deviceName} -> {self.obj_trac.deviceModelTrack[self.deviceName]}")

    def ihpCornerChanged(self, corner):
        """Handle IHP corner selection change."""
        sending_combo = self.sender()
        beg = int(sending_combo.objectName())
        self.deviceName = self.deviceDetail[beg]
        
        lib_path = self.entry_var[beg].text()
        params = self.entry_var[beg + 2].text()
        
        if lib_path:
            self.obj_trac.deviceModelTrack[self.deviceName] = f"{lib_path}:{corner}:{params}"
            print(f"IHP Corner changed: {self.deviceName} -> {corner}")

    def ihpParamChanged(self, params):
        """Handle IHP parameter change."""
        sending_entry = self.sender()
        beg = int(sending_entry.objectName())
        self.deviceName = self.deviceDetail[beg]
        
        lib_path = self.entry_var[beg].text()
        corner = self.entry_var[beg + 1].currentText()
        
        if lib_path:
            self.obj_trac.deviceModelTrack[self.deviceName] = f"{lib_path}:{corner}:{params}"

    # --- General device-model libraries: grouped by shared model ------------
    #
    # Instances that reference the same model (e.g. five eSim_NPN transistors)
    # are shown as ONE ModelGroupWidget: assign the library once and it fans out
    # to every instance, with per-instance override still available. The
    # per-instance QLineEdits stay registered in entry_var / devicemodel_dict_*
    # exactly as before, so the three downstream consumers (Convert, the
    # callConvert Previous_Values writer, and tab reload) are unchanged.

    _KIND_LABEL = {
        'q': 'Transistor', 'd': 'Diode', 'j': 'JFET',
        's': 'Switch', 'm': 'MOSFET',
    }

    def eSim_general_libs(self, schematicInfo):
        components = ModelGrouping.parse_device_components(schematicInfo)
        groups = ModelGrouping.group_by_model(components)

        for (kind, model), instances in groups.items():
            rows = []
            for comp in instances:
                ref = comp.ref
                beg = self.count
                self.devicemodel_dict_beg[ref] = beg
                self.deviceDetail[beg] = ref

                lib_edit = QtWidgets.QLineEdit()
                self.entry_var[beg] = lib_edit
                self.count += 1

                extras = []
                restore_indices = [beg]
                if kind == 'm':
                    # W / L / M are always per-instance, never inherited.
                    for offset, (label, default) in enumerate(
                            (("W", "100u"), ("L", "100u"), ("M", "1")),
                            start=1):
                        dim_edit = QtWidgets.QLineEdit()
                        dim_edit.setMaximumWidth(zoom_px(120))
                        dim_edit.setPlaceholderText("default %s" % default)
                        self.entry_var[beg + offset] = dim_edit
                        extras.append((label, dim_edit))
                        restore_indices.append(beg + offset)
                        dim_edit.textChanged.connect(
                            self._make_dim_changed(ref))
                    self.count += 3

                self.devicemodel_dict_end[ref] = self.count - 1

                # Restore remembered values (Previous_Values.xml -> self.root).
                self._restore_device(ref, restore_indices)
                if lib_edit.text():
                    self._resolve_device(ref, lib_edit.text())

                rows.append(InstanceRow(
                    ref, lib_edit,
                    browse_fn=self._browse_lib, extras=extras))

            title = "%s  (%s)" % (model, self._KIND_LABEL.get(kind, kind))
            group = ModelGroupWidget(
                title, rows,
                resolve_fn=self._resolve_device,
                group_browse_fn=self._browse_lib)
            self._apply_cache_hint(model, group, rows)
            self.grid.addWidget(group)
            self._groups.append((model, group))

        # Only this branch fills the tab with group cards (sky130 / IHP build
        # their own boxes), so the row-share setup belongs here.
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setVerticalSpacing(8)
        finish_group_layout(self.grid)


    def _apply_cache_hint(self, model, group, rows):
        """Pre-fill a blank group default from the cross-project model_cache.

        Only touches a group with no restored value and no overrides, so a
        project's own Previous_Values always wins. modelCache.lookup already
        drops a remembered path that does not exist on this machine, so this can
        only ever suggest a usable, visible, editable default."""
        if group.group_path() or any(group.is_overridden(r.ref) for r in rows):
            return
        hint = modelCache.lookup(model)
        if hint:
            group.set_group_path(hint)

    def remembered_models(self):
        """{model_name: lib_path} for groups where every instance resolved to
        the same non-empty library. Fed to modelCache after a successful
        convert. MOSFET W/L/M are separate per-instance fields and are not part
        of the model->library mapping."""
        out = {}
        for model, group in self._groups:
            vals = set(group.resolved().values())
            if len(vals) == 1:
                path = next(iter(vals))
                if path:
                    out[model] = path
        return out

    def _make_dim_changed(self, ref):
        """A MOSFET W/L/M edit changed: refresh that instance's tracked value
        (the library path is read back from the instance's path field)."""
        def handler(_text):
            beg = self.devicemodel_dict_beg[ref]
            self._resolve_device(ref, self.entry_var[beg].text())
        return handler

    def _browse_lib(self):
        """Open the device-library file picker; return the chosen path or ''."""
        return QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                self, "Open Library Directory",
                paths.library_path("deviceModelLibrary"), "*.lib")[0])

    def _resolve_device(self, ref, path):
        """Write one instance's selection into deviceModelTrack -- the same
        per-ref entry Convert reads. An empty path removes the entry, so an
        unfilled instance is never emitted (matching the legacy behaviour)."""
        track = self.obj_trac.deviceModelTrack
        if not path:
            track.pop(ref, None)
            return
        beg = self.devicemodel_dict_beg[ref]
        if ref[0] == 'm':
            width = self.entry_var[beg + 1].text() or "100u"
            length = self.entry_var[beg + 2].text() or "100u"
            mult = self.entry_var[beg + 3].text() or "1"
            track[ref] = "%s:W=%s L=%s M=%s" % (path, width, length, mult)
        else:
            track[ref] = path

    def _restore_device(self, ref, indices):
        """Refill an instance's widgets from self.root (Previous_Values.xml).

        Field 0 is the library path and is dropped if it no longer exists on
        this machine (the leak guard, now applied to every device kind --
        previously the switch/ymod branches referenced an undefined ``root``
        and silently restored nothing). The remaining fields (MOSFET W/L/M)
        restore verbatim.
        """
        node = None
        for child in self.root:
            if child.tag == ref:
                node = child
                break
        if node is None:
            return
        for field, idx in enumerate(indices):
            try:
                text = node[field].text or ""
            except IndexError:
                continue
            if field == 0:
                if text and os.path.exists(text):
                    self.entry_var[idx].setText(text)
                else:
                    self.entry_var[idx].setText("")
            else:
                self.entry_var[idx].setText(text)

    def trackDefaultLib(self):
        sending_btn = self.sender()
        self.widgetObjCount = int(sending_btn.objectName())
        if os.name == 'nt':
            path_name = paths.library_path(
                "sky130_fd_pr/models/sky130.lib.spice"
            )
        else:
            path_name = os.path.abspath(
                "/usr/share/local/" +
                "sky130_fd_pr/models/sky130.lib.spice"
            )
        self.entry_var[self.widgetObjCount].setText(path_name)
        self.trackLibraryWithoutButton(self.widgetObjCount, path_name)

    def textChange(self):
        sending_btn = self.sender()
        self.widgetObjCount = int(sending_btn.objectName())
        self.deviceName = self.deviceDetail[self.widgetObjCount]
        # self.widgetObjCount = self.count_beg
        # if self.deviceName[0] == 'm':
        #     width = str(self.entry_var[self.widgetObjCount + 1].text())
        #     length = str(self.entry_var[self.widgetObjCount + 2].text())
        #     multifactor = str(self.entry_var[self.widgetObjCount + 3].text())
        #     if width == "":
        #         width = "100u"
        #     if length == "":
        #         length = "100u"
        #     if multifactor == "":
        #         multifactor = "1"

        #     self.obj_trac.deviceModelTrack[self.deviceName] =\
        # str(self.entry_var[self.widgetObjCount].text()) + \
        #         ":" + "W=" + width + " L=" + length + " M=" + multifactor

        if self.deviceName[0:7] == 'ihpmode':
            # IHP mode: path:corner format
            self.obj_trac.deviceModelTrack[self.deviceName] = \
                self.entry_var[self.widgetObjCount].text() + \
                ":" + str(self.entry_var[self.widgetObjCount + 1].text())
            print("IHP mode tracked:", self.obj_trac.deviceModelTrack[self.deviceName])
        elif self.deviceName[0:3] == 'ihp':
            # IHP component: store parameters directly (e.g., W=1u L=130n nf=1)
            self.obj_trac.deviceModelTrack[self.deviceName] = str(
                self.entry_var[self.widgetObjCount].text())
            print("IHP component tracked:", self.obj_trac.deviceModelTrack[self.deviceName])
        elif self.deviceName[0:6] == 'scmode':
            self.obj_trac.deviceModelTrack[self.deviceName] = \
                self.entry_var[self.widgetObjCount].text() + \
                ":" + str(self.entry_var[self.widgetObjCount + 1].text())
            print(self.obj_trac.deviceModelTrack[self.deviceName])
        elif self.deviceName[0:2] == 'sc':
            self.obj_trac.deviceModelTrack[self.deviceName] = str(
                self.entry_var[self.widgetObjCount].text())
            print(self.obj_trac.deviceModelTrack[self.deviceName])

        else:
            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile

    def trackLibrary(self):
        """
        This function is use to keep track of all Device Model widget
        """
        print("Calling Track Device Model Library funtion")
        sending_btn = self.sender()
        self.widgetObjCount = int(sending_btn.objectName())

        self.libfile = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                self, "Open Library Directory",
                paths.library_path("deviceModelLibrary"), "*.lib"
            )[0]
        )

        if not self.libfile:
            return

        # Setting Library to Text Edit Line
        self.entry_var[self.widgetObjCount].setText(self.libfile)
        self.deviceName = self.deviceDetail[self.widgetObjCount]

        # Storing to track it during conversion
        if self.deviceName[0] == 'm':
            width = str(self.entry_var[self.widgetObjCount + 1].text())
            length = str(self.entry_var[self.widgetObjCount + 2].text())
            multifactor = str(self.entry_var[self.widgetObjCount + 3].text())
            if width == "":
                width = "100u"
            if length == "":
                length = "100u"
            if multifactor == "":
                multifactor = "1"

            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile + \
                ":" + "W=" + width + " L=" + length + " M=" + multifactor

        elif self.deviceName[0:6] == 'scmode':
            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile + \
                ":" + str(self.entry_var[self.widgetObjCount + 1].text())
            print(self.obj_trac.deviceModelTrack[self.deviceName])

        elif self.deviceName[0:2] == 'sc':
            self.obj_trac.deviceModelTrack[self.deviceName] = str(
                self.entry_var[self.widgetObjCount].text())
            print(self.obj_trac.deviceModelTrack[self.deviceName])

        else:
            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile

    def trackLibraryWithoutButton(self, iter_value, path_value):
        """
        This function is use to keep track of all Device Model widget
        """
        print("Calling Track Library function Without Button")
        self.widgetObjCount = iter_value
        print("self.widgetObjCount-----", self.widgetObjCount)
        self.libfile = path_value
        print("PATH VALUE", path_value)

        # Setting Library to Text Edit Line
        self.entry_var[self.widgetObjCount].setText(self.libfile)
        self.deviceName = self.deviceDetail[self.widgetObjCount]

        # Storing to track it during conversion
        if self.deviceName[0] == 'm':
            width = str(self.entry_var[self.widgetObjCount + 1].text())
            length = str(self.entry_var[self.widgetObjCount + 2].text())
            multifactor = str(self.entry_var[self.widgetObjCount + 3].text())
            if width == "":
                width = "100u"
            if length == "":
                length = "100u"
            if multifactor == "":
                multifactor = "1"
            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile + \
                ":" + "W=" + width + " L=" + length + " M=" + multifactor

        elif self.deviceName[0:6] == 'scmode':
            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile + \
                ":" + str(self.entry_var[self.widgetObjCount + 1].text())
            print(self.obj_trac.deviceModelTrack[self.deviceName])

        elif self.deviceName[0:2] == 'sc':
            self.obj_trac.deviceModelTrack[self.deviceName] = str(
                self.entry_var[self.widgetObjCount].text())
            print(self.obj_trac.deviceModelTrack[self.deviceName])

        else:
            self.obj_trac.deviceModelTrack[self.deviceName] = self.libfile

    def GenerateSOCbutton(self):
        #############################################################
        # ***************** SPICE to Verilog Converter **************

        # The development is under progress and may not be accurate

        # Developed by:
        #               Sumanto Kar, sumantokar@iitb.ac.in
        #               Nagesh Karmali, nags@cse.iitb.ac.in
        #               Firuza Karmali, firuza@cse.iitb.ac.in
        #               Rahul Paknikar, rahulp@iitb.ac.in
        # GUIDED BY:
        #               Kunal Ghosh, VLSI System Design Corp.Pvt.Ltd
        #               Anagha Ghosh, VLSI System Design Corp.Pvt.Ltd
        #               Philipp Gühring

        # ***********************************************************

        kicadFile = self.clarg1
        (projpath, filename) = os.path.split(kicadFile)
        # Read the netlist and close the handle immediately rather than leaking
        # it until GC; the output file is opened at the end under a `with` too.
        with open(os.path.join(projpath, filename)) as analysisfile:
            content = analysisfile.read()
        contentlines = content.split("\n")
        # print("module "+filename)
        i = 1
        inputlist = []
        realinputlist = []
        outputlist = []
        realoutputlist = []
        wirelist = []
        realwirelist = []
        uutlist = []
        filelist = []
        parsedcontent = []
        for contentlist in contentlines:
            if "IPDD" in contentlist or "IPAD" in contentlist:
                # if len(contentlist)>1 and ( contentlist[0:1]=='U'\
                # or contentlist[0:1]=='X') and not 'plot_' in contentlist :
                # print(contentlist)
                netnames = contentlist.split()
                net = ' '.join(map(str, netnames[1:-1]))
                netnames[-1] = netnames[-1].replace("IPAD", '')
                netnames[-1] = netnames[-1].replace("IPDD", '')
                # net=net.replace(netnames[-1],'')
                # net=net.replace('BI_','')
                # net=net.replace('BO_','')
                net2 = []

                for j in net.split():
                    # print(j)
                    secondpart = j
                    if '_' in j:
                        secondpart = j.split('_')[1]
                    if secondpart in net2:
                        continue
                    if net.count(secondpart)-1 > 0:
                        k = "["+str(net.count(secondpart)-1) + \
                            ":0"+"] "+secondpart
                    else:
                        k = secondpart

                    net2.append(secondpart)
                    if '_I_' in str(j):
                        inputlist.append(k)
                    if '_IR_' in str(j):
                        inputlist.append(k)
                    if '_O_' in str(j):
                        outputlist.append(k)
                    if '_OR_' in str(j):
                        realoutputlist.append(k)
                    if '_W_' in str(j) and not (k in wirelist):
                        wirelist.append(k)
                    if '_WR_' in str(j) and not (k in realwirelist):
                        realwirelist.append(k)

                netnames[-1] = netnames[-1].replace("IPAD", '')
                netnames[-1] = netnames[-1].replace("IPDD", '')
                uutlist.append(netnames[-1]+" uut" +
                               str(i)+" ("+', '.join(net2)+');')
                filelist.append(netnames[-1])
                i = i+1
        # print(inputlist)
        # print(outputlist)
        # print(wirelist)
        parsedcontent.append(
            "\\\\Generated from SPICE to Verilog. \
Converter developed at FOSSEE, IIT Bombay\n")
        parsedcontent.append(
            "\\\\The development is under progress and may not be accurate.\n")

        for j in filelist:
            parsedcontent.append('''`include "'''+j+'''.v"''')
        parsedcontent.append(
            "module "+filename+"("+', '.join(inputlist  # noqa
            + realinputlist + outputlist + realoutputlist)+");")  # noqa
        if inputlist:
            parsedcontent.append("input "+', '.join(inputlist)+";")
        if realinputlist:
            parsedcontent.append("input real "+', '.join(inputlist)+";")
        if outputlist:
            parsedcontent.append("output "+', '.join(outputlist)+";")
        if realoutputlist:
            parsedcontent.append("output real "+', '.join(realoutputlist)+";")
        if wirelist:
            parsedcontent.append("wire "+', '.join(wirelist)+";")
        if realwirelist:
            parsedcontent.append("wire real"+', '.join(realwirelist)+";")
        for j in uutlist:
            parsedcontent.append(j)
        parsedcontent.append("endmodule;")

        print('\n**************Generated Verilog File: ' +
              filename + '.parsed.v***************\n')
        parsed_path = os.path.join(projpath, filename + '.parsed.v')
        with open(parsed_path, 'w') as parsedfile:
            for j in parsedcontent:
                print(j)
                parsedfile.write(j + "\n")
        print(
            '\n*************************************\
************************************\n')
        self.msg = Dialogs.make_error_message(self)
        self.msg.setModal(True)
        self.msg.setWindowTitle("Verilog File Generated")
        self.content = "The Verilog file has been successfully \
             generated from the SPICE netlist"
        self.msg.showMessage(self.content)
        self.msg.exec()
        return
