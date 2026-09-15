# =========================================================================
#          FILE: Workspace.py
#
#   DESCRIPTION: Workspace selector — the small dialog that appears when
#                the user runs eSim for the first time (or resets their
#                workspace). Lets them pick a folder under which all
#                projects will live.
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#         NOTES: Layout uses QFormLayout + button row instead of a
#                hand-rolled QGridLayout, so widgets size cleanly on
#                HiDPI and the dialog can be resized without breaking.
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in + eSim UX refresh
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Wednesday 05 February 2015
#      REVISION: 2026 — layout refresh, removed blocking time.sleep,
#                 removed WindowStaysOnTopHint, replaced app-level
#                 globals with attribute dispatch.
# =========================================================================

from PyQt6 import QtCore, QtGui, QtWidgets
from configuration.Appconfig import Appconfig
from configuration import Dialogs
from configuration import paths
import os
import json


class Workspace(QtWidgets.QDialog):
    """
    Select-or-confirm your eSim workspace folder.

    The dialog is modal and blocks until the user chooses either:
      - the default workspace (~/eSim-Workspace), or
      - a custom folder, optionally marked as the default for next run.
    """

    def __init__(self, parent=None):
        super(Workspace, self).__init__(parent)
        self.obj_appconfig = Appconfig()
        self._app_view = None  # filled in by returnWhetherClickedOrNot()
        self.init_ui()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle('Choose your workspace')
        self.setModal(True)
        from frontEnd.theme_utils import zoom_px
        self.setMinimumWidth(zoom_px(520))

        # On first run this picker is the ONLY visible window (the main
        # window is built hidden, the splash is already closed). Since Qt 6.3
        # QDialog.done() calls close(), so accepting the dialog fired
        # lastWindowClosed and quitOnLastWindowClosed exited the event loop:
        # clicking EITHER button silently killed eSim on a fresh install.
        # The picker must never drive the application's lifetime -- reject()
        # below decides explicitly what a first-run cancel means.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)

        # Window icon
        logo = paths.image_path('logo.png')
        if os.path.exists(logo):
            self.setWindowIcon(QtGui.QIcon(logo))

        # --- Header -----------------------------------------------------
        title = QtWidgets.QLabel('Workspace')
        title.setProperty('cssClass', 'title')

        sub = QtWidgets.QLabel(
            'eSim stores every project inside a single workspace folder. '
            'You can change this later from the toolbar.'
        )
        sub.setProperty('cssClass', 'muted')
        sub.setWordWrap(True)

        # --- Description card ------------------------------------------
        info_box = QtWidgets.QGroupBox()
        info_box.setTitle('What goes here?')
        info_layout = QtWidgets.QVBoxLayout(info_box)
        info_text = QtWidgets.QLabel(self.obj_appconfig.workspace_text)
        info_text.setWordWrap(True)
        info_text.setProperty('cssClass', 'subtle')
        info_layout.addWidget(info_text)

        # --- Form -------------------------------------------------------
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(10)

        path_row = QtWidgets.QHBoxLayout()
        self.workspace_loc = QtWidgets.QLineEdit(self.obj_appconfig.home)
        self.workspace_loc.setPlaceholderText('Path to your workspace folder')

        self.browse_btn = QtWidgets.QPushButton('Browse…')
        self.browse_btn.setProperty('cssClass', 'secondary')
        self.browse_btn.clicked.connect(self.browseLocation)

        path_row.addWidget(self.workspace_loc, 1)
        path_row.addWidget(self.browse_btn)

        self.chkbox = QtWidgets.QCheckBox('Use this workspace by default')
        # Defense in depth: read_workspace already clamps the token, but this
        # line runs during Application() construction and must never abort
        # startup or set a bogus tri-state, whatever value the attribute holds
        # This is a two-state box, so decide explicitly -- don't feed an
        # unvalidated int into Qt.CheckState(): an out-of-range value raises on
        # some Qt builds and silently coerces to Checked on others.
        try:
            raw_check = int(self.obj_appconfig.workspace_check)
        except (TypeError, ValueError):
            raw_check = 0
        check_state = (QtCore.Qt.CheckState.Checked if raw_check == 2
                       else QtCore.Qt.CheckState.Unchecked)
        self.chkbox.setCheckState(check_state)

        form.addRow('Location', path_row)
        form.addRow('', self.chkbox)

        # --- Buttons ----------------------------------------------------
        button_box = QtWidgets.QDialogButtonBox()

        self.default_btn = QtWidgets.QPushButton('Use default')
        self.default_btn.clicked.connect(self.defaultWorkspace)

        self.ok_btn = QtWidgets.QPushButton('Use this folder')
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.createWorkspace)

        button_box.addButton(
            self.default_btn,
            QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(
            self.ok_btn,
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)

        # Compose
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(title)
        outer.addWidget(sub)
        outer.addSpacing(4)
        outer.addWidget(info_box)
        outer.addLayout(form)
        outer.addSpacing(4)
        outer.addWidget(button_box)

    # ------------------------------------------------------------------ helpers
    def returnWhetherClickedOrNot(self, appView):
        """Capture the main app view so we can refresh it after close."""
        self._app_view = appView

    def _refresh_project_explorer(self):
        """Reload the project explorer tree for the chosen workspace.

        Routes through ProjectExplorer.loadProjects() — our idempotent bulk
        loader that migrates entries to canonical keys, renders missing folders
        as stale and re-focuses the active project — instead of a hand-rolled
        clear()+addTreeNode loop. A failed refresh must never stop the main
        window from appearing.
        """
        view = self._app_view
        if view is None:
            return
        try:
            # loadProjects() blocks the GUI thread for seconds on a big
            # workspace; drain pending input first so Windows resets its
            # not-responding timer before the block starts.
            QtWidgets.QApplication.processEvents()
            view.obj_Mainview.obj_projectExplorer.loadProjects()
        except Exception as e:
            print(f"[Workspace] project explorer refresh failed: {e}")

    def _finish_workspace_change(self):
        """Show the main window now that the workspace is chosen.

        Replaces the legacy ``time.sleep(1.5)`` on the GUI thread (which froze
        the window for 1.5 s after every workspace change). The refresh and the
        show() are split so the explorer rebuilds before the splash hides.
        """
        view = self._app_view
        if view is None:
            return
        try:
            if view.splash is not None:
                view.splash.close()
        except Exception:
            pass
        # Maximize here (not in Application.__init__): this is where the main
        # window is first actually revealed, so the maximized layout+paint
        # happens once instead of being built behind the splash then discarded.
        view.showMaximized()

    # ------------------------------------------------------------------ slots
    def reject(self):
        """Closing the picker without choosing (X button, Esc).

        With WA_QuitOnClose off, Qt no longer quits for us -- decide here:
        on first run (main window never shown yet) there is no workspace to
        work in, so cancelling the picker exits eSim. From the toolbar's
        change-workspace flow the main window is visible and the cancel just
        closes the dialog.
        """
        super().reject()
        view = self._app_view
        if view is not None and not view.isVisible():
            QtWidgets.QApplication.quit()

    def defaultWorkspace(self):
        """User picked the default workspace — use it and close."""
        path = self.obj_appconfig.default_workspace["workspace"]

        # Same persistence contract as createWorkspace: honour the "use this
        # workspace by default" checkbox so the next launch can skip the
        # picker. Before this, only the custom-folder button ever wrote
        # workspace.txt and "Use default" asked again on every launch.
        self.obj_appconfig.workspace_check = self.chkbox.checkState().value
        paths.workspace_is_usable(path)   # best effort: pre-create the folder
        try:
            paths.write_workspace(self.obj_appconfig.workspace_check, path)
        except OSError as e:
            # Non-fatal: the workspace still works for this session.
            print(f"[Workspace] could not persist workspace choice: {e}")

        self.obj_appconfig.print_info('Default workspace selected: ' + path)
        self.accept()
        self._refresh_project_explorer()
        self._finish_workspace_change()

    def createWorkspace(self):
        """User picked a custom workspace — validate and save it."""
        self.obj_appconfig.workspace_check = self.chkbox.checkState().value

        path = self.workspace_loc.text().strip()
        if not path:
            Dialogs.warning(
                self, "Workspace",
                "Please choose a folder for your workspace."
            )
            return

        # Create the destination and prove THIS process can write in it
        # before persisting it as the new default -- an existing folder the
        # user cannot write (network share, another account's dir) would
        # otherwise poison every later launch.
        if not paths.workspace_is_usable(path):
            Dialogs.critical(
                self, "Workspace",
                "Could not create or write in that folder.\n"
                "Choose a folder you have permission to write to."
            )
            return

        try:
            paths.write_workspace(self.obj_appconfig.workspace_check, path)
        except OSError as e:
            Dialogs.critical(
                self, "Workspace",
                f"Could not save workspace path:\n{e}"
            )
            return

        self.obj_appconfig.default_workspace["workspace"] = path
        self.obj_appconfig.print_info('Workspace: ' + path)
        self.accept()

        # Refresh project explorer cache
        self.obj_appconfig.dictPath["path"] = os.path.join(
            self.obj_appconfig.default_workspace["workspace"],
            '.projectExplorer.txt'
        )

        try:
            with open(self.obj_appconfig.dictPath["path"]) as f:
                loaded = json.load(f)
        except (OSError, ValueError):
            loaded = {}

        # Rebuild the shared class-level project_explorer dict in place. Other
        # Appconfig instances (openProject, newProject, ProjectExplorer) hold
        # and mutate this same object; reassigning it would shadow it on this
        # instance only and desync everyone else (the identity hazard
        # ProjectExplorer.loadProjects documents). clear()+update() keeps the
        # one shared dict.
        self.obj_appconfig.project_explorer.clear()
        self.obj_appconfig.project_explorer.update(loaded)

        self._refresh_project_explorer()
        self._finish_workspace_change()

    def browseLocation(self):
        self.workspace_directory = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getExistingDirectory(
                self, 'Choose workspace folder', os.path.expanduser('~')
            )
        )
        if self.workspace_directory:
            self.workspace_loc.setText(self.workspace_directory)
