from PyQt6 import QtWidgets
from configuration import Dialogs
from projManagement.Validation import Validation
from configuration.Appconfig import Appconfig
from subcircuit.subPaths import resolve_subcircuit, netlist_path
import os


# This class is called when user creates new Project
class convertSub(QtWidgets.QWidget):
    """
    Contains functions that checks project present for conversion and
    also function to convert Kicad Netlist to Ngspice Netlist.
    """

    def __init__(self, dockarea):
        super(convertSub, self).__init__()
        self.obj_validation = Validation()
        self.obj_appconfig = Appconfig()
        self.obj_dockarea = dockarea
        self._netlist_job = None

    def createSub(self):
        """
        This function create command to call KiCad to Ngspice converter.
            If the netlist is not generated for selected project it will show
            error **The subcircuit does not contain any Kicad netlist file for
            conversion.**
            And if no project is selected for conversion, it again show error
            message to select a file or create a file.

        """
        print("Openinig Kicad-to-Ngspice converter from Subcircuit Module")
        self.projDir = self.obj_appconfig.current_subcircuit["SubcircuitName"]
        # Validating if current project is available or not
        if not self.obj_validation.validateKicad(self.projDir):
            self._error(
                'Please select the subcircuit first. You can either create '
                'new subcircuit or open existing subcircuit')
            return

        # The stem the user actually opened wins. Only when nothing was
        # recorded (a selection made by older code, or the folder changed
        # underneath us) do we re-derive it -- and then through the same
        # resolver Edit used, so the two can no longer disagree.
        stem = self.obj_appconfig.get_subcircuit_stem()
        if stem is None:
            stem, _status = resolve_subcircuit(self.projDir)
        if stem is None:
            self._error(
                'This folder holds several subcircuits and none of them is '
                'named after it, so eSim cannot tell which one to convert.\n\n'
                'Open the one you want with Edit first, then convert.')
            return

        # Flush unsaved editor buffers so the converter reads current files off
        # disk, not a stale copy. The project path has always done this; the
        # subcircuit path did not, so a subcircuit edited in eSim's own text
        # editor could be converted from its previous contents.
        try:
            from codeEditor import EditorWindow
            EditorWindow.flush_all_dirty()
        except Exception:
            pass

        if self._netlist_job is not None and self._netlist_job.isRunning():
            self.obj_appconfig.print_info(
                'KiCad netlist generation already in progress.')
            return

        # KiCad >= 7 `--format spice` strips connectivity for eSim symbols
        # (they carry no Sim.* model), degrading every part to "<ref> __<REF>".
        # The project converter has regenerated <proj>.cir from the kicadxml
        # netlist since that broke; subcircuits were left on the old path, so
        # building one on a modern KiCad meant hand-exporting a netlist that
        # had already lost its nets. Same generator, same guarantees, and it
        # removes the undocumented "export a netlist in eeschema first" step.
        #
        # generate_netlist is a no-op that reports why whenever it cannot help
        # (no .kicad_sch -- true of the 460 KiCad-4 subcircuits eSim ships --
        # or no kicad-cli on PATH), leaving any existing .cir untouched, so the
        # legacy workflow keeps working unchanged.
        from maker.hdl.jobs import BackgroundJob
        from kicadtoNgspice import KicadNetlister
        self.obj_appconfig.print_info(
            'Generating KiCad netlist for subcircuit ' + str(stem) + '...')
        # Capture the folder and stem the run started with: the user may pick a
        # different subcircuit while the export runs, and the continuation must
        # act on the one that was actually converted.
        projDir = self.projDir
        job = BackgroundJob(KicadNetlister.generate_netlist, projDir, stem)
        job.succeeded.connect(
            lambda res, d=projDir, s=stem: self._onNetlistReady(d, s, res))
        job.failed.connect(
            lambda err, d=projDir, s=stem: self._onNetlistFailed(d, s, err))
        job.finished.connect(job.deleteLater)
        self._netlist_job = job
        job.start()

    def _onNetlistReady(self, subDir, stem, result):
        """Netlist worker returned (ok, msg). Runs on the GUI thread."""
        try:
            _ok, msg = result
        except (TypeError, ValueError):
            msg = str(result)
        self.obj_appconfig.print_info('KiCad netlist: ' + str(msg))
        self._continueConvert(subDir, stem)

    def _onNetlistFailed(self, subDir, stem, err):
        """Netlist worker raised. Log and still try any pre-existing .cir, so a
        failure here can never be worse than the old manual workflow. Runs on
        the GUI thread."""
        self.obj_appconfig.print_warning(
            'Netlist auto-generation skipped: ' + str(err))
        self._continueConvert(subDir, stem)

    def _continueConvert(self, subDir, stem):
        """Resume once the netlist step has settled: validate the .cir and open
        the converter, else explain what is missing."""
        self._netlist_job = None
        if not self.obj_validation.validateCir(subDir, stem):
            self._error(
                'The subcircuit does not contain any Kicad netlist file'
                ' for conversion.')
            return

        self.projName = stem
        self.project = os.path.join(subDir, str(stem))
        # Registered under the open project so Close Project reaps the tab,
        # but LABELLED with the subcircuit, which is what it actually rebuilds.
        self.obj_appconfig.print_info('Converting subcircuit ' + str(stem))
        self.obj_dockarea.kicadToNgspiceEditor(
            netlist_path(subDir, stem), "sub", label=str(stem))

    def _error(self, message):
        """Show a modal converter error and mirror it into the eSim log."""
        self.msg = Dialogs.make_error_message(self)
        self.msg.setModal(True)
        self.msg.setWindowTitle("Error Message")
        self.msg.showMessage(message)
        self.obj_appconfig.print_error(message)
        self.msg.exec()
