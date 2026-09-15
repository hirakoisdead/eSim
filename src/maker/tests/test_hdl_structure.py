"""Tests for the Qt-free structural analysis in maker.hdl.ports: comment-safe
module discovery, ANSI/bus-width-aware port extraction, dependency ordering,
and width-honouring testbench stubs.

These pin the design-side hardening: each test corresponds to a way the
previous implementation silently produced wrong output (empty ports on
single-line ANSI headers, dropped bus widths, comment-hijacked module names,
first-module-instead-of-top, missed parameterised instantiations,
duplicate-name collapse).
"""
import importlib.util

import pytest

from maker.hdl.ports import (
    extract_ports, generate_stub_testbench, order_modules,
    strip_comments, find_modules,
)

_HAS_HDLPARSE = importlib.util.find_spec("hdlparse") is not None
needs_hdlparse = pytest.mark.skipif(
    not _HAS_HDLPARSE, reason="hdlparse not installed (regex fallback active)")


# --------------------------------------------------------------------------- #
#  strip_comments / find_modules
# --------------------------------------------------------------------------- #
def test_strip_comments_blanks_but_keeps_newlines():
    src = "module a; // module b\n/* module c */ wire x;\n"
    clean = strip_comments(src)
    assert "module a" in clean
    assert "module b" not in clean   # line comment gone
    assert "module c" not in clean   # block comment gone
    assert clean.count("\n") == src.count("\n")  # line structure preserved


def test_strip_comments_blanks_string_literals():
    assert "module" not in strip_comments('$display("module top");')


def test_find_modules_ignores_comments_and_strings():
    src = ('// instantiate module ghost\n'
           'module real_one(input a); endmodule\n'
           '$display("module phantom");')
    assert find_modules(src) == ["real_one"]


# --------------------------------------------------------------------------- #
#  extract_ports — the reported breakages
# --------------------------------------------------------------------------- #
SINGLE_LINE_ANSI = "module alu(input [3:0] a, input [3:0] b, output [7:0] y, output cout);\nendmodule"


def test_single_line_ansi_header_yields_ports():
    # hdlparse parses single-line ANSI headers as ZERO ports; the regex
    # fallback must recover them (mode + name + bus width).
    name, ports = extract_ports(SINGLE_LINE_ANSI)
    assert name == "alu"
    by_name = {p[1]: p for p in ports}
    assert set(by_name) == {"a", "b", "y", "cout"}
    assert by_name["a"] == ("input", "a", "[3:0]")
    assert by_name["y"] == ("output", "y", "[7:0]")
    assert by_name["cout"][2] == ""           # scalar carries no width


def test_comment_does_not_hijack_module_name():
    src = ("// this module does cool things, see module foo\n"
           "module top(input clk, output done);\nendmodule")
    name, ports = extract_ports(src)
    assert name == "top"                       # not 'does' / 'foo'
    assert {p[1] for p in ports} == {"clk", "done"}


def test_multi_module_picks_top_not_first():
    src = ("module helper(input a, output b); endmodule\n"
           "module main(input clk, output q);\n"
           "  helper h(.a(clk), .b(q));\n"
           "endmodule")
    name, ports = extract_ports(src)
    assert name == "main"                      # the uninstantiated top
    assert {p[1] for p in ports} == {"clk", "q"}


def test_inout_port_kept_with_width():
    name, ports = extract_ports("module pad(inout [7:0] io, input oe);\nendmodule")
    by_name = {p[1]: p for p in ports}
    assert by_name["io"] == ("inout", "io", "[7:0]")


def test_no_ports_module():
    name, ports = extract_ports("module blk;\n wire x;\nendmodule")
    assert name == "blk"
    assert ports == []


def test_no_module_returns_none():
    assert extract_ports("// just a comment\n") == (None, [])


@needs_hdlparse
def test_multiline_ansi_width_via_hdlparse():
    # The shipped default design: hdlparse parses it, but the bus width lives in
    # data_type and must survive into the tuple.
    src = ("module counter (\n  input clk,\n  input rst,\n"
           "  output reg [3:0] count\n);\nendmodule")
    _, ports = extract_ports(src)
    assert ("output", "count", "[3:0]") in ports


def test_non_ansi_still_parses():
    src = ("module m(a, b, y);\n  input [3:0] a;\n  input [3:0] b;\n"
           "  output y;\nendmodule")
    name, ports = extract_ports(src)
    by_name = {p[1]: p for p in ports}
    assert name == "m"
    assert by_name["a"] == ("input", "a", "[3:0]")
    assert by_name["y"] == ("output", "y", "")


# --------------------------------------------------------------------------- #
#  generate_stub_testbench — widths, no-ports, resets
# --------------------------------------------------------------------------- #
def test_stub_declares_bus_widths():
    name, ports = extract_ports(SINGLE_LINE_ANSI)
    tb = generate_stub_testbench(name, ports)
    assert "reg [3:0] a;" in tb
    assert "wire [7:0] y;" in tb
    assert "wire cout;" in tb                  # scalar: no stray width
    assert "module tb_alu;" in tb
    assert "alu uut (" in tb
    assert '$dumpvars(0, tb_alu);' in tb


