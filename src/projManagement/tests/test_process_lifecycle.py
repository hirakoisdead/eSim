# =========================================================================
# Regression tests for process lifecycle: handles-not-pids in proc_dict,
# child reaping via the babysitting WorkerThread, and graceful terminate_handle
# for both subprocess.Popen and QProcess.
# =========================================================================

import os
import sys
import subprocess

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from projManagement import Worker  # noqa: E402


# ---- terminate_handle: subprocess.Popen branch ------------------------------

def test_terminate_handle_stops_running_popen():
    proc = subprocess.Popen(['sleep', '30'])
    assert proc.poll() is None                 # alive
    Worker.terminate_handle(proc)
    assert proc.poll() is not None             # reaped/stopped, no zombie


def test_terminate_handle_on_exited_popen_is_noop():
    proc = subprocess.Popen(['true'])
    proc.wait()
    # Must not raise even though the child is already gone.
    Worker.terminate_handle(proc)
    assert proc.poll() is not None


def test_terminate_handle_swallows_garbage():
    # A stale/foreign entry must never propagate an exception into Close Project.
    Worker.terminate_handle(object())


# ---- _handle_running --------------------------------------------------------

def test_handle_running_tracks_popen_lifecycle():
    proc = subprocess.Popen(['sleep', '30'])
    assert Worker._handle_running(proc) is True
    proc.terminate()
    proc.wait()
    assert Worker._handle_running(proc) is False


# ---- _deregister ------------------------------------------------------------

class _Appconf:
    """Minimal stand-in for Appconfig's shared registries."""
    def __init__(self, proj, proc):
        self.procThread_list = [proc]
        self.proc_dict = {proj: [proc]}


def test_deregister_removes_handle_from_every_registry():
    proc = object()
    proj = '/tmp/proj'
    appconf = _Appconf(proj, proc)
    wt = Worker.WorkerThread.__new__(Worker.WorkerThread)  # skip QThread init
    wt.my_workers = [proc]

    wt._deregister(appconf, proj, proc)

    assert proc not in wt.my_workers
    assert proc not in appconf.procThread_list
    assert proc not in appconf.proc_dict[proj]


def test_deregister_is_idempotent_when_gui_already_cleared():
    proc = object()
    proj = '/tmp/proj'
    appconf = _Appconf(proj, proc)
    appconf.procThread_list.clear()            # GUI (Close Project) got here first
    appconf.proc_dict[proj].clear()
    wt = Worker.WorkerThread.__new__(Worker.WorkerThread)
    wt.my_workers = []

    # No ValueError despite the handle being absent everywhere.
    wt._deregister(appconf, proj, proc)


def test_deregister_tolerates_missing_project_key():
    proc = object()
    appconf = _Appconf('/tmp/proj', proc)
    wt = Worker.WorkerThread.__new__(Worker.WorkerThread)
    wt.my_workers = [proc]
    # Project switched/closed: its proc_dict key is gone.
    wt._deregister(appconf, '/tmp/other', proc)
    assert proc not in wt.my_workers


# ---- terminate_handle: QProcess branch (needs a Qt app) ---------------------

def test_terminate_handle_stops_running_qprocess():
    QtCore = pytest.importorskip('PyQt6.QtCore')
    app = QtCore.QCoreApplication.instance() or \
        QtCore.QCoreApplication(sys.argv)
    assert app is not None

    proc = QtCore.QProcess()
    proc.start('sleep', ['30'])
    assert proc.waitForStarted(2000)
    assert proc.state() != QtCore.QProcess.ProcessState.NotRunning

    Worker.terminate_handle(proc)
    assert proc.state() == QtCore.QProcess.ProcessState.NotRunning
