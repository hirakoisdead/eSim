# =========================================================================
#             FILE: NgVeri.py
#
#            USAGE: ---
#
#      DESCRIPTION: This define all components of the NgVeri Tab.
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
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Monday 29, November 2021
#      REVISION: Tuesday 25, January 2022
# =========================================================================


# importing the files and libraries
from PyQt6 import QtCore, QtWidgets
from configuration import Dialogs
from configuration import paths
from frontEnd.theme_utils import zoom_px, on_zoom_changed
from . import Maker
from . import ModelGeneration
from . import createkicad
from . import createkicadCosim
from .model_teardown import (
    _safe_model_subdir, _resolve_backend, _ensure_modpath,
    _strip_modpath_line, discover_ngveri_models, _MODEL_DIR_MARKERS,
    _actual_subdir_name)
from .kicad_symlib import generated_symlib_path, ensure_lib_registered
from . import CosimConfig
from . import model_registry
from . import verilog_library
from .CosimLogger import CosimLog
from .RemoveItemsDialog import RemoveItemsDialog
from .hdl.jobs import BackgroundJob
from .hdl.ports import extract_ports, find_modules, top_module_name
import os
import shutil
from configuration.Appconfig import Appconfig


class NgVeri(QtWidgets.QWidget):
    '''
        This class create the NgVeri Tab
    '''

    # Emitted from the removal worker thread. Both are connected to GUI-thread
    # receivers, so Qt queues them automatically -- the worker never touches a
    # widget. removeLog carries one HTML log line; removeStep carries
    # (models_done, status text), with models_done < 0 meaning "switch the bar
    # back to indeterminate" for the closing code-model rebuild.
    removeLog = QtCore.pyqtSignal(str)
    removeStep = QtCore.pyqtSignal(int, str)

    def __init__(self, filecount):
        QtWidgets.QWidget.__init__(self)
        # Maker.addverilog(self)
        self.obj_Appconfig = Appconfig()

        # NGHDL may not be installed/configured yet. Read defensively so a
        # missing or partial ~/.nghdl/config.ini degrades this tab instead of
        # crashing the whole Makerchip dock -- NgVeri is built eagerly, unlike
        # the NGHDL tab which is already lazy+guarded.
        self.nghdl_home = CosimConfig.nghdl_cfg('NGHDL', 'NGHDL_HOME')
        self.release_dir = CosimConfig.nghdl_cfg('NGHDL', 'RELEASE')
        self.src_home = CosimConfig.nghdl_cfg('SRC', 'SRC_HOME')
        self.licensefile = CosimConfig.nghdl_cfg('SRC', 'LICENSE')
        self.config_available = bool(self.nghdl_home)
        digital = CosimConfig.digital_model_root()
        self.digital_home = digital + "/Ngveri"
        # NGHDL (GHDL) models live in a sibling tree under the same icm base.
        self.ghdl_home = digital + "/ghdl"
        # modelParamXML root (from the maker Appconfig, keyed off eSim_HOME).
        # Used to list/resolve d_cosim models, which live only under
        # NgVeriCosim/ and never appear in modpath.lst.
        try:
            self._xml_loc = createkicad.Appconfig.Appconfig.xml_loc
        except AttributeError:
            self._xml_loc = ""
        self.count = 0
        self.text = ""
        self.entry_var = {}
        # Async model-removal state (see open_remove_models): the detached log
        # buffer, the shared logger and the running job. None == idle.
        self._remove_logs = None
        self._remove_log = None
        self._remove_job = None
        self._remove_model = None
        self.createNgveriWidget()
        self.fname = ""
        self.filecount = filecount

    def createNgveriWidget(self):
        '''
            Creating the various components of the Widget(Ngveri Tab)
        '''
        self.grid = QtWidgets.QGridLayout()
        self.setLayout(self.grid)

        # Row 0 (options) keeps its natural height via the box's Fixed vertical
        # policy; row 1 (terminal) takes all remaining space. The old code
        # used AlignTop + a rowSpan-5/colSpan-0 span that starved row 0 and
        # crushed the options box's contents into each other.
        self.grid.addWidget(self.createoptionsBox(), 0, 0)
        self.grid.addWidget(self.creategroup(), 1, 0)
        self.grid.setRowStretch(0, 0)
        self.grid.setRowStretch(1, 1)


    def addverilog(self):
        '''
            Adding the verilog file in Maker tab to Ngveri Tab automatically
        '''
        # b=Maker.Maker(self)
        print(Maker.verilogFile)
        if self.filecount >= len(Maker.verilogFile) or \
                Maker.verilogFile[self.filecount] == "":
            Dialogs.critical(
                self,
                "Error Message",
                "<b>Error: No Verilog File Chosen. \
                Write or open a design in the Author stage first.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                'No Verilog File Chosen. '
                'Write or open a design in the Author stage first.'
            )
            return

        self.fname = Maker.verilogFile[self.filecount]
        currentTermLogs = QtWidgets.QTextEdit()
        model = ModelGeneration.ModelGeneration(self.fname, currentTermLogs)
        if not model.require_legacy_toolchain():
            self.entry_var[0].append(currentTermLogs.toHtml())
            return
        # Resolve the model's identity from the SOURCE before anything derives
        # a name from it. The backend-switch prompt below, the build dirs and
        # the KiCad symbol all key off this name, so asking about (or tearing
        # down) a model named after the file would target the wrong one.
        if model.resolve_identity(
                prefer=self.selected_top_module()) == "Error":
            self._flush_build_logs(currentTermLogs)
            return
        self._snapshot_source(model)
        # Settle the NAME before verilator, make and the ngspice rebuild spend
        # minutes on a model that a foreign library already owns.
        if not self._preflight_model_name("ngveri", model):
            self._flush_build_logs(currentTermLogs)
            return
        file = model.model_stem
        # If this name was previously built via d_cosim, ASK, then remove that
        # version first so the switch to the legacy NgVeri flow is clean. A
        # declined switch aborts the build.
        if not self._switch_backends_if_needed("ngveri", file):
            return
        # The remove-model dialog reads modpath.lst fresh each time it opens, so
        # a successful build (model.modpathlst()) is what makes this model show
        # up there -- no combo to pre-register into anymore.

        if not Maker.makerchipTOSAccepted(True):
            Dialogs.warning(
                self, "Warning Message",
                "Please accept the Makerchip Terms of Service "
                "to proceed further.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )

            return

        # Fast file-generation stays on the GUI thread (it runs in
        # milliseconds and is also the ONLY place a dialog is raised --
        # verilogParse's name-mismatch box -- so no QWidget is ever touched
        # off-thread). If any of these fail, abort before spawning a worker.
        try:
            if model.verilogfile() == "Error":
                self._flush_build_logs(currentTermLogs)
                return
            if model.verilogParse() == "Error":
                self._flush_build_logs(currentTermLogs)
                return
            model.getPortInfo()
            # NOTE: model.validate_ports() is deliberately NOT called here.
            # It catches two port shapes this backend cannot represent (inout,
            # and anything wider than 64 bits), both of which build and run and
            # are quietly wrong -- but eSim 2.5 built them too, and refusing a
            # build 2.5 accepted is a maintainer decision, not ours. Parked and
            # documented in docs/UPSTREAM_DECISIONS.md items 2 and 3.
            model.cfuncmod()
            model.ifspecwrite()
            model.sim_main_header()
            model.sim_main()
            model.modpathlst()
        except Exception as err:
            currentTermLogs.append(
                "Error in Ngspice code model generation "
                "from Verilog: " + str(err))
            currentTermLogs.append(self._build_failure_html())
            self._flush_build_logs(currentTermLogs)
            return

        # The slow half -- verilator, make, the ngspice code-model rebuild and
        # `make install` -- can take several minutes. Run it on a worker thread
        # so the GUI stays responsive (the old QProcess+waitForFinished froze
        # eSim, "not responding" overlay and all, for the whole build). Disable
        # both convert buttons until it returns so a second build can't race
        # this one.
        self._set_convert_buttons_enabled(False)
        model.phase.connect(self._on_build_phase)
        self._show_build_progress(True)
        self._build_model = model            # keep refs alive for the build
        self._build_logs = currentTermLogs
        self._build_job = BackgroundJob(
            self._legacy_build_pipeline, model, parent=self)
        self._build_job.succeeded.connect(self._on_legacy_build_finished)
        self._build_job.failed.connect(self._on_legacy_build_error)
        self._build_job.finished.connect(self._build_job.deleteLater)
        self._build_job.start()

    @staticmethod
    def _snapshot_source(model):
        '''
            Keep a dated copy of the source a Convert was run on, under the
            design's .history/ folder.

            Only on Convert -- not on every autosave. A build is a decision the
            user made, so one snapshot per build reads as a list of the versions
            that actually became models, which is the thing worth pointing at
            later. Snapshotting keystrokes would bury that in noise. Failures
            are ignored: this is a courtesy, never a reason to stop a build.
        '''
        try:
            with open(model.file, 'r', errors='replace') as fh:
                verilog_library.snapshot(model.model_stem, fh.read())
        except OSError:
            pass

    def _legacy_build_pipeline(self, model):
        '''
            The slow half of the legacy NgVeri build, run on a BackgroundJob
            worker thread: verilator -> make -> copy artifacts -> ngspice
            `make` [-> `make install`]. Each step returns True only when its
            process exits cleanly (exit code 0), so we short-circuit at the
            first failure and base the verdict on real exit codes rather than a
            "is the word 'error' somewhere in the log" search (which both
            passed broken models and failed working ones). Touches only files +
            model.line (queued to the GUI terminal); never a widget directly.
        '''
        ok = (
            model.run_verilator()
            and model.make_verilator()
            and model.copy_verilator()
            and model.runMake()
        )
        if not ok:
            return False
        # make install on EVERY platform: the Windows nghdl tree is configured
        # with prefix=install_dir exactly like Ubuntu, so Ngveri.cm lands
        # where ngspice loads code models from (<install_dir>/lib/ngspice).
        # The old nt hand-copy targeted <NGHDL_HOME>/lib/ngspice, where
        # ngspice never looks.
        return model.runMakeInstall()

    def _on_legacy_build_finished(self, ok):
        '''GUI-thread epilogue for a completed legacy build (success path).'''
        logs = self._build_logs
        logs.append(self._diag_summary_html())
        if ok:
            logs.append('''
                <p style=\" font-size:16pt; font-weight:1000;
                color:#00FF00;\"> Model Created Successfully!
                </p>
            ''')
            # The name the model was actually built under -- resolved from the
            # design's top module, not from the file it arrived in.
            model = getattr(self, '_build_model', None)
            placedName = getattr(model, 'model_stem', None) or os.path.splitext(
                os.path.basename(self.fname))[0].lower()
            logs.append(
                '<p style="color:#00AA00; font-weight:600;">'
                'Model "' + placedName + '" — place it from the '
                'eSim_Ngveri library in KiCad.</p>')
        else:
            logs.append(self._build_failure_html())
        self._flush_build_logs(logs)

    def _on_legacy_build_error(self, msg):
        '''GUI-thread epilogue when the build worker raised an exception.'''
        self._build_logs.append(
            "Error in Ngspice code model generation from Verilog: " + msg)
        self._build_logs.append(self._build_failure_html())
        self._flush_build_logs(self._build_logs)

    def _diag_summary_html(self):
        '''
            One-line tally of what the toolchain actually reported, printed
            just above the verdict.

            Several hundred lines of gcc/make output scroll past during a
            build, so without a closing count the user judges the run by how
            much coloured text went by -- and a perfectly good model whose
            build emitted a couple of routine compiler warnings reads as a
            failure. Say the numbers, and say plainly that warnings are not
            failures.
        '''
        model = getattr(self, '_build_model', None)
        errors = getattr(model, 'diag_errors', 0)
        warnings = getattr(model, 'diag_warnings', 0)

        def _count(n, word):
            return str(n) + ' ' + word + ('' if n == 1 else 's')

        text = ('Toolchain reported ' + _count(errors, 'error') + ' and ' +
                _count(warnings, 'warning') + '.')
        if warnings and not errors:
            text += ' Warnings do not stop a build.'
        return ('<p style="font-size:11pt; color:#666666;">' + text + '</p>')

    @staticmethod
    def _build_failure_html():
        return '''
            <p style=\" font-size:16pt; font-weight:1000;
            color:#FF0000;\">There was an error during model creation,
            <br/>Please rectify the error and try again!
            </p>
        '''

    def _set_convert_buttons_enabled(self, enabled):
        '''Enable/disable the two convert buttons around an async build.'''
        for name in ("addverilogbutton", "addcosimbutton"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    def _toggle_convert_hint(self, shown):
        '''Fold the "which method" explainer in or out, and point the arrow
        the way it will move.'''
        self.convertHint.setVisible(shown)
        self.convertHintToggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if shown
            else QtCore.Qt.ArrowType.RightArrow)

    def _scroll_progress_into_view(self):
        '''
            Make sure the progress row is on screen when a build starts.

            The page is mounted behind a QScrollArea (FlowNavigator._scroll),
            so on a short dock the bar can sit below the fold. A user who has
            just pressed Convert and sees nothing move assumes the click did
            not register -- and has no reason to suspect this page scrolls at
            all. The page is laid out to fit without scrolling at ordinary
            sizes; this is what covers the sizes where it cannot.
        '''
        bar = getattr(self, "buildBar", None)
        if bar is None:
            return
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QtWidgets.QScrollArea):
                widget.ensureWidgetVisible(bar)
                return
            widget = widget.parentWidget()

    def _show_build_progress(self, on, message="Starting build…"):
        '''
            Show/hide the live build progress bar + phase label. Called on the
            GUI thread: on when a build is dispatched, off in the shared build
            epilogue (_flush_build_logs).
        '''
        if on:
            self.buildStatus.setText(message)
        self.buildStatus.setVisible(on)
        self.buildBar.setVisible(on)
        if on:
            self._scroll_progress_into_view()

    def _on_build_phase(self, phase):
        '''
            Slot for ModelGeneration.phase (queued from the build worker):
            name the step currently running under the spinning bar.
        '''
        self.buildStatus.setText(phase)

    def _flush_build_logs(self, logs):
        '''
            Append the build's captured HTML into the visible terminal, scroll
            to the bottom, re-enable the convert buttons and drop the build
            refs. Shared by the success, failure and pre-worker abort paths.
        '''
        self.entry_var[0].append(logs.toHtml())
        self.entry_var[0].verticalScrollBar().setValue(
            self.entry_var[0].verticalScrollBar().maximum()
        )
        self._show_build_progress(False)
        self._set_convert_buttons_enabled(True)
        self._build_model = None
        self._build_logs = None
        # The build may have renamed the design's home (the model is named
        # from its top module), so re-read what the next convert would target.
        self.refresh_subject()

    def addverilog_cosim(self):
        '''
            d_cosim (Icarus Verilog) flow. Compiles the chosen Verilog file to a
            vvp via iverilog and creates an "NgVeriCosim" KiCad symbol. Unlike
            "Convert Verilog to Ngspice" (legacy static Ngveri.cm), this needs no
            C/C++ compiler, never rebuilds ngspice, and runs fully locally (no
            Makerchip). Gated on the d_cosim toolchain being present.
        '''
        # Doctor gate: covers iverilog/vvp/libvvp AND the ngspice ivlng
        # adapter, with the exact probed paths + fix hints, so a broken
        # install fails here instead of at simulation time.
        from . import ToolchainCheck
        doctor_msg = ToolchainCheck.failure_message(ToolchainCheck.DCOSIM)
        if doctor_msg:
            Dialogs.warning(
                self, "d_cosim unavailable", doctor_msg,
                QtWidgets.QMessageBox.StandardButton.Ok)
            return

        if len(Maker.verilogFile) < (self.filecount + 1) or \
                Maker.verilogFile[self.filecount] == "":
            Dialogs.critical(
                self, "Error Message",
                "<b>Error: No Verilog File Chosen. Write or open a "
                "design in the Author stage first.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            return

        self.fname = Maker.verilogFile[self.filecount]
        currentTermLogs = QtWidgets.QTextEdit()
        model = ModelGeneration.ModelGeneration(self.fname, currentTermLogs)
        # Canonical model identity = the lowercased TOP MODULE in the source.
        # The symbol, param XML, compiled vvp, picker entry and netlist all key
        # off THIS one name, so the build location matches the netlister's
        # lookup (a case-sensitive filesystem otherwise loses the vvp at sim
        # time). Resolved before use_cosim_tree/verilogfile, both of which
        # build paths out of it.
        if model.resolve_identity(
                prefer=self.selected_top_module()) == "Error":
            self._flush_build_logs(currentTermLogs)
            return
        self._snapshot_source(model)
        # Settle the NAME before the build tree is created and iverilog runs.
        if not self._preflight_model_name("cosim", model):
            self._flush_build_logs(currentTermLogs)
            return
        modelname = model.model_stem

        # Fast GUI-thread half: the backend-switch prompt, source generation and
        # parse. These are the only dialog-raising steps, so they stay on the
        # GUI thread; abort before spawning a worker if any fails.
        # Build into the d_cosim tree (<DIGITAL_MODEL>/NgVeriCosim), NOT the
        # legacy Ngveri tree the two backends used to share. This is what makes
        # "remove the d_cosim model" incapable of touching a Verilator build of
        # the same name. Must precede verilogfile(), which creates the dir.
        model.use_cosim_tree()

        try:
            # If this name was previously built via the legacy NgVeri flow,
            # ASK, then remove that version first so the user ends up with one
            # backend per name rather than two half-models in KiCad. Since the
            # trees are now separate this is a clarity guard, not a safety one:
            # a declined switch aborts the build and nothing is deleted.
            if not self._switch_backends_if_needed("cosim", modelname):
                return
            if model.verilogfile() == "Error":
                self._flush_build_logs(currentTermLogs)
                return
            if model.verilogParse(make_symbol=False) == "Error":
                self._flush_build_logs(currentTermLogs)
                return
        except Exception as err:
            currentTermLogs.append(
                "Error in d_cosim model creation: " + str(err))
            self._flush_build_logs(currentTermLogs)
            return

        # Slow half: the iverilog compile (build_cosim) can take a while on a
        # large model. Run it on a worker thread so the GUI stays responsive
        # (it used to block the event loop). KiCad symbol creation stays in the
        # epilogue because it may raise an overwrite-confirmation dialog, which
        # must run on the GUI thread. Disable both convert buttons until the
        # build returns so a second build can't race it.
        self._set_convert_buttons_enabled(False)
        model.phase.connect(self._on_build_phase)
        self._show_build_progress(True, "Building d_cosim model…")
        self._build_model = model            # keep refs alive for the build
        self._build_logs = currentTermLogs
        self._cosim_modelname = modelname
        self._build_job = BackgroundJob(model.build_cosim, parent=self)
        self._build_job.succeeded.connect(self._on_cosim_build_finished)
        self._build_job.failed.connect(self._on_cosim_build_error)
        self._build_job.finished.connect(self._build_job.deleteLater)
        self._build_job.start()

    def _on_cosim_build_finished(self, sim_lib):
        '''GUI-thread epilogue for a completed d_cosim build. build_cosim ran on
        the worker; the KiCad symbol is created here (it may prompt).'''
        model = self._build_model
        logs = self._build_logs
        modelname = self._cosim_modelname
        try:
            if sim_lib and sim_lib != "Error":
                model.clog.phase("Create KiCad symbol")
                schematicLib = createkicadCosim.CosimSchematic()
                schematicLib.init(modelname, model.modelpath, "icarus", sim_lib)
                if schematicLib.createKicadSymbol() != "Error":
                    # The model now exists on disk as NgVeriCosim/<name>.xml,
                    # which is what the remove-model dialog scans -- nothing to
                    # register in a combo anymore.
                    model.clog.ok(
                        'd_cosim model "' + modelname + '" created (Icarus). '
                        'Place it from the eSim_NgVeriCosim library.')
                else:
                    model.clog.error(
                        'KiCad symbol generation failed for "' + modelname +
                        '". The vvp built but the symbol was not created.')
                    # Roll the build back. A model with no symbol cannot be
                    # placed on a schematic, so leaving its build tree behind
                    # only puts an unusable entry in Remove Models -- which is
                    # how a failed convert ended up looking like a successful
                    # one everywhere except the schematic.
                    model.clog.info(
                        "Rolling back the incomplete build so it does not "
                        "linger as a half-model.")
                    self._remove_cosim_model(modelname, log=model.clog)
            # sim_lib == "Error": build_cosim already logged the phased failure.
        except Exception as err:
            model.clog.error("Error in d_cosim model creation: " + str(err))
        self._flush_build_logs(logs)

    def _on_cosim_build_error(self, msg):
        '''GUI-thread epilogue when the d_cosim build worker raised.'''
        self._build_model.clog.error(
            "Error in d_cosim model creation: " + msg)
        self._flush_build_logs(self._build_logs)

    def addfile(self):
        '''
            This function is used to add additional files required
            by the verilog top module
        '''
        if len(Maker.verilogFile) < (self.filecount + 1):
            Dialogs.critical(
                self,
                "Error Message",
                "<b>Error: No Verilog File Chosen. \
                Write or open a design in the Author stage first.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                'No Verilog File Chosen. Write or open \
                 a design in the Author stage first.')
            return

        self.fname = Maker.verilogFile[self.filecount]
        model = ModelGeneration.ModelGeneration(self.fname, self.entry_var[0])
        # model.verilogfile()
        model.addfile()

    def addfolder(self):
        '''
            This function is used to add additional folder required
            by the verilog top module.
        '''
        if len(Maker.verilogFile) < (self.filecount + 1):
            Dialogs.critical(
                self,
                "Error Message",
                "<b>Error: No Verilog File Chosen. \
                Write or open a design in the Author stage first.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                'No Verilog File Chosen. Write or open \
                a design in the Author stage first.')
            return
        self.fname = Maker.verilogFile[self.filecount]
        model = ModelGeneration.ModelGeneration(self.fname, self.entry_var[0])
        # model.verilogfile()
        model.addfolder()

    def clearTerminal(self):
        '''
            This function is used to clear the terminal
        '''
        self.entry_var[0].setText("")

    def createoptionsBox(self):
        '''
            This function is used to create buttons/options
        '''
        self.optionsbox = QtWidgets.QGroupBox()
        self.optionsbox.setTitle("Select Options")

        # A single vertical stack gives a clean top-to-bottom read: one verb
        # heading, the two convert actions, then the low-stakes utilities.
        # (The old grid stretched every button to full width and left a hole
        # in the utility row.) The "which method / when" copy is NOT here --
        # it lives in the terminal side column so the top stays uncluttered.
        outer = QtWidgets.QVBoxLayout()
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        self.optionsgroupbtn = QtWidgets.QButtonGroup()

        # The verb is stated ONCE as a heading; the two buttons then only need
        # to name the method. Killing the repeated "Convert to Ngspice (...)"
        # prefix is what stops them reading as two identical buttons.
        convertHeading = QtWidgets.QLabel("Convert Verilog to Ngspice")
        convertHeading.setProperty("cssClass", "heading")

        # What is about to be built, named from the design's own top module.
        # This stage used to say nothing at all: the model's name, its ports
        # and its source were only revealed by the build log afterwards -- or,
        # when something was wrong, by an error about a file the user had never
        # deliberately named.
        #
        # It rides on the heading's own line, right-aligned, rather than
        # standing as two paragraphs beneath it. Vertical space on this page is
        # not decoration: the page lives in a dock behind a scroll area, and
        # every row added here is a row that can push the build progress bar
        # below the fold -- where a user who has just pressed Convert cannot
        # see that anything is happening. The source path moves to the tooltip;
        # it is reference information, and the build log states it in full.
        self.subjectLabel = QtWidgets.QLabel()
        self.subjectLabel.setWordWrap(False)
        self.subjectLabel.setProperty("cssClass", "muted")
        self.subjectLabel.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight |
            QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.subjectLabel.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        # Never let a long model name widen the page: the label gives up its
        # width first and elides (refresh_subject re-elides on demand).
        self.subjectLabel.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)

        heading_row = QtWidgets.QHBoxLayout()
        heading_row.setSpacing(12)
        heading_row.addWidget(convertHeading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.subjectLabel)
        outer.addLayout(heading_row)

        # Escape hatch for a multi-module design whose top eSim guessed wrong.
        # The guess (the module nothing else instantiates) is right for
        # essentially every design, so this row stays hidden until there is
        # genuinely more than one module to choose between -- an always-visible
        # picker would imply a decision the user does not normally have to make.
        self.topRow = QtWidgets.QWidget()
        top_row = QtWidgets.QHBoxLayout(self.topRow)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_label = QtWidgets.QLabel("Build which module?")
        top_label.setProperty("cssClass", "muted")
        top_row.addWidget(top_label)
        self.topModuleBox = QtWidgets.QComboBox()
        self.topModuleBox.setToolTip(
            "The design's top module. eSim picks the one nothing else "
            "instantiates; change it only if that guess is wrong.")
        self.topModuleBox.currentIndexChanged.connect(
            lambda _i: self.refresh_subject())
        top_row.addWidget(self.topModuleBox, 1)
        self.topRow.setVisible(False)
        outer.addWidget(self.topRow)

        expanding = QtWidgets.QSizePolicy.Policy.Expanding
        fixed = QtWidgets.QSizePolicy.Policy.Fixed

        # Two backends, same result -> equal weight (both primary, equal
        # width). Dual Co-sim sits FIRST (left = first in reading order) so a
        # user reaching for the simpler path lands on it without us having to
        # dim the other or slap on a "recommended" badge.
        convert_row = QtWidgets.QHBoxLayout()
        convert_row.setSpacing(12)

        self.addcosimbutton = QtWidgets.QPushButton("Dual Co-sim")
        self.addcosimbutton.setProperty("cssClass", "primary")
        self.addcosimbutton.setSizePolicy(expanding, fixed)
        self.addcosimbutton.setMinimumHeight(44)
        self.addcosimbutton.setToolTip(
            "Icarus Verilog co-simulation via ngspice d_cosim: "
            "no C/C++ compiler and no ngspice rebuild")
        self.optionsgroupbtn.addButton(self.addcosimbutton)
        self.addcosimbutton.clicked.connect(self.addverilog_cosim)
        convert_row.addWidget(self.addcosimbutton)

        self.addverilogbutton = QtWidgets.QPushButton("NgVeri")
        self.addverilogbutton.setProperty("cssClass", "primary")
        self.addverilogbutton.setSizePolicy(expanding, fixed)
        self.addverilogbutton.setMinimumHeight(44)
        self.addverilogbutton.setToolTip(
            "Compiles Verilog into a native ngspice code model "
            "(builds a C model and rebuilds ngspice)")
        self.addverilogbutton.setToolTipDuration(5000)
        self.optionsgroupbtn.addButton(self.addverilogbutton)
        self.addverilogbutton.clicked.connect(self.addverilog)
        convert_row.addWidget(self.addverilogbutton)

        outer.addLayout(convert_row)

        # Low-stakes utilities. Three equal-width buttons span the full row
        # (equal stretch, no trailing spacer) so the space is filled evenly
        # instead of leaving a gap between the dependency pair and Clear
        # Terminal.
        util_row = QtWidgets.QHBoxLayout()
        util_row.setSpacing(8)

        self.addfilebutton = QtWidgets.QPushButton("Add dependency files…")
        self.addfilebutton.setSizePolicy(expanding, fixed)
        self.optionsgroupbtn.addButton(self.addfilebutton)
        self.addfilebutton.clicked.connect(self.addfile)
        util_row.addWidget(self.addfilebutton, 1)

        self.addfolderbutton = QtWidgets.QPushButton("Add dependency folder…")
        self.addfolderbutton.setSizePolicy(expanding, fixed)
        self.optionsgroupbtn.addButton(self.addfolderbutton)
        self.addfolderbutton.clicked.connect(self.addfolder)
        util_row.addWidget(self.addfolderbutton, 1)

        self.clearTerminalBtn = QtWidgets.QPushButton("Clear Terminal")
        # Low-stakes utility — text-only tertiary so it recedes.
        self.clearTerminalBtn.setProperty("cssClass", "tertiary")
        self.clearTerminalBtn.setSizePolicy(expanding, fixed)
        self.optionsgroupbtn.addButton(self.clearTerminalBtn)
        self.clearTerminalBtn.clicked.connect(self.clearTerminal)
        util_row.addWidget(self.clearTerminalBtn, 1)

        outer.addLayout(util_row)

        self.optionsbox.setLayout(outer)

        # Fixed vertical policy: the box keeps its natural height instead of
        # being squeezed by the terminal group's row-span below it (which was
        # crushing the three rows into each other).
        self.optionsbox.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed)

        return self.optionsbox

    def refresh_subject(self):
        '''
            Re-read the current design and say what a Convert would build:
            the model name, its ports, and the file it comes from. Called when
            this stage is shown, so it always describes what is on screen now.

            The name here is derived exactly the way the build derives it (the
            design's top module), so what this line promises and what the build
            produces cannot drift apart.

            Describes only -- it never enables or disables the convert buttons.
            Those belong to the build, which greys them out for the duration
            and hands them back in its epilogue. A second owner would fight it,
            and a design this function merely failed to READ would leave the
            user locked out of a build that would have worked.
        '''
        label = getattr(self, 'subjectLabel', None)
        if label is None:
            return
        path = self._current_verilog_fname()
        code = ""
        if path:
            try:
                with open(path, 'r', errors='replace') as fh:
                    code = fh.read()
            except OSError:
                code = ""

        modules = find_modules(code) if code else []
        chosen = self._sync_top_picker(code, modules)
        module, ports = ("", [])
        if code:
            module, ports = extract_ports(code, top=chosen)
        if not module:
            label.setText("No design yet — write one in Author")
            label.setToolTip(
                "Write a design in the Author stage, or open a .v file, and "
                "what a Convert would build appears here.")
            return

        ins = sum(1 for mode, _n, _w in ports if mode == "input")
        outs = sum(1 for mode, _n, _w in ports if mode == "output")

        label.setText('<b>' + module.lower() + '</b> · ' + str(ins) +
                      ' in, ' + str(outs) + ' out')
        # The full source path is the tooltip, not a second line: it is the
        # answer to "which file is this?", which is asked far less often than
        # this page is looked at.
        label.setToolTip("Will build '" + module.lower() + "' from " + path)

    def _sync_top_picker(self, code, modules):
        '''
            Refill the "build which module?" picker for the current design and
            return the module to describe -- which is also the one that will be
            built.

            The box always SHOWS the module that will actually be built, never
            merely a list to choose from. Letting it settle on its own first
            entry while the build used a different module would recreate, one
            level up, the exact defect this whole change removes: the interface
            naming one thing and the build producing another.

            A choice the user made survives a trip to another stage and back,
            and heals itself when it stops making sense: if the design is
            replaced and the chosen module is no longer in it, the automatic
            pick takes over rather than naming a module that is not there.
        '''
        box = getattr(self, 'topModuleBox', None)
        if box is None:
            return None
        previous = box.currentText()
        box.blockSignals(True)
        box.clear()
        box.addItems(modules)
        # Only offer the choice when there IS one.
        self.topRow.setVisible(len(modules) > 1)
        chosen = previous if previous in modules else top_module_name(code)
        if chosen:
            box.setCurrentText(chosen)
        box.blockSignals(False)
        return chosen or None

    def selected_top_module(self):
        '''
            The module a Convert will build, or None to let eSim choose.

            Safe to pass straight to resolve_identity: the picker is kept in
            step with the description, so this is never a module other than the
            one the user was just told about.
        '''
        box = getattr(self, 'topModuleBox', None)
        if box is None or not self.topRow.isVisible():
            return None
        return box.currentText() or None

    def showEvent(self, event):
        '''Describe the current design every time this stage comes forward --
        the design may well have been rewritten in Author or Verify since the
        last look.'''
        super().showEvent(event)
        self.refresh_subject()

    def _sym_paths(self):
        '''
            (eSim_Ngveri, eSim_NgVeriCosim) .kicad_sym paths -- the very files
            createkicad/createkicadCosim write, resolved through the same
            legacy-migration probe so symbols accumulated in the OLD location
            (/usr/share/kicad/symbols on Ubuntu, <inst>/KiCad/share/kicad/
            symbols on Windows) are copied in, seen, and therefore removable.

            Registering the two libraries here is not cosmetic. The sym-lib-
            table is only ever refreshed when a model is CREATED, so a user who
            upgraded and has not built anything since still has KiCad pointing
            at the legacy path. Removal rewrites the ~/.esim copy, KiCad reads
            the legacy one, and the "removed" symbol is still in the picker.
            The call is idempotent, best-effort (swallows OSError) and only
            rewrites an entry whose uri is actually stale.
        '''
        legacy = []
        if os.name == 'nt':
            try:
                src_home = createkicad.Appconfig.Appconfig.src_home
            except AttributeError:
                src_home = ""
            legacy.append((src_home or "").replace('\\eSim', '') +
                          '/KiCad/share/kicad/symbols')
        ngveri_sym = generated_symlib_path("eSim_Ngveri", legacy_dirs=legacy)
        cosim_sym = generated_symlib_path("eSim_NgVeriCosim",
                                          legacy_dirs=legacy)
        ensure_lib_registered("eSim_Ngveri", ngveri_sym,
                              descr="eSim NgVeri (Ngspice code model) symbols")
        ensure_lib_registered(
            "eSim_NgVeriCosim", cosim_sym,
            descr="eSim NgVeri d_cosim (Icarus Verilog) symbols")
        return ngveri_sym, cosim_sym

    def _list_models(self):
        '''
            Scan disk for every removable model and tag each with its backend.

            Disk is the single source of truth, and "on disk" means EVERY
            trace, not just modpath.lst: a model built by an older eSim (or one
            whose teardown was interrupted) can be left as nothing but a KiCad
            symbol, or nothing but a param XML, or nothing but a build dir.
            Listing only modpath.lst + NgVeriCosim/*.xml is what made those
            leftovers permanently unremovable from the GUI while still showing
            up in KiCad's eSim_Ngveri / eSim_NgVeriCosim libraries. The union
            comes from discover_ngveri_models; the teardown helpers are all
            idempotent, so removing a model that owns a single trace is safe.

            Returns (names, badges) where badges maps each name to
            "NgVeri"/"d_cosim". modpath.lst is created on demand so a fresh
            install lists cleanly.

            NGHDL (GHDL) models are intentionally NOT listed here: they are
            uninstalled from the NGHDL app's own "Uninstall Models" button (the
            VHDL workflow), not this Verilog-side dialog.
        '''
        _ensure_modpath(self.digital_home + '/modpath.lst')
        ngveri_sym, cosim_sym = self._sym_paths()
        badges = discover_ngveri_models(
            self.digital_home, self.release_dir, self._xml_loc,
            ngveri_sym=ngveri_sym, cosim_sym=cosim_sym,
            cosim_home=CosimConfig.cosim_build_root())
        return list(badges.keys()), badges

    def open_remove_models(self):
        '''
            Open the searchable, multi-select dialog and tear down whatever the
            user picks. Dispatches each name to the right backend teardown --
            legacy NgVeri (Verilator -> Ngveri.cm) vs d_cosim (Icarus ->
            eSim_NgVeriCosim). The two build into separate trees and share
            nothing on disk, so the wrong teardown cannot delete the other
            backend's files -- it just silently leaves the model behind.

            The teardown itself runs on a worker thread with the same progress
            bar a convert build uses. It used to run inline on the GUI thread,
            where the rmtree passes and -- far worse -- the closing `make` +
            `make install` of the ngspice code model froze eSim solid ("not
            responding") for the whole removal.
        '''
        if self._remove_job is not None:
            Dialogs.information(
                self, "Remove Models",
                "A model removal is already in progress. "
                "Please wait for it to finish.",
                QtWidgets.QMessageBox.StandardButton.Ok)
            return

        names, badges = self._list_models()
        if not names:
            Dialogs.information(
                self, "Remove Models",
                "There are no models to remove.",
                QtWidgets.QMessageBox.StandardButton.Ok)
            return

        dlg = RemoveItemsDialog(
            "Remove Models", names, badges=badges,
            item_noun="model", parent=self)
        if not dlg.exec():
            return

        # Belt-and-braces: a blank name must never reach the teardown helpers
        # (os.path.join(base, "") -> "base/" -> rmtree wipes all models). The
        # helpers guard too; this is defence in depth.
        doomed = [n for n in dlg.selected_items() if n and n.strip()]
        if not doomed:
            return

        # Resolve every backend HERE, on the GUI thread, so the worker only
        # does file surgery: on-disk layout is the source of truth for which
        # engine owns a name, and a leftover with no param XML is resolved from
        # the symbol libraries instead of being mislabelled "ngveri".
        plan = [(name, self._model_backend(name)) for name in doomed]

        # One reusable, detached log buffer: worker log lines arrive through
        # the queued removeLog signal and are flushed into the visible console
        # in the epilogue, exactly like a build's currentTermLogs.
        if self._remove_logs is None:
            self._remove_logs = QtWidgets.QTextEdit()
            self.removeLog.connect(self._remove_logs.append)
            self.removeStep.connect(self._on_remove_step)
        self._remove_logs.clear()
        self._remove_log = CosimLog(self._remove_logs,
                                    sink=self.removeLog.emit)

        # ModelGeneration owns the Ngveri.cm rebuild. Build it on the GUI
        # thread (it is a QObject wired to this tab's phase label) and only
        # when a legacy model is actually going away -- a pure d_cosim removal
        # needs no code-model rebuild at all.
        self._remove_model = None
        if any(backend != "cosim" for _, backend in plan):
            self.fname = self._current_verilog_fname()
            self._remove_model = ModelGeneration.ModelGeneration(
                self.fname, self._remove_logs)
            self._remove_model.phase.connect(self._on_build_phase)

        self._set_convert_buttons_enabled(False)
        self._set_remove_buttons_enabled(False)
        self.buildBar.setRange(0, len(plan))
        self.buildBar.setValue(0)
        self._show_build_progress(
            True, "Removing " + str(len(plan)) + " model" +
            ("s" if len(plan) != 1 else "") + "…")
        self._remove_job = BackgroundJob(
            self._removal_pipeline, plan, self._remove_model, parent=self)
        self._remove_job.succeeded.connect(self._on_removal_finished)
        self._remove_job.failed.connect(self._on_removal_error)
        self._remove_job.finished.connect(self._remove_job.deleteLater)
        self._remove_job.start()

    def _removal_pipeline(self, plan, model):
        '''
            Worker-thread half of a removal: the per-model file surgery, then
            ONE Ngveri.cm rebuild for the whole batch. Returns "" on success or
            the rebuild's error text (the dialog is raised by the GUI-thread
            epilogue -- a QMessageBox must never be built off-thread).

            Touches no widget: every line goes through the removeLog sink and
            every progress tick through removeStep, both queued back to the GUI
            thread.
        '''
        log = self._remove_log
        ngveri_needed = False
        for done, (name, backend) in enumerate(plan):
            self.removeStep.emit(done, 'Removing "' + name + '"…')
            if backend == "cosim":
                self._remove_cosim_model(name, log=log)
            else:
                # Defer the (expensive) Ngveri.cm rebuild to one pass after
                # every model is gone, not once per model.
                self._remove_ngveri_model(name, rebuild=False, log=log)
                ngveri_needed = True
        self.removeStep.emit(len(plan), "Finishing…")

        if ngveri_needed and model is not None:
            # Indeterminate from here: make/make install give no countable
            # steps, and the phase label takes over the narration.
            self.removeStep.emit(-1, "Rebuilding Ngveri.cm…")
            return self._run_cm_rebuild(model, log)
        return ""

    def _on_remove_step(self, done, message):
        '''
            Queued from the removal worker: advance the shared progress bar and
            name the model currently being torn down. done < 0 switches the bar
            back to indeterminate for the closing code-model rebuild.
        '''
        if done < 0:
            self.buildBar.setRange(0, 0)
        else:
            self.buildBar.setValue(done)
        if message:
            self.buildStatus.setText(message)

    def _on_removal_finished(self, err):
        '''GUI-thread epilogue for a completed removal.'''
        if err:
            Dialogs.critical(
                self, "Error Message",
                "The ngspice code model could not be rebuilt after removal: " +
                str(err),
                QtWidgets.QMessageBox.StandardButton.Ok)
        self._finish_removal()

    def _on_removal_error(self, msg):
        '''GUI-thread epilogue when the removal worker itself raised.'''
        if self._remove_log is not None:
            self._remove_log.error("Model removal failed: " + msg)
        Dialogs.critical(
            self, "Error Message",
            "Model removal failed: " + str(msg),
            QtWidgets.QMessageBox.StandardButton.Ok)
        self._finish_removal()

    def _finish_removal(self):
        '''
            Flush the removal log into the visible console, restore the bar to
            its build (indeterminate) state, re-enable the controls and drop
            the job refs. Shared by the success and failure epilogues.
        '''
        if self._remove_logs is not None:
            self.entry_var[0].append(self._remove_logs.toHtml())
            self.entry_var[0].verticalScrollBar().setValue(
                self.entry_var[0].verticalScrollBar().maximum())
        self._show_build_progress(False)
        # Builds expect the shared bar indeterminate; put it back.
        self.buildBar.setRange(0, 0)
        self._set_convert_buttons_enabled(True)
        self._set_remove_buttons_enabled(True)
        self._remove_job = None
        self._remove_model = None
        self._remove_log = None

    def _set_remove_buttons_enabled(self, enabled):
        '''Enable/disable the model-management buttons around an async
        removal, so a second teardown cannot race the running one.'''
        for name in ("removeModelsBtn", "removeLintOffBtn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    def _model_backend(self, name):
        '''
            Resolve which backend created a model from the on-disk
            modelParamXML layout -- the single source of truth that survives
            restarts: NgVeriCosim/<name>.xml => cosim, Nghdl/<name>.xml =>
            nghdl, else legacy NgVeri (ngveri). A leftover with no param XML at
            all (an older eSim's model, or an interrupted teardown) is resolved
            from the eSim_NgVeriCosim symbol library instead, so the right
            dismantler runs and the symbol really leaves KiCad. Delegates to
            the tested free function _resolve_backend.
        '''
        return _resolve_backend(self._xml_loc, name,
                                cosim_sym=self._sym_paths()[1])

    def _remove_cosim_model(self, text, log=None):
        '''
            Tear down a d_cosim (Icarus) model: drop its symbol from
            eSim_NgVeriCosim.kicad_sym + its NgVeriCosim/<name>.xml, and delete
            its build directory <DIGITAL_MODEL>/NgVeriCosim/<id>/ (sources,
            connection_info.txt and the compiled vvp).

            Nothing here can touch the legacy NgVeri backend. The two used to
            build into ONE directory per model name, so this teardown deleted
            the Verilator backend's ifspec.ifs/cfunc.mod for a model of the
            same name, left its compiled .o behind in the release tree, and
            (because it therefore HAD to) rewrote the legacy modpath.lst. The
            trees are separate now: this deletes only the d_cosim tree, never
            reads or rewrites modpath.lst, and cannot leave the legacy backend
            in a half-removed state.

            The one exception is a model built BEFORE the split, whose vvp sits
            in the old shared directory. That single FILE is removed; its
            directory is not, because it may be a legacy NgVeri build dir.

            No Ngveri.cm rebuild -- d_cosim never registered a code model.

            `log` is injected by the async removal pipeline (a logger whose GUI
            sink is a queued signal). The default -- writing straight to the
            console widget -- is only for the GUI-thread callers (a backend
            switch during a build).
        '''
        if log is None:
            log = CosimLog(self.entry_var[0])
        log.phase('REMOVE d_cosim model "' + str(text) + '"')

        model_id = CosimConfig.cosim_model_id(text)
        if not model_id:
            log.warn("Refusing to remove a d_cosim model with a blank name.")
            return

        try:
            symbol = createkicadCosim.CosimSchematic()
            symbol.init(model_id, "")
            symbol.deleteKicadSymbol()
            log.info("Removed eSim_NgVeriCosim symbol + NgVeriCosim/" +
                     model_id + ".xml")
        except Exception as err:
            log.warn("Could not remove d_cosim KiCad symbol for '" +
                     model_id + "': " + str(err))

        # The d_cosim build tree. _safe_model_subdir re-derives it from the
        # root so a name carrying a separator or resolving outside the root can
        # never reach rmtree (defence in depth: cosim_model_id already rejects
        # blanks, and cosim_build_dir joins one component).
        build_dir = _safe_model_subdir(CosimConfig.cosim_build_root(),
                                       model_id)
        if build_dir is None:
            log.warn("Refusing to remove unsafe d_cosim build dir for model "
                     "name: " + repr(text))
        else:
            try:
                shutil.rmtree(build_dir)
                log.info("Removed build dir: " + build_dir)
            except FileNotFoundError:
                log.detail("Build dir already absent: " + build_dir)
            except OSError as err:
                log.warn("Could not remove d_cosim build dir '" +
                         build_dir + "': " + str(err))

        # Pre-split leftover: the vvp only, never its directory.
        stale = CosimConfig.legacy_cosim_vvp_path(model_id)
        if stale and os.path.isfile(stale):
            try:
                os.remove(stale)
                log.info("Removed the pre-split vvp at " + stale)
            except OSError as err:
                log.warn("Could not remove the pre-split vvp at " + stale +
                         ": " + str(err))

        log.ok('d_cosim model "' + model_id + '" removed.')

    def _remove_legacy_dirs(self, name, log):
        '''
            Delete both per-model directories of a legacy NgVeri model:

              * source   <digital_home>/<model>            -- ifspec.ifs (what
                cmpp reads) plus cfunc/sim_main, and
              * release  <release>/src/xspice/icm/Ngveri/<model> -- the
                compiled .o/.a, which otherwise get re-bundled and keep the
                model answering in ngspice long after its symbol and
                modpath.lst line are gone.

            Both, always: deleting only the sources is the half-removal that
            makes a model look deleted and behave alive.

            The directory is resolved by its ACTUAL on-disk name
            (_actual_subdir_name), because the name being removed comes from a
            modpath line or a symbol block and need not match the directory's
            case. rmtree on the wrong case silently does nothing on Linux, and
            the model reappears in the next listing.
        '''
        for label, base in (
                ("source", self.digital_home),
                ("release", os.path.join(
                    self.release_dir or "", "src/xspice/icm/Ngveri"))):
            on_disk = _actual_subdir_name(base, name) or name
            model_dir = _safe_model_subdir(base, on_disk)
            if model_dir is None:
                log.warn("Refusing to remove unsafe " + label +
                         " dir for model name: " + repr(name))
                continue
            try:
                shutil.rmtree(model_dir)
                log.info("Removed " + label + " dir: " + model_dir)
            except FileNotFoundError:
                log.detail(label + " dir already absent: " + model_dir)
            except OSError as err:
                log.warn("Could not remove " + label + " dir '" +
                         model_dir + "': " + str(err))

    def _rescue_presplit_vvp(self, name, log):
        '''
            Migrate a pre-split d_cosim vvp out of the LEGACY build dir before
            a legacy teardown deletes that directory.

            Until the backends were given separate trees they built into one
            directory per model name, so <DIGITAL_MODEL>/Ngveri/<id>/<id> could
            be a d_cosim artifact sitting inside a Verilator build dir. Removing
            the NgVeri model then destroyed a d_cosim model that is still listed
            in KiCad, leaving a symbol that fails at simulation time with
            nothing on screen to explain it.

            Only fires when the model is still a live d_cosim model (its
            NgVeriCosim param XML exists) and the canonical location is empty,
            so it can neither resurrect a removed model nor overwrite a newer
            build. Best-effort: a failure is logged and the teardown continues.
        '''
        model_id = CosimConfig.cosim_model_id(name)
        if not model_id:
            return False
        if not os.path.isfile(os.path.join(self._xml_loc, 'NgVeriCosim',
                                           model_id + '.xml')):
            return False
        stale = CosimConfig.legacy_cosim_vvp_path(model_id)
        target = CosimConfig.cosim_vvp_target(model_id)
        if not stale or not target or not os.path.isfile(stale):
            return False
        if os.path.exists(target):
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.move(stale, target)
        except OSError as err:
            log.warn('Could not move the pre-split d_cosim vvp for "' +
                     model_id + '" out of the NgVeri build dir: ' + str(err) +
                     ' -- the d_cosim model will need rebuilding.')
            return False
        log.info('Moved the d_cosim vvp for "' + model_id + '" to its own '
                 'tree (' + target + ') so this NgVeri removal cannot delete '
                 'it.')
        return True

    def _strip_modpathlst(self, text, log=None):
        '''
            Remove every line equal to `text` from modpath.lst (idempotent).
            Returns True if a line was dropped. Logs via `log` when given.

            Delegates to the stdlib-only shared helper so the rewrite is atomic
            and identical to the NGHDL-side teardown: a crash part-way through
            truncates the list, and cmpp then aborts EVERY later code-model
            build with an error pointing nowhere near model removal.
        '''
        dropped = _strip_modpath_line(
            self.digital_home + '/modpath.lst', str(text))
        if dropped and log:
            log.info('Dropped "' + str(text) + '" from modpath.lst')
        return dropped

    def _remove_ngveri_model(self, text, rebuild=True, log=None):
        '''
            Tear down a legacy NgVeri (Verilator) model: drop it from
            modpath.lst, remove its eSim_Ngveri symbol + param XML, delete the
            per-model build dir, then rebuild/reinstall Ngveri.cm so ngspice
            truly unlinks it.

            Pass rebuild=False when removing several models in one pass; the
            caller then runs a single _rebuild_ngveri_cm() at the end rather
            than rebuilding the code model once per model. `log` is injected by
            the async removal pipeline (see _remove_cosim_model).
        '''
        if log is None:
            log = CosimLog(self.entry_var[0])
        log.phase('REMOVE NgVeri model "' + str(text) + '"')

        # A model built before the two backends were given separate trees keeps
        # its d_cosim vvp INSIDE this legacy build dir. Move it to the d_cosim
        # tree before the rmtree below so tearing down the NgVeri model cannot
        # take a still-live d_cosim model's only artifact with it.
        self._rescue_presplit_vvp(text, log)

        # Drop the model from modpath.lst (guarded: absent => no crash)
        self._strip_modpathlst(text, log)

        # Remove the KiCad symbol + orphan param XML too, so the model
        # actually disappears from eSim_Ngveri in KiCad (previously left
        # behind forever).
        try:
            symbol = createkicad.AutoSchematic()
            symbol.init(text, "")
            symbol.deleteKicadSymbol()
            log.info("Removed eSim_Ngveri symbol + param XML")
        except Exception as err:
            log.warn("Could not remove KiCad symbol for '" +
                     str(text) + "': " + str(err))

        self._remove_legacy_dirs(text, log)

        log.ok('NgVeri model "' + str(text) + '" files removed.')
        if rebuild:
            self._rebuild_ngveri_cm(log)

    def _current_verilog_fname(self):
        '''
            The current tab's Verilog path, or "" when this tab has no slot in
            Maker.verilogFile yet (a remove-only session). The whole-icm
            rebuild ignores the value entirely, so an empty string is safe and
            this guard avoids an IndexError -- matching the length checks the
            add* siblings already do.
        '''
        vf = Maker.verilogFile
        return vf[self.filecount] if len(vf) > self.filecount else ""

    def _run_cm_rebuild(self, model, log):
        '''
            Rebuild and reinstall the Ngveri.cm code model so ngspice unlinks
            every model already stripped from modpath.lst. Run once after a
            batch removal. prune_modpathlst() first sweeps any unrelated ghost
            entries so the rebuild can't fail on a dead line left by something
            else.

            Worker-thread safe: returns "" on success or the error text, and
            raises no dialog -- the caller shows it on the GUI thread.

            A missing legacy toolchain is NOT an error here. Removing leftovers
            (an old install's orphan symbol, an interrupted teardown) has to
            work on a machine that can no longer build code models at all; the
            files are gone either way, and the next successful build reconciles
            ngspice.
        '''
        if not model.require_legacy_toolchain():
            log.warn(
                "Ngveri.cm was NOT rebuilt: the NgVeri (Verilator) toolchain "
                "is not available on this machine. The model files are "
                "removed; ngspice drops the models on the next successful "
                "code-model build.")
            return ""
        model.prune_modpathlst()

        try:
            log.phase("Rebuild Ngveri.cm")
            # make + make install on every platform (Windows is configured
            # with prefix=install_dir like Ubuntu; see _legacy_build_pipeline).
            ok = model.runMake()
            ok = model.runMakeInstall() and ok
            if not ok:
                raise RuntimeError(
                    "the ngspice code-model rebuild returned a "
                    "non-zero exit status")
        except Exception as err:
            return str(err)
        log.ok("Ngveri.cm rebuilt.")
        return ""

    def _rebuild_ngveri_cm(self, log):
        '''
            GUI-thread wrapper around _run_cm_rebuild: rebuild the code model
            and report a failure in a dialog. Used by the single-model
            teardown path (_remove_ngveri_model(rebuild=True)); the batch
            removal calls _run_cm_rebuild directly from its worker.
        '''
        self.fname = self._current_verilog_fname()
        model = ModelGeneration.ModelGeneration(self.fname, self.entry_var[0])
        err = self._run_cm_rebuild(model, log)
        if err:
            Dialogs.critical(
                self, "Error Message",
                "The ngspice code model could not be rebuilt after removal: " +
                err,
                QtWidgets.QMessageBox.StandardButton.Ok
            )

    # ------------------------------------------------------------------ #
    #  Backend switching (d_cosim <-> legacy NgVeri for the same model)
    # ------------------------------------------------------------------ #
    def _legacy_registered(self, name):
        '''
            True if `name` exists as a legacy NgVeri model.

            Every trace counts, not just the modpath.lst line: a build dir with
            cmpp inputs, an eSim_Ngveri param XML, or a compiled release dir is
            just as much "this name is already an NgVeri model", and each one
            outlives an interrupted teardown or a build that died after
            creating its directory. Checking modpath.lst alone is what let a
            d_cosim build silently start on top of a live NgVeri model, since a
            ghost line is pruned (prune_modpathlst) while the files stay.

            Case-insensitive, because on Windows the filesystem is: a modpath
            line reading "Counter" and a probe for "counter" name the same
            directory there, and an exact compare would answer False while
            rmtree happily deletes it.
        '''
        low = str(name).strip().lower()
        if not low:
            return False
        try:
            with open(self.digital_home + '/modpath.lst') as f:
                if any(ln.strip().lower() == low for ln in f):
                    return True
        except OSError:
            pass
        for base in (self.digital_home,
                     os.path.join(self.release_dir or "",
                                  "src/xspice/icm/Ngveri")):
            try:
                entries = os.listdir(base)
            except OSError:
                continue
            for entry in entries:
                if entry.lower() != low:
                    continue
                if any(os.path.exists(os.path.join(base, entry, marker))
                       for marker in _MODEL_DIR_MARKERS):
                    return True
        try:
            if any(n.lower() == low + '.xml'
                   for n in os.listdir(os.path.join(self._xml_loc, 'Ngveri'))):
                return True
        except OSError:
            pass
        return False

    def _purge_legacy_registration(self, name, log):
        '''
            Light teardown of a legacy NgVeri model: drop its modpath.lst line,
            eSim_Ngveri symbol and both build dirs -- but NO Ngveri.cm rebuild,
            so a d_cosim create stays independent of the Verilator toolchain.
            prune_modpathlst() keeps later legacy builds safe.
        '''
        # Same pre-split rescue as _remove_ngveri_model: this runs while
        # switching a model TO d_cosim, so a vvp left in the legacy dir by an
        # older eSim must survive the rmtree below.
        self._rescue_presplit_vvp(name, log)
        self._strip_modpathlst(name, log)
        try:
            symbol = createkicad.AutoSchematic()
            symbol.init(name, "")
            symbol.deleteKicadSymbol()
            log.info("Removed eSim_Ngveri symbol for " + str(name))
        except Exception as err:
            log.warn("Could not remove eSim_Ngveri symbol for '" +
                     str(name) + "': " + str(err))
        self._remove_legacy_dirs(name, log)

    def _preflight_model_name(self, target, model):
        '''
            Settle the model's NAME before a single file is written.

            One name means one backend, because the netlister resolves a
            schematic value to a model by filename alone (Processing indexes
            library/modelParamXML/**/<value>.xml): two libraries holding the
            same <name>.xml make that lookup ambiguous and the convert fails.

            That rule was previously enforced at the END of a build, inside
            KiCad symbol creation -- so a d_cosim user paid an iverilog compile
            and an NgVeri user paid verilator plus a full ngspice rebuild
            before being told the name was taken, and the half-built model was
            left behind in the remove-model dialog with nothing to remove it
            for. Asking here costs a directory listing.

            A clash with the OTHER Verilog backend is not handled here: that is
            the same design moving between backends, and
            _switch_backends_if_needed offers exactly that.

            For a real clash the way out is to build under a free name rather
            than to refuse. The model name is not the module name -- the
            wrapper instantiates the module, the model name only labels the
            block -- so an alternative renames nothing in the user's code.
            eSim will NOT offer to delete the NGHDL model in its place: that
            one was built by a different toolchain from different sources, and
            removing it needs a ghdl.cm rebuild the Verilog page cannot
            honestly promise. It says where to do that instead.

            Returns True to proceed (possibly under a renamed model), False to
            abort the build.
        '''
        name = CosimConfig.cosim_model_id(getattr(model, "model_stem", ""))
        if not name:
            return True
        own = "NgVeriCosim" if target == "cosim" else "Ngveri"
        owner = model_registry.owner_of(self._xml_loc, name)
        if owner in ("", own) or owner in model_registry.VERILOG_DIRS:
            return True

        log = CosimLog(self.entry_var[0])
        label = model_registry.library_label(owner)
        alt = model_registry.free_name(self._xml_loc, name)
        detail = (
            "eSim looks a block up in the netlist by its name alone, so one "
            "name can only ever mean one model. Building a second '%s' would "
            "make every schematic that uses it ambiguous."
            % name)
        if owner == model_registry.NGHDL_DIR:
            detail += ("\n\nTo free the name instead, remove the VHDL model "
                       "from Makerchip ▸ NGHDL ▸ Remove Models "
                       "(that rebuilds ghdl.cm) and convert again.")
        else:
            detail += ("\n\nThis name belongs to a model eSim ships, so it "
                       "cannot be freed.")

        box = Dialogs.make_message_box(
            self, Dialogs.Icon.Warning, "That model name is taken",
            "<b>'" + name + "' is already a " + label + " model.</b>",
            informative_text=detail,
            buttons=Dialogs.Button.Cancel,
            default_button=Dialogs.Button.Cancel)
        build_btn = None
        if alt:
            build_btn = box.addButton(
                "Build as '" + alt + "'",
                QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(build_btn)
        Dialogs.show_modal(box)

        if build_btn is not None and box.clickedButton() is build_btn:
            model.rename_model(alt)
            log.warn('"' + name + '" is already a ' + label +
                     ' model -- building this one as "' + alt +
                     '" instead. Your Verilog is unchanged; only the block '
                     'name differs.')
            return True
        log.warn('Convert cancelled -- "' + name + '" is already a ' + label +
                 ' model. Nothing was built.')
        return False

    def _confirm_switch(self, name, from_backend, to_backend):
        '''
            Yes/No dialog shown before replacing an existing model's backend.
            Returns True if the user agreed to switch.
        '''
        ret = Dialogs.question(
            self, "Switch model backend?",
            '<b>"' + str(name) + '"</b> already exists as a <b>' +
            from_backend + '</b> model.<br><br>Rebuild it as a <b>' +
            to_backend + '</b> model instead?<br>'
            'The existing ' + from_backend + ' version will be removed.',
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        return ret == QtWidgets.QMessageBox.StandardButton.Yes

    def _switch_backends_if_needed(self, target, name):
        '''
            If `name` already exists under the OTHER backend, ASK the user, then
            remove that stale copy so building under `target` is a clean switch
            instead of a duplicate (two symbols, a co-mingled build dir, or a
            ghost modpath.lst entry). target is "ngveri" or "cosim".

            Returns True to proceed with the build, False if no switch is needed
            is also True; only a user-declined switch returns False (the caller
            must then abort the build).
        '''
        log = CosimLog(self.entry_var[0])
        low = CosimConfig.cosim_model_id(name)
        if not low:
            return True
        if target == "ngveri":
            if not self._cosim_registered(low):
                return True
            if not self._confirm_switch(low, "d_cosim", "NgVeri (Verilator)"):
                log.warn('Switch cancelled -- "' + low + '" kept as a d_cosim '
                         'model. NgVeri build aborted.')
                return False
            log.phase('SWITCH backend: d_cosim -> NgVeri for "' + low + '"')
            log.info("Removing existing d_cosim version first.")
            self._remove_cosim_model(low)
            return True
        elif target == "cosim":
            if not self._legacy_registered(low):
                return True
            if not self._confirm_switch(low, "NgVeri (Verilator)", "d_cosim"):
                log.warn('Switch cancelled -- "' + low + '" kept as a '
                         'NgVeri model. d_cosim build aborted.')
                return False
            log.phase('SWITCH backend: NgVeri -> d_cosim for "' + low + '"')
            log.info("Removing existing NgVeri version first "
                     "(no Ngveri.cm rebuild).")
            self._purge_legacy_registration(low, log)
            return True
        return True

    def _cosim_registered(self, name):
        '''
            True if `name` exists as a d_cosim model: a param XML under
            NgVeriCosim/, or a build dir in the d_cosim tree. Mirrors
            _legacy_registered -- both must count every trace, or a build
            starts on top of a live model of the other backend.
        '''
        model_id = CosimConfig.cosim_model_id(name)
        if not model_id:
            return False
        try:
            if any(n.lower() == model_id + '.xml' for n in
                   os.listdir(os.path.join(self._xml_loc, 'NgVeriCosim'))):
                return True
        except OSError:
            pass
        build_dir = CosimConfig.cosim_build_dir(model_id)
        return bool(build_dir) and os.path.isdir(build_dir)

    def _lint_off_path(self):
        '''Path to library/tlv/lint_off.txt, anchored to the install root.'''
        return paths.library_path("tlv/lint_off.txt")

    def _list_lint_off(self):
        '''Current lint_off entries (one per non-blank line), in file order.'''
        try:
            with open(self._lint_off_path()) as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return []

    def open_remove_lint_off(self):
        '''
            Open the searchable, multi-select dialog and drop the chosen
            lint_off entries from library/tlv/lint_off.txt in one pass.
        '''
        entries = self._list_lint_off()
        if not entries:
            Dialogs.information(
                self, "Remove lint_off",
                "There are no lint_off entries to remove.",
                QtWidgets.QMessageBox.StandardButton.Ok)
            return

        dlg = RemoveItemsDialog(
            "Remove lint_off", entries, item_noun="lint_off entry",
            parent=self)
        if not dlg.exec():
            return

        doomed = set(dlg.selected_items())
        try:
            kept = [e for e in self._list_lint_off() if e not in doomed]
            with open(self._lint_off_path(), 'w') as fh:
                fh.write("\n".join(kept) + ("\n" if kept else ""))
        except OSError as err:
            Dialogs.warning(
                self, "Warning",
                "Could not update lint_off.txt: " + str(err),
                QtWidgets.QMessageBox.StandardButton.Ok)

    def add_lint_off(self):
        '''
            This is to add lint_off comments needed by the verilator warnings.
            This function writes to the lint_off.txt in the library/tlv folder.
        '''
        text = self.entry_var[3].text().strip()
        if not text:
            return

        # Dedup against the file (the picker is now a dialog read fresh each
        # time, so there is no combo to query for an existing entry).
        if text not in self._list_lint_off():
            with open(self._lint_off_path(), 'a+') as fh:
                fh.write(text + "\n")
        self.entry_var[3].setText("")

    def creategroup(self):
        '''
            Creates various other groups like terminal, remove modlst,
            remove lint_off and add lint_off
        '''
        self.trbox = QtWidgets.QGroupBox()
        self.trbox.setTitle("Terminal")
        # self.trbox.setDisabled(True)
        # self.trbox.setVisible(False)
        self.trgrid = QtWidgets.QGridLayout()
        self.trbox.setLayout(self.trgrid)
        self.count = 0

        self.start = QtWidgets.QLabel("Terminal")
        # self.trgrid.addWidget(self.start, 2,0)
        self.trgrid.setContentsMargins(12, 12, 12, 12)
        self.trgrid.setHorizontalSpacing(12)

        # Left: the console fills the panel and grows with the window.
        self.entry_var[self.count] = QtWidgets.QTextEdit()
        self.entry_var[self.count].setReadOnly(1)
        self.entry_var[self.count].setMaximumWidth(1000)
        self.entry_var[self.count].setMaximumHeight(1000)
        # Enough console to read a build step in, and no more: this is the one
        # elastic widget on the page, so its minimum sets the floor under which
        # the whole stage starts scrolling (and hides the progress bar).
        self.entry_var[self.count].setMinimumHeight(120)
        self.trgrid.addWidget(self.entry_var[self.count], 0, 0)
        self.count += 1

        # Right: model-management controls stacked in a tidy column that hugs
        # the top of the console instead of floating in the grid's empty rows
        # (which used to spread the buttons out and leave a void beneath them).
        controls = QtWidgets.QVBoxLayout()
        controls.setSpacing(8)
        controls.setContentsMargins(0, 0, 0, 0)

        # A button opens a searchable, multi-select dialog instead of the old
        # giant QComboBox -- whose popup, crippled by the groupbox stylesheet,
        # listed every model with no scrollbar and deleted one at a time.
        self.entry_var[self.count] = QtWidgets.QPushButton(
            "Remove Verilog Models…")
        self.entry_var[self.count].clicked.connect(self.open_remove_models)
        controls.addWidget(self.entry_var[self.count])
        # Named ref so the async teardown can grey it out while it runs
        # (entry_var is index-keyed and shared with the lint controls).
        self.removeModelsBtn = self.entry_var[self.count]
        self.count += 1

        self.entry_var[self.count] = QtWidgets.QPushButton("Remove lint_off")
        self.entry_var[self.count].clicked.connect(self.open_remove_lint_off)
        controls.addWidget(self.entry_var[self.count])
        self.removeLintOffBtn = self.entry_var[self.count]
        self.count += 1

        # lint_off entry + its Add button share one row so they read as a pair.
        add_row = QtWidgets.QHBoxLayout()
        add_row.setSpacing(6)
        self.entry_var[self.count] = QtWidgets.QLineEdit(self)
        self.entry_var[self.count].setPlaceholderText("lint_off entry")
        add_row.addWidget(self.entry_var[self.count], 1)
        self.count += 1
        self.entry_var[self.count] = QtWidgets.QPushButton("Add lint_off")
        self.entry_var[self.count].clicked.connect(self.add_lint_off)
        add_row.addWidget(self.entry_var[self.count])
        self.count += 1
        controls.addLayout(add_row)

        # The convert top bar stays uncluttered by parking the "which method,
        # when" explainer down here, in what used to be dead space beneath the
        # lint controls. Neutral copy: names what each backend does and states
        # they are equivalent, without claiming either is buggy or naming an
        # unverified cause ("doesn't complete" is true of any tool). "caps"
        # and "muted" QLabel classes are theme-safe (defined in both QSS).
        controls.addSpacing(14)

        # Collapsed by default, and that is a layout decision as much as an
        # editorial one. A word-wrapped paragraph in a 210px column is ~250px
        # of MINIMUM height, and a panel's minimum is a hard floor on the whole
        # page: it is what forced the convert stage to scroll in the dock, and
        # a scrolled convert stage hides the build progress bar exactly when
        # the user needs it. Folded away, the same copy costs one row and is
        # one click from being read.
        self.convertHintToggle = QtWidgets.QToolButton()
        self.convertHintToggle.setText("Which method?")
        self.convertHintToggle.setCheckable(True)
        self.convertHintToggle.setChecked(False)
        self.convertHintToggle.setAutoRaise(True)
        self.convertHintToggle.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.convertHintToggle.setArrowType(
            QtCore.Qt.ArrowType.RightArrow)
        controls.addWidget(self.convertHintToggle)

        self.convertHint = QtWidgets.QLabel(
            "Both convert your Verilog into an ngspice model — same result, "
            "different backend.\n\n"
            "Dual Co-sim runs Icarus through ngspice d_cosim: no compiler "
            "and no ngspice rebuild.\n\n"
            "NgVeri builds a native ngspice code model.\n\n"
            "If one doesn't complete, use the other.")
        self.convertHint.setWordWrap(True)
        self.convertHint.setProperty("cssClass", "muted")
        self.convertHint.setVisible(False)
        controls.addWidget(self.convertHint)
        self.convertHintToggle.toggled.connect(self._toggle_convert_hint)

        # Stretch pins everything to the top; empty space collapses below,
        # flush with the console rather than wedged between the widgets.
        controls.addStretch(1)

        controls_box = QtWidgets.QWidget()
        controls_box.setLayout(controls)
        # The buttons in this column ("Add Project", "Remove Models", ...) take
        # their padding and font from the QSS, which scales with zoom -- so the
        # column that holds them has to as well, or their labels outgrow it.
        # Registered rather than set once: this panel outlives a zoom change.
        on_zoom_changed(
            controls_box,
            lambda z, w=controls_box: w.setFixedWidth(zoom_px(210, z)))
        self.trgrid.addWidget(
            controls_box, 0, 1, QtCore.Qt.AlignmentFlag.AlignTop)

        # Live build progress under the console: an indeterminate bar + a label
        # naming the current step, shown ONLY while a convert build runs on the
        # worker thread. The bar animates because the GUI event loop stays free
        # (the build is off-thread), and the label is driven by
        # ModelGeneration.phase -- so a long verilator/make reads as "working",
        # not "hung".
        self.buildStatus = QtWidgets.QLabel("")
        self.buildStatus.setProperty("cssClass", "muted")
        self.buildStatus.setVisible(False)
        self.buildBar = QtWidgets.QProgressBar()
        self.buildBar.setRange(0, 0)          # 0..0 == indeterminate "busy"
        self.buildBar.setTextVisible(False)
        self.buildBar.setVisible(False)
        progress_row = QtWidgets.QHBoxLayout()
        progress_row.setContentsMargins(0, 6, 0, 0)
        progress_row.setSpacing(10)
        progress_row.addWidget(self.buildStatus)
        progress_row.addWidget(self.buildBar, 1)
        progress_wrap = QtWidgets.QWidget()
        progress_wrap.setLayout(progress_row)
        self.trgrid.addWidget(progress_wrap, 1, 0, 1, 2)
        # Console takes all the vertical slack; the progress row stays compact.
        self.trgrid.setRowStretch(0, 1)
        self.trgrid.setRowStretch(1, 0)

        # Console soaks up horizontal space; the control column stays compact.
        self.trgrid.setColumnStretch(0, 1)
        self.trgrid.setColumnStretch(1, 0)

        # Border/title styling comes from the global Aurora QGroupBox QSS so
        # the group reads with the same gradient hairline as the rest of eSim.

        return self.trbox
