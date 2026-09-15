# =========================================================================
#          FILE: WorkerThread.py
#
#         USAGE: ---
#
#   DESCRIPTION: This class open all third party application using QT Thread
#
#       OPTIONS: ---
#  REQUIREMENTS: ---
#          BUGS: ---
#         NOTES: ---
#        AUTHOR: Fahim Khan, fahim.elex@gmail.com
#      MODIFIED: Rahul Paknikar, rahulp@iitb.ac.in
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Tuesday 24 February 2015
#      REVISION: Sunday 16 August 2020
# =========================================================================

from PyQt6 import QtCore
from configuration import Dialogs
import subprocess
import shlex
import time
from configuration.Appconfig import Appconfig


def _handle_running(handle):
    """True while the tracked child (Popen or QProcess) is alive."""
    if isinstance(handle, QtCore.QProcess):
        return handle.state() != QtCore.QProcess.ProcessState.NotRunning
    try:
        return handle.poll() is None
    except Exception:
        return False


def terminate_handle(handle):
    """Gracefully stop a tracked child through its process *handle*.

    Accepts either a ``subprocess.Popen`` (WorkerThread children) or a
    ``QProcess`` (ngspice). SIGTERM first so eeschape/ngspice can shut down
    cleanly (SIGKILL loses unsaved schematic data), escalating to kill only if
    the child ignores it. Never operates on a bare stored pid -- pids get
    recycled by the OS, so killing a remembered integer can hit an unrelated
    process.
    """
    try:
        if isinstance(handle, QtCore.QProcess):
            if handle.state() != QtCore.QProcess.ProcessState.NotRunning:
                handle.terminate()
                if not handle.waitForFinished(2000):
                    handle.kill()
                    handle.waitForFinished(1000)
        else:                                   # subprocess.Popen
            if handle.poll() is None:
                handle.terminate()
                try:
                    handle.wait(timeout=2)
                except Exception:
                    handle.kill()
    except Exception:
        pass


def terminate_all(handles, total_deadline=2.0):
    """Stop every tracked child with ONE shared wait budget.

    terminate_handle escalates terminate -> wait(2 s) -> kill -> wait(1 s) per
    child; calling it in a loop at exit serialises those waits, so N open
    external windows froze the GUI thread for up to N * 3 s (users read that as
    a hang and force-killed, which fed teardown crashes). Instead: ask ALL
    children to terminate first (no wait), then wait for them within a single
    total_deadline shared across the batch, then kill whatever is still alive.
    Bounds exit to ~total_deadline wall regardless of child count.
    """
    live = []
    for handle in handles:
        if handle is None:
            continue
        try:
            if _handle_running(handle):
                handle.terminate()          # Popen and QProcess both have it
                live.append(handle)
        except Exception:
            pass

    deadline = time.monotonic() + max(0.0, total_deadline)
    for handle in live:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            if isinstance(handle, QtCore.QProcess):
                handle.waitForFinished(int(remaining * 1000))
            else:
                try:
                    handle.wait(timeout=remaining)
                except Exception:
                    pass
        except Exception:
            pass

    for handle in live:                     # kill stragglers, brief reap
        try:
            if _handle_running(handle):
                handle.kill()
                if isinstance(handle, QtCore.QProcess):
                    handle.waitForFinished(200)
        except Exception:
            pass


