"""d_cosim build-step guards: `timescale precision and multi-file resolution.

Both are silent failures at simulation time, not build time:

* ivlng advances VVP by ``(spice_time - vvp_time) / precision`` ticks and
  truncates, so a source declaring a precision coarser than one SPICE step
  never advances at all -- ngspice reports success and every output reads 0;
* dependency sources added through "Add dependency files/folder" land beside
  the top source but were never handed to iverilog, so any design with a
  submodule in another file died on "Unknown module type".

No iverilog needed: run_iverilog is stubbed so the tests assert on the command
eSim builds and on the source text it hands over.
"""
import importlib
import os

import pytest
from PyQt6 import QtWidgets

from maker import CosimConfig, ModelGeneration
from maker.ModelGeneration import normalise_timescale


# --------------------------------------------------------------------------- #
# normalise_timescale (pure)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("declared, expected, flagged", [
    # already fine enough -- untouched
    ("`timescale 1ns / 1ps", "`timescale 1ns / 1ps", []),
    ("`timescale 100ps / 10fs", "`timescale 100ps / 10fs", []),
    ("`timescale 1s/1fs", "`timescale 1s/1fs", []),
    # too coarse -- only the precision field moves
    ("`timescale 1ms / 1ms", "`timescale 1ms / 1ps", ["1ms/1ms"]),
    ("`timescale 1ns/1ns", "`timescale 1ns/1ps", ["1ns/1ns"]),
    ("`timescale 10us / 100ns", "`timescale 10us / 1ps", ["10us/100ns"]),
])
def test_precision_is_sharpened_and_the_unit_is_not(declared, expected,
                                                    flagged):
    text, coarse = normalise_timescale(declared + "\nmodule m; endmodule\n")
    assert text.splitlines()[0] == expected
    assert coarse == flagged


def test_source_without_a_directive_is_returned_unchanged():
    src = "module m; endmodule\n"
    assert normalise_timescale(src) == (src, [])


def test_every_directive_in_a_file_is_normalised():
    text, coarse = normalise_timescale(
        "`timescale 1us/1us\nmodule a; endmodule\n"
        "`timescale 1ns/1ps\nmodule b; endmodule\n"
        "`timescale 1ms/1ms\nmodule c; endmodule\n")
    assert text.count("1ps") == 3
    assert coarse == ["1us/1us", "1ms/1ms"]


# --------------------------------------------------------------------------- #
# build_cosim: what actually reaches iverilog
# --------------------------------------------------------------------------- #
class _Recorded:
    """Stands in for icarus.run_iverilog, capturing its arguments."""

    def __init__(self):
        self.calls = []

    def __call__(self, iverilog, srcs, out, **kwargs):
        self.calls.append({"srcs": list(srcs), "out": out, **kwargs})
        self.source_text = open(srcs[0]).read()
        with open(out, "w") as fh:            # a plausible vvp artifact
            fh.write("#! /usr/bin/vvp\n")
        return ModelGeneration.icarus.CompileResult(
            ok=True, returncode=0, stdout="", stderr="", out_path=out)


