# =========================================================================
#          FILE: Appconfig.py
#
#         USAGE: ---
#
#   DESCRIPTION: This define all configuration used in Application.
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in
#                Sumanto Kar, sumantokar@iitb.ac.in
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Tuesday 24 February 2015
#      REVISION: Thursday 29 June 2023
# =========================================================================

import os
import json
from configparser import ConfigParser
from configuration import paths


class Appconfig:
    """
    All configuration goes here.
    May change in future for code optimization.

    This class also contains function for
    - Printing error.
    - Showing warnings.
    - Displaying information.

    This is a plain class, not a QWidget: it is instantiated dozens of times
    across the app purely to reach its shared class-level state, and a QWidget
    base only leaked parentless invisible widgets. All the attributes below are
    **class-level, shared** -- Appconfig is a de-facto singleton, and callers
    read/mutate the shared dicts/lists through any instance.

    The file I/O that seeds this state (workspace.txt, config.ini,
    .projectExplorer.txt) is NOT done at import time. It lives in the
    ``load_*`` classmethods, which ``Application.__init__`` calls once at
    startup. That keeps importing this module side-effect-free (tests can
    isolate; import order stops mattering) while every non-GUI caller still
    sees the same populated state once the app is up.
    """

    # class-level, shared -- the user's home dir. Cheap, no I/O, always valid.
    user_home = paths.user_home()
    # class-level, shared -- seeded by load_workspace(); safe defaults so a
    # read before startup (or in an isolated test) never explodes.
    workspace_check = '0'
    home = ''

    default_workspace = {"workspace": ''}
    # Current Project detail.
    #   ProjectName => the project *folder* path
    #   ProjName    => the project *stem* (basename shared by <stem>.proj/.cir/
    #                  .sch/...), resolved from the .proj anchor, NOT the folder
    #                  name. Use get_proj_stem() to read it.
    current_project = {"ProjectName": None, "ProjName": None}
    # Current Subcircuit detail
    #   SubcircuitName => the subcircuit *folder* path
    #   Stem           => the subcircuit *stem* actually being worked on. A
    #                     folder may hold several .sub files (a subcircuit
    #                     ships the models of the ones nested inside it), so
    #                     the folder alone does not identify the subcircuit.
    #                     Use get_subcircuit_stem() to read it.
    current_subcircuit = {"SubcircuitName": None, "Stem": None}
    # Workspace detail
    workspace_text = "eSim stores your project in a folder called "
    workspace_text += "eSim-Workspace. You can choose a different "
    workspace_text += "workspace folder to use for this session."

    procThread_list = []
    # Holds the *process handles* (subprocess.Popen / QProcess) of the current
    # project's external windows -- NOT bare pids. Close Project / app exit
    # terminate through the handle; a stored integer pid can be recycled by the
    # OS between spawn and kill and take out an unrelated process.
    proc_dict = {}
    # Live WorkerThread instances. Each babysits its child with a blocking
    # wait(), so a per-launch thread must be retained here or Python may GC the
    # QThread while it is still running (deleting a running QThread crashes).
    worker_threads = []
    dock_dict = {}  # holds all dockwidgets
    # class-level, shared -- path to .projectExplorer.txt; seeded by
    # load_workspace() (depends on the resolved workspace home).
    dictPath = {"path": ''}

    noteArea = {"Note": []}

    #: Set by Application to its QStatusBar. print_* mirror their latest line
    #: here so the full console panel can stay collapsed by default.
    statusbar = None

    #: The GUI-thread reporter (a QObject) that print_* emit through once the
    #: window is up. None in headless/test/pre-GUI runs -- print_* then write
    #: the plain-list sink directly. Created on the GUI thread by
    #: attach_gui_reporter(); see the thread-affinity note there.
    _reporter = None

    # class-level, shared -- seeded by load_config(). Default None so ModelicaUI
    # reading Appconfig.modelica_map_json gets None (not AttributeError) if
    # config.ini is missing the key or is unreadable on Win10.
    modelica_map_json = None

    # class-level, shared -- the known-projects registry; seeded by
    # load_project_explorer(). Kept as a stable dict identity (mutated in place)
    # so callers that cache a reference stay in sync.
    project_explorer = {}
    process_obj = []

    @classmethod
    def load_workspace(cls):
        """Read workspace.txt and seed the workspace-derived paths. Called once
        from Application.__init__ (was import-time I/O)."""
        cls.workspace_check, cls.home = paths.read_workspace()
        cls.default_workspace["workspace"] = cls.home
        cls.dictPath["path"] = os.path.join(
            cls.home, ".projectExplorer.txt")

    @classmethod
    def load_config(cls):
        """Read config.ini for the Modelica map location. Called once from
        Application.__init__ (was import-time I/O). Tolerant of a missing key
        or an unreadable .esim folder (Win10)."""
        parser_esim = ConfigParser()
        parser_esim.read(paths.esim_config_path('config.ini'))
        try:
            cls.modelica_map_json = parser_esim.get(
                'eSim', 'MODELICA_MAP_JSON')
        except BaseException as e:
            print("Cannot access Modelica map file --- .esim folder")
            print(str(e))

    @classmethod
    def load_project_explorer(cls):
        """Load the known-projects registry from .projectExplorer.txt. Called
        once from Application.__init__, after load_workspace() has resolved
        dictPath. Updates the registry in place so its dict identity is stable.
        A missing/corrupt file falls back to an empty registry."""
        try:
            with open(cls.dictPath["path"]) as _pe_fh:
                loaded = json.load(_pe_fh)
        except BaseException:
            loaded = {}
        cls.project_explorer.clear()
        cls.project_explorer.update(loaded)

    def __init__(self):
        # Application Details
        self._APPLICATION = 'eSim'
        self._VERSION = '2.6'
        self._AUTHOR = 'Fahim'
        self._REVISION = 'Rahul, Sumanto'

        # Application geometry setting
        self._app_xpos = 100
        self._app_ypos = 100
        self._app_width = 600
        self._app_heigth = 400

    def set_current_project(self, proj_dir, stem=None):
        """
        Set the active project. This is the single place that updates both the
        project folder path and its resolved stem, so callers never have to
        derive the stem from the folder name themselves.

        @params
            :proj_dir   => the project folder path, or None to clear the project
            :stem        => the already-resolved stem; if omitted it is resolved
                            from the folder's .proj anchor
        """
        self.current_project["ProjectName"] = proj_dir
        if not proj_dir:
            self.current_project["ProjName"] = None
            return
        if stem is None:
            from projManagement.projectPaths import resolve_stem
            stem, _status = resolve_stem(proj_dir, 'proj')
        self.current_project["ProjName"] = stem

    def get_proj_stem(self):
        """
        Return the active project's stem (the basename shared by its files).

        This is the canonical replacement for ``os.path.basename(projDir)``
        when constructing project file paths. Resolves lazily from the .proj
        anchor if not cached, and falls back to the folder basename so legacy
        code paths keep working.

        @return
            the project stem, or None if no project is open
        """
        stem = self.current_project.get("ProjName")
        if stem:
            return stem
        proj_dir = self.current_project.get("ProjectName")
        if not proj_dir:
            return None
        from projManagement.projectPaths import resolve_stem
        stem, _status = resolve_stem(proj_dir, 'proj')
        self.current_project["ProjName"] = stem
        return stem

    def set_current_subcircuit(self, sub_dir, stem=None):
        """
        Set the subcircuit the Subcircuit Builder is working on.

        Single place that updates both the folder and the stem, so Edit and
        Convert can never disagree about which subcircuit is open (they
        used to:
        Edit opened the one the user picked, Convert independently re-derived a
        different one and rebuilt the wrong model).

        @params
            :sub_dir    => the subcircuit folder path, or None to clear
            :stem        => the already-chosen stem; resolved from the folder
                            when omitted
        """
        self.current_subcircuit["SubcircuitName"] = sub_dir
        if not sub_dir:
            self.current_subcircuit["Stem"] = None
            return
        if stem is None:
            from subcircuit.subPaths import resolve_subcircuit
            stem, _status = resolve_subcircuit(sub_dir)
        self.current_subcircuit["Stem"] = stem

    def get_subcircuit_stem(self):
        """
        Return the stem of the subcircuit currently selected, or None.

        Falls back to resolving from the folder so a selection made by older
        code (which only recorded the folder) still yields an answer.
        """
        stem = self.current_subcircuit.get("Stem")
        if stem:
            return stem
        sub_dir = self.current_subcircuit.get("SubcircuitName")
        if not sub_dir:
            return None
        from subcircuit.subPaths import resolve_subcircuit
        stem, _status = resolve_subcircuit(sub_dir)
        self.current_subcircuit["Stem"] = stem
        return stem

    def _append_note(self, line):
        """Append to the log sink. Before the GUI attaches its console,
        noteArea['Note'] is a plain list (class-level, never cleared) -- bound
        it so a long pre-GUI session cannot grow it without limit. After the
        GUI attaches, it is a QTextEdit that manages its own buffer.

        MUST run on the GUI thread once the sink is a QTextEdit -- callers reach
        it only through _dispatch(), which marshals worker-thread calls onto the
        GUI thread via the reporter."""
        notes = self.noteArea['Note']
        try:
            notes.append(line)
        except RuntimeError:        # QTextEdit was destroyed (app closing)
            return
        if isinstance(notes, list) and len(notes) > 5000:
            del notes[:1000]

    def print_info(self, info):
        self._dispatch('[INFO]: ' + info)

    def print_warning(self, warning):
        self._dispatch('[WARNING]: ' + warning)

    def print_error(self, error):
        self._dispatch('[ERROR]: ' + error)

    def _dispatch(self, line):
        """Route one already-tagged log line to the console panel + status bar.

        The console sink is a QTextEdit and the status bar is a QStatusBar once
        the GUI is up; touching either from a thread other than the GUI thread
        is undefined behaviour in Qt and can corrupt state natively. The
        codebase does not print from workers today, but nothing stops a future
        BackgroundJob fn from calling print_info -- so route through the
        GUI-thread reporter when it exists: its signals use AutoConnection, so a
        same-thread emit runs the slot directly (order preserved, identical to
        the old inline path) while a worker-thread emit is queued onto the GUI
        thread. Before the GUI attaches (and in headless/test runs it never
        does) there is no reporter and no live widget, so write the plain-list
        sink directly."""
        reporter = Appconfig._reporter
        if reporter is not None:
            try:
                reporter.note.emit(line)
                reporter.status.emit(line)
                return
            except RuntimeError:
                # Reporter's C++ object was torn down (QApplication gone, e.g.
                # a stale reporter left over between test QApplications). Fall
                # through to the direct sink rather than crash the caller.
                Appconfig._reporter = None
        self._append_note(line)
        self._echo_status(line)

    def _echo_status(self, msg):
        """Mirror the newest log line to the status bar (if Application has
        wired one), so the bottom console panel can stay collapsed. GUI thread
        only once wired -- reached via _dispatch()/the reporter."""
        bar = Appconfig.statusbar
        if bar is not None:
            try:
                bar.showMessage(' '.join(msg.split()), 0)
            except RuntimeError:        # bar was destroyed (app closing)
                Appconfig.statusbar = None

    @classmethod
    def attach_gui_reporter(cls):
        """Create the GUI-thread log reporter. Call once, ON THE GUI THREAD,
        after QApplication exists (Application startup does this). Idempotent.

        The reporter is a tiny QObject constructed here (on the GUI thread), so
        it LIVES on the GUI thread -- the one place the console QTextEdit, the
        QStatusBar and any QWidget dialog may be touched. It carries two kinds
        of signal, both of which deliver their slot on the GUI thread:

        * ``note`` / ``status`` (AutoConnection). A same-thread emit runs
          the slot directly (order preserved, identical to the old inline
          print_* path); a worker-thread emit is queued onto the GUI thread.
        * ``deferred`` (QueuedConnection, carries a callable). It is
          queued even for a same-thread emit, so post_to_gui() below always
          defers: safe from a worker thread AND safe from inside a
          paint/close/teardown handler (it cannot re-enter the event loop that
          is already running). The excepthook posts its modal dialog through
          this.

        This is the single queued-signal error reporter used by background
        workers, keeping message-box creation on the GUI thread.

        Defined lazily inside the method so ``import Appconfig`` stays Qt-free
        for the many non-GUI importers (matching this module's no-import-side-
        effects contract)."""
        if cls._reporter is not None:
            return
        from PyQt6 import QtCore

        class _GuiReporter(QtCore.QObject):
            note = QtCore.pyqtSignal(str)
            status = QtCore.pyqtSignal(str)
            deferred = QtCore.pyqtSignal(object)

            def __init__(self):
                super().__init__()
                # AutoConnection (the default): same-thread emit -> direct call
                # (keeps note-before-status ordering); cross-thread emit ->
                # queued onto this object's (GUI) thread.
                self.note.connect(self._on_note)
                self.status.connect(self._on_status)
                # QueuedConnection: ALWAYS deferred to the next GUI event-loop
                # turn, even on the GUI thread, to prevent re-entrancy.
                self.deferred.connect(
                    self._on_deferred,
                    QtCore.Qt.ConnectionType.QueuedConnection)

            @QtCore.pyqtSlot(str)
            def _on_note(self, line):
                Appconfig()._append_note(line)

            @QtCore.pyqtSlot(str)
            def _on_status(self, msg):
                Appconfig()._echo_status(msg)

            @QtCore.pyqtSlot(object)
            def _on_deferred(self, fn):
                # Runs on the GUI thread, off the emitting stack. fn guards
                # itself; a raising fn must never take the reporter down.
                try:
                    fn()
                except Exception:
                    pass

        cls._reporter = _GuiReporter()

    @classmethod
    def post_to_gui(cls, fn):
        """Queue ``fn`` (a no-arg callable) to run on the GUI thread's event
        loop, always deferred. Returns True if it was queued, False if no GUI
        reporter exists yet (very early startup / headless) or the reporter was
        torn down.

        This is the marshalling primitive the excepthook uses to show its error
        dialog: PyQt6's ``QTimer.singleShot`` has no (msec, context, slot)
        overload, so a callable cannot be posted to *another* thread's loop that
        way -- only a signal on a GUI-thread QObject crosses threads correctly.
        See attach_gui_reporter (the ``deferred`` signal)."""
        reporter = cls._reporter
        if reporter is None:
            return False
        try:
            reporter.deferred.emit(fn)
            return True
        except RuntimeError:        # reporter C++ side gone (stale QApplication)
            cls._reporter = None
            return False

    def save_current_project(self):
        try:
            path = paths.esim_config_path("last_project.json")
            with open(path, "w") as f:
                json.dump(self.current_project, f)
        except Exception as e:
            print("Failed to save current project:", str(e))

    def load_last_project(self):
        try:
            path = paths.esim_config_path("last_project.json")
            with open(path, "r") as f:
                data = json.load(f)
                project_path = data.get("ProjectName", None)
                if project_path and os.path.exists(project_path):
                    self.set_current_project(project_path)
                    return project_path
                else:
                    print("Project path does not exist: ", project_path)
        except Exception as e:
            print("Error: ", str(e))
        return None

    def load_preferences(self):
        """Return the persisted Aurora theme preferences, with safe defaults
        when ~/.esim/preferences.json is absent or unreadable."""
        # enable_motion defaults ON everywhere, Windows included: only the
        # hovered button carries a blur now (see frontEnd/motion.py), so the
        # per-button CPU blur that made it a drag on Windows is gone. Keep this
        # in step with motion._MOTION_DEFAULT. Preferences overrides it.
        prefs = {"theme_mode": "System", "accent_color": "default",
                 "secondary_accent_color": "system",
                 "internal_bg_color": "system",
                 "enable_motion": True}
        try:
            path = paths.esim_config_path("preferences.json")
            if os.path.exists(path):
                with open(path, "r") as f:
                    prefs.update(json.load(f))
        except Exception as e:
            print("Error loading preferences: ", str(e))
        return prefs

    def save_preferences(self, theme_mode, accent_color,
                         secondary_accent_color="system",
                         internal_bg_color="system"):
        """Persist the Aurora theme preferences to ~/.esim/preferences.json.

        Merges into the existing file instead of overwriting it: writing only
        these four keys used to DROP zoom_level, enable_motion and any other
        stored key (a data-loss trap that PreferencesDialog had to compensate
        for). Written atomically so a crash mid-write can't corrupt the file.
        """
        try:
            path = paths.esim_config_path("preferences.json")
            existing = {}
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        existing = json.load(f)
                except Exception:
                    existing = {}
            existing.update({
                "theme_mode": theme_mode,
                "accent_color": accent_color,
                "secondary_accent_color": secondary_accent_color,
                "internal_bg_color": internal_bg_color,
            })
            paths.write_json_atomic(path, existing)
        except Exception as e:
            print("Failed to save preferences:", str(e))
