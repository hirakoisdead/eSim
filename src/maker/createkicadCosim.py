# ==============================================================================
#             FILE: createkicadCosim.py
#
#      DESCRIPTION: Build the KiCad symbol + modelParamXML record for a d_cosim
#                   (Icarus Verilog) digital block.
#
#                   Parallel to createkicad.AutoSchematic (legacy static
#                   Ngveri.cm). Emits model type "NgVeriCosim" into its own
#                   library, eSim_NgVeriCosim.kicad_sym, so d_cosim blocks and
#                   legacy Ngveri blocks coexist in the same schematic. Pin
#                   geometry, the shared-library writer, and port extraction are
#                   all inherited from AutoSchematic unchanged.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

import os
import xml.etree.cElementTree as ET
from PyQt6 import QtWidgets
from configuration import Dialogs

from . import createkicad
from . import kicad_symlib


class CosimSchematic(createkicad.AutoSchematic):
    '''
        KiCad symbol + modelParamXML record for a Verilog block co-simulated
        through ngspice's d_cosim code model (Icarus engine).

        Overrides only the target library file, the modelParamXML "type", and
        the parameter set; reuses AutoSchematic.getPortInformation / createSym /
        removeOldLibrary (identical pin geometry + atomic shared-lib writer).
    '''

    def init(self, modelname, modelpath, engine="icarus", sim_lib=""):
        super().init(modelname, modelpath)
        self.engine = engine
        # Absolute path of the compiled d_cosim artifact (Icarus vvp). Recorded
        # in the XML so the netlister never has to re-derive it.
        self.sim_lib = sim_lib
        # Mirror AutoSchematic.init's symbol-library path convention (now
        # ~/.esim/kicad_symbols via kicad_symlib), but target the separate
        # eSim_NgVeriCosim library. super().init already set this attribute to
        # the eSim_Ngveri path; override it here.
        legacy = []
        if os.name == 'nt':
            inst_dir = self.App_obj.src_home.replace('\\eSim', '')
            legacy.append(inst_dir + '/KiCad/share/kicad/symbols')
        self.kicad_ngveri_sym = kicad_symlib.generated_symlib_path(
            "eSim_NgVeriCosim", legacy_dirs=legacy)

    def createKicadSymbol(self):
        '''
            Same flow/guards as AutoSchematic.createKicadSymbol, but keyed to the
            "NgVeriCosim" modelParamXML subdirectory and library. createSym ->
            _commit_block creates the library file on first use and replaces an
            existing block idempotently, so no pre-seed / removeOldLibrary needed.
        '''
        target = os.path.join(self.xml_loc, 'NgVeriCosim')
        xmlFound = None
        for root, dirs, files in os.walk(self.xml_loc):
            if (str(self.modelname) + '.xml') in files:
                xmlFound = root
                break

        if xmlFound is None:
            self.getPortInformation()
            self.createXML()
            try:
                self.createSym()
            except Exception:
                # createSym failed after createXML wrote the param file: remove
                # the orphan so a retry doesn't see a false "already exists"
                # with stale port data and skip the rebuild.
                orphan = os.path.join(
                    self.xml_loc, 'NgVeriCosim', self.modelname + '.xml')
                try:
                    os.remove(orphan)
                except OSError:
                    pass
                raise
            self._ensure_lib_registered()
            return "No Error"

        if xmlFound == target:
            ret = Dialogs.warning(
                None, "Warning",
                "<b>d_cosim library files for this model already exist. "
                "Do you want to overwrite them?</b>",
                QtWidgets.QMessageBox.StandardButton.Ok,
                QtWidgets.QMessageBox.StandardButton.Cancel)
            if ret != QtWidgets.QMessageBox.StandardButton.Ok:
                return "Error"
            self.getPortInformation()
            self.createXML()
            self.createSym()
            self._ensure_lib_registered()
            return "No Error"

        found = os.path.basename(os.path.normpath(xmlFound))
        if found == 'Ngveri':
            # Same name currently a legacy NgVeri code model. One name = one
            # backend, so offer to switch instead of erroring: drop the NgVeri
            # version, then build the d_cosim block. Latest wins.
            ret = Dialogs.question(
                None, "Model already exists",
                "<b>'" + str(self.modelname) + "' already exists as an "
                "NgVeri Ngspice code model.</b><br/>"
                "Switch it to a d_cosim block (Icarus Verilog)? "
                "The NgVeri version will be removed.",
                QtWidgets.QMessageBox.StandardButton.Ok |
                QtWidgets.QMessageBox.StandardButton.Cancel)
            if ret != QtWidgets.QMessageBox.StandardButton.Ok:
                return "Error"
            oldModel = createkicad.AutoSchematic()
            oldModel.init(self.modelname, self.modelpath)
            oldModel.deleteKicadSymbol()
            self.getPortInformation()
            self.createXML()
            self.createSym()
            self._ensure_lib_registered()
            return "No Error"
        # A built-in / NgHDL / standard library primitive — not ours to
        # replace. The user must rename their module.
        Dialogs.critical(
            None, "Error",
            "<b>A model named '" + str(self.modelname) + "' already exists in "
            "the eSim '" + found + "' library.</b><br/>"
            "Please rename your Verilog module/file and add it again.",
            QtWidgets.QMessageBox.StandardButton.Ok)
        return "Error"

    def deleteKicadSymbol(self):
        '''
            Remove this d_cosim model from eSim_NgVeriCosim.kicad_sym and delete
            its library/modelParamXML/NgVeriCosim/<name>.xml.

            Overrides AutoSchematic.deleteKicadSymbol, which hardcodes the
            legacy 'Ngveri' XML subdir (so the base method would orphan the
            cosim param XML). removeOldLibrary is inherited and already targets
            the cosim library, because init() repointed self.kicad_ngveri_sym at
            eSim_NgVeriCosim. Idempotent: safe when either is already absent.
        '''
        self.removeOldLibrary()
        xml = os.path.join(self.xml_loc, 'NgVeriCosim', self.modelname + '.xml')
        try:
            os.remove(xml)
        except FileNotFoundError:
            pass

    def _ensure_lib_registered(self):
        '''
            Make sure eSim_NgVeriCosim is in the user's KiCad symbol library
            table(s), pointing at its ~/.esim path. A library added AFTER
            install (this one) is absent for existing users, and after the
            relocation any pre-existing ${KICAD6_SYMBOL_DIR} entry is stale;
            kicad_symlib.ensure_lib_registered appends when absent and rewrites
            a stale uri in place. Best-effort: never blocks model creation.
        '''
        kicad_symlib.ensure_lib_registered(
            "eSim_NgVeriCosim", self.kicad_ngveri_sym,
            descr="eSim NgVeri d_cosim (Icarus Verilog) symbols")

    def createXML(self):
        '''
            Write library/modelParamXML/NgVeriCosim/<model>.xml. Convert keys off
            type == "NgVeriCosim" to emit a d_cosim ".model" line instead of the
            generic param= form. The compiled vvp path is NOT stored here: both
            the build step and the netlister derive it from the nghdl config via
            CosimConfig.cosim_vvp_path(), so there is exactly one source of truth
            and nothing absolute/stale to carry in the schematic.
        '''
        xmlDestination = os.path.join(self.xml_loc, 'NgVeriCosim')
        os.makedirs(xmlDestination, exist_ok=True)

        # d_cosim has a fixed 2-port ifspec (one d_in vector, one d_out vector),
        # so ALL input bits collapse into one bracket group and ALL output bits
        # into another, regardless of how many separate Verilog ports were
        # declared. node_number=2 + this split drive Processing to emit exactly
        # two bracket groups on the a-device line.
        in_bits = sum(int(self.portInfo[i]) for i in range(self.input_length))
        out_bits = sum(int(self.portInfo[i])
                       for i in range(self.input_length, len(self.portInfo)))
        self.splitText = str(in_bits) + "-V:" + str(out_bits) + "-V"

        # Absolute-path write, no os.chdir: on a read-only install the write
        # raises, but the process CWD is never stranded inside the library tree
        # (which used to silently break later relative-path operations).
        root = ET.Element("model")
        ET.SubElement(root, "name").text = self.modelname
        ET.SubElement(root, "type").text = "NgVeriCosim"
        ET.SubElement(root, "node_number").text = "2"
        ET.SubElement(root, "title").text = (
            "Add parameters for " + str(self.modelname))
        ET.SubElement(root, "split").text = self.splitText
        param = ET.SubElement(root, "param")
        ET.SubElement(param, "instance_id", default="1").text = (
            "Enter Instance ID (Between 0-99)")
        tree = ET.ElementTree(root)
        tree.write(os.path.join(xmlDestination, str(self.modelname) + '.xml'))
