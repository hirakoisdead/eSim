# ==============================================================================
#             FILE: createkicad.py
#
#            USAGE: ---
#
#      DESCRIPTION: This define all components of to create the Kicad Library.
#
#          OPTIONS: ---
#     REQUIREMENTS: ---
#             BUGS: ---
#            NOTES: ---
#           AUTHOR: Sumanto Kar, sumantokar@iitb.ac.in, FOSSEE, IIT Bombay
# ACKNOWLEDGEMENTS: Rahul Paknikar, rahulp@iitb.ac.in, FOSSEE, IIT Bombay
#                Digvijay Singh, digvijay.singh@iitb.ac.in, FOSSEE, IIT Bombay
#                Prof. Maheswari R. and Team, VIT Chennai
#     GUIDED BY: Steve Hoover, Founder Redwood EDA
#                Kunal Ghosh, VLSI System Design Corp.Pvt.Ltd
#                Anagha Ghosh, VLSI System Design Corp.Pvt.Ltd
# OTHER CONTRIBUTERS:
#                Prof. Madhuri Kadam, Shree L. R. Tiwari College of Engineering
#                Rohinth Ram, Madras Institue of Technology
#                Charaan S., Madras Institue of Technology
#                Nalinkumar S., Madras Institue of Technology
#                Partha Singha Roy, Kalyani Government Engineering College
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Monday 29, November 2021
#      REVISION: Friday 16, June 2023
# ==============================================================================

from . import Appconfig
import os
import xml.etree.cElementTree as ET
from PyQt6 import QtWidgets
from configuration import Dialogs
from .kicad_symlib import (
    _balanced_end, _read_parts, _write_lib,
    generated_symlib_path, ensure_lib_registered)


