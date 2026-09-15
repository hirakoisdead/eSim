"""Verify-stage run-side hardening (GUI-wired, but iverilog-free).

Pins the behaviour that only shows up around the compile/sim/plot pipeline and
its async/cancel/lifecycle machinery -- none of which needs a toolchain to
verify, because the failures are in our own plumbing:

* compile filenames are sanitised so an error squiggle / jump survives a tab
  label the diagnostic regex can't carry (spaces, parens);
* a partial failure (sim exits nonzero but still wrote a VCD) still plots, yet
  does not report success;
* a cancelled run renders nothing;
* the per-run temp dir is reaped even when the stage is torn down mid-run.

Ungated -- constructs the widget headlessly.
"""
import re

import pytest

from PyQt6 import QtGui


@pytest.fixture
def verifier(qapp):
    from maker.VerilogVerifier import VerilogVerifier
    w = VerilogVerifier()
    w.unlock_ui()
    yield w
    w.deleteLater()


# --- error -> editor mapping survives messy tab labels ------------------- #

def test_safe_source_name_is_diagnostic_regex_safe():
    from maker.VerilogVerifier import VerilogVerifier as V
    assert V._safe_source_name("alu.v") == "alu.v"
    assert V._safe_source_name("counter") == "counter.v"      # extension added
    n = V._safe_source_name("foo (2).v")       # duplicate disambiguation
    assert n.endswith(".v")
    # the squiggle/jump regex is [\w./-]+ ; spaces and parens would break it
    assert re.fullmatch(r"[\w./-]+\.v", n)


def test_design_sources_names_are_unique_after_sanitising(verifier):
    # Two tabs whose sanitised names would collide must still map distinctly,
    # so no module silently overwrites another on disk at compile time.
    verifier.add_module_tab("a b.v", "module x; endmodule")
    verifier.add_module_tab("a_b.v", "module y; endmodule")
    verifier._design_sources()
    names = list(verifier._compile_editors)
    assert len(names) == len(set(names))                       # collision-free
    assert all(re.fullmatch(r"[\w./-]+\.(?:v|sv)", n) for n in names)


def test_error_squiggle_survives_spaced_duplicate_label(verifier):
    # Same module in two tabs -> the second is labelled 'alu (2).v', whose
    # space and parens must not reach a compile filename.
    verifier.add_module_tab("alu.v", "module alu; endmodule")
    verifier.add_module_tab("alu.v", "module alu; endmodule // second copy")
    labels = [verifier.editor_tabs.tabText(i)
              for i in range(verifier.editor_tabs.count())]
    assert "alu (2).v" in labels

    verifier._design_sources()
    safe = [n for n in verifier._compile_editors if n != "alu.v"
            and "second copy" in verifier._compile_editors[n].toPlainText()]
    assert safe, "duplicate tab should get its own sanitised compile name"
    name = safe[0]
    assert " " not in name and "(" not in name

    second = verifier._compile_editors[name]
    hits = []
    second.mark_error_line = lambda ln: hits.append(ln)
    verifier.highlight_errors_from_log(f"{name}:7: error: oops")
    assert hits == [7]


def test_jump_to_error_uses_compile_name_map(verifier):
    verifier.add_module_tab("alu.v", "module alu; endmodule")
    verifier._design_sources()
    ed = verifier._compile_editors["alu.v"]
    goto = []
    ed.mark_error_line = lambda ln: None
    ed.goto_line = lambda ln: goto.append(ln)
    verifier.jump_to_error(5, "alu.v")
    assert goto == [5]


# --- success / failure detection ----------------------------------------- #

def _run(compile_ok, sim_ok=None, vcd=None):
    from maker.hdl.icarus import RunResult, CompileResult, SimResult
    cres = CompileResult(ok=compile_ok, returncode=0 if compile_ok else 1,
                         stdout="", stderr="" if compile_ok else "boom",
                         out_path="x" if compile_ok else None)
    sres = None
    if sim_ok is not None:
        sres = SimResult(ok=sim_ok, returncode=0 if sim_ok else 1,
                         stdout="", stderr="", vcd_path="x" if vcd else None)
    return RunResult(compile=cres, sim=sres, vcd_content=vcd)


