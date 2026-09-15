from Appconfig import Appconfig
import os
import xml.etree.cElementTree as ET
from PyQt6 import QtWidgets
from kicad_symlib import (
    _balanced_end, _read_parts, _write_lib,
    generated_symlib_path, ensure_lib_registered)

class AutoSchematic(QtWidgets.QWidget):

    def __init__(self, parent, modelname):
        QtWidgets.QWidget.__init__(self)
        self.parent = parent
        self.modelname = modelname.split('.')[0]
        self.template = Appconfig.kicad_sym_template.copy()
        self.xml_loc = Appconfig.xml_loc
        self.lib_loc = Appconfig.lib_loc
        # eSim_Nghdl now lives in ~/.esim/kicad_symbols (see kicad_symlib);
        # the old Windows install path is passed as a legacy migration probe.
        legacy = []
        if os.name == 'nt':
            inst_dir = Appconfig.src_home.replace('\\eSim', '')
            legacy.append(inst_dir + '/KiCad/share/kicad/symbols')
        self.kicad_nghdl_sym = generated_symlib_path(
            "eSim_Nghdl", legacy_dirs=legacy)
        self.parser = Appconfig.parser_nghdl

    def createKicadSymbol(self):
        xmlFound = None
        for root, dirs, files in os.walk(self.xml_loc):
            if (str(self.modelname) + '.xml') in files:
                xmlFound = root
                print(xmlFound)
        if xmlFound is None:
            self.getPortInformation()
            self.createXML()
            self.createSym()
        elif (xmlFound == os.path.join(self.xml_loc, 'Nghdl')):
            print('Library already exists...')
            ret = QtWidgets.QMessageBox.warning(
                self.parent, "Warning", '''<b>Library files for this model''' +
                ''' already exist. Do you want to overwrite it?</b><br/>
                If yes press ok, else cancel it and ''' +
                '''change the name of your vhdl file.''',
                QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
            )
            if ret == QtWidgets.QMessageBox.StandardButton.Ok:
                print("Overwriting existing libraries")
                self.getPortInformation()
                self.createXML()
                self.removeOldLibrary()     # Removes the existng library
                self.createSym()
            else:
                print("Exiting Nghdl")
                quit()
        else:
            print('Pre existing library...')
            ret = QtWidgets.QMessageBox.critical(
                self.parent, "Error", '''<b>A standard library already ''' +
                '''exists with this name.</b><br/><b>Please change the ''' +
                '''name of your vhdl file and upload it again.</b>''',
                QtWidgets.QMessageBox.StandardButton.Ok
            )

            # quit()

    def getPortInformation(self):
        '''
            getting the port information here
        '''
        portInformation = PortInfo(self)
        portInformation.getPortInfo()
        self.portInfo = portInformation.bit_list
        self.input_length = portInformation.input_len

    def createXML(self):
        '''
            creating the XML files in eSim /library/modelParamXML/Nghdl
        '''
        cwd = os.getcwd()
        xmlDestination = os.path.join(self.xml_loc, 'Nghdl')
        self.splitText = ""
        for bit in self.portInfo[:-1]:
            self.splitText += bit + "-V:"
        self.splitText += self.portInfo[-1] + "-V"

        print("changing directory to ", xmlDestination)
        os.chdir(xmlDestination)

        root = ET.Element("model")
        ET.SubElement(root, "name").text = self.modelname
        ET.SubElement(root, "type").text = "Nghdl"
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
        tree.write(str(self.modelname) + '.xml')
        print("Leaving the directory ", xmlDestination)
        os.chdir(cwd)

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

    # def removeOldLibrary(self):
    #     '''
    #         removing the old library
    #     '''
    #     cwd = os.getcwd()
    #     os.chdir(self.lib_loc)
    #     print("Changing directory to ", self.lib_loc)
    #     sym_file = open(self.kicad_nghdl_sym)
    #     lines = sym_file.readlines()
    #     lines = lines[0:-2]
    #     sym_file.close()

    #     output = []
    #     line_reading_flag = False

    #     for line in lines:
    #         if line.startswith("(symbol"):      # Eeschema template start
    #             if line.split()[1] == f"\"{self.modelname}\"":
    #                 line_reading_flag = True
    #         if not line_reading_flag:
    #             output.append(line)
    #         if line.startswith("))"):           # Eeschema template end
    #             line_reading_flag = False

    #     sym_file = open(self.kicad_nghdl_sym, 'w')
    #     for line in output:
    #         sym_file.write(line)
    #     sym_file.close()
    #     os.chdir(cwd)
    #     print("Leaving directory, ", self.lib_loc)

    def removeOldLibrary(self):
        """
        Remove this model's KiCad symbol block from eSim_Nghdl.kicad_sym.

        Parse-based (kicad_symlib): the file is read into balanced top-level
        part blocks keyed by *exact* model name, this model's block is dropped,
        and a valid file is re-serialized atomically. This replaces the old
        line-by-line paren scanner, which (a) matched on
        ``startswith(modelname + "_")`` and so wiped UNRELATED models whose name
        merely began with this one (``and2`` killing ``and2_gate``), (b) counted
        parens that appear inside quoted pin-name/property strings, and (c) wrote
        the shared file non-atomically, so a crash mid-write corrupted it.
        Sub-units (``name_0_1`` / ``name_1_1``) are nested inside the parent
        block and so are removed with it -- no separate prefix match needed.
        Idempotent: a no-op when the model (or the file) is absent.
        """
        parts = _read_parts(self.kicad_nghdl_sym)
        parts.pop(self.modelname, None)
        _write_lib(self.kicad_nghdl_sym, parts)

    # def createSym(self):
    #     self.dist_port = 2.54         # Distance between two ports (mil)
    #     self.inc_size = 2.54          # Increment size of a block (mil)
    #     cwd = os.getcwd()
    #     os.chdir(self.lib_loc)
    #     print("Changing directory to ", self.lib_loc)

    #     # Removing ")" from "eSim_Nghdl.kicad_sym"
    #     file = open(self.kicad_nghdl_sym, "r")
    #     content_file = file.read()
    #     new_content_file = content_file[:-2]
    #     file.close()
    #     file = open(self.kicad_nghdl_sym, "w")
    #     file.write(new_content_file)
    #     file.close()

    #     # Appending new schematic block
    #     sym_file = open(self.kicad_nghdl_sym, "a")
    #     line1 = self.template["start_def"]
    #     line1 = line1.split()
    #     line1 = [w.replace('comp_name', self.modelname) for w in line1]
    #     self.template["start_def"] = ' '.join(line1)

    #     if os.stat(self.kicad_nghdl_sym).st_size == 0:
    #         sym_file.write(
    #             "(kicad_symbol_lib (version 20211014) " +
    #             "(generator kicad_symbol_editor)" + "\n\n"
    #         )  # Eeschema starter code

    #     sym_file.write(
    #         self.template["start_def"] + "\n" + self.template["U_field"] + "\n"
    #     )

    #     line3 = self.template["comp_name_field"]
    #     line3 = line3.split()
    #     line3 = [w.replace('comp_name', self.modelname) for w in line3]
    #     self.template["comp_name_field"] = ' '.join(line3)

    #     sym_file.write(self.template["comp_name_field"] + "\n")

    #     line4 = self.template["blank_field"]
    #     line4_1 = line4[0]
    #     line4_2 = line4[1]
    #     line4_1 = line4_1.split()
    #     line4_1 = [w.replace('blank_quotes', '""') for w in line4_1]
    #     line4_2 = line4_2.split()
    #     line4_2 = [w.replace('blank_quotes', '""') for w in line4_2]
    #     line4[0] = ' '.join(line4_1)
    #     line4[1] = ' '.join(line4_2)
    #     self.template["blank_qoutes"] = line4

    #     sym_file.write(line4[0] + "\n" + line4[1] + "\n")

    #     draw_pos = self.template["draw_pos"]
    #     draw_pos = draw_pos.split()

    #     draw_pos = \
    #         [w.replace('comp_name', f"{self.modelname}_0_1") for w in draw_pos]
    #     draw_pos[8] = str(
    #         float(draw_pos[8]) + float(self.findBlockSize() * self.inc_size)
    #     )
    #     draw_pos_rec = draw_pos[8]

    #     self.template["draw_pos"] = ' '.join(draw_pos)

    #     sym_file.write(
    #         self.template["draw_pos"] + "\n" + self.template["start_draw"] +
    #         " \"" + f"{self.modelname}_1_1\"" + "\n"
    #     )

    #     input_port = self.template["input_port"]
    #     input_port = input_port.split()
    #     output_port = self.template["output_port"]
    #     output_port = output_port.split()
    #     inputs = self.portInfo[0: self.input_length]
    #     outputs = self.portInfo[self.input_length:]

    #     inputs = self.char_sum(inputs)
    #     outputs = self.char_sum(outputs)

    #     total = inputs + outputs

    #     port_list = []

    #     # Set input & output port
    #     input_port[4] = draw_pos_rec
    #     output_port[4] = draw_pos_rec

    #     for i in range(total):
    #         if (i < inputs):
    #             input_port[9] = f"\"in{str(i + 1)}\""
    #             input_port[13] = f"\"{str(i + 1)}\""
    #             input_port[4] = \
    #                 str(float(input_port[4]) - float(self.dist_port))
    #             input_list = ' '.join(input_port)
    #             port_list.append(input_list)

    #         else:
    #             output_port[9] = f"\"out{str(i - inputs + 1)}\""
    #             output_port[13] = f"\"{str(i + 1)}\""
    #             output_port[4] = \
    #                 str(float(output_port[4]) - float(self.dist_port))
    #             output_list = ' '.join(output_port)
    #             port_list.append(output_list)

    #     for ports in port_list:
    #         sym_file.write(ports + "\n")
    #     sym_file.write(
    #         self.template["end_draw"] + "\n\n" + ")"
    #     )
    #     sym_file.close()
    #     os.chdir(cwd)

    #     print('Leaving directory, ', self.lib_loc)
    #     QtWidgets.QMessageBox.information(
    #         self.parent, "Symbol Added",
    #         '''Symbol details for this model is added to the \'''' +
    #         '''<b>eSim_Nghdl.kicad_sym</b>\' in the KiCad shared directory.''',
    #         QtWidgets.QMessageBox.Ok
    #     )

    def createSym(self):
        '''
            creating the symbol
            (pins snapped to KiCad grid)
        '''
        # Rounding quantum for every coordinate written below. It must be the
        # KiCad placement grid itself (100 mil = 2.54 mm): a smaller quantum
        # (it used to be 0.635 = 25 mil) lets pins settle on half-grid points
        # such as y=80.645, which no schematic grid ever hits, so wires cannot
        # be attached to them.
        self.grid = 2.54
        self.dist_port = self.grid          # Distance between two ports # 100 mil (= 2.54 mm)
        self.inc_size = self.dist_port      # Increment size of a block

        def snap(val):
            snapped = round(float(val) / self.grid) * self.grid
            return f"{snapped:.3f}"

        # -------------------------------
        # 3. Build symbol definition
        # -------------------------------
        tmpl = dict(self.template)  # copy template safely

        # start symbol
        start_def = tmpl["start_def"].replace("comp_name", self.modelname)
        symbol_block = []
        symbol_block.append(start_def)
        symbol_block.append(tmpl["U_field"])

        # component name field
        comp_field = tmpl["comp_name_field"].replace("comp_name", self.modelname)
        symbol_block.append(comp_field)

        # blank fields
        blank_1 = tmpl["blank_field"][0].replace("blank_quotes", '""')
        blank_2 = tmpl["blank_field"][1].replace("blank_quotes", '""')
        symbol_block.append(blank_1)
        symbol_block.append(blank_2)

        # -------------------------------
        # 4. Draw block
        # -------------------------------
        draw_pos = tmpl["draw_pos"].replace(
            "comp_name", f"{self.modelname}_0_1"
        ).split()

        # Body width (7) and height (8) are snapped too, so the body edges land
        # on the grid and the pin roots meet them exactly instead of overshoot-
        # ing the outline by a fraction of a mm.
        draw_pos[7] = snap(draw_pos[7])
        draw_pos[8] = snap(
            float(draw_pos[8]) + self.findBlockSize() * self.inc_size
        )
        draw_pos_rec = draw_pos[8]

        symbol_block.append(" ".join(draw_pos))
        symbol_block.append(
            tmpl["start_draw"] + f' "{self.modelname}_1_1"'
        )

        # -------------------------------
        # 5. Ports
        # -------------------------------
        input_port = tmpl["input_port"].split()
        output_port = tmpl["output_port"].split()
        input_port[3] = snap(float(input_port[3]))
        output_port[3] = snap(float(output_port[3]))

        inputs = self.char_sum(self.portInfo[:self.input_length])
        outputs = self.char_sum(self.portInfo[self.input_length:])
        total = inputs + outputs

        input_port[4] = draw_pos_rec
        output_port[4] = draw_pos_rec

        for i in range(total):
            if i < inputs:
                input_port[9] = f"\"in{i+1}\""
                input_port[13] = f"\"{i+1}\""
                input_port[4] = snap(float(input_port[4]) - self.dist_port)
                symbol_block.append(" ".join(input_port))
            else:
                output_port[9] = f"\"out{i-inputs+1}\""
                output_port[13] = f"\"{i+1}\""
                output_port[4] = snap(float(output_port[4]) - self.dist_port)
                symbol_block.append(" ".join(output_port))

        # end draw + end symbol
        # end_draw is "))" which closes both (symbol "<name>_1_1" and
        # the outer (symbol "<name>" — no additional ")" needed.
        symbol_block.append(tmpl["end_draw"])

        # -------------------------------
        # 6. Commit to library (idempotent + atomic)
        # -------------------------------
        # Assemble this model's block as one balanced s-expression and hand it
        # to the shared writer, which replaces any existing block of the same
        # name and re-serializes a valid, balanced file via a temp file +
        # os.replace. No raw byte/line surgery and no CWD change, so repeated
        # add/overwrite/remove can never glue blocks, leave residue, or corrupt
        # the shared library -- and overwriting 1000x leaves exactly one block.
        block = "\n".join(symbol_block).strip()
        if _balanced_end(block, 0) != len(block):
            raise ValueError(
                "Refusing to write malformed symbol block for '" +
                str(self.modelname) + "': not a single balanced s-expression")
        parts = _read_parts(self.kicad_nghdl_sym)
        parts[self.modelname] = block
        _write_lib(self.kicad_nghdl_sym, parts)

        # eSim_Nghdl moved out of ${KICAD6_SYMBOL_DIR}; point the user's
        # sym-lib-table(s) at the ~/.esim path (best-effort, non-blocking).
        ensure_lib_registered(
            "eSim_Nghdl", self.kicad_nghdl_sym,
            descr="eSim NGHDL (GHDL co-simulation) symbols")

        QtWidgets.QMessageBox.information(
            self.parent,
            "Symbol Added",
            (
                "Symbol details for this model were added to "
                "<b>eSim_Nghdl.kicad_sym</b> successfully."
            ),
            QtWidgets.QMessageBox.StandardButton.Ok
        )



