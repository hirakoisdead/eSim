"""Tests for Qt-free port extraction + testbench stub (maker.hdl.ports)."""
import importlib.util

import pytest

from maker.hdl.ports import extract_ports, generate_stub_testbench

# Accurate port typing/mode parsing needs hdlparse (eSim's runtime dep). Without
# it extract_ports falls back to a loose regex, so port-level assertions are
# gated on hdlparse being importable; module-name detection works either way.
_HAS_HDLPARSE = importlib.util.find_spec("hdlparse") is not None
needs_hdlparse = pytest.mark.skipif(
    not _HAS_HDLPARSE, reason="hdlparse not installed (regex fallback active)")


COUNTER = """\
module counter (
    input clk,
    input rst,
    output reg [3:0] count
);
endmodule
"""


def test_extract_ports_module_name_always_detected():
    # Module-name regex is independent of hdlparse.
    name, _ = extract_ports(COUNTER)
    assert name == 'counter'


@needs_hdlparse
def test_extract_ports_names_and_modes():
    _, ports = extract_ports(COUNTER)
    port_names = {p[1] for p in ports}
    assert {'clk', 'rst', 'count'} <= port_names
    modes = {p[0] for p in ports}
    assert 'input' in modes and 'output' in modes


def test_extract_ports_no_module():
    assert extract_ports("// just a comment\n") == (None, [])


def test_generate_stub_wires_vcd_and_clock():
    name, ports = extract_ports(COUNTER)
    tb = generate_stub_testbench(name, ports)
    # These are independent of accurate port parsing.
    assert 'module tb_counter;' in tb
    assert 'counter uut (' in tb
    assert '$dumpfile("sim_out.vcd");' in tb
    assert '$dumpvars(0, tb_counter);' in tb
    # clk is the first port and is detected by the regex fallback too.
    assert 'always #5 clk = ~clk;' in tb


@needs_hdlparse
def test_generate_stub_reset_stimulus():
    name, ports = extract_ports(COUNTER)
    tb = generate_stub_testbench(name, ports)
    assert 'rst = 1;' in tb