def test_partial_failure_still_plots_without_success_signal(verifier):
    vcd = ("$timescale 1ns $end\n$var wire 1 ! clk $end\n"
           "$enddefinitions $end\n#0\n0!\n#5\n1!\n")
    run = _run(compile_ok=True, sim_ok=False, vcd=vcd)
    plotted, fired = [], []
    verifier.render_waveform = lambda *a: plotted.append(a)
    verifier.simulationSucceeded.connect(lambda: fired.append(1))
    verifier._render_sim_result(run, cancelled=False)
    assert plotted              # nonzero sim exit but a VCD -> still plotted
    assert not fired            # run.ok is False -> no success report


def test_clean_run_emits_success(verifier):
    vcd = ("$timescale 1ns $end\n$var wire 1 ! clk $end\n"
           "$enddefinitions $end\n#0\n0!\n#5\n1!\n")
    run = _run(compile_ok=True, sim_ok=True, vcd=vcd)
    fired = []
    verifier.render_waveform = lambda *a: None
    verifier.simulationSucceeded.connect(lambda: fired.append(1))
    verifier._render_sim_result(run, cancelled=False)
    assert fired == [1]


def test_cancelled_run_renders_nothing(verifier):
    run = _run(compile_ok=False)
    plotted = []
    verifier.render_waveform = lambda *a: plotted.append(a)
    verifier._render_sim_result(run, cancelled=True)
    assert not plotted


# --- design / testbench scoping ------------------------------------------ #
# Check Syntax compiles the design on its own first, so a testbench the user
# never wrote cannot make their design look broken. These pin the reporting
# either side of that split; the two-phase run itself needs iverilog and is
# covered by test_verifier_sim.

_STALE = ("tb_design.v:8: error: Unknown module type: counter\n"
          "2 error(s) during elaboration.\n")


def _compile_failure(stderr):
    from maker.hdl.icarus import CompileResult
    return CompileResult(ok=False, returncode=1, stdout="", stderr=stderr,
                         out_path=None)


def test_stale_testbench_is_named_not_blamed_on_the_design(verifier):
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    named = verifier._stale_testbench_note(
        _compile_failure(_STALE), [("or_gate.v", "module or_gate; endmodule")])
    assert named is True
    msg = " ".join(logged)
    assert "'counter'" in msg and "no design tab defines" in msg
    assert "Auto-Generate Testbench" in msg


def test_module_defined_by_a_design_tab_is_not_called_stale(verifier):
    # Same diagnostic, but the module DOES exist in a design tab (e.g. the tab
    # failed to compile for its own reasons). Not a testbench mismatch.
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    assert verifier._stale_testbench_note(
        _compile_failure(_STALE),
        [("counter.v", "module counter; endmodule")]) is False
    assert not logged


def test_design_side_missing_module_is_not_called_stale(verifier):
    # The unresolved instantiation is in a design file, so the testbench is not
    # the story -- the user is missing a submodule.
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    assert verifier._stale_testbench_note(
        _compile_failure("top.v:12: error: Unknown module type: alu\n"),
        [("top.v", "module top; endmodule")]) is False
    assert not logged


def test_compile_errors_report_where_to_look(verifier):
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    verifier.log_sim = lambda text: None
    verifier._report_compile_errors(_compile_failure("or_gate.v:2: syntax error\n"))
    assert any("or_gate.v:2" in m for m in logged)
    assert any("double-click" in m for m in logged)


def test_locator_is_silent_when_the_failure_has_no_location(verifier):
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    verifier.log_sim = lambda text: None
    verifier._report_compile_errors(_compile_failure("I give up.\n"))
    assert not any("error line(s)" in m for m in logged)


