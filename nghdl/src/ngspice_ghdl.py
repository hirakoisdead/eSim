#!/usr/bin/env python3

# This file create the GUI to install code model in the Ngspice.

import os
import re
import sys
import shutil
import subprocess
import tempfile
from PyQt6 import QtGui, QtCore, QtWidgets
from configparser import ConfigParser
from Appconfig import Appconfig
from createKicadLibrary import AutoSchematic
from model_generation import ModelGeneration
# Vendored, byte-identical copies of eSim's helpers (drift-guarded by tests).
# NGHDL is packaged separately and must never import eSim, so the model
# removal here uses these local copies, exactly as the symbol writer does.
import kicad_symlib
import model_teardown
from RemoveItemsDialog import RemoveItemsDialog


class _BackgroundJob(QtCore.QThread):
    """Run ``fn(*args)`` on a worker thread, reporting back through queued
    signals.

    NGHDL is packaged standalone and must never import eSim, so this is a local
    twin of maker.hdl.jobs.BackgroundJob. It exists for model removal: the
    teardown deletes whole build trees and rewrites the symbol library, which
    on the GUI thread froze the window for seconds with no feedback at all."""

    succeeded = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self):
        try:
            result = self._fn(*self._args)
        except Exception as exc:            # surfaced to the UI as failed()
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class Mainwindow(QtWidgets.QWidget):

    # Emitted from the removal worker; both receivers live on the GUI thread,
    # so Qt queues the calls and the worker never touches a widget.
    removeLog = QtCore.pyqtSignal(str)
    removeStep = QtCore.pyqtSignal(int, str)

    def __init__(self, parent=None, embedded=False):
        # NOTE: this class is a QWidget. Initialise it as one (the previous
        # QtWidgets.QMainWindow.__init__ call worked only by accident).
        super().__init__(parent)
        # embedded=True  -> running as a tab inside eSim's Makerchip dock.
        # embedded=False -> running standalone via the `nghdl`/`nghdl -e` CLI.
        self.embedded = embedded
        # When embedded, behave like `nghdl -e` so the KiCad schematic symbol
        # is generated after a successful build.
        if embedded:
            Appconfig.esimFlag = 1
        # Remember the host (eSim) working directory. The upload flow changes
        # the CWD; this lets us always restore it and never strand eSim.
        self._home_cwd = os.getcwd()
        print("Initializing..........")

        # Per-user config lives at ~/.nghdl/config.ini on EVERY platform (the
        # Windows bootstrap writes it there too). The old nt branch read a
        # CWD-relative 'library/config/.nghdl/config.ini', which only worked
        # when eSim happened to be launched from its install root.
        self.home = os.path.expanduser('~')

        # Reading all variables from config.ini. A missing/empty config raises
        # here; when embedded the caller catches it and shows a placeholder
        # instead of letting NGHDL break the Makerchip dock.
        self.parser = ConfigParser()
        self.parser.read(
            os.path.join(self.home, os.path.join('.nghdl', 'config.ini'))
        )
        self.nghdl_home = self.parser.get('NGHDL', 'NGHDL_HOME')
        self.release_dir = self.parser.get('NGHDL', 'RELEASE')
        self.src_home = self.parser.get('SRC', 'SRC_HOME')
        self.licensefile = self.parser.get('SRC', 'LICENSE')
        # Printing LICENCE file on terminal (non-fatal if it is missing)
        try:
            with open(self.licensefile, 'r') as fileopen:
                print(fileopen.read())
        except OSError as e:
            print("Could not read NGHDL license file:", e)
        self.file_list = []       # to keep the supporting files
        self.filename = ''
        self.errorFlag = False    # to keep the check of "make install" errors
        self._removejob = None    # running teardown worker; None == idle
        self.initUI()

    def initUI(self):
        # The page is one linear task read top to bottom: (1) pick the VHDL
        # model, (2) optionally stage supporting .vhdl files, (3) Upload &
        # Build. The console shows the build output and owns the vertical
        # space. Model *uninstall* is maintenance, not part of that flow, so it
        # lives in a quiet footer with a distinct verb -- never mistaken for
        # the list's "Remove".

        # ---- Step 1: the top-level VHDL model file --------------------------
        self.ledit = QtWidgets.QLineEdit(self)
        self.ledit.setPlaceholderText("Select the .vhdl model file to build…")
        self.ledit.setClearButtonEnabled(True)
        self.browsebtn = QtWidgets.QPushButton('Browse…')
        self.browsebtn.setToolTip("Choose the top-level .vhdl file for your model.")
        self.browsebtn.clicked.connect(self.browseFile)

        modelbox = QtWidgets.QGroupBox("1 · VHDL model")
        modelrow = QtWidgets.QHBoxLayout()
        modelrow.setSpacing(8)
        modelrow.addWidget(self.ledit, 1)
        modelrow.addWidget(self.browsebtn)
        modelbox.setLayout(modelrow)

        # ---- Step 2: optional supporting (dependency) files ----------------
        # A compact list, not a full text editor -- these are just a handful of
        # file paths. Add/Remove are scoped right beside the list, so "Remove"
        # unambiguously means "drop from this list".
        self.filelist = QtWidgets.QListWidget(self)
        self.filelist.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.filelist.setMaximumHeight(130)
        self.filelist.setToolTip(
            "Dependency .vhdl files compiled alongside the model above.")
        self.filelist.itemSelectionChanged.connect(self._sync_file_buttons)

        self.addbtn = QtWidgets.QPushButton('Add…')
        self.addbtn.setToolTip(
            "Add dependency .vhdl file(s) to compile with the model.")
        self.addbtn.clicked.connect(self.addFiles)
        self.removebtn = QtWidgets.QPushButton('Remove')
        self.removebtn.setToolTip(
            "Remove the selected file(s) from this list. Does NOT uninstall a "
            "built model — use “Uninstall Models” above.")
        self.removebtn.setEnabled(False)
        self.removebtn.clicked.connect(self.removeFiles)

        fileshint = QtWidgets.QLabel(
            "Optional — extra .vhdl files your model depends on.")
        fileshint.setObjectName("hint")

        supportbox = QtWidgets.QGroupBox("2 · Supporting files")
        supportv = QtWidgets.QVBoxLayout()
        supportv.setSpacing(6)
        supportv.addWidget(fileshint)
        supportrow = QtWidgets.QHBoxLayout()
        supportrow.setSpacing(8)
        supportrow.addWidget(self.filelist, 1)
        filebtns = QtWidgets.QVBoxLayout()
        filebtns.setSpacing(6)
        filebtns.addWidget(self.addbtn)
        filebtns.addWidget(self.removebtn)
        filebtns.addStretch(1)
        supportrow.addLayout(filebtns)
        supportv.addLayout(supportrow)
        supportbox.setLayout(supportv)

        # ---- The one primary action ----------------------------------------
        self.uploadbtn = QtWidgets.QPushButton('Upload && Build')
        self.uploadbtn.setObjectName("primary")
        self.uploadbtn.setMinimumHeight(34)
        self.uploadbtn.setToolTip(
            "Compile the selected VHDL into an ngspice code model and KiCad "
            "symbol.")
        self.uploadbtn.clicked.connect(self.uploadModel)
        actionrow = QtWidgets.QHBoxLayout()
        actionrow.addStretch(1)
        actionrow.addWidget(self.uploadbtn)

        # ---- Console: build output, owns the vertical stretch --------------
        self.termedit = QtWidgets.QTextEdit(self)
        self.termedit.setReadOnly(True)
        mono = QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(10)
        self.termedit.setFont(mono)
        pal = QtGui.QPalette()
        pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(17, 17, 17))
        self.termedit.setPalette(pal)
        self.termedit.setStyleSheet(
            "QTextEdit { color: #e6e6e6; background-color: #111111; "
            "border: none; }")
        self.process = QtCore.QProcess(self)

        consolebox = QtWidgets.QGroupBox("Console")
        consolev = QtWidgets.QVBoxLayout()
        consolev.addWidget(self.termedit)
        consolebox.setLayout(consolev)

        # ---- Live progress: a bar + a label naming the current step --------
        # Shown while a build or an uninstall runs. Both are off the GUI thread
        # (QProcess for make, a worker for the teardown), so the bar actually
        # animates -- which is the whole point: an uninstall used to freeze the
        # window with no indication that anything was happening.
        self.progressStatus = QtWidgets.QLabel("")
        self.progressStatus.setObjectName("hint")
        self.progressStatus.setVisible(False)
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setRange(0, 0)       # 0..0 == indeterminate "busy"
        self.progressBar.setTextVisible(False)
        self.progressBar.setVisible(False)
        progressrow = QtWidgets.QHBoxLayout()
        progressrow.setSpacing(10)
        progressrow.addWidget(self.progressStatus)
        progressrow.addWidget(self.progressBar, 1)

        # Queued sinks for the removal worker (see _BackgroundJob).
        self.removeLog.connect(self.termedit.append)
        self.removeStep.connect(self._on_remove_step)

        # ---- Header: page title + model maintenance (uninstall) ------------
        # Uninstall is maintenance, kept out of the numbered build flow so it is
        # never mistaken for a build step -- but it now sits top-right where it
        # is always visible and fully legible, instead of marooned in a footer
        # below the console where it read as an afterthought.
        pagetitle = QtWidgets.QLabel("Build an NGHDL model from VHDL")
        pagetitle.setObjectName("pagetitle")

        self.removemodelbtn = QtWidgets.QPushButton('Uninstall Models…')
        self.removemodelbtn.setObjectName("uninstall")
        self.removemodelbtn.setMinimumHeight(30)
        self.removemodelbtn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.removemodelbtn.setToolTip(
            "Remove one or more NGHDL models already installed on this "
            "machine.")
        self.removemodelbtn.clicked.connect(self.openRemoveModels)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(pagetitle)
        header.addStretch(1)
        header.addWidget(self.removemodelbtn)

        # Exit is created in every mode (the build callbacks toggle it), but a
        # tab has no business exiting all of eSim, so it is only *placed* in
        # the standalone window's footer.
        self.exitbtn = QtWidgets.QPushButton('Exit')
        self.exitbtn.clicked.connect(self.closeWindow)

        # ---- Assemble -------------------------------------------------------
        grid = QtWidgets.QVBoxLayout()
        grid.setSpacing(10)
        grid.addLayout(header)
        grid.addWidget(modelbox)
        grid.addWidget(supportbox)
        grid.addLayout(actionrow)
        grid.addWidget(consolebox, 1)   # console takes the remaining height
        grid.addLayout(progressrow)
        # Standalone keeps a slim Exit footer; embedded there is nothing left
        # to show, so no footer row is added at all.
        if not self.embedded:
            footer = QtWidgets.QHBoxLayout()
            footer.addStretch(1)
            footer.addWidget(self.exitbtn)
            grid.addLayout(footer)
        self.setLayout(grid)

        # Rounded group-boxes matching the other Makerchip dock tabs, plus the
        # primary button's hover/pressed/disabled feedback states.
        self.setStyleSheet(
            "QGroupBox { border: 1px solid gray; border-radius: 9px; "
            "margin-top: 0.6em; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; "
            "padding: 0 4px 0 4px; } "
            "QLabel#hint { font-style: italic; } "
            "QLabel#pagetitle { font-size: 15px; font-weight: 700; } "
            "QPushButton#uninstall { border: 1px solid #c0563a; "
            "color: #c0563a; border-radius: 6px; padding: 6px 16px; "
            "font-weight: 600; } "
            "QPushButton#uninstall:hover { "
            "background-color: rgba(192, 86, 58, 0.12); } "
            "QPushButton#uninstall:pressed { "
            "background-color: rgba(192, 86, 58, 0.22); } "
            "QPushButton#primary { background-color: #2e7d32; color: white; "
            "font-weight: bold; border-radius: 6px; padding: 7px 22px; } "
            "QPushButton#primary:hover { background-color: #33883a; } "
            "QPushButton#primary:pressed { background-color: #24632a; } "
            "QPushButton#primary:disabled { background-color: #b9c9ba; "
            "color: #eef3ee; }")

        # Standalone window chrome; skipped when embedded as a tab.
        if not self.embedded:
            self.setGeometry(300, 300, 640, 620)
            self.setWindowTitle("Ngspice Digital Model Creator (from VHDL)")
            # self.setWindowIcon(QtGui.QIcon('logo.png'))
            self.show()

    def closeWindow(self):
        try:
            self.process.close()
        except BaseException:
            pass
        print("Close button clicked")
        # Never exit the process when embedded - that would kill all of eSim.
        if not self.embedded:
            sys.exit()

    def closeEvent(self, event):
        # Kill any running build so closing the tab/eSim leaves no orphan.
        try:
            if self.process is not None:
                self.process.kill()
        except BaseException:
            pass
        # A teardown worker must finish before this widget dies: it emits into
        # the console and the progress row, and a half-deleted receiver during
        # a queued emit is a hard crash. The steps are file ops, so the wait is
        # short and bounded.
        job = getattr(self, "_removejob", None)
        if job is not None:
            try:
                if job.isRunning():
                    job.wait(10000)
            except BaseException:
                pass
        super().closeEvent(event)

    def browseFile(self):
        print("Browse button clicked")
        self.filename = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open File', '.')[0]
        self.ledit.setText(self.filename)
        print("Vhdl file uploaded to process :", self.filename)

    def addFiles(self):
        print("Starts adding supporting files")
        for file in QtWidgets.QFileDialog.getOpenFileNames(
                self, "Add supporting .vhdl files")[0]:
            self.file_list.append(file)
        self._refresh_file_list()
        print("Supporting Files are :", self.file_list)

    def removeFiles(self):
        # Un-stage the selected supporting files from the pre-upload list.
        # (This only edits the list; it never uninstalls a built model.)
        selected_rows = {self.filelist.row(item)
                         for item in self.filelist.selectedItems()}
        if not selected_rows:
            return
        self.file_list = [f for i, f in enumerate(self.file_list)
                          if i not in selected_rows]
        self._refresh_file_list()

    def _refresh_file_list(self):
        """Rebuild the supporting-files list widget from file_list (the source
        of truth). Row order stays 1:1 with file_list so removeFiles can map a
        selected row straight back to an entry."""
        self.filelist.clear()
        for f in self.file_list:
            item = QtWidgets.QListWidgetItem(os.path.basename(str(f)))
            item.setToolTip(str(f))
            self.filelist.addItem(item)
        self._sync_file_buttons()

    def _sync_file_buttons(self):
        """Remove is only meaningful when something in the list is selected."""
        self.removebtn.setEnabled(bool(self.filelist.selectedItems()))

    # ------------------------------------------------------------------ #
    #  NGHDL model uninstall. Mirrors eSim's NgVeri._remove_nghdl_model
    #  against the ghdl/ tree, but uses NGHDL's OWN vendored helpers
    #  (model_teardown + kicad_symlib) so it works standalone, without
    #  importing eSim.
    # ------------------------------------------------------------------ #
    def _ghdl_home(self):
        '''<DIGITAL_MODEL>/ghdl -- where per-model source dirs and the NGHDL
        modpath.lst live (same value createModelDirectory computes).'''
        return os.path.join(
            self.parser.get('NGHDL', 'DIGITAL_MODEL'), "ghdl")

    def _list_nghdl_models(self):
        '''Every NGHDL model with ANY trace left on this machine, sorted.

        modpath.lst alone is not that list. A model built by an older NGHDL --
        or one whose teardown was interrupted -- can survive as nothing but an
        eSim_Nghdl KiCad symbol, a Nghdl/<name>.xml, or a build dir, and
        anything this list cannot name is something the user cannot delete from
        the GUI (while KiCad happily keeps showing the symbol). So the union of
        all five traces is offered; every teardown step below is idempotent and
        absence-tolerant, so removing a model that owns only one of them is
        safe.'''
        sym_path = model_teardown._nghdl_sym_path(self.src_home)
        # Point KiCad at the library this teardown actually rewrites. The
        # sym-lib-table is otherwise only refreshed when a model is CREATED, so
        # a user who upgraded without building anything still has KiCad reading
        # the legacy copy (/usr/share/kicad/symbols on Ubuntu) -- and every
        # symbol removed here would keep showing up there. Idempotent and
        # best-effort; a correct entry is left untouched.
        kicad_symlib.ensure_lib_registered(
            "eSim_Nghdl", sym_path,
            descr="eSim NGHDL (GHDL co-simulation) symbols")
        return model_teardown.discover_nghdl_models(
            self._ghdl_home(), self.release_dir, Appconfig.xml_loc,
            nghdl_sym=sym_path)

    def openRemoveModels(self):
        '''Open the checkbox remover listing only NGHDL models and tear down
        whatever the user picks (on a worker thread, behind the progress bar).'''
        proc = getattr(self, "process", None)
        if proc is not None and proc.state() != QtCore.QProcess.ProcessState.NotRunning:
            QtWidgets.QMessageBox.information(
                self, "Remove Models",
                "A build is in progress. Please wait for it to finish.")
            return
        if self._removejob is not None:
            QtWidgets.QMessageBox.information(
                self, "Remove Models",
                "A removal is already in progress. "
                "Please wait for it to finish.")
            return
        names = self._list_nghdl_models()
        if not names:
            QtWidgets.QMessageBox.information(
                self, "Remove Models", "There are no NGHDL models to remove.")
            return
        # Same searchable, multi-select picker the eSim NgVeri tab uses, so the
        # remove-model UX is uniform across the app. Badge every row "Nghdl" for
        # the shared colour legend; the dialog only collects the choice, the
        # teardown still happens in _remove_nghdl_models.
        dlg = RemoveItemsDialog(
            "Remove NGHDL Models", names,
            badges={name: "Nghdl" for name in names},
            item_noun="model", parent=self)
        if not dlg.exec():
            return
        doomed = [n for n in dlg.selected_items() if n and str(n).strip()]
        if not doomed:
            return

        # Off the GUI thread: the rmtree passes and the symbol-library rewrite
        # are what made "Uninstall Models" freeze the window.
        self.uploadbtn.setEnabled(False)
        self.removemodelbtn.setEnabled(False)
        self._show_progress(True, "Removing " + str(len(doomed)) + " model" +
                            ("s" if len(doomed) != 1 else "") + "…",
                            maximum=len(doomed))
        self._removejob = _BackgroundJob(
            self._remove_nghdl_models, doomed, parent=self)
        self._removejob.succeeded.connect(self._on_removal_finished)
        self._removejob.failed.connect(self._on_removal_error)
        self._removejob.finished.connect(self._removejob.deleteLater)
        self._removejob.start()

    def _show_progress(self, on, message="", maximum=0):
        '''Show/hide the progress row. maximum=0 keeps the bar indeterminate
        (a build, or the closing ghdl.cm rebuild); a positive maximum makes it
        count models torn down.'''
        if on:
            self.progressStatus.setText(message)
            self.progressBar.setRange(0, maximum)
            self.progressBar.setValue(0)
        self.progressStatus.setVisible(on)
        self.progressBar.setVisible(on)

    def _on_remove_step(self, done, message):
        '''Queued from the removal worker: advance the bar and name the model
        being torn down. done < 0 switches back to indeterminate.'''
        if done < 0:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setValue(done)
        if message:
            self.progressStatus.setText(message)

    def _remove_nghdl_models(self, names):
        '''Tear down each selected NGHDL model -- ghdl/modpath.lst line,
        eSim_Nghdl KiCad symbol, Nghdl/<name>.xml, and the source + release
        per-model dirs. Returns True if anything was processed, so the caller
        knows to rebuild ghdl.cm.

        Runs on the removal worker thread: every line goes through the queued
        removeLog signal, never straight to the console widget.'''
        ghdl_home = self._ghdl_home()
        xml_loc = Appconfig.xml_loc
        removed_any = False
        for done, text in enumerate(names):
            if not text or not str(text).strip():
                continue
            self.removeStep.emit(done, 'Removing "' + str(text) + '"…')
            self.removeLog.emit('Removing NGHDL model "' + str(text) + '"')

            # Drop from ghdl/modpath.lst (absent file/line => no crash).
            if model_teardown._strip_modpath_line(
                    os.path.join(ghdl_home, "modpath.lst"), text):
                self.removeLog.emit('  dropped from ghdl/modpath.lst')

            # Strip the symbol + the orphan param XML (both idempotent).
            try:
                sym_path = model_teardown._nghdl_sym_path(self.src_home)
                parts = kicad_symlib._read_parts(sym_path)
                if parts.pop(str(text), None) is not None:
                    kicad_symlib._write_lib(sym_path, parts)
                    self.removeLog.emit('  removed eSim_Nghdl symbol')
                xml = os.path.join(xml_loc, 'Nghdl', str(text) + '.xml')
                try:
                    os.remove(xml)
                    self.removeLog.emit('  removed Nghdl/' + str(text) +
                                        '.xml')
                except FileNotFoundError:
                    pass
            except Exception as err:
                self.removeLog.emit("  WARN: symbol/XML removal failed: " +
                                    str(err))

            # Drop both per-model dirs (guarded against blank/unsafe names).
            for label, base in (
                    ("source", ghdl_home),
                    ("release", os.path.join(
                        self.release_dir, "src/xspice/icm/ghdl"))):
                model_dir = model_teardown._safe_model_subdir(base, text)
                if model_dir is None:
                    self.removeLog.emit("  WARN: refusing unsafe " + label +
                                        " dir for " + repr(text))
                    continue
                try:
                    shutil.rmtree(model_dir)
                    self.removeLog.emit("  removed " + label + " dir")
                except FileNotFoundError:
                    pass
                except OSError as err:
                    self.removeLog.emit("  WARN: could not remove " + label +
                                        " dir: " + str(err))
            removed_any = True

        self.removeStep.emit(len(names), "Finishing…")
        return removed_any

    def _on_removal_finished(self, removed_any):
        '''GUI-thread epilogue: chain into the (already async) ghdl.cm rebuild,
        or just close the progress row when nothing was touched.'''
        self._removejob = None
        if removed_any:
            self._show_progress(True, "Rebuilding ghdl.cm…")
            self._rebuild_ghdl_cm()
            return
        self._end_removal_ui()

    def _on_removal_error(self, msg):
        '''GUI-thread epilogue when the teardown worker raised.'''
        self._removejob = None
        self.termedit.append('<b style="color:red">Model removal failed: ' +
                             str(msg) + '</b>')
        self._end_removal_ui()
        QtWidgets.QMessageBox.critical(
            self, 'Error', 'Model removal failed: ' + str(msg))

    def _end_removal_ui(self):
        '''Hide the progress row and give the controls back.'''
        self._show_progress(False)
        self.uploadbtn.setEnabled(True)
        self.exitbtn.setEnabled(True)
        self.removemodelbtn.setEnabled(True)

    def _rebuild_ghdl_cm(self):
        '''Rebuild + reinstall ghdl.cm so ngspice unlinks every model already
        stripped from ghdl/modpath.lst. Prune ghost lines first (a single
        orphaned entry makes cmpp abort the whole build), then reuse the async
        make chain in rebuild-only mode (no schematic symbol is created).'''
        ghdl_home = self._ghdl_home()
        dropped = model_teardown._prune_modpath(
            os.path.join(ghdl_home, "modpath.lst"), ghdl_home)
        for name in dropped:
            self.termedit.append('Pruned stale model "' + name +
                                 '" from ghdl/modpath.lst (build dir missing).')
        # runMake/_createSchematicLib reference these; set them so the rebuild
        # path never depends on a prior uploadModel() having run.
        self.cur_dir = os.getcwd()
        self.errorFlag = False
        self.uploadbtn.setEnabled(False)
        self.termedit.append("Rebuilding ghdl.cm ...")
        self.runMake(rebuild_only=True)

    # Check extensions of all supporting files
    def checkSupportFiles(self):
        # Rebuild via comprehension: mutating the list while iterating it (the
        # old approach) skips the element after each removal, so back-to-back
        # non-.vhdl files could slip through.
        vhdl_only = [f for f in self.file_list
                     if os.path.splitext(str(f))[1] == ".vhdl"]
        if len(vhdl_only) != len(self.file_list):
            self.file_list = vhdl_only
            self._refresh_file_list()
            QtWidgets.QMessageBox.critical(
                self, 'Critical', '''<b>Important Message.</b>
                <br/><br/>Supporting files should be <b>.vhdl</b> file '''
            )

    def createModelDirectory(self):
        """Create the model directory. Returns False if the user cancels an
        overwrite (the upload is then aborted without touching eSim)."""
        print("Create Model Directory Called")
        self.digital_home = self.parser.get('NGHDL', 'DIGITAL_MODEL')
        self.digital_home = os.path.join(self.digital_home, "ghdl")
        self.modelname = os.path.splitext(
            os.path.basename(str(self.filename)))[0]
        print("Model to be created :", self.modelname)
        # An empty model name (no file chosen / odd filename) would make
        # model_path == the ghdl icm ROOT below -- and the overwrite branch
        # would rmtree every installed model plus modpath.lst. Refuse it.
        if not self.modelname:
            QtWidgets.QMessageBox.critical(
                self, "Error",
                "No VHDL file selected - cannot derive a model name.")
            return False
        # Reject a name that is not a bare identifier BEFORE creating anything:
        # the stem is spliced into a VHDL entity, a C cfunc (cm_<name>) and a
        # make target, so a dotted (adder.v1), hyphenated or spaced filename
        # would otherwise fail deep inside ghdl/cmpp with a message pointing
        # nowhere near the cause. Mirrors ModelGeneration._stem_is_valid on the
        # maker side.
        if re.fullmatch(r'[A-Za-z_]\w*', self.modelname) is None:
            QtWidgets.QMessageBox.critical(
                self, "Error",
                "'" + os.path.basename(str(self.filename)) + "' is not a "
                "usable model name. Use only letters, digits and underscore, "
                "and do not start with a digit (the name becomes a VHDL "
                "entity, a C function and a make target). Rename the file "
                "and try again.")
            return False
        # Work with an absolute path so we never have to chdir (chdir would
        # change eSim's process-global CWD).
        model_path = os.path.join(self.digital_home, self.modelname)
        # Looking if model directory is present or not
        if os.path.isdir(model_path):
            print("Model Already present")
            ret = QtWidgets.QMessageBox.warning(
                self, "Warning",
                "<b>This model already exist. Do you want to " +
                "overwrite it?</b><br/> If yes press ok, else cancel it and " +
                "change the name of your vhdl file.",
                QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
            )
            if ret == QtWidgets.QMessageBox.StandardButton.Ok:
                print("Overwriting existing model " + self.modelname)
                # A real rmtree (errors surfaced, not swallowed): a partial
                # failure left by ignore_errors=True keeps the dir alive and
                # the following mkdir then crashes with FileExistsError. Abort
                # cleanly instead, and makedirs(exist_ok=True) so a stray race
                # can't re-trigger that crash.
                try:
                    shutil.rmtree(model_path)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    QtWidgets.QMessageBox.critical(
                        self, "Error",
                        "Could not overwrite the existing model: " + str(e))
                    return False
                os.makedirs(model_path, exist_ok=True)
            else:
                print("Model creation cancelled by user")
                return False
        else:
            print("Creating model " + self.modelname + " directory")
            os.mkdir(model_path)
        return True

    def addingModelInModpath(self):
        print("Adding Model " + self.modelname +
              " in Modpath file " + self.digital_home)
        # Append via the vendored teardown helper: it skips the write when the
        # name is already listed AND guarantees the new entry starts on its own
        # line. The old in-place 'r+' write glued the name onto a final line
        # that lacked a trailing newline ("oldnamenewname"), a ghost entry that
        # makes cmpp abort the whole ghdl.cm build.
        path = os.path.join(self.digital_home, "modpath.lst")
        if model_teardown._append_modpath_line(path, self.modelname):
            print("Adding model name " + self.modelname + " into modpath.lst")
        else:
            print("Model name is already into modpath.lst")

    def createModelFiles(self):
        print("Create Model Files Called")
        # Generate into a private temp dir and move the results into place.
        # The generator used to write cfunc.mod/ifspec.ifs/the testbench into
        # eSim's CWD -- so a read-only launch directory (packaged launcher, "/"
        # on some setups) failed on the very first write -- and this method then
        # chdir'ed twice, mutating the whole application's process-global CWD
        # for the duration of a build. Neither is needed: every path below is
        # absolute and the compile step gets cwd= like the rest of the pipeline.
        path = os.path.join(self.digital_home, self.modelname)
        dut = os.path.join(path, "DUTghdl")
        ghdlsrc = os.path.join(self.home, self.src_home, "src", "ghdlserver")
        workdir = tempfile.mkdtemp(prefix="nghdl-")
        try:
            # Generate model corresponding to the uploaded VHDL file
            model = ModelGeneration(str(self.ledit.text()), outdir=workdir)
            model.readPortInfo()
            model.createCfuncModFile()
            model.createIfSpecFile()
            model.createTestbench()
            model.createServerScript()
            model.createSockScript()

            # Moving file to model directory
            shutil.move(os.path.join(workdir, "cfunc.mod"), path)
            shutil.move(os.path.join(workdir, "ifspec.ifs"), path)

            # Creating directory inside model directoy
            print("Creating DUT directory at " + dut)
            os.makedirs(dut, exist_ok=True)
            print("Copying required file to DUTghdl directory")
            for name in ("connection_info.txt", "start_server.sh",
                         "sock_pkg_create.sh", self.modelname + "_tb.vhdl"):
                shutil.move(os.path.join(workdir, name), dut)

            shutil.copy(str(self.filename), dut)
            for name in ("compile.sh", "uthash.h", "ghdlserver.c",
                         "ghdlserver.h", "Utility_Package.vhdl",
                         "Vhpi_Package.vhdl"):
                shutil.copy(os.path.join(ghdlsrc, name), dut)

            # (Winsock is linked with -lws2_32 by the generated
            # start_server.sh; no bundled libws2_32.a copy is needed.)

            for file in self.file_list:
                shutil.copy(str(file), dut)

            if os.name == 'nt':
                # Compile ghdlserver.c with the MSYS2 mingw64 gcc. A bare
                # (non-login) bash has no /mingw64/bin on PATH, so export it
                # explicitly; run via cwd + relative script so spaced install
                # paths cannot split the command. Arg-list form: nothing to
                # re-quote.
                self.msys_home = self.parser.get('COMPILER', 'MSYS_HOME')
                bash = os.path.join(self.msys_home, 'usr', 'bin', 'bash.exe')
                mingw_env = "export PATH=/mingw64/bin:/usr/bin:$PATH && "
                # CREATE_NO_WINDOW: this GUI process has no console, so each
                # bash.exe would otherwise flash its own blank console window.
                no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                subprocess.call([bash, '-c', mingw_env + 'sh compile.sh'],
                                cwd=dut, creationflags=no_window)
                subprocess.call([bash, '-c', 'chmod a+x start_server.sh'],
                                cwd=dut, creationflags=no_window)
                subprocess.call([bash, '-c', 'chmod a+x sock_pkg_create.sh'],
                                cwd=dut, creationflags=no_window)
            else:
                # cwd=DUTghdl instead of an os.chdir, so relative script names
                # resolve there without moving eSim's own working directory.
                # Arg-list form, like the nt branch: a spaced or
                # metacharacter-bearing install path can neither split the
                # command into extra arguments nor be shell-interpreted -- the
                # old shell=True string concatenation did both and was an
                # injection surface for a hostile model path.
                subprocess.call(['bash', 'compile.sh'], cwd=dut)
                subprocess.call(['chmod', 'a+x', 'start_server.sh'], cwd=dut)
                subprocess.call(['chmod', 'a+x', 'sock_pkg_create.sh'], cwd=dut)

            os.remove(os.path.join(dut, "compile.sh"))
            # os.remove("ghdlserver.c")
        finally:
            # Best-effort: a leftover temp dir is harmless, a raised cleanup
            # error would mask the real failure the caller is reporting.
            shutil.rmtree(workdir, ignore_errors=True)

    # Slot to redirect stdout and stderr to window console
    @QtCore.pyqtSlot()
    def readAllStandard(self):
        proc = self.sender()
        if not isinstance(proc, QtCore.QProcess):
            return
        # errors='replace': mingw make/gcc can emit cp1252 bytes and a raw
        # UnicodeDecodeError in this slot would kill the whole output stream.
        self.termedit.append(
            str(proc.readAllStandardOutput().data(),
                encoding='utf-8', errors='replace')
        )
        stderror = proc.readAllStandardError()
        # Kept only as a secondary hint; the real build verdict is the process
        # exit code, checked in _build_step_failed (see runMakeInstall).
        if stderror.toUpper().contains(QtCore.QByteArray(b"ERROR")):
            self.errorFlag = True
        self.termedit.append(
            str(stderror.data(), encoding='utf-8', errors='replace'))

    def _apply_build_env(self, process):
        """On Windows, prepend the MSYS2 mingw64/usr dirs to the QProcess
        PATH: mingw32-make itself is started by full path, but its child
        gcc/g++/ar/sh processes resolve via PATH, which eSim's own process
        does not have. No-op on POSIX."""
        if os.name != 'nt':
            return
        msys_home = self.parser.get('COMPILER', 'MSYS_HOME')
        env = QtCore.QProcessEnvironment.systemEnvironment()
        extra = os.pathsep.join([
            os.path.join(msys_home, 'mingw64', 'bin'),
            os.path.join(msys_home, 'usr', 'bin'),
        ])
        existing = env.value('PATH', '')
        env.insert('PATH',
                   extra + (os.pathsep + existing if existing else ''))
        process.setProcessEnvironment(env)

    def _build_step_failed(self, exitCode, exitStatus, label):
        '''Gate the async make chain on the process's real verdict instead of a
        stderr "ERROR" substring sniff. QProcess.finished delivers
        (exitCode, exitStatus); when make exits non-zero or is killed
        (CrashExit) the chain MUST stop -- otherwise `make install` and the
        KiCad symbol are built over a ghdl.cm that never rebuilt, and the model
        fails later at simulation time with nothing pointing back to the failed
        make. Mirrors ModelGeneration._run's exit-code verdict.

        Returns True when the step failed (caller must return immediately);
        on failure it flags the error, re-enables the controls and does NOT
        chain to the next step.'''
        crashed = exitStatus == QtCore.QProcess.ExitStatus.CrashExit
        if exitCode == 0 and not crashed:
            return False
        self.errorFlag = True
        reason = "was killed" if crashed else "exit code " + str(exitCode)
        self.termedit.append('<b style="color:red">' + label +
                             ' failed (' + reason + '). Build stopped.</b>')
        self._show_progress(False)
        self.uploadbtn.setEnabled(True)
        self.exitbtn.setEnabled(True)
        if getattr(self, "_rebuild_only", False):
            self._rebuild_only = False
            self.removemodelbtn.setEnabled(True)
        return True

    def runMake(self, rebuild_only=False):
        print("run Make Called")
        # rebuild_only=True is the post-removal path: build+install the icm
        # tree to refresh ghdl.cm, but skip the schematic-symbol creation in
        # _createSchematicLib (there is no new model to draw a symbol for).
        self._rebuild_only = rebuild_only
        self.release_home = self.parser.get('NGHDL', 'RELEASE')
        # Keep the icm path so make/make install run there via QProcess's
        # own working directory - we never chdir eSim's process into it.
        self.path_icm = os.path.join(self.release_home, "src/xspice/icm")

        try:
            if os.name == 'nt':
                self.msys_home = self.parser.get('COMPILER', 'MSYS_HOME')
                cmd = self.msys_home + "/mingw64/bin/mingw32-make.exe"
            else:
                cmd = "make"

            print("Running Make command in " + self.path_icm)
            self.process = QtCore.QProcess(self)
            self.process.setWorkingDirectory(self.path_icm)
            self._apply_build_env(self.process)
            self.process.readyReadStandardOutput.connect(self.readAllStandard)
            self.process.readyReadStandardError.connect(self.readAllStandard)
            # make install runs on every platform: the Windows nghdl tree is
            # configured with prefix=install_dir exactly like Ubuntu, so the
            # rebuilt ghdl.cm lands where ngspice loads code models from
            # (<install_dir>/lib/ngspice) instead of a hand-copied guess.
            self.process.finished.connect(self.runMakeInstall)
            self.process.start(cmd)
            print("make command process pid ---------- >", self.process.processId())

        except BaseException:
            print("There is error in 'make' ")
            if not self.embedded:
                sys.exit()
            self.uploadbtn.setEnabled(True)
            self.exitbtn.setEnabled(True)

    def runMakeInstall(self, exitCode=0, exitStatus=None):
        # Fired by QProcess.finished after `make`. Stop here if make failed.
        if self._build_step_failed(exitCode, exitStatus, "make"):
            return
        print("run Make Install Called")
        try:
            if os.name == 'nt':
                self.msys_home = self.parser.get('COMPILER', 'MSYS_HOME')
                prog = self.msys_home + "/mingw64/bin/mingw32-make.exe"
                args = ["install"]
                # The configured tree bakes the BUILD machine's absolute
                # prefix into makedefs (pkglibdir/pkgdatadir), so a stock
                # `make install` on an end-user PC would write the rebuilt
                # ghdl.cm into the packager's path instead of this install's
                # install_dir. Override both on the command line (forward
                # slashes: these are make variables). Same fix as
                # ModelGeneration.runMakeInstall.
                nghdl_home = self.parser.get('NGHDL', 'NGHDL_HOME')
                if nghdl_home:
                    inst = os.path.join(nghdl_home, 'install_dir').replace(
                        '\\', '/')
                    args += ["pkglibdir=" + inst + "/lib/ngspice",
                             "pkgdatadir=" + inst + "/share/ngspice"]
            else:
                prog = "make"
                args = ["install"]
            print("Running Make Install")

            self.process = QtCore.QProcess(self)
            self.process.setWorkingDirectory(self.path_icm)
            self._apply_build_env(self.process)
            self.process.readyReadStandardOutput.connect(self.readAllStandard)
            self.process.readyReadStandardError.connect(self.readAllStandard)
            self.process.finished.connect(self.createSchematicLib)
            self.process.start(prog, args)

        except BaseException:
            print("There is error in 'make install' ")
            if not self.embedded:
                sys.exit()
            self.uploadbtn.setEnabled(True)
            self.exitbtn.setEnabled(True)

    def createSchematicLib(self, exitCode=0, exitStatus=None):
        # Fired by QProcess.finished after `make install`. Stop here (no symbol)
        # if the install step failed.
        if self._build_step_failed(exitCode, exitStatus, "make install"):
            return
        try:
            self._createSchematicLib()
        except Exception as e:
            print("createSchematicLib exception:", e)
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(
                self, 'Error', 'Library creation failed: ' + str(e)
            )
            self._show_progress(False)
            self.uploadbtn.setEnabled(True)
            self.exitbtn.setEnabled(True)

    def _createSchematicLib(self):
        # (ghdl.cm is installed by `make install` into
        # <install_dir>/lib/ngspice on every platform now; the old nt-only
        # hand copy into the release tree pointed where ngspice never looks.)
        os.chdir(self.cur_dir)
        self._show_progress(False)
        # Post-removal rebuild: ghdl.cm is refreshed (copied on nt / installed
        # on posix); there is no model to draw, so skip symbol creation.
        if getattr(self, "_rebuild_only", False):
            self.termedit.append("ghdl.cm rebuilt.")
            self._rebuild_only = False
            self._end_removal_ui()
            return
        if Appconfig.esimFlag == 1:
            if not self.errorFlag:
                print('Creating library files................................')
                schematicLib = AutoSchematic(self, self.modelname)
                schematicLib.createKicadSymbol()
            else:
                QtWidgets.QMessageBox.critical(
                    self, 'Error', '''Cannot create Schematic Library of ''' +
                    '''your model. Resolve the <b>errors</b> shown on ''' +
                    '''console of NGHDL window. '''
                )
        else:
            QtWidgets.QMessageBox.information(
                self, 'Message', '''<b>Important Message</b><br/><br/>''' +
                '''To create Schematic Library of your model, ''' +
                '''use NGHDL through <b>eSim</b> '''
            )
        self.uploadbtn.setEnabled(True)
        self.exitbtn.setEnabled(True)

    def uploadModel(self):
        print("Upload button clicked")
        try:
            self.process.close()
        except BaseException:
            pass
        if not self.filename:
            QtWidgets.QMessageBox.warning(
                self, 'No File', 'Use Browse to select a .vhdl file first.')
            return
        try:
            self.file_extension = os.path.splitext(str(self.filename))[1]
            print("Uploaded File extension :" + self.file_extension)
            self.cur_dir = os.getcwd()
            print("Current Working Directory :" + self.cur_dir)
            self.checkSupportFiles()
            if self.file_extension == ".vhdl":
                self.errorFlag = False
                self.uploadbtn.setEnabled(False)
                self.exitbtn.setEnabled(False)
                self.termedit.append('<b style="color:yellow">Processing... do not close until Symbol Added dialog appears.</b>')
                self._show_progress(True, "Building model…")
                if not self.createModelDirectory():
                    # User cancelled an overwrite - abort cleanly.
                    self._show_progress(False)
                    self.uploadbtn.setEnabled(True)
                    self.exitbtn.setEnabled(True)
                    return
                self.addingModelInModpath()
                self.createModelFiles()
                self.runMake()
            else:
                QtWidgets.QMessageBox.information(
                    self, 'Message', '''<b>Important Message.</b><br/>''' +
                    '''<br/>This accepts only <b>.vhdl</b> file '''
                )
        except Exception as e:
            # Restore eSim's CWD and re-enable controls so a failed upload
            # never leaves the host application or this tab in a bad state.
            try:
                os.chdir(self.cur_dir)
            except BaseException:
                pass
            self._show_progress(False)
            self.uploadbtn.setEnabled(True)
            self.exitbtn.setEnabled(True)
            QtWidgets.QMessageBox.critical(self, 'Error', str(e))


def main():
    app = QtWidgets.QApplication(sys.argv)
    if len(sys.argv) > 1:
        if sys.argv[1] == '-e':
            Appconfig.esimFlag = 1

    # Mainwindow() object must be assigned to a variable.
    # Otherwise, it is destroyed as soon as it gets created.
    w = Mainwindow()    # noqa
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