class AutoSchematic:
    def init(self, modelname, modelpath):
        self.App_obj = Appconfig.Appconfig()
        self.modelname = os.path.splitext(modelname)[0]
        self.template = self.App_obj.kicad_sym_template.copy()
        self.xml_loc = self.App_obj.xml_loc
        self.lib_loc = self.App_obj.lib_loc
        self.modelpath = modelpath
        # eSim_Ngveri now lives in ~/.esim/kicad_symbols (see kicad_symlib);
        # pass the old Windows install path as a legacy probe so existing
        # Windows users' accumulated models migrate in on first use.
        legacy = []
        if os.name == 'nt':
            inst_dir = self.App_obj.src_home.replace('\\eSim', '')
            legacy.append(inst_dir + '/KiCad/share/kicad/symbols')
        self.kicad_ngveri_sym = generated_symlib_path(
            "eSim_Ngveri", legacy_dirs=legacy)
        # self.parser = self.App_obj.parser_ngveri

    def createKicadSymbol(self):
        '''
            creating KiCad library using this function
        '''
        xmlFound = None
        for root, dirs, files in os.walk(self.xml_loc):
            if (str(self.modelname) + '.xml') in files:
                xmlFound = root
                print(xmlFound)
                break

        if xmlFound is None:
            self.getPortInformation()
            self.createXML()
            self.createSym()
            self._register_lib()

        elif (xmlFound == os.path.join(self.xml_loc, 'Ngveri')):
            print('Library already exists...')
            ret = Dialogs.warning(
                None, "Warning", '''<b>Library files for this model''' +
                ''' already exist. Do you want to overwrite it?</b><br/>
                If yes press ok, else cancel it and ''' +
                '''change the name of your verilog model.''',
                QtWidgets.QMessageBox.StandardButton.Ok, QtWidgets.QMessageBox.StandardButton.Cancel
            )

            if ret == QtWidgets.QMessageBox.StandardButton.Ok:
                print("Overwriting existing libraries")
                self.getPortInformation()
                self.createXML()
                # No explicit removeOldLibrary() here: createSym() ->
                # _commit_block() already replaces any existing block of this
                # name idempotently, so pre-removing only rewrites the shared
                # file twice (and widened the crash window it guards against).
                self.createSym()
                self._register_lib()
            else:
                print("Library Creation Cancelled")
                return "Error"

        else:
            found = os.path.basename(os.path.normpath(xmlFound))
            print('Pre-existing library in', found)
            if found == 'NgVeriCosim':
                # Same name currently a d_cosim block. One name = one backend,
                # so offer to switch instead of erroring: drop the d_cosim
                # version, then build the NgVeri code model. Latest wins.
                ret = Dialogs.question(
                    None, "Model already exists",
                    "<b>'" + str(self.modelname) + "' already exists as a "
                    "d_cosim block (Icarus Verilog).</b><br/>"
                    "Switch it to an NgVeri Ngspice code model? "
                    "The d_cosim version will be removed.",
                    QtWidgets.QMessageBox.StandardButton.Ok |
                    QtWidgets.QMessageBox.StandardButton.Cancel)
                if ret != QtWidgets.QMessageBox.StandardButton.Ok:
                    return "Error"
                # Local import: createkicadCosim imports this module at load
                # time, so a top-level import here would be circular.
                from . import createkicadCosim
                oldModel = createkicadCosim.CosimSchematic()
                oldModel.init(self.modelname, self.modelpath)
                oldModel.deleteKicadSymbol()
                self.getPortInformation()
                self.createXML()
                self.createSym()
                self._register_lib()
                return "No Error"
            # A built-in / NgHDL / standard library primitive — not ours to
            # replace. The user must rename their module.
            Dialogs.critical(
                None, "Error",
                "<b>A model named '" + str(self.modelname) + "' already "
                "exists in the eSim '" + found + "' library.</b><br/>"
                "Please rename your Verilog module/file and add it again.",
                QtWidgets.QMessageBox.StandardButton.Ok)
            return "Error"

    def getPortInformation(self):
        '''
            getting the port information here
        '''
        portInformation = PortInfo(self, self.modelpath)
        portInformation.getPortInfo()
        self.portInfo = portInformation.bit_list
        self.input_length = portInformation.input_len
        self.portName = portInformation.port_name

    def createXML(self):
        '''
            creating the XML files at `library/modelParamXML/Ngveri`
        '''
        xmlDestination = os.path.join(self.xml_loc, 'Ngveri')
        self.splitText = ""
        # Empty port list would IndexError on portInfo[-1]; a model with no
        # parsed ports is malformed, so bail cleanly (the NgVeri caller logs it)
        # rather than crash mid-build.
        if not self.portInfo:
            raise ValueError(
                "No ports parsed for '" + str(self.modelname) +
                "' — check connection_info.txt")
        for bit in self.portInfo[:-1]:
            self.splitText += bit + "-V:"
        self.splitText += self.portInfo[-1] + "-V"

        # Absolute-path write, no os.chdir. modelParamXML lives in the install
        # tree; on a read-only install the write raises, but without chdir it
        # can no longer strand the process CWD inside the library folder (which
        # silently corrupted every later relative-path operation this session).
        os.makedirs(xmlDestination, exist_ok=True)

        root = ET.Element("model")
        ET.SubElement(root, "name").text = self.modelname
        ET.SubElement(root, "type").text = "Ngveri"
        ET.SubElement(root, "node_number").text = str(len(self.portInfo))
        ET.SubElement(root, "title").text = (
            "Add parameters for " + str(self.modelname))
        ET.SubElement(root, "split").text = self.splitText
        param = ET.SubElement(root, "param")
        ET.SubElement(param, "rise_delay", default="1.0e-9").text = (
            "Enter Rise Delay (default=1.0e-9)")
        ET.SubElement(param, "fall_delay", default="1.0e-9").text = (
            "Enter Fall Delay (default=1.0e-9)")
        ET.SubElement(param, "input_load", default="1.0e-12").text = (
            "Enter Input Load (default=1.0e-12)")
        ET.SubElement(param, "instance_id", default="1").text = (
            "Enter Instance ID (Between 0-99)")

        tree = ET.ElementTree(root)
        tree.write(os.path.join(xmlDestination, str(self.modelname) + '.xml'))

    def findBlockSize(self):
        '''
            Calculates the maximum between input and output ports
        '''
        ind = self.input_length
        return max(
            self.char_sum(self.portInfo[:ind]),
            self.char_sum(self.portInfo[ind:])
        )

    def char_sum(self, ls):
        return sum([int(x) for x in ls])

    def _register_lib(self):
        '''
            Register eSim_Ngveri in the user's KiCad sym-lib-table(s) pointing
            at its ~/.esim path. Existing users' tables point this lib at the
            stale ${KICAD6_SYMBOL_DIR} location after relocation, so rewrite it
            in place; best-effort, never blocks model creation.
        '''
        ensure_lib_registered(
            "eSim_Ngveri", self.kicad_ngveri_sym,
            descr="eSim NgVeri (Ngspice code model) symbols")

    def removeOldLibrary(self):
        '''
            Remove every block for this model name from the shared library and
            rewrite a clean, balanced file. Parse-based, so it correctly strips
            glued/duplicated blocks (which the old startswith() scan missed).
        '''
        parts = _read_parts(self.kicad_ngveri_sym)
        parts.pop(self.modelname, None)
        _write_lib(self.kicad_ngveri_sym, parts)

    def deleteKicadSymbol(self):
        '''
            Public entry point for the NgVeri "Remove Verilog Models" feature:
            drop this model's symbol from eSim_Ngveri.kicad_sym AND delete the
            orphan param XML the build left at
            library/modelParamXML/Ngveri/<name>.xml (previously left behind, so
            a re-add saw a stale "Library already exists" and re-used old port
            data). Idempotent and safe to call when either is already absent.
        '''
        self.removeOldLibrary()
        xml = os.path.join(self.xml_loc, 'Ngveri', self.modelname + '.xml')
        try:
            os.remove(xml)
        except FileNotFoundError:
            pass

    def _commit_block(self, block):
        '''
            Idempotently insert/overwrite this model's symbol block in the
            shared library, then re-serialize a valid balanced file. The block
            is verified to be a single balanced s-expression first, so a
            malformed block is rejected instead of poisoning the shared file.
        '''
        block = block.strip()
        if _balanced_end(block, 0) != len(block):
            raise ValueError(
                "Refusing to write malformed symbol block for '" +
                str(self.modelname) + "': not a single balanced s-expression")
        parts = _read_parts(self.kicad_ngveri_sym)
        parts[self.modelname] = block
        _write_lib(self.kicad_ngveri_sym, parts)

    def createSym(self):
        '''
            Build this model's KiCad symbol block (pins snapped to the KiCad-6
            grid) and commit it idempotently to the shared library. The block
            is assembled as a balanced string and handed to _commit_block(),
            which replaces any existing block of the same name and
            re-serializes a valid file — no raw byte/line surgery, so the
            library can never be left glued or unbalanced.
        '''
        # Rounding quantum for every coordinate written below. It must be the
        # KiCad placement grid itself (100 mil = 2.54 mm): a smaller quantum
        # (it used to be 0.635 = 25 mil) lets pins settle on half-grid points
        # that no schematic grid ever hits, so wires cannot be attached to them.
        self.grid = 2.54
        self.dist_port = self.grid          # Distance between two ports # 100 mil (= 2.54 mm)
        self.inc_size = self.dist_port      # Increment size of a block (mil)
        def snap(val):
                snapped = round(float(val) / self.grid) * self.grid
                return f"{snapped:.3f}"

        block = []                          # lines of this one (symbol ...)

        line1 = self.template["start_def"]
        line1 = line1.split()
        line1 = [w.replace('comp_name', self.modelname) for w in line1]
        self.template["start_def"] = ' '.join(line1)

        block.append(self.template["start_def"])
        block.append(self.template["U_field"])

        line3 = self.template["comp_name_field"]
        line3 = line3.split()
        line3 = [w.replace('comp_name', self.modelname) for w in line3]
        self.template["comp_name_field"] = ' '.join(line3)

        block.append(self.template["comp_name_field"])

        line4 = self.template["blank_field"]
        line4_1 = line4[0]
        line4_2 = line4[1]
        line4_1 = line4_1.split()
        line4_1 = [w.replace('blank_quotes', '""') for w in line4_1]
        line4_2 = line4_2.split()
        line4_2 = [w.replace('blank_quotes', '""') for w in line4_2]
        line4[0] = ' '.join(line4_1)
        line4[1] = ' '.join(line4_2)
        self.template["blank_qoutes"] = line4

        block.append(line4[0])
        block.append(line4[1])

        draw_pos = self.template["draw_pos"]
        draw_pos = draw_pos.split()

        draw_pos = \
            [w.replace('comp_name', f"{self.modelname}_0_1") for w in draw_pos]
        # Body width (7) and height (8) are snapped too, so the body edges land
        # on the grid and the pin roots meet them exactly instead of overshoot-
        # ing the outline by a fraction of a mm.
        draw_pos[7] = snap(draw_pos[7])
        draw_pos[8] = snap(float(draw_pos[8]) +           # previously it is (-)
                          float(self.findBlockSize() * self.inc_size))
        draw_pos_rec = draw_pos[8]

        self.template["draw_pos"] = ' '.join(draw_pos)

        block.append(self.template["draw_pos"])
        block.append(
            self.template["start_draw"] + " \"" + f"{self.modelname}_1_1\""
        )

        input_port = self.template["input_port"]
        input_port = input_port.split()
        output_port = self.template["output_port"]
        output_port = output_port.split()
        input_port[3] = snap(float(input_port[3]))
        output_port[3] = snap(float(output_port[3]))
        inputs = self.portInfo[0: self.input_length]
        outputs = self.portInfo[self.input_length:]
        inputName = []
        outputName = []

        for i in range(self.input_length):
            for j in range(int(inputs[i])):
                inputName.append(
                    self.portName[i] + str(int(inputs[i]) - j - 1))

        for i in range(self.input_length, len(self.portName)):
            for j in range(int(outputs[i - self.input_length])):
                outputName.append(
                    self.portName[i] +
                    str(int(outputs[i - self.input_length]) - j - 1))

        inputs = self.char_sum(inputs)
        outputs = self.char_sum(outputs)

        total = inputs + outputs

        port_list = []

        # Set input & output port
        input_port[4] = draw_pos_rec
        output_port[4] = draw_pos_rec

        j = 0
        for i in range(total):
            if (i < inputs):
                input_port[9] = f"\"{inputName[i]}\""
                input_port[13] = f"\"{str(i + 1)}\""
                input_port[4] = \
                    snap(float(input_port[4]) - float(self.dist_port))
                input_list = ' '.join(input_port)
                port_list.append(input_list)
                j = j + 1

            else:
                output_port[9] = f"\"{outputName[i - inputs]}\""
                output_port[13] = f"\"{str(i + 1)}\""
                output_port[4] = \
                    snap(float(output_port[4]) - float(self.dist_port))
                output_list = ' '.join(output_port)
                port_list.append(output_list)

        for ports in port_list:
            block.append(ports)
        block.append(self.template["end_draw"])      # "))" closes _1_1 + part

        self._commit_block('\n'.join(block))


