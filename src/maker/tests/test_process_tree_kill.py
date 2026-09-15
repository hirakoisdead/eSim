"""Regression tests for process-tree termination.

The build watchdog (``ModelGeneration._run``) and the IDE's Cancel button
(``hdl.icarus.CancelToken``) both used ``Popen.kill()``, which ends the direct
child only. ``mingw32-make`` had already spawned gcc/ld and those survived,
holding handles on the objects in the model directory; the user's retry then
failed with "Permission denied" rewriting a .o — a confusing second bug with no
visible link to the step that was cancelled.
"""
import os
import subprocess
import sys

import pytest

from maker.hdl import icarus, procs

psutil = pytest.importorskip("psutil")

# Parent prints its child's pid, then both sit still until they are killed.
_SLEEP = "import time; time.sleep(90)"
_PARENT = (
    "import subprocess, sys, time;"
    "p = subprocess.Popen([sys.executable, '-c', " + repr(_SLEEP) + "]);"
    "print(p.pid, flush=True);"
    "time.sleep(90)"
)


def _spawn_tree():
    """Start a parent process holding one child; return (proc, child_pid)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _PARENT],
        stdout=subprocess.PIPE, text=True)
    child_pid = int(proc.stdout.readline().strip())
    assert psutil.pid_exists(child_pid)
    return proc, child_pid


def _cleanup(proc, child_pid):
    for target in (child_pid, proc.pid):
        try:
            psutil.Process(target).kill()
        except Exception:
            pass
    try:
        proc.stdout.close()
        proc.wait(timeout=10)
    except Exception:
        pass


def _assert_dead(pid, why):
    """psutil.Process().wait() polls a non-child too, and reaps the zombie a
    bare pid_exists() would still report as alive."""
    try:
        psutil.Process(pid).wait(timeout=15)
    except psutil.NoSuchProcess:
        return
    except psutil.TimeoutExpired:
        pytest.fail(why)


def test_kill_process_tree_takes_the_grandchildren(tmp_path):
    proc, child_pid = _spawn_tree()
    try:
        assert procs.kill_process_tree(proc) is True    # psutil walked it
        _assert_dead(proc.pid, "the direct child survived")
        _assert_dead(child_pid,
                     "the grandchild survived: this is exactly the leak that "
                     "locks the model directory after a timeout")
    finally:
        _cleanup(proc, child_pid)


def test_cancel_token_kills_the_tree(tmp_path):
    """The IDE's Cancel path goes through the same helper."""
    proc, child_pid = _spawn_tree()
    try:
        token = icarus.CancelToken()
        token.bind(proc)
        token.cancel()
        _assert_dead(proc.pid, "cancel left the direct child running")
        _assert_dead(child_pid, "cancel left a grandchild running")
    finally:
        _cleanup(proc, child_pid)


def test_falls_back_to_a_plain_kill_without_psutil(monkeypatch):
    """psutil is a hard dependency, but a half-provisioned environment must
    degrade to the old behaviour instead of crashing the watchdog."""
    monkeypatch.setattr(procs, "psutil", None)
    proc, child_pid = _spawn_tree()
    try:
        assert procs.kill_process_tree(proc) is False
        _assert_dead(proc.pid, "the direct child survived the fallback kill")
    finally:
        _cleanup(proc, child_pid)


def test_no_process_is_not_an_error():
    """Called from watchdog timers and GUI slots: never raise."""
    assert procs.kill_process_tree(None) is False

    class _Broken:
        pid = None

        def kill(self):
            raise OSError("gone")

    assert procs.kill_process_tree(_Broken()) is False


def test_model_generation_watchdog_uses_the_tree_kill():
    """Guard the wiring: the watchdog must not fall back to proc.kill()."""
    import inspect

    from maker import ModelGeneration

    src = inspect.getsource(ModelGeneration.ModelGeneration._run)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "kill_process_tree(proc)" in code
    assert "proc.kill()" not in code
    assert os.path.isfile(procs.__file__)