def test_stub_no_ports_emits_clean_instance():
    tb = generate_stub_testbench("blk", [])
    assert "blk uut ();" in tb                 # not 'uut (   )'
    assert "$finish;" in tb


def test_stub_active_low_reset_releases_high():
    ports = [("input", "clk", ""), ("input", "rst_n", "")]
    tb = generate_stub_testbench("c", ports)
    assert "rst_n = 0;" in tb and "#20 rst_n = 1;" in tb


def test_stub_active_high_reset_releases_low():
    ports = [("input", "clk", ""), ("input", "reset", "")]
    tb = generate_stub_testbench("c", ports)
    assert "reset = 1;" in tb and "#20 reset = 0;" in tb


def test_stub_clock_toggles():
    tb = generate_stub_testbench("c", [("input", "clk", "")])
    assert "always #5 clk = ~clk;" in tb


def test_stub_accepts_two_tuple_ports():
    # Defensive: callers passing legacy (mode, name) tuples must not crash.
    tb = generate_stub_testbench("c", [("input", "a"), ("output", "b")])
    assert "reg a;" in tb and "wire b;" in tb


# --------------------------------------------------------------------------- #
#  order_modules — dependency topology
# --------------------------------------------------------------------------- #
def test_order_parent_before_child():
    top = "module top(input c); child u0(.c(c)); endmodule"
    child = "module child(input c); endmodule"
    order = order_modules([("child.v", child), ("top.v", top)])
    assert order.index("top.v") < order.index("child.v")


def test_order_detects_parameterised_instantiation():
    top = "module top(input c); child #(.W(8)) u0(.c(c)); endmodule"
    child = "module child #(parameter W=8)(input c); endmodule"
    order = order_modules([("child.v", child), ("top.v", top)])
    assert order.index("top.v") < order.index("child.v")


def test_order_ignores_commented_instantiation():
    # 'child' only appears in a comment -> no dependency, input order kept.
    top = "module top(input c); // could use child here\n endmodule"
    child = "module child(input c); endmodule"
    order = order_modules([("top.v", top), ("child.v", child)])
    assert order == ["top.v", "child.v"]


def test_order_independent_modules_stable():
    mods = [("p.v", "module p; endmodule"),
            ("q.v", "module q; endmodule"),
            ("r.v", "module r; endmodule")]
    assert order_modules(mods) == ["p.v", "q.v", "r.v"]


def test_order_cycle_terminates_without_dropping():
    a = "module a(input x); b ib(.x(x)); endmodule"
    b = "module b(input x); a ia(.x(x)); endmodule"
    order = order_modules([("a.v", a), ("b.v", b)])
    assert sorted(order) == ["a.v", "b.v"]     # both kept, no hang


def test_order_keeps_duplicate_keys():
    order = order_modules([("d.v", "module d; endmodule"),
                           ("d.v", "module e; endmodule")])
    assert order == ["d.v", "d.v"]             # every unit returned once


# --------------------------------------------------------------------------- #
#  generate_stub_testbench — the stimulus itself
#
#  A testbench that compiles but drives nothing produces a waveform of solid X.
#  That is the single most common "the simulator is broken" report, so these
#  pin the property that actually matters: every input is driven.
# --------------------------------------------------------------------------- #
import re                                                     # noqa: E402
from maker.hdl.ports import (autodump_source, dump_file_name,     # noqa: E402
                             has_dump, has_finish,
                             is_self_contained_testbench,
                             module_parameters)
# Imported under an alias: pytest's default python_functions glob is 'test*',
# so a module-level name starting with 'test' is collected as a test.
from maker.hdl.ports import testbench_matches as tb_matches       # noqa: E402

COMB = """\
module and_gate(input wire a, input wire b, output wire y);
  assign y = a & b;
endmodule
"""

SEQ = """\
module counter(input i_clk, input rst_n, input [7:0] seed, output reg [7:0] q);
  always @(posedge i_clk or negedge rst_n)
    if (!rst_n) q <= seed; else q <= q + 1;
endmodule
"""


def _tb_for(code):
    name, ports = extract_ports(code)
    return generate_stub_testbench(name, ports, design_code=code)


def test_every_input_is_assigned_not_just_declared():
    tb = _tb_for(COMB)
    for sig in ('a', 'b'):
        assert f"reg {sig};" in tb                     # declared ...
        assert re.search(rf'\b{sig}\s*=', tb)          # ... and driven


def test_small_combinational_space_is_swept_exhaustively():
    tb = _tb_for(COMB)
    assert "for (esim_i = 0; esim_i < 4;" in tb        # 2 inputs -> 4 vectors
    assert "{a, b} = esim_i;" in tb
    assert "integer esim_i;" in tb