def test_hints_can_be_suppressed(verifier):
    # The generic "module instantiated but not defined" hint is noise once the
    # stale-testbench note has said the same thing more precisely.
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    verifier.highlight_errors_from_log(_STALE, hints=False)
    assert not logged
    verifier.highlight_errors_from_log(_STALE, hints=True)
    assert any("not defined" in m for m in logged)


def test_default_testbench_is_dropped_with_the_default_design(
        verifier, tmp_path, monkeypatch):
    # DEFAULT_DESIGN and DEFAULT_TB are a matched pair. Opening a source file
    # closes the default design; keeping its testbench leaves one instantiating
    # a module nothing defines -- the reported "Check Syntax is broken" bug.
    from PyQt6 import QtWidgets
    from maker.VerilogVerifier import DEFAULT_TB
    src = tmp_path / "or_gate.v"
    src.write_text("module or_gate(input a, input b, output y);\n"
                   "  assign y = a | b;\nendmodule\n")
    assert verifier.tb_view.toPlainText().strip() == DEFAULT_TB.strip()

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(src)], "")))
    verifier.load_source_files()

    assert verifier.tb_view.toPlainText().strip() == ""
    assert [e.toPlainText() for e in verifier.design_views][0].startswith(
        "module or_gate")


def test_user_written_testbench_is_never_cleared(verifier, tmp_path, monkeypatch):
    from PyQt6 import QtWidgets
    mine = "`timescale 1ns/1ps\nmodule tb_mine; endmodule\n"
    verifier.tb_view.setPlainText(mine)
    src = tmp_path / "alu.v"
    src.write_text("module alu; endmodule\n")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(src)], "")))
    verifier.load_source_files()

    assert verifier.tb_view.toPlainText() == mine


def test_bus_render_also_drops_the_paired_default_testbench(verifier):
    # The flow-navigator path replaces every design tab too, and the pinned
    # testbench survives it -- same mismatch, different door.
    class _Bus:
        path = None

        def get_content(self):
            return "module or_gate(input a, output y);\n  assign y = a;\nendmodule\n"

    verifier.set_design_bus(_Bus())
    verifier.render_from_bus()
    assert verifier.tb_view.toPlainText().strip() == ""


# --- temp dir hygiene ---------------------------------------------------- #

def test_cleanup_tmpdir_is_idempotent(verifier, tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    verifier._active_tmpdir = str(d)
    verifier._cleanup_tmpdir()
    assert not d.exists()
    assert verifier._active_tmpdir is None
    verifier._cleanup_tmpdir()          # second call must be a harmless no-op


def test_closeevent_reaps_orphaned_tmpdir(verifier, tmp_path):
    # Simulate a stage torn down mid-run: the done/fail closures never fired,
    # so closeEvent is the only thing left to reap the temp dir.
    d = tmp_path / "orphan"
    d.mkdir()
    verifier._active_tmpdir = str(d)
    verifier.closeEvent(QtGui.QCloseEvent())
    assert not d.exists()


# --- Simulate must not demand a hand-written testbench -------------------- #
# The realistic path into this tool is "paste a module, press Simulate". If
# that also required writing a matching testbench -- correct instance name,
# correct port map, the exact $dumpfile eSim looked for -- the user stops here.

_OR_GATE = "module or_gate(input a, input b, output y);\n" \
           "  assign y = a | b;\nendmodule\n"


def _only_design(verifier, code, name="or_gate.v"):
    for editor in list(verifier.design_views):
        verifier.close_tab(verifier.editor_tabs.indexOf(editor))
    verifier.add_module_tab(name, code)
    return verifier._design_sources()


def test_empty_testbench_is_generated_at_simulate_time(verifier):
    sources = _only_design(verifier, _OR_GATE)
    verifier.tb_view.setPlainText("")
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)

    tb = verifier._ensure_testbench(sources)

    assert tb and "or_gate uut" in tb
    assert verifier.tb_view.toPlainText() == tb     # and it is shown to them
    assert any("generated one" in m for m in logged)


