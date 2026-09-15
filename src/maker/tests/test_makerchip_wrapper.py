"""Makerchip wrappers must compile into a useful, deterministic simulation."""

from maker.Maker import build_makerchip_wrapper
from maker.hdl.ports import extract_ports


def _wrap(source, lint_codes=("UNUSED\n", "\n", "   ")):
    module, ports = extract_ports(source)
    return build_makerchip_wrapper(source, module, ports, lint_codes)


def test_gate_wrapper_filters_blank_lints_and_exercises_truth_table():
    source = ("module nand_gate(input a, input b, output y);\n"
              "  assign y = ~(a & b);\n"
              "endmodule\n")
    wrapper = _wrap(source)

    assert "/* verilator lint_off UNUSED */" in wrapper
    assert "/* verilator lint_off */" not in wrapper
    assert "logic a;  // input" in wrapper
    assert "logic b;  // input" in wrapper
    assert "logic y;  // output" in wrapper
    assert "assign a = cyc_cnt[0];" in wrapper
    assert "assign b = cyc_cnt[1];" in wrapper
    assert "nand_gate dut(.a(a), .b(b), .y(y));" in wrapper


def test_counter_wrapper_maps_clock_reset_and_vector_input():
    source = """module counter(
  input wire clock,
  input wire rst_n,
  input wire [7:0] load,
  output reg [7:0] count
);
endmodule
"""
    wrapper = _wrap(source)

    assert "logic clock;  // input" in wrapper
    assert "logic rst_n;  // input" in wrapper
    assert "logic [7:0] load;  // input" in wrapper
    assert "logic [7:0] count;  // output" in wrapper
    assert "assign clock = clk;" in wrapper
    assert "assign rst_n = ~reset;" in wrapper
    assert "assign load = cyc_cnt;" in wrapper


def test_dut_passed_and_failed_ports_do_not_collide_with_testbench():
    source = ("module checks(input passed, output failed);\n"
              "endmodule\n")
    wrapper = _wrap(source)

    assert "logic dut_passed;  // input" in wrapper
    assert "logic dut_failed;  // output" in wrapper
    assert "checks dut(.passed(dut_passed), .failed(dut_failed));" in wrapper
    assert "assign passed = cyc_cnt > 32'd20;" in wrapper
    assert "assign failed = 1'b0;" in wrapper