class PortInfo:
    '''
        The class contains port information
    '''
    def __init__(self, model, modelpath):
        self.modelname = model.modelname
        self.bit_list = []
        self.port_name = []
        self.input_len = 0
        self.modelpath = modelpath

    def getPortInfo(self):
        '''
            getting the port information from `connection_info.txt`
        '''
        input_list = []
        output_list = []
        info_path = self.modelpath + 'connection_info.txt'
        try:
            with open(info_path, 'r') as read_file:
                data = read_file.readlines()
        except OSError as e:
            raise ValueError(
                "Cannot read connection_info.txt for '" +
                str(self.modelname) + "': " + str(e)) from e

        # Classify on the direction FIELD, not a substring search of the whole
        # line (see ModelGeneration.getPortInfo): a port whose name contains a
        # direction keyword — e.g. "output_valid" — was otherwise counted in
        # both lists, corrupting the KiCad symbol pin count. A line with < 3
        # fields (blank or malformed) is skipped, which also fixes the old
        # UnboundLocalError on a leading blank line.
        for line in data:
            parts = line.split()
            if len(parts) < 3:
                continue
            direction = parts[1].lower()
            if direction in ("input", "inout"):
                input_list.append(parts)
            elif direction == "output":
                output_list.append(parts)

        for in_list in input_list:
            self.bit_list.append(in_list[2])
            self.port_name.append(in_list[0])
        self.input_len = len(self.bit_list)
        for out_list in output_list:
            self.bit_list.append(out_list[2])
            self.port_name.append(out_list[0])
