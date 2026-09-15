"""End-to-end test of the Verilog Simulator IDE's async simulate path.

Drives VerilogVerifier.simulate_and_wave on its default design+testbench under a
real Qt event loop and asserts the simulationSucceeded signal fires. Skipped
unless a working iverilog+vvp is present (so CI without Icarus stays green).
"""
import pytest

from maker import CosimConfig

_IV = CosimConfig.iverilog_binary()
_VVP = CosimConfig.vvp_binary()
needs_sim = pytest.mark.skipif(
    not (_IV and _VVP and CosimConfig.has_iverilog()),
    reason="iverilog+vvp (with libvvp) not installed")


@needs_sim
def test_verifier_emits_simulation_succeeded(qapp, monkeypatch):
    from PyQt6.QtCore import QEventLoop, QTimer
    from maker.VerilogVerifier import VerilogVerifier

    # Pin the toolchain resolved at import time through the env override.
    # The module-level probe above ran against the real machine config
    # (~/.nghdl), but the test itself executes inside the suite's sandboxed
    # home (src/conftest.py) where that config does not exist -- without the
    # pin, find_iverilog falls through to a MODAL install prompt and the
    # headless run hangs forever.
    monkeypatch.setenv("ESIM_IVERILOG", _IV)
    monkeypatch.setenv("ESIM_VVP", _VVP)

    w = VerilogVerifier()
    loop = QEventLoop()
    fired = {"ok": False}

    def on_ok():
        fired["ok"] = True
        loop.quit()

    w.simulationSucceeded.connect(on_ok)
    # Kick the (async) run once the loop is spinning; bail after 20s.
    QTimer.singleShot(0, w.simulate_and_wave)
    QTimer.singleShot(20000, loop.quit)
    loop.exec()

    assert fired["ok"], "default counter design should compile+simulate cleanly"
    w.deleteLater()


def _run_sim(qapp, monkeypatch, design, tb=None, timeout_ms=30000):
    """Drive one full Simulate on ``design`` and return (verifier, plot data).

    ``plot`` is the (timestamps, signals, types) triple the stage would hand
    to the waveform tab, or None if no waveform was produced.
    """
    from PyQt6.QtCore import QEventLoop, QTimer
    from maker.VerilogVerifier import VerilogVerifier

    monkeypatch.setenv("ESIM_IVERILOG", _IV)
    monkeypatch.setenv("ESIM_VVP", _VVP)

    w = VerilogVerifier()
    for editor in list(w.design_views):
        w.close_tab(w.editor_tabs.indexOf(editor))
    w.add_module_tab("design.v", design)
    w.tb_view.setPlainText(tb if tb is not None else "")

    captured = {}
    loop = QEventLoop()

    def grab(ts, signals, types):
        captured['plot'] = (ts, signals, types)

    w.render_waveform = grab
    # The run is async; end the loop when the job's buttons come back.
    def poll():
        if not w._job_running() and 'started' in captured:
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(50)

    def start():
        captured['started'] = True
        w.simulate_and_wave()

    QTimer.singleShot(0, start)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return w, captured.get('plot')


@needs_sim
def test_pasting_a_module_and_pressing_simulate_produces_a_waveform(
        qapp, monkeypatch):
    """The whole point of the stage, with NO testbench written by the user."""
    design = ("module and_gate(input a, input b, output y);\n"
              "  assign y = a & b;\nendmodule\n")
    w, plot = _run_sim(qapp, monkeypatch, design)
    try:
        assert plot is not None, "Simulate with no testbench produced nothing"
        timestamps, signals, _types = plot
        assert timestamps and len(timestamps) > 2
        # ...and the trace is real data, not a wall of undefined.
        assert set(signals) >= {'a', 'b', 'y'}
        assert any(v for v in signals['y']), "output never went high"
        # The generated testbench is left in the tab for the user to edit.
        assert "and_gate uut" in w.tb_view.toPlainText()
    finally:
        w.deleteLater()


@needs_sim
def test_a_testbench_dumping_to_its_own_filename_is_read_back(qapp,
                                                              monkeypatch):
    design = ("module inv(input a, output y);\n  assign y = ~a;\nendmodule\n")
    tb = ("`timescale 1ns/1ps\nmodule tb_inv;\n  reg a; wire y;\n"
          "  inv uut(.a(a), .y(y));\n  initial begin\n"
          '    $dumpfile("my_own_name.vcd");\n    $dumpvars(0, tb_inv);\n'
          "    a = 0; #10 a = 1; #10 $finish;\n  end\nendmodule\n")
    w, plot = _run_sim(qapp, monkeypatch, design, tb)
    try:
        assert plot is not None, "a non-default $dumpfile name was not read"
        assert 'y' in plot[1]
    finally:
        w.deleteLater()


@needs_sim
def test_a_testbench_with_no_dump_still_yields_a_waveform(qapp, monkeypatch):
    """No $dumpfile, no $dumpvars, no $finish -- the three things a pasted
    testbench is most often missing. eSim supplies all of them."""
    design = ("module inv(input a, output y);\n  assign y = ~a;\nendmodule\n")
    tb = ("`timescale 1ns/1ps\nmodule tb_inv;\n  reg a; wire y;\n"
          "  inv uut(.a(a), .y(y));\n"
          "  initial begin a = 0; #10 a = 1; end\nendmodule\n")
    w, plot = _run_sim(qapp, monkeypatch, design, tb)
    try:
        assert plot is not None, "no waveform without an explicit $dumpfile"
        assert 'y' in plot[1] or 'uut.y' in plot[1]
    finally:
        w.deleteLater()
