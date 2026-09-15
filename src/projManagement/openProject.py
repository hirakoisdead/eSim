# =========================================================================
#          FILE: openProject.py
#
#         USAGE: ---
#
#   DESCRIPTION: It is called whenever new project is being called.
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Wednesday 12 February 2015
#      REVISION: Sunday 26 July 2020
# =========================================================================

from PyQt6 import QtWidgets, QtCore
from configuration import Dialogs
from .Validation import Validation
from .projectPaths import find_anchors, resolve_stem, \
    main_schematic, stem_from_file, canonical_path, save_project_explorer
from configuration.Appconfig import Appconfig
import os


class OpenProjectInfo(QtWidgets.QWidget):
    """
    This class is called when User click on Open Project Button
    """

    def __init__(self):
        super(OpenProjectInfo, self).__init__()
        self.obj_validation = Validation()

    def body(self, projDir=None):
        """
        Open a project folder, resolve the project from its .proj anchor
        regardless of the folder's name, and register it as the current project.

        @params
            :projDir     => when given (e.g. restoring the last project at
                            startup), open this folder directly and skip the
                            folder picker. When None, prompt the user to choose.

        @return
            :projDir     => the project folder path (or None if not opened)
            :filelist    => the top-level files inside the project folder
        """
        self.obj_Appconfig = Appconfig()
        self.openDir = self.obj_Appconfig.default_workspace["workspace"]

        # `restoring` (projDir supplied) means a non-interactive startup reopen:
        # use the saved path as-is and never pop a dialog.
        restoring = projDir is not None
        if restoring:
            self.projDir = QtCore.QDir.toNativeSeparators(str(projDir))
        else:
            # A project is a folder of files, so we pick the folder; the project
            # is then resolved from the .proj anchor inside it regardless of the
            # folder's name (see projectPaths.resolve_stem).
            self.projDir = QtCore.QDir.toNativeSeparators(
                QtWidgets.QFileDialog.getExistingDirectory(
                    Dialogs.resolve_parent(self), "Open Project", self.openDir
                )
            )
        if not self.projDir:
            self.obj_Appconfig.print_info('No Project opened')
            return None, None

        # Canonicalise to the project's identity key the moment we have a path:
        # everything downstream (current_project, project_explorer keys, the
        # tree node) must use this one form so the same folder -- reached via a
        # symlink, a '..' path, a trailing slash or a case variant -- is never
        # registered twice. See projectPaths.canonical_path.
        self.projDir = canonical_path(self.projDir)

        proj_files = find_anchors(self.projDir, 'proj')

        # No anchor -> not an eSim project.
        if not proj_files:
            if restoring:
                # Don't show the interactive retry dialog during startup; just
                # decline to restore.
                self.obj_Appconfig.print_warning(
                    "Could not restore last project: no .proj anchor in " +
                    str(self.projDir))
                return None, None
            return self._reportNoProject()

        # Resolve the stem from the anchor. If the folder holds more than one
        # project, ask the user which to open.
        if len(proj_files) > 1:
            stem = self._chooseProject(proj_files)
            if stem is None:
                self.obj_Appconfig.print_info('No Project opened')
                return None, None
        else:
            stem, _status = resolve_stem(self.projDir, 'proj')

        # Warn (but still open) when the project is missing its schematic and
        # netlist -- this is a genuinely incomplete project, distinct from a
        # folder that simply isn't an eSim project at all.
        #
        # The modal is only for a folder the user just picked: on the startup
        # restore it is a nag with no way out. createProject writes the .proj
        # anchor and nothing else, so EVERY project is "incomplete" from the
        # moment it is made until eeschema saves a schematic into it -- and the
        # newest project is exactly the one startup restores. That made the
        # warning fire on every single launch, blocking the splash behind a
        # modal, for a state the user cannot clear without first dismissing it.
        # Same rule the no-anchor branch above already follows: startup logs,
        # it does not interrogate.
        schematic = main_schematic(self.projDir, stem)
        has_cir = os.path.exists(
            os.path.join(self.projDir, str(stem) + ".cir"))
        if not os.path.exists(schematic) and not has_cir:
            if not restoring:
                Dialogs.warning(
                    self, "Incomplete Project",
                    "<b>Warning: this folder has a project (.proj) file but no "
                    "schematic ({0}.kicad_sch / {0}.sch) or netlist "
                    "({0}.cir).</b><br/>The project will open, but some "
                    "operations may be unavailable until those files "
                    "exist.".format(stem)
                )
            self.obj_Appconfig.print_warning(
                "Project '" + str(stem) +
                "' is missing its schematic/netlist files.")

        self.obj_Appconfig.set_current_project(str(self.projDir), stem)

        # Build the top-level file list for the project explorer tree.
        try:
            filelist = sorted(
                f for f in os.listdir(self.projDir)
                if os.path.isfile(os.path.join(self.projDir, f))
            )
        except OSError:
            filelist = []

        self.obj_Appconfig.project_explorer[self.projDir] = filelist
        save_project_explorer(
            self.obj_Appconfig.dictPath["path"],
            self.obj_Appconfig.project_explorer)
        self.obj_Appconfig.print_info('Open Project called')
        self.obj_Appconfig.print_info('Current Project is ' + self.projDir)
        return self.projDir, filelist

    def _chooseProject(self, proj_files):
        """
        When a folder contains more than one .proj, ask the user which project
        to open. Returns the chosen stem, or None if cancelled.
        """
        stems = [stem_from_file(p) for p in proj_files]
        choice, ok = QtWidgets.QInputDialog.getItem(
            Dialogs.resolve_parent(self), "Select Project",
            "This folder contains multiple eSim projects.\n"
            "Choose one to open:",
            stems, 0, False
        )
        if ok and choice:
            return str(choice)
        return None

    def _reportNoProject(self):
        """
        Report a folder that contains no .proj anchor, and offer to retry.
        Returns the result of the retried open, or (None, None) on cancel.
        """
        self.obj_Appconfig.print_error(
            "No eSim project (.proj) file found in the selected folder. "
            "Please select a folder that contains an eSim project."
        )
        reply = Dialogs.critical(
            self, "Error Message",
            "<b>Error: No eSim project (.proj) file found in this folder."
            "</b><br/><b>Please select a folder that contains an eSim project "
            "(a .proj file), or cancel.</b>",
            QtWidgets.QMessageBox.StandardButton.Ok
            | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Ok:
            return self.body()
        self.obj_Appconfig.print_info('No Project opened')
        return None, None
