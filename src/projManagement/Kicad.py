# =========================================================================
#          FILE: Kicad.py
#
#         USAGE: ---
#
#   DESCRIPTION: It calls kicad schematic
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, Partha Singh Roy
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Tuesday 17 February 2015
#      REVISION: Thursday 29 Jun 2023
# =========================================================================

import os
import shlex
from . import Validation
from .projectPaths import main_schematic
from configuration.Appconfig import Appconfig
from . import Worker
from configuration import Dialogs


class Kicad:
    """
    This class called the Kicad Schematic, KicadtoNgspice Converter, Layout
    editor and Footprint Editor
    Initialise validation, appconfig and dockarea

    @params
        :dockarea   => passed from DockArea in frontEnd folder, consists
                        of all functions for dockarea

    @return
    """

    def __init__(self, dockarea):
        self.obj_validation = Validation.Validation()
        self.obj_appconfig = Appconfig()
        self.obj_dockarea = dockarea

    def openSchematic(self):
        """
        This function create command to open Kicad schematic after
        appropriate validation checks

        @params

        @return
        """
        print("Function : Open Kicad Schematic")
        self.projDir = self.obj_appconfig.current_project["ProjectName"]
        try:
            self.obj_appconfig.print_info(
                'Kicad Schematic is called for project ' + self.projDir)
        except BaseException:
            pass

        # Validating if current project is available or not
        if self.obj_validation.validateKicad(self.projDir):
            self.projName = self.obj_appconfig.get_proj_stem()
            self.project = os.path.join(self.projDir, str(self.projName))

            # Resolve the main schematic from the .proj anchor (handles kicad6
            # .kicad_sch and kicad4 .sch, independent of the folder name).
            schematic_file = main_schematic(self.projDir, self.projName)

            # A *missing* schematic is NOT an error: eSim's new-project flow
            # only writes the .proj (with its schematicFile token) and lets
            # eeschema create <stem>.kicad_sch the first time the user opens
            # and saves it. main_schematic returns that best-guess path, so
            # blocking on os.path.exists here would make every brand-new
            # project un-openable. Only a missing project *folder* is a real
            # fault (registered project moved or deleted behind eSim's back) --
            # eeschema cannot create a file inside a directory that is gone.
            if not os.path.isdir(self.projDir):
                Dialogs.critical(
                    None, "Error Message",
                    "The project folder could not be found:\n" + self.projDir +
                    "\n\nIt may have been moved or deleted. Reopen the "
                    "project from its new location, or create a new one.")
                self.obj_appconfig.print_warning(
                    'Project folder not found: ' + self.projDir)
                return

            # Path is quoted so workspaces containing spaces still launch
            # (Worker runs the command through shlex.split).
            self.cmd = "eeschema " + shlex.quote(schematic_file)

            # Fresh thread per launch: the thread now babysits eeschema with a
            # blocking wait(), so a reused thread would silently refuse a second
            # launch while the first schematic is still open. WorkerThread
            # retains itself (Appconfig.worker_threads) until its child exits.
            self.obj_workThread = Worker.WorkerThread(self.cmd)
            self.obj_workThread.start()

        else:
            self.msg = Dialogs.make_error_message(None)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                'Please select the project first. You can either ' +
                'create new project or open an existing project')
            self.msg.exec()
            self.obj_appconfig.print_warning(
                'Please select the project first. You can either ' +
                'create new project or open an existing project')

    '''
    # Commenting as it is no longer needed as PCB and Layout will open from
    # eeschema
    def openFootprint(self):
        """
        This function create command to open Footprint editor
        """
        print "Kicad Foot print Editor called"
        self.projDir = self.obj_appconfig.current_project["ProjectName"]
        try:
            self.obj_appconfig.print_info('Kicad Footprint Editor is called'
            + 'for project : ' + self.projDir)
        except:
            pass
        #Validating if current project is available or not

        if self.obj_validation.validateKicad(self.projDir):
            #print "calling Kicad FootPrint Editor ",self.projDir
            self.projName = os.path.basename(self.projDir)
            self.project = os.path.join(self.projDir,self.projName)

            #Creating a command to run
            self.cmd = "cvpcb "+self.project+".net "
            self.obj_workThread = Worker.WorkerThread(self.cmd)
            self.obj_workThread.start()

        else:
            self.msg = Dialogs.make_error_message(None)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage('Please select the project first. You can'
            + 'either create new project or open an existing project')
            self.msg.exec()
            self.obj_appconfig.print_warning('Please select the project'
            + 'first. You can either create new project or open an existing'
            + 'project')

    def openLayout(self):
        """
        This function create command to open Layout editor
        """
        print "Kicad Layout is called"
        self.projDir = self.obj_appconfig.current_project["ProjectName"]
        try:
            self.obj_appconfig.print_info('PCB Layout is called for project : '
            + self.projDir)
        except:
            pass
        #Validating if current project is available or not
        if self.obj_validation.validateKicad(self.projDir):
            print "calling Kicad schematic ",self.projDir
            self.projName = os.path.basename(self.projDir)
            self.project = os.path.join(self.projDir,self.projName)

            #Creating a command to run
            self.cmd = "pcbnew "+self.project+".net "
            self.obj_workThread = Worker.WorkerThread(self.cmd)
            self.obj_workThread.start()

        else:
            self.msg = Dialogs.make_error_message(None)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage('Please select the project first. You can'
            + 'either create new project or open an existing project')
            self.msg.exec()
            self.obj_appconfig.print_warning('Please select the project'
            + 'first. You can either create new project or open an existing'
            + 'project')
    '''

    def openKicadToNgspice(self):
        """
        This function create command to validate and then call
        KicadToNgSPice converter from DockArea file

        @params

        @return
        """
        print("Function: Open Kicad to Ngspice Converter")

        # Flush unsaved editor buffers so the converter reads current
        # files off disk, not a stale copy.
        try:
            from codeEditor import EditorWindow
            EditorWindow.flush_all_dirty()
        except Exception:
            pass

        self.projDir = self.obj_appconfig.current_project["ProjectName"]
        try:
            self.obj_appconfig.print_info(
                'Kicad to Ngspice Conversion is called')
            self.obj_appconfig.print_info('Current Project is ' + self.projDir)
        except BaseException:
            pass
        # Validating if current project is available or not
        if self.obj_validation.validateKicad(self.projDir):
            projName = self.obj_appconfig.get_proj_stem()

            # Guard against a second Convert click while an export is running.
            existing = getattr(self, '_netlist_job', None)
            if existing is not None and existing.isRunning():
                self.obj_appconfig.print_info(
                    'KiCad netlist generation already in progress.')
                return

            # KiCad >= 7 `--format spice` strips connectivity for eSim symbols
            # (they carry no Sim.* model), degrading every part to "<ref>
            # __<REF>". Regenerate <proj>.cir ourselves from the kicadxml
            # netlist, which always preserves ref/value/pin->net regardless of
            # simulation models.
            #
            # kicad-cli start can take 5-15 s on a cold Windows boot (Defender
            # scan + KiCad DLL load), and generate_netlist waits up to 120 s.
            # Run it on a worker thread so the UI event loop stays responsive;
            # the conversion is resumed on the GUI thread by the completion
            # slots below (which may safely touch widgets -- the signal is
            # queued).
            from maker.hdl.jobs import BackgroundJob
            from kicadtoNgspice import KicadNetlister
            self.obj_appconfig.print_info('Generating KiCad netlist...')
            # Capture projDir alongside projName: self.projDir is mutated by
            # the other Kicad entry points, so if the user opens another
            # project's schematic while the export runs, the continuation must
            # still act on the project that was converted.
            projDir = self.projDir
            job = BackgroundJob(
                KicadNetlister.generate_netlist, projDir, projName)
            job.succeeded.connect(
                lambda res, d=projDir, p=projName:
                    self._onNetlistReady(d, p, res))
            job.failed.connect(
                lambda err, d=projDir, p=projName:
                    self._onNetlistFailed(d, p, err))
            job.finished.connect(job.deleteLater)
            self._netlist_job = job
            job.start()

        else:
            self.msg = Dialogs.make_error_message(None)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                'Please select the project first. You can either ' +
                'create new project or open an existing project')
            self.msg.exec()
            self.obj_appconfig.print_warning(
                'Please select the project first. You can either ' +
                'create new project or open an existing project')

    def _onNetlistReady(self, projDir, projName, result):
        """Netlist worker returned (ok, msg). Runs on the GUI thread."""
        try:
            ok, msg = result
        except (TypeError, ValueError):
            ok, msg = bool(result), str(result)
        self.obj_appconfig.print_info('KiCad netlist: ' + str(msg))
        self._continueKicadToNgspice(projDir, projName)

    def _onNetlistFailed(self, projDir, projName, err):
        """Netlist worker raised. Mirror the old inline behaviour: log and
        still try opening any pre-existing .cir. Runs on the GUI thread."""
        self.obj_appconfig.print_warning(
            'Netlist auto-generation skipped: ' + str(err))
        self._continueKicadToNgspice(projDir, projName)

    def _continueKicadToNgspice(self, projDir, projName):
        """Resume the conversion once the netlist step has settled: validate
        the .cir and open the KicadToNgspice editor, else show the error."""
        self._netlist_job = None
        # Checking if project has .cir file or not
        if self.obj_validation.validateCir(projDir, projName):
            self.projName = projName
            self.project = os.path.join(projDir, self.projName)
            var = self.project + ".cir"
            # Pass the project CAPTURED when the background netlist export began,
            # not the live one: the user may have closed/switched projects during
            # the 5-15 s export, and the editor must register + label under the
            # project it is actually converting (see kicadToNgspiceEditor).
            self.obj_dockarea.kicadToNgspiceEditor(
                var, projDir=projDir, projName=projName)
        else:
            self.msg = Dialogs.make_error_message(None)
            self.msg.setModal(True)
            self.msg.setWindowTitle("Error Message")
            self.msg.showMessage(
                'The project does not contain any Kicad netlist file ' +
                'for conversion.')
            self.obj_appconfig.print_error(
                'The project does not contain any Kicad netlist file ' +
                'for conversion.')
            self.msg.exec()