class WorkerThread(QtCore.QThread):
    """
    Initialise a QThread with the passed arguments
    WorkerThread uses QThread to support threading operations for
    other PyQT windows
    This is a helper functions, used to create threads for various commands

    @params
        :args   => takes a space separated string of comamnds to be execute
                   in different child processes (see subproces.Popen())

    @return
        None
    """

    # Emitted from run()/call_system on the worker thread when no project is
    # selected. The QThread object itself has GUI-thread affinity, so a slot
    # connected on `self` is delivered queued and runs the dialog on the GUI
    # thread -- never construct a QWidget inside run() (undefined behaviour).
    errorOccurred = QtCore.pyqtSignal(str)

    def __init__(self, args):
        QtCore.QThread.__init__(self)
        self.args = args
        self.my_workers = []
        # Retain a reference for the lifetime of the run so a per-launch thread
        # is not garbage-collected while it is still babysitting its child
        # (deleting a running QThread crashes). Dropped again once finished.
        self._appconfig = Appconfig()
        self._appconfig.worker_threads.append(self)
        self.finished.connect(self._forget_self)
        self.errorOccurred.connect(self._show_error)

    def _show_error(self, text):
        """Show a project-required error on the GUI thread (queued slot)."""
        Dialogs.critical(None, "Error Message", text)

    def _forget_self(self):
        """Drop this thread from the retention list once its child exits."""
        try:
            self._appconfig.worker_threads.remove(self)
        except ValueError:
            pass

    def __del__(self):
        """
        __del__ is called whenever garbage collection is initialised.
        Here it waits (bounded) for the thread to finish executing before
        garbage collecting it.

        The wait is capped at 2000 ms: an unbounded ``self.wait()`` during
        interpreter shutdown (when a still-running child holds the thread
        alive) could block process exit indefinitely. The retention list
        (``worker_threads``) already keeps a live worker off the GC path, so
        in practice this __del__ only fires on an already-finished thread and
        returns at once; the cap is purely a shutdown-stall backstop.

        @params

        @return
            None
        """
        try:
            self.wait(2000)
        except BaseException:
            pass

    def get_proc_threads(self):
        """
        This function is a getter for the list of project's workers,
        and is called to check if project's schematic is open or not.

        @params

        @return
            :self.my_workers
        """
        return self.my_workers

    def run(self):
        """
        run is the function that is called, when we start the thread as
        thisThread.start()
        Here, it makes system calls for all args passed (self.args)

        @params

        @return
            None
        """
        print("Worker Thread Calling Command :", self.args)
        self.call_system(self.args)

    def call_system(self, command):
        """
        call_system is used to create childprocess for the passed arguments
        (self.args) and also pass the process created and its id to config file
        Apponfig() object contains procThread and proc_dist used to
        track processes called

        @params
            :command    => (self.args) takes space separated string of\
                        comamnds to be executed in different child processes
                        (see subprocess.Popen())
        """

        procThread = Appconfig()
        projDir = procThread.current_project["ProjectName"]

        if (projDir is None) and ('nghdl' not in command):
            # No QWidget here -- we are on the worker thread. Emit; the queued
            # slot raises the dialog on the GUI thread.
            self.errorOccurred.emit(
                'Please select the project first. You can either '
                'create a new project or open an existing project.')
            return

        # CREATE_NO_WINDOW: console children (python scripts, CLI tools) must
        # not flash a blank console; GUI children (eeschema, OMEdit) are
        # unaffected by the flag. 0 on POSIX.
        argv = shlex.split(command)
        try:
            proc = subprocess.Popen(
                argv,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as err:
            # An absent external tool (KiCad's eeschema, OMEdit, OMOptim not on
            # PATH) raises FileNotFoundError right here -- on the *worker*
            # thread. Letting it escape run() dumps it into sys.excepthook off
            # the GUI thread, which is the one place a dialog must never be
            # born. Report through errorOccurred, whose slot is delivered
            # queued to the GUI thread.
            tool = argv[0] if argv else command
            self.errorOccurred.emit(
                'Could not launch "%s".\n\n%s\n\nCheck that the tool is '
                'installed and on your PATH, then try again.'
                % (tool, err))
            return

        if 'nghdl' in command:
            return

        proj_key = procThread.current_project['ProjectName']
        self.my_workers.append(proc)
        procThread.procThread_list.append(proc)
        # Store the handle (not proc.pid): Close Project / exit terminate the
        # child through this object, never a bare recycled pid. setdefault: the
        # project key may not exist yet (a tool launched before the project
        # tree registered it) -- avoid a KeyError.
        procThread.proc_dict.setdefault(proj_key, []).append(proc)

        # Babysit the child: this thread exists precisely to wait on it. wait()
        # reaps the process (no lingering zombies on Linux) and lets us drop it
        # from the shared registries the moment it exits, so a long eSim session
        # does not accumulate dead handles.
        try:
            proc.wait()
        except Exception:
            pass
        finally:
            self._deregister(procThread, proj_key, proc)

    def _deregister(self, appconf, proj_key, proc):
        """Remove an exited child's handle from every shared registry.

        Guarded per-container: the GUI thread (Close Project / exit) may have
        already cleared these while we were waiting.
        """
        for container in (self.my_workers, appconf.procThread_list):
            try:
                container.remove(proc)
            except ValueError:
                pass
        handles = appconf.proc_dict.get(proj_key)
        if handles is not None:
            try:
                handles.remove(proc)
            except ValueError:
                pass