def test_wide_combinational_space_falls_back_to_random():
    code = ("module wide(input [15:0] a, input [15:0] b, output [15:0] y);\n"
            "  assign y = a + b;\nendmodule\n")
    tb = _tb_for(code)
    assert "$random" in tb
    assert "esim_i < 65536" not in tb                  # never sweep 2**32
    assert "{16{1'b1}}" in tb                          # all-ones corner case


def test_clock_is_found_by_usage_when_the_name_is_unfamiliar():
    # 'i_clk' is not in any name whitelist; the posedge in the design is what
    # identifies it. Missing this leaves a clocked design frozen at X.
    tb = _tb_for(SEQ)
    assert "always #5 i_clk = ~i_clk;" in tb


def test_active_low_reset_is_released_high():
    tb = _tb_for(SEQ)
    assert "rst_n = 0;" in tb and "#20 rst_n = 1;" in tb


def test_clocked_stimulus_is_applied_off_the_active_edge():
    tb = _tb_for(SEQ)
    assert "@(negedge i_clk);" in tb                   # no race with posedge
    assert "seed = $random;" in tb or "seed = esim_i;" in tb


def test_enable_like_inputs_are_held_asserted():
    code = ("module core(input clk, input enable, input [3:0] d,"
            " output reg [3:0] q);\n"
            "  always @(posedge clk) if (enable) q <= d;\nendmodule\n")
    tb = _tb_for(code)
    assert "enable = 1;" in tb          # random-toggling leaves the core idle


def test_parameterised_port_widths_bring_their_parameters_along():
    # 'output reg [Bits-1:0] r' is meaningless in a testbench that has never
    # heard of Bits: iverilog fails with "Unable to bind parameter".
    code = ("module adc(clk, r);\n  parameter Bits = 6;\n"
            "  input clk;\n  output reg [Bits - 1 : 0] r;\nendmodule\n")
    tb = _tb_for(code)
    assert "localparam Bits = 6;" in tb
    assert "wire [Bits - 1 : 0] r;" in tb


def test_unrelated_parameters_are_not_copied_into_the_testbench():
    code = ("module m(input clk, output [W-1:0] o);\n"
            "  parameter W = 4;\n  parameter UNUSED = 99;\n"
            "  assign o = 0;\nendmodule\n")
    tb = _tb_for(code)
    assert "localparam W = 4;" in tb
    assert "UNUSED" not in tb


def test_module_parameters_reads_header_and_body():
    code = ("module m #(parameter A = 1, B = 2) (input x);\n"
            "  localparam [1:0] C = 2'b01;\nendmodule\n")
    names = [n for _r, n, _e in module_parameters(code, "m")]
    assert names == ["A", "B", "C"]


def test_generated_testbench_always_dumps_and_finishes():
    for code in (COMB, SEQ):
        tb = _tb_for(code)
        assert '$dumpfile("sim_out.vcd");' in tb
        assert "$dumpvars(0, tb_" in tb
        assert "$finish;" in tb


# --------------------------------------------------------------------------- #
#  Inspecting a testbench the user brought with them
# --------------------------------------------------------------------------- #

def test_dump_file_name_is_read_from_the_testbench():
    assert dump_file_name('initial $dumpfile("wave.vcd");') == "wave.vcd"
    assert dump_file_name('// $dumpfile("commented.vcd")') is None
    assert dump_file_name("module tb; endmodule") is None


def test_dump_and_finish_detection_ignores_comments():
    assert has_dump("initial $dumpvars(0, tb);")
    assert not has_dump("// $dumpvars(0, tb);")
    assert has_finish("initial #10 $finish;")
    assert has_finish("initial #10 $stop;")
    assert not has_finish("/* $finish; */")


def test_autodump_module_dumps_everything_and_can_guard():
    src = autodump_source("wave.vcd", guard_ns=1000)
    assert '$dumpfile("wave.vcd");' in src
    assert "$dumpvars;" in src          # no arguments: every scope
    assert "#1000;" in src and "$finish;" in src
    assert "$finish" not in autodump_source("wave.vcd")


def test_testbench_matches_only_when_it_instantiates_the_design():
    design = {"counter"}
    assert tb_matches("module tb; counter uut(.a(a)); endmodule", design)
    assert not tb_matches("module tb; other uut(.a(a)); endmodule", design)
    assert not tb_matches("", design)
    assert not tb_matches("// counter uut (", design)


def test_self_contained_testbench_is_recognised():
    assert is_self_contained_testbench(
        "module top;\n  initial begin #10 $finish; end\nendmodule")
    # A design with ports is not one, even if it has an initial block.
    assert not is_self_contained_testbench(
        "module m(input a);\n  initial $display(\"hi\");\nendmodule")
    assert not is_self_contained_testbench("module m; endmodule")