class PortInfo:
    '''
        The class contains port information
    '''
    def __init__(self, model):
        self.modelname = model.modelname
        self.model_loc = os.path.join(
            model.parser.get('NGHDL', 'DIGITAL_MODEL'), 'ghdl'
        )
        self.bit_list = []
        self.input_len = 0

    def getPortInfo(self):
        info_loc = os.path.join(self.model_loc, self.modelname + '/DUTghdl/')
        input_list = []
        output_list = []
        read_file = open(info_loc + 'connection_info.txt', 'r')
        data = read_file.readlines()
        read_file.close()

        for line in data:
            # Classify on the direction FIELD, not a substring of the whole
            # line (see model_generation.readPortInfo): a port whose name
            # contains "in"/"out" — e.g. "sout" — was otherwise double-counted,
            # inflating the KiCad symbol pin count. Skip < 3-field lines
            # (blank/malformed); this also fixes the old unbound-name crash on
            # a leading blank line.
            parts = line.split()
            if len(parts) < 3:
                continue
            direction = parts[1].lower()
            if direction in ("in", "inout"):
                input_list.append(parts)
            elif direction == "out":
                output_list.append(parts)

        for in_list in input_list:
            self.bit_list.append(in_list[2])
        self.input_len = len(self.bit_list)
        for out_list in output_list:
            self.bit_list.append(out_list[2])
