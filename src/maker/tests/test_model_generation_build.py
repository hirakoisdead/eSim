"""Regression tests for the asynchronous NgVeri legacy build and its
ModelGeneration integration.

None of these need verilator/make/iverilog installed: the _run tests drive the
real (streaming Popen) subprocess boundary with the Python interpreter itself
as the child, so they assert on *how* the pipeline drives its tools (argument
lists, cwd, no os.chdir, live output, real exit-code verdict, timeout kill) --
and on the pure-Python file handling (SV rename, empty-source parse guard).
"""
import importlib
import os
import sys

import pytest
from PyQt6 import QtWidgets

from maker import CosimConfig, ModelGeneration


@pytest.fixture
def model(qapp, tmp_path, monkeypatch):
    """A ModelGeneration whose model dir lives under a throwaway HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)
    terminal = QtWidgets.QTextEdit()
    m = ModelGeneration.ModelGeneration(str(tmp_path / "counter.v"), terminal)
    m.modelpath = str(tmp_path / "counter") + "/"
    os.makedirs(m.modelpath, exist_ok=True)
    return m


# --------------------------------------------------------------------------- #
# _run: subprocess argument list, working directory, and exit-code verdict
# --------------------------------------------------------------------------- #
def test_run_passes_arglist_and_cwd_no_chdir(model, tmp_path):
    cwd_before = os.getcwd()
    # The child prints its own cwd: proves cwd= was passed to the process
    # (not achieved via a fragile os.chdir dance in the parent).
    ok = model._run(
        [sys.executable, "-c", "import os; print('CHILD_CWD=' + os.getcwd())"],
        "STEP", cwd=str(tmp_path))
    assert ok is True
    assert os.getcwd() == cwd_before                 # parent cwd untouched
    text = model.termedit.toPlainText()
    assert "CHILD_CWD=" + str(tmp_path) in text      # streamed child stdout


def test_run_streams_stdout_and_reports_stderr(model):
    ok = model._run(
        [sys.executable, "-c",
         "import sys; print('out-line-1'); print('out-line-2'); "
         "sys.stderr.write('err-line\\n')"],
        "STEP")
    assert ok is True
    text = model.termedit.toPlainText()
    assert "out-line-1" in text
    assert "out-line-2" in text
    assert "err-line" in text


def test_run_returns_false_on_nonzero_exit(model):
    assert model._run(
        [sys.executable, "-c", "import sys; sys.exit(2)"], "STEP") is False
    assert "exit code 2" in model.termedit.toPlainText()


def test_run_returns_false_on_timeout(model):
    model.PROCESS_TIMEOUT = 1        # instance override; class default is 600
    assert model._run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        "STEP") is False
    assert "timed out" in model.termedit.toPlainText()


def test_run_returns_false_when_binary_missing(model):
    assert model._run(
        ["definitely-not-a-real-binary-xyz"], "STEP") is False
    assert "could not be started" in model.termedit.toPlainText()


# --------------------------------------------------------------------------- #
# verilogfile: SystemVerilog "top" rename is word-boundary only
# --------------------------------------------------------------------------- #
def test_sv_rename_is_word_boundary_only(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Windows expanduser('~') reads USERPROFILE, not HOME -- without this the
    # test writes into the REAL ~/.nghdl and the tmp_path assert fails.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)
    src = tmp_path / "mymod.sv"
    src.write_text(
        "module top(input stop, output laptop);\n"
        "  // topology note, top_val kept\n"
        "  assign laptop = stop;\n"
        "endmodule\n")
    terminal = QtWidgets.QTextEdit()
    m = ModelGeneration.ModelGeneration(str(src), terminal)
    os.makedirs(m.digital_home, exist_ok=True)   # NGHDL install makes this
    m.verilogfile()

    written = (tmp_path / ".nghdl" / "DigitalModelLibrary" / "Ngveri" /
               "mymod" / "mymod.sv").read_text()
    assert "module mymod(" in written          # standalone top -> stem
    assert "stop" in written                   # substring 'top' untouched
    assert "laptop" in written
    assert "topology" in written
    assert "top_val" in written
    assert "module top(" not in written


# --------------------------------------------------------------------------- #
# verilogParse: empty or unparseable source returns "Error", not NameError
# --------------------------------------------------------------------------- #
def test_verilogparse_empty_source_returns_error(model, monkeypatch):
    monkeypatch.setattr(ModelGeneration.Dialogs, "critical",
                        lambda *a, **k: None)
    with open(model.modelpath + "counter.v", "w") as fh:
        fh.write("")   # nothing hdlparse can extract
    assert model.verilogParse() == "Error"


def test_verilogparse_name_mismatch_returns_error(model, monkeypatch):
    monkeypatch.setattr(ModelGeneration.Dialogs, "critical",
                        lambda *a, **k: None)
    # Module name differs from the file stem ("counter").
    with open(model.modelpath + "counter.v", "w") as fh:
        fh.write("module widget(input a, output b);\nendmodule\n")
    assert model.verilogParse() == "Error"


# --------------------------------------------------------------------------- #
# NgVeri async orchestration: the slow pipeline short-circuits on real exit
# codes and drives the steps in order
# --------------------------------------------------------------------------- #
class _StubModel:
    """Records which build steps ran; each returns a scripted bool."""

    def __init__(self, results):
        self._results = dict(results)
        self.ran = []

    def _step(self, name):
        self.ran.append(name)
        return self._results.get(name, True)

    def run_verilator(self):
        return self._step("run_verilator")

    def make_verilator(self):
        return self._step("make_verilator")

    def copy_verilator(self):
        return self._step("copy_verilator")

    def runMake(self):
        return self._step("runMake")

    def runMakeInstall(self):
        return self._step("runMakeInstall")

    def termtext(self, *_):
        pass


@pytest.fixture
def ngveri(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from maker import NgVeri, Maker
    importlib.reload(CosimConfig)
    Maker.verilogFile = [""]
    return NgVeri.NgVeri(0)


def test_pipeline_all_steps_pass(ngveri):
    # NB: do NOT monkeypatch os.name here. _legacy_build_pipeline is platform-
    # agnostic (make install on every platform), so the patch was vestigial —
    # and setting os.name='posix' on Windows makes pathlib.Path() build
    # PosixPath objects, which crashes pytest's own terminal reporter
    # (Path("C:\\...").relative_to -> ValueError -> INTERNALERROR, aborting the
    # whole session) in the window after the test body but before monkeypatch
    # teardown restores it. Order/layout-dependent (only bites when rootdir !=
    # invocation dir takes pytest's bestrelpath branch).
    stub = _StubModel({})
    assert ngveri._legacy_build_pipeline(stub) is True
    assert stub.ran == ["run_verilator", "make_verilator", "copy_verilator",
                        "runMake", "runMakeInstall"]


def test_pipeline_short_circuits_on_failure(ngveri):
    stub = _StubModel({"make_verilator": False})
    assert ngveri._legacy_build_pipeline(stub) is False
    # Stops at the first failing step; later steps never run.
    assert stub.ran == ["run_verilator", "make_verilator"]
    assert "copy_verilator" not in stub.ran


def test_convert_buttons_toggle(ngveri):
    ngveri._set_convert_buttons_enabled(False)
    assert not ngveri.addverilogbutton.isEnabled()
    assert not ngveri.addcosimbutton.isEnabled()
    ngveri._set_convert_buttons_enabled(True)
    assert ngveri.addverilogbutton.isEnabled()
    assert ngveri.addcosimbutton.isEnabled()


# --------------------------------------------------------------------------- #
# d_cosim asynchronous build parity
# --------------------------------------------------------------------------- #
class _StubClog:
    """Records severity-tagged log calls."""

    def __init__(self):
        self.msgs = []

    def phase(self, m):
        self.msgs.append(("phase", m))

    def ok(self, m):
        self.msgs.append(("ok", m))

    def error(self, m):
        self.msgs.append(("error", m))


class _CosimModel:
    def __init__(self):
        self.clog = _StubClog()
        self.modelpath = "/tmp/cosim/"


def test_cosim_epilogue_creates_symbol_and_reenables(ngveri, monkeypatch):
    from maker import NgVeri
    created = {}

    class StubSchem:
        def init(self, name, path, engine, sim_lib):
            created["args"] = (name, engine, sim_lib)

        def createKicadSymbol(self):
            return "OK"

    monkeypatch.setattr(NgVeri.createkicadCosim, "CosimSchematic",
                        lambda: StubSchem())
    model = _CosimModel()
    ngveri._build_model = model
    ngveri._build_logs = QtWidgets.QTextEdit()
    ngveri._cosim_modelname = "counter"
    ngveri._set_convert_buttons_enabled(False)

    ngveri._on_cosim_build_finished("/path/to/counter")

    assert created["args"] == ("counter", "icarus", "/path/to/counter")
    assert any(tag == "ok" for tag, _ in model.clog.msgs)
    # _flush_build_logs must re-enable both buttons.
    assert ngveri.addcosimbutton.isEnabled()
    assert ngveri.addverilogbutton.isEnabled()


def test_cosim_epilogue_skips_symbol_when_build_errored(ngveri, monkeypatch):
    from maker import NgVeri
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise AssertionError("symbol creation must not run on build error")

    monkeypatch.setattr(NgVeri.createkicadCosim, "CosimSchematic", boom)
    model = _CosimModel()
    ngveri._build_model = model
    ngveri._build_logs = QtWidgets.QTextEdit()
    ngveri._cosim_modelname = "counter"
    ngveri._set_convert_buttons_enabled(False)

    ngveri._on_cosim_build_finished("Error")

    assert calls["n"] == 0
    assert ngveri.addcosimbutton.isEnabled()


def test_cosim_build_worker_error_logs_and_reenables(ngveri):
    model = _CosimModel()
    ngveri._build_model = model
    ngveri._build_logs = QtWidgets.QTextEdit()
    ngveri._set_convert_buttons_enabled(False)

    ngveri._on_cosim_build_error("compiler blew up")

    assert any(tag == "error" and "compiler blew up" in m
               for tag, m in model.clog.msgs)
    assert ngveri.addverilogbutton.isEnabled()


# --------------------------------------------------------------------------- #
# CosimLog sink routing (worker-thread-safe GUI logging)
# --------------------------------------------------------------------------- #
def test_cosimlog_sink_overrides_termedit():
    from maker.CosimLogger import CosimLog
    captured = []
    log = CosimLog(sink=captured.append)
    log.info("hello world")
    assert any("hello world" in h for h in captured)


def test_cosimlog_falls_back_to_termedit_append():
    from maker.CosimLogger import CosimLog

    class FakeEdit:
        def __init__(self):
            self.calls = []

        def append(self, html):
            self.calls.append(html)

    fake = FakeEdit()
    CosimLog(fake).ok("done")
    assert fake.calls


def test_cosimlog_no_sink_no_crash():
    from maker.CosimLogger import CosimLog
    # No termedit and no sink: terminal/file only, must not raise.
    CosimLog().error("boom")


def test_modelgen_clog_routes_through_line_signal(model):
    # build_cosim logs via self.clog; that GUI sink must go through the queued
    # `line` signal (not a direct QTextEdit.append) so it is safe to call from
    # the build worker thread.
    received = []
    model.line.connect(received.append)
    model.clog.info("phase marker")
    assert any("phase marker" in t for t in received)
