"""Rebuilt d_cosim models are re-staged at simulation start.

``Convert._cosim_model_line`` copies each compiled vvp next to the netlist so
ivlng can load it relative to ngspice's working directory -- but only at
*conversion* time. Convert once, spot a logic bug, rebuild the model in the
NgVeri tab, hit Simulate again, and the stale copy ran: the user's fix
silently did nothing. NgspiceWidget now compares the staged copy against the
canonical build output before every run (including a redo, which restarts
ngspice from inside TerminalUi) and refreshes what is older.
"""
import os

import pytest
from PyQt6 import QtCore

from frontEnd.TerminalUi import TerminalUi
from maker import CosimConfig
from ngspiceSimulation.NgspiceWidget import NgspiceWidget

_NETLIST = """* adder.cir.out
a1 [n1 n2] [n3] u5
.model u5 d_cosim simulation="ivlng" lib_args=["libvvp", "ivlng"] \
sim_args=["adder"]
a2 [n4] [n5] u6
.model u6 d_cosim simulation="ivlng" sim_args=["counter"]
a3 [n6] [n7] u7
.model u7 d_cosim simulation="ivlng" sim_args=["adder"]
.end
"""


def _write(path, text, mtime=None):
    with open(path, "w") as handle:
        handle.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class _Log:
    """Stand-in for CosimLog: records what the re-stager reported."""

    def __init__(self):
        self.info_lines = []
        self.error_lines = []

    def info(self, msg):
        self.info_lines.append(msg)

    def error(self, msg):
        self.error_lines.append(msg)


@pytest.fixture
def bench(tmp_path, monkeypatch):
    """A project dir with a staged vvp, and a build tree behind it."""
    project = tmp_path / "project"
    build = tmp_path / "build"
    project.mkdir()
    build.mkdir()
    netlist = _write(str(project / "adder.cir.out"), _NETLIST)
    monkeypatch.setattr(CosimConfig, "cosim_vvp_path",
                        lambda name: str(build / name))
    return {"project": str(project), "build": str(build), "netlist": netlist}


# ── model-name extraction ─────────────────────────────────────────────────

def test_model_names_come_from_sim_args_only(bench):
    # lib_args sits on the same line and must not be mistaken for a model;
    # 'adder' backs two instances but is staged once.
    assert NgspiceWidget._dcosim_model_names(bench["netlist"]) == [
        "adder", "counter"]


def test_model_names_tolerate_an_unreadable_netlist(tmp_path):
    assert NgspiceWidget._dcosim_model_names(str(tmp_path / "gone.cir")) == []


# ── re-staging ────────────────────────────────────────────────────────────

def test_rebuilt_model_replaces_the_stale_staged_copy(bench):
    # Staged at conversion time, then rebuilt one minute later.
    _write(os.path.join(bench["project"], "adder"), "old vvp", mtime=1000)
    _write(os.path.join(bench["build"], "adder"), "new vvp", mtime=1060)
    log = _Log()

    refreshed = NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"], log)

    assert refreshed == ["adder"]
    with open(os.path.join(bench["project"], "adder")) as handle:
        assert handle.read() == "new vvp"
    assert any("restaged newer" in line for line in log.info_lines)


def test_an_up_to_date_staged_copy_is_left_alone(bench):
    # Staged AFTER the build: nothing to do (Convert's shutil.copy leaves the
    # project copy newer than its source, so this is the ordinary case).
    _write(os.path.join(bench["build"], "adder"), "built", mtime=1000)
    staged = _write(os.path.join(bench["project"], "adder"), "staged",
                    mtime=1060)
    before = os.stat(staged)

    assert NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"]) == []
    after = os.stat(staged)
    assert (after.st_mtime, after.st_size) == (before.st_mtime, before.st_size)


def test_restaging_is_idempotent(bench):
    """copy2 keeps the source mtime, so the next run is a no-op."""
    _write(os.path.join(bench["project"], "adder"), "old", mtime=1000)
    _write(os.path.join(bench["build"], "adder"), "new", mtime=1060)

    assert NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"]) == ["adder"]
    assert NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"]) == []


def test_a_model_that_was_never_staged_gets_staged(bench):
    _write(os.path.join(bench["build"], "counter"), "built", mtime=1000)
    log = _Log()

    assert NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"], log) == ["counter"]
    assert os.path.isfile(os.path.join(bench["project"], "counter"))
    assert any("staged missing" in line for line in log.info_lines)


def test_an_unbuilt_model_is_skipped_not_invented(bench):
    # No build output: the netlister already reported it and ngspice will
    # complain; re-staging must not create or delete anything.
    log = _Log()

    assert NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"], log) == []
    assert os.listdir(bench["project"]) == ["adder.cir.out"]
    assert log.error_lines == []


def test_a_copy_failure_is_reported_and_the_run_continues(bench):
    # 'adder' cannot be written (a directory sits where the vvp goes), but
    # 'counter' still gets staged.
    _write(os.path.join(bench["build"], "adder"), "new", mtime=1060)
    _write(os.path.join(bench["build"], "counter"), "new", mtime=1060)
    os.mkdir(os.path.join(bench["project"], "adder"))
    log = _Log()

    assert NgspiceWidget._restage_dcosim_vvps(
        bench["netlist"], bench["project"], log) == ["counter"]
    assert len(log.error_lines) == 1
    assert "adder" in log.error_lines[0]


# ── redo path ─────────────────────────────────────────────────────────────

class _StubProcess:
    """Only what TerminalUi.redoSimulation touches."""

    def __init__(self):
        self.started_with = None

    def state(self):
        return QtCore.QProcess.ProcessState.NotRunning

    def setProperty(self, *_args):
        return True

    def start(self, binary, args):
        self.started_with = (binary, args)


def _redo_ui(qapp, hook):
    ui = TerminalUi(_StubProcess(), ["-b"], "ngspice", pre_start=hook)
    # Skip the plot-choice popup; it is unrelated to the hook.
    ui._resolveNgspicePlotChoice = lambda: False
    return ui


def test_redo_runs_the_pre_start_hook_before_relaunching(qapp):
    calls = []
    ui = _redo_ui(qapp, lambda: calls.append("hook"))
    try:
        ui.redoSimulation()
        assert calls == ["hook"]
        assert ui.qProcess.started_with == ("ngspice", ["-b"])
    finally:
        ui.deleteLater()


def test_a_failing_hook_never_blocks_the_redo(qapp):
    def boom():
        raise OSError("staging blew up")

    ui = _redo_ui(qapp, boom)
    try:
        ui.redoSimulation()
        assert ui.qProcess.started_with == ("ngspice", ["-b"])
    finally:
        ui.deleteLater()


def test_no_hook_is_the_old_behaviour(qapp):
    ui = _redo_ui(qapp, None)
    try:
        ui.redoSimulation()
        assert ui.qProcess.started_with == ("ngspice", ["-b"])
    finally:
        ui.deleteLater()