def test_a_stale_generated_testbench_is_replaced_not_compiled(verifier):
    # A testbench eSim generated for a design that has since been renamed
    # fails with "Unknown module type" against a file the user never wrote.
    # It is eSim's own, so eSim replaces it rather than reporting it.
    from maker.hdl.ports import generate_stub_testbench
    sources = _only_design(verifier, _OR_GATE)
    verifier.tb_view.setPlainText(
        generate_stub_testbench("counter", [("input", "clk", "")]))
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)

    tb = verifier._ensure_testbench(sources)

    assert "or_gate uut" in tb
    assert any("does not instantiate" in m for m in logged)


def test_a_mismatched_testbench_of_the_users_is_reported_not_overwritten(
        verifier):
    """The line eSim must not cross. A testbench with no provenance marker is
    somebody's work: renaming a module used to silently replace it with
    boilerplate, which is the one outcome a user cannot undo."""
    sources = _only_design(verifier, _OR_GATE)
    mine = "module tb_counter;\n  counter uut();\nendmodule\n"
    verifier.tb_view.setPlainText(mine)
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)

    assert verifier._ensure_testbench(sources) is None
    assert verifier.tb_view.toPlainText() == mine
    assert any("does not instantiate" in m for m in logged)
    assert any("it is yours" in m for m in logged)


def test_a_matching_testbench_is_left_exactly_as_written(verifier):
    sources = _only_design(verifier, _OR_GATE)
    mine = "module tb_mine;\n  reg a, b; wire y;\n" \
           "  or_gate uut(.a(a), .b(b), .y(y));\nendmodule\n"
    verifier.tb_view.setPlainText(mine)

    assert verifier._ensure_testbench(sources) == mine
    assert verifier.tb_view.toPlainText() == mine


def test_no_module_at_all_reports_instead_of_generating(verifier):
    sources = _only_design(verifier, "// just a comment\n")
    verifier.tb_view.setPlainText("")
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)

    assert verifier._ensure_testbench(sources) is None
    assert any("no Verilog module" in m for m in logged)


def test_undriven_signals_are_named_not_left_as_a_silent_red_plot(verifier):
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    verifier._warn_if_undriven(
        {'a': [], 'y': []},
        {'a': ['0', '1'], 'y': ['x', 'x']})
    assert any("'y'" in m or " y." in m or ": y" in m for m in logged)
    assert any("X/Z" in m for m in logged)


def test_no_undriven_note_when_everything_moved(verifier):
    logged = []
    verifier.log = lambda text, level=None: logged.append(text)
    verifier._warn_if_undriven({'a': []}, {'a': ['0', '1']})
    assert not logged


# --- the waveform must not open empty ------------------------------------- #

def test_waveform_opens_with_the_designs_own_signals_drawn(qapp):
    """Traces default to hidden (right for the ngspice flow, where you pick
    nodes off a schematic). Here it meant the tab a simulation had just opened
    was a blank plot next to a list of every internal reg $dumpvars captured --
    the user pressed Simulate and got nothing to look at."""
    from maker.VerilogVerifier import make_vcd_plot_window

    timestamps = [0, 5, 10]
    signals = {'clk': [0, 1, 0], 'y': [0, 0, 1],
               'uut.state': [0, 1, 2], 'esim_i': [0, 1, 2]}
    types = {k: 'wire' for k in signals}

    plot = make_vcd_plot_window(timestamps, signals, types, "t")
    try:
        visible = {t.name for t in plot.traces.values() if t.visible}
        assert visible, "the waveform opened with nothing drawn"
        # Top-level testbench signals (= the design's ports) are the default;
        # instance internals and eSim's own loop counter are not.
        assert visible == {'clk', 'y'}
    finally:
        plot.deleteLater()