@pytest.fixture
def cosim(qapp, tmp_path, monkeypatch):
    """A ModelGeneration ready for build_cosim, with iverilog stubbed out."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)
    monkeypatch.setattr(CosimConfig, "iverilog_binary", lambda: "iverilog")
    monkeypatch.setattr(CosimConfig, "has_iverilog", lambda: True)

    model = ModelGeneration.ModelGeneration(
        str(tmp_path / "counter.v"), QtWidgets.QTextEdit())
    model.modelpath = str(tmp_path / "counter") + "/"
    os.makedirs(model.modelpath, exist_ok=True)
    monkeypatch.setattr(model, "_tool_version", lambda _b: "stub")

    recorded = _Recorded()
    monkeypatch.setattr(ModelGeneration.icarus, "run_iverilog", recorded)
    return model, recorded


def write_source(model, text):
    path = os.path.abspath(os.path.join(model.modelpath, "counter.v"))
    with open(path, "w") as fh:
        fh.write(text)
    return path


def test_dependency_directory_is_on_the_library_search_path(cosim):
    model, recorded = cosim
    write_source(model, "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    assert model.build_cosim() != "Error"

    flags = recorded.calls[0]["extra_flags"]
    libdir = os.path.abspath(model.modelpath)
    assert flags[flags.index("-y") + 1] == libdir      # sibling modules
    assert flags[flags.index("-I") + 1] == libdir      # `include files
    assert flags[flags.index("-Y") + 1] == ".sv"       # SystemVerilog members


def test_a_good_timescale_is_compiled_from_the_users_own_file(cosim):
    model, recorded = cosim
    src = write_source(model,
                       "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    assert model.build_cosim() != "Error"
    assert recorded.calls[0]["srcs"] == [src]         # no temp copy


def test_a_coarse_timescale_is_sharpened_before_compiling(cosim):
    model, recorded = cosim
    src = write_source(model,
                       "`timescale 1ms/1ms\nmodule counter; endmodule\n")
    assert model.build_cosim() != "Error"

    assert recorded.calls[0]["srcs"] != [src]         # compiled from a copy
    assert "`timescale 1ms/1ps" in recorded.source_text
    assert open(src).read().startswith("`timescale 1ms/1ms")   # user's intact
    assert "Sharpened" in model.clog.termedit.toPlainText()


def test_a_missing_timescale_is_still_injected(cosim):
    model, recorded = cosim
    write_source(model, "module counter; endmodule\n")
    assert model.build_cosim() != "Error"
    assert recorded.source_text.startswith("`timescale 1ns/1ps")


def test_the_temporary_copy_does_not_survive_the_build(cosim):
    model, recorded = cosim
    write_source(model, "`timescale 1ms/1ms\nmodule counter; endmodule\n")
    assert model.build_cosim() != "Error"
    assert not os.path.exists(recorded.calls[0]["srcs"][0])


# --------------------------------------------------------------------------- #
# inout: refused, not warned about
# --------------------------------------------------------------------------- #
def write_ports(model, lines):
    path = os.path.join(model.modelpath, "connection_info.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def test_an_inout_port_is_refused_before_the_compiler_runs(cosim):
    """eSim's parser files inout under the inputs, so the netlist declares a
    plain d_in and d_cosim's d_inout group stays empty. ngspice then reports
    "mismatched ... input counts: 2/1" and carries on with the port indices
    shifted: measured on a probe module, the inout never left the simulation
    AND a sibling output declared `assign q = 1'b1;` toggled with the clock.
    Every port is wrong, so a warning is not enough."""
    model, recorded = cosim
    write_source(model, "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    write_ports(model, ["clk input 1", "bus inout 2", "q output 1"])

    assert model.build_cosim() == "Error"
    assert recorded.calls == []                  # never reached iverilog
    log = model.clog.termedit.toPlainText()
    assert "REFUSED" in log and "bus" in log


def test_a_port_merely_named_inout_is_not_refused(cosim):
    """The direction is a field, not a substring: `inout_en` is an input."""
    model, recorded = cosim
    write_source(model, "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    write_ports(model, ["inout_en input 1", "q output 1"])

    assert model.build_cosim() != "Error"
    assert len(recorded.calls) == 1


def test_a_module_with_no_port_file_still_builds(cosim):
    """connection_info.txt is written by verilogParse; a build driven without
    it must not be blocked by the inout gate."""
    model, recorded = cosim
    write_source(model, "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    assert model.build_cosim() != "Error"
    assert recorded.calls[0]["srcs"] == [
        os.path.abspath(os.path.join(model.modelpath, "counter.v"))]


# --------------------------------------------------------------------------- #
# The x-as-1 wrapper
#
# adc_bridge emits x between in_low and in_high, Icarus counts 0->x and x->1 as
# two posedges, and the design is clocked twice per analog edge. NgVeri never
# sees it, because its generated C reads anything that is not a definite 0 as a
# 1. The wrapper makes d_cosim do the same, so the netlist can stay exactly as
# eSim 2.5 wrote it. See docs/NGVERI_ACCURACY.md D1.
# --------------------------------------------------------------------------- #
def test_the_design_is_compiled_behind_a_generated_wrapper(cosim):
    model, recorded = cosim
    src = write_source(model,
                       "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    write_ports(model, ["clk input 1", "q output 1"])
    assert model.build_cosim() != "Error"

    srcs = recorded.calls[0]["srcs"]
    # Wrapper first: it must be the root module VVP reports, and iverilog
    # roots whatever nothing instantiates.
    assert os.path.basename(srcs[0]) == \
        ModelGeneration.COSIM_TOP_MODULE + ".v"
    assert srcs[1] == src


def test_the_wrapper_reads_x_as_one_per_bit(cosim):
    model, recorded = cosim
    write_source(model, "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    write_ports(model, ["clk input 1", "data input 8", "q output 4"])
    assert model.build_cosim() != "Error"

    text = recorded.source_text
    # === (case equality), so the comparison itself cannot return x, and one
    # assign per BIT, because each bit carries its own state -- a vector-wide
    # == would poison the whole port.
    assert "=== 1'b0) ? 1'b0 : 1'b1" in text
    assert "gi < 9" in text          # clk + data[8], every input bit
    # Outputs are passed straight through: nothing on the way out is x.
    assert ".q(esim_d_out[3:0])" in text


def test_the_wrapper_has_exactly_one_port_per_direction(cosim):
    """ivlng discovers ports by walking vpi_iterate(vpiPort, top) and gives
    each a running bit offset, so which node reaches which port depends on the
    order VVP reports them in -- which is not declaration order, and was seen
    to change between compiles of the same source. One vector per direction
    leaves a single port at offset 0 and pure arithmetic after it."""
    model, recorded = cosim
    write_source(model, "`timescale 1ns/1ps\nmodule counter; endmodule\n")
    write_ports(model, ["clk input 1", "rst input 1", "q output 1"])
    assert model.build_cosim() != "Error"

    text = recorded.source_text
    assert "module %s (%s, %s);" % (
        ModelGeneration.COSIM_TOP_MODULE,
        ModelGeneration.IN_PORT, ModelGeneration.OUT_PORT) in text
    assert text.count("input  [") == 1
    assert text.count("output [") == 1
    # Node j of a group is bit (width - 1 - j): big-endian, icarus_shim.c:97.
    assert ".clk(esim_d_in_lv[1])" in text
    assert ".rst(esim_d_in_lv[0])" in text


def test_the_wrapper_carries_the_designs_own_timescale(cosim):
    """ivlng derives its tick length from the simulation's global time unit,
    so a wrapper with a different timescale could change how fast the design
    advances -- the D3 failure, reintroduced by the D1 fix."""
    model, recorded = cosim
    write_source(model, "`timescale 1us/1ps\nmodule counter; endmodule\n")
    write_ports(model, ["clk input 1", "q output 1"])
    assert model.build_cosim() != "Error"

    assert recorded.source_text.startswith("`timescale 1us/1ps")


def test_a_sharpened_timescale_reaches_the_wrapper_too(cosim):
    model, recorded = cosim
    write_source(model, "`timescale 1ms/1ms\nmodule counter; endmodule\n")
    write_ports(model, ["clk input 1", "q output 1"])
    assert model.build_cosim() != "Error"

    assert recorded.source_text.startswith("`timescale 1ms/1ps")


# --------------------------------------------------------------------------- #
# cosim_wrapper_source in isolation
# --------------------------------------------------------------------------- #
def test_nodes_map_to_bits_big_endian_in_netlist_order():
    """The netlist lists the d_in nodes then the d_out nodes, each group in
    port-declaration order, and node j of a group is bit (width - 1 - j)."""
    text = ModelGeneration.cosim_wrapper_source(
        [("m", "m", [("q", "output", 1), ("clk", "input", 1),
                     ("d", "input", 4), ("r", "output", 2)])])
    assert "input  [4:0] esim_d_in;" in text     # clk + d[4]
    assert "output [2:0] esim_d_out;" in text    # q + r[2]
    assert ".clk(esim_d_in_lv[4])" in text       # first input node -> top bit
    assert ".d(esim_d_in_lv[3:0])" in text
    assert ".q(esim_d_out[2])" in text           # first output node -> top bit
    assert ".r(esim_d_out[1:0])" in text


def test_several_blocks_take_disjoint_slices():
    """Two placements of one block get their own bits, in schematic order."""
    ports = [("clk", "input", 1), ("q", "output", 1)]
    blocks = [("a1", "counter", ports), ("a2", "counter", ports)]
    text = ModelGeneration.cosim_wrapper_source(blocks)

    assert "counter u_a1 (" in text and "counter u_a2 (" in text
    assert ".clk(esim_d_in_lv[1])" in text and ".q(esim_d_out[1])" in text
    assert ".clk(esim_d_in_lv[0])" in text and ".q(esim_d_out[0])" in text
    assert ModelGeneration.port_widths(blocks) == (2, 2)


def test_connection_info_lines_that_are_not_ports_are_skipped():
    assert ModelGeneration.parse_connection_info(
        "\n\tclk   input   1\ngarbage\n\tq  output  x\n\tz input 0\n") == \
        [("clk", "input", 1)]
