"""End-to-end gate for the d_cosim backend: compile, simulate, decode.

The failure mode this whole area is being hardened against is *a model that
builds and runs and is wrong*, which no unit test over the generators can
catch. This one drives the real chain -- iverilog -> vvp-format artifact ->
ngspice + ivlng -> `print allv` -- and decodes the counter's output bus back
into integers, so a regression shows up as the wrong number rather than as a
plausible-looking waveform.

Skipped unless the machine has both Icarus (with libvvp) and an ngspice build
carrying the ivlng adapter, so it is a no-op on a bare CI box.
"""
import os
import re
import subprocess

import pytest

from maker import CosimConfig
from maker.hdl import icarus
from maker.ModelGeneration import COSIM_TOP_MODULE, cosim_wrapper_source
from kicadtoNgspice.KicadtoNgspice import collapse_adc_band_for_hdl

# Resolved once, at import, and used for both the skip decision and the runs.
# CosimConfig reads ~/.nghdl/config.ini, and the suite's fixtures redirect HOME
# to a tmp dir -- resolving inside a test would silently fall back to a bare
# "ngspice" that is not on PATH, so the skip guard would pass and the run would
# then die on WinError 2.
NGSPICE = CosimConfig.ngspice_binary()
IVERILOG = CosimConfig.iverilog_binary()
CODEMODELS = CosimConfig.ngspice_codemodel_dir()
LOADER = CosimConfig.loader_path_var()
LOADER_DIRS = [d for d in (os.path.dirname(NGSPICE or ""),
                           CosimConfig.iverilog_libdir(),
                           os.path.dirname(CosimConfig.vvp_binary() or ""))
               if d and os.path.isdir(d)]


def _toolchain_present():
    """Every binary and adapter this test shells out to, actually on disk.

    has_dcosim() answers "is this install configured for d_cosim", which a
    source checkout can satisfy by pointing at a tools/ tree that was never
    built. Only files that exist can be run."""
    return bool(
        CosimConfig.has_dcosim(force=True)
        and os.path.isfile(NGSPICE or "")
        and os.path.isfile(IVERILOG or "")
        and CODEMODELS
        and os.path.isfile(os.path.join(CODEMODELS, "ivlng.vpi")))


pytestmark = pytest.mark.skipif(
    not _toolchain_present(),
    reason="needs iverilog with libvvp and an ngspice carrying ivlng")


# A 4-bit up counter with a one-clock wrap strobe: the strobe is the witness.
# A model whose outputs are naturally static cannot tell a frozen pin from a
# working one, which is why the counter is the test vehicle.
COUNTER_V = """\
`timescale 1ns / 1ps
module dccount (
    input clk,
    input rst,
    output [3:0] cnt,
    output wrap
);
    reg [3:0] cnt_reg;
    reg       wrap_reg;

    always @(posedge clk) begin
        wrap_reg <= 1'b0;
        if (rst) begin
            cnt_reg <= 4'd0;
        end else begin
            cnt_reg <= cnt_reg + 4'd1;
            if (cnt_reg == 4'd15)
                wrap_reg <= 1'b1;
        end
    end

    assign cnt  = cnt_reg;
    assign wrap = wrap_reg;
endmodule
"""

# 1 ms clock with a 1 us ramp -- the ramp is the point: it is what walks the
# adc_bridge through its unknown band. Reset clears at 1.9-2.0 ms, so the
# first counted edge is at 3 ms.
NETLIST = """\
* d_cosim end-to-end
v1 clk_a gnd pulse(0 5 0 1u 1u 0.5m 1m)
v2 rst_a gnd pwl(0 5 1.9m 5 2m 0)
a1 [clk_a rst_a] [clk_d rst_d] u1
a2 [clk_d rst_d] [c3_d c2_d c1_d c0_d w_d] u2
a3 [c3_d c2_d c1_d c0_d w_d] [c3 c2 c1 c0 w] u3
.model u1 adc_bridge(in_low=1.0 in_high=2.0 rise_delay=1.0e-9 \
fall_delay=1.0e-9 )
.model u2 d_cosim simulation="ivlng" lib_args=["libvvp", "ivlng"] \
sim_args=["dccount"]
.model u3 dac_bridge(out_low=0.0 out_high=5.0 out_undef=0.5 t_rise=1.0e-9 \
t_fall=1.0e-9 )
.control
set width=1000
tran 10e-06 20e-03 0e-00
print allv > OUTFILE
.endc
.end
"""


def read_columns(path):
    """``(names, rows)`` from an ngspice ``print allv`` dump."""
    names, rows = None, []
    with open(path, errors="replace") as fh:
        for line in fh:
            token = line.strip()
            if token.startswith("Index"):
                names = token.split()[1:]
                continue
            if names is None or not re.match(r"^\d+\s", token):
                continue
            values = token.split()[1:len(names) + 1]
            if len(values) == len(names):
                rows.append([float(v) for v in values])
    assert names, "no data block in " + path
    return names, rows


def sample(names, rows, when, signals):
    """The last sample at or before ``when``, decoded MSB-first as digital."""
    index = {n: i for i, n in enumerate(names)}
    latest = None
    for row in rows:
        if row[index["time"]] > when:
            break
        latest = row
    value = 0
    for name in signals:
        value = (value << 1) | (1 if latest[index[name]] > 2.5 else 0)
    return value


def run_ngspice(tmp_path, netlist_lines, tag):
    """Run ``netlist_lines`` under the d_cosim ngspice.

    Returns ``(dump_path, console)``. Split out of :func:`simulate` because
    some checks are on what ngspice *said*, not on the numbers it produced --
    a co-simulator whose time base has drifted still emits data, it just warns
    while doing it.
    """
    out = tmp_path / (tag + ".txt")
    cir = tmp_path / (tag + ".cir")
    cir.write_text("\n".join(netlist_lines).replace("OUTFILE", out.name))

    # ivlng resolves both the vvp and its VPI module relative to the working
    # directory, which is why the converter stages them beside the netlist.
    with open(os.path.join(CODEMODELS, "ivlng.vpi"), "rb") as fh:
        (tmp_path / "ivlng.vpi").write_bytes(fh.read())

    # libvvp and ngspice's own runtime DLLs are found through the loader path,
    # exactly as the eSim launcher sets it up.
    env = dict(os.environ)
    env[LOADER] = os.pathsep.join(LOADER_DIRS + [env.get(LOADER, "")])

    res = subprocess.run([NGSPICE, "-b", str(cir)],
                         cwd=str(tmp_path), env=env, capture_output=True,
                         text=True, timeout=300)
    assert out.is_file(), "ngspice produced no output for " + tag
    return out, (res.stdout or "") + (res.stderr or "")


def simulate(tmp_path, netlist_lines, tag):
    """Run ``netlist_lines`` under the d_cosim ngspice; return its dump."""
    out, _console = run_ngspice(tmp_path, netlist_lines, tag)
    return read_columns(str(out))


@pytest.fixture(scope="module")
def counter_vvp(tmp_path_factory):
    """The design compiled bare, exactly as d_cosim did before the wrapper.

    Kept so the defect itself stays reproducible: this is the artifact that
    double-clocks."""
    workdir = tmp_path_factory.mktemp("dccount")
    (workdir / "dccount.v").write_text(COUNTER_V)
    res = icarus.run_iverilog(
        IVERILOG, ["dccount.v"],
        str(workdir / "dccount"), cwd=str(workdir), timeout=300)
    assert res.ok, res.output
    return workdir / "dccount"


@pytest.fixture(scope="module")
def wrapped_vvp(tmp_path_factory):
    """The design compiled the way build_cosim does it now: behind the
    generated wrapper that reads x as logic 1."""
    workdir = tmp_path_factory.mktemp("dcwrap")
    (workdir / "dccount.v").write_text(COUNTER_V)
    ports = [("clk", "input", 1), ("rst", "input", 1),
             ("cnt", "output", 4), ("wrap", "output", 1)]
    (workdir / (COSIM_TOP_MODULE + ".v")).write_text(
        cosim_wrapper_source([("dccount", "dccount", ports)],
                             "`timescale 1ns / 1ps"))
    res = icarus.run_iverilog(
        IVERILOG, [COSIM_TOP_MODULE + ".v", "dccount.v"],
        str(workdir / "dccount"), cwd=str(workdir), timeout=300)
    assert res.ok, res.output
    return workdir / "dccount"


def stage(tmp_path, counter_vvp, lines):
    (tmp_path / "dccount").write_bytes(counter_vvp.read_bytes())
    return lines


BITS = ["c3", "c2", "c1", "c0"]

#: Reset clears between 1.9 and 2.0 ms, so the clock at 2 ms is the first one
#: counted; sample 50 us after each rise, well clear of the 1 us ramp.
def counts(names, rows, n):
    return [sample(names, rows, 2.05e-3 + k * 1e-3, BITS) for k in range(n)]


def test_unwrapped_design_double_clocks_the_design(tmp_path, counter_vvp):
    """The defect itself, pinned: compiled bare, with adc_bridge's stock
    1.0/2.0 band, the counter advances two per clock, because the x between the
    thresholds reaches Icarus as a second posedge."""
    lines = stage(tmp_path, counter_vvp, NETLIST.splitlines())
    names, rows = simulate(tmp_path, lines, "raw")
    assert counts(names, rows, 7) == [2, 4, 6, 8, 10, 12, 14]


def test_wrapper_advances_once_per_clock_on_the_2_5_netlist(
        tmp_path, wrapped_vvp):
    """The fix that ships: the netlist still says in_low=1.0 in_high=2.0,
    exactly as eSim 2.5 wrote it, and the design counts once per clock because
    the wrapper reads the x as 1 the way NgVeri does."""
    lines = stage(tmp_path, wrapped_vvp, NETLIST.splitlines())
    assert any("in_low=1.0 in_high=2.0" in ln for ln in lines)

    names, rows = simulate(tmp_path, lines, "wrapped")
    assert counts(names, rows, 9) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_collapsed_band_advances_once_per_clock(tmp_path, counter_vvp):
    """Evidence for the PARKED netlist-level fix (UPSTREAM_DECISIONS item 1).

    It is not wired into the converter, but it works, and the maintainers
    should be able to see that it works without rebuilding the investigation.
    Note this uses the BARE vvp: the two fixes are independent cures for the
    same defect, and either one alone is sufficient."""
    lines, collapsed = collapse_adc_band_for_hdl(
        stage(tmp_path, counter_vvp, NETLIST.splitlines()))
    assert [c[0] for c in collapsed] == ["u1"]

    names, rows = simulate(tmp_path, lines, "fixed")
    assert counts(names, rows, 9) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_one_clock_strobe_is_one_clock_wide(tmp_path, wrapped_vvp):
    """The wrap strobe is the signal a frozen or double-clocked model gets
    wrong while the datapath still looks plausible."""
    lines = stage(tmp_path, wrapped_vvp, NETLIST.splitlines())
    names, rows = simulate(tmp_path, lines, "strobe")

    index = {n: i for i, n in enumerate(names)}
    edges, previous = [], 0
    for row in rows:
        level = 1 if row[index["w"]] > 2.5 else 0
        if level != previous:
            edges.append(row[index["time"]])
            previous = level

    assert len(edges) == 2, "expected exactly one strobe, got %d edges" % len(
        edges)
    assert edges[1] - edges[0] == pytest.approx(1e-3, abs=5e-6)


# --------------------------------------------------------------------------- #
# Several blocks in one schematic
#
# Icarus's engine is process-global and single-shot, so a second d_cosim device
# segfaults ngspice. The converter merges every block into one device running a
# generated wrapper that instantiates all of them, which lifts the limit to any
# number of blocks. This is the end-to-end proof: two DIFFERENT models, placed
# three times between them, counting independently in one simulation.
# --------------------------------------------------------------------------- #
TOGGLE_V = """\
`timescale 1ns / 1ps
module dctog (
    input clk,
    input rst,
    output [1:0] q
);
    reg [1:0] q_reg;
    always @(posedge clk) begin
        if (rst)
            q_reg <= 2'd0;
        else
            q_reg <= q_reg + 2'd1;
    end
    assign q = q_reg;
endmodule
"""

# Two counters and one toggler off one clock. The second counter is held in
# reset a further 3 ms, so a merge that crossed the blocks' nodes -- or gave
# them the same nodes -- shows up as two identical columns.
MULTI_NETLIST = """\
* d_cosim, three blocks
v1 clk_a gnd pulse(0 5 0 1u 1u 0.5m 1m)
v2 rst_a gnd pwl(0 5 1.9m 5 2m 0)
v3 rstb_a gnd pwl(0 5 4.9m 5 5m 0)
a1 [clk_a rst_a rstb_a] [clk_d rst_d rstb_d] u1
a2 [clk_d rst_d] [c3_d c2_d c1_d c0_d w_d] u2
a4 [clk_d rstb_d] [d3_d d2_d d1_d d0_d x_d] u2
a5 [clk_d rst_d] [t1_d t0_d] u4
a3 [c3_d c2_d c1_d c0_d w_d d3_d d2_d d1_d d0_d x_d t1_d t0_d] \
[c3 c2 c1 c0 w d3 d2 d1 d0 x t1 t0] u3
.model u1 adc_bridge(in_low=1.0 in_high=2.0 rise_delay=1.0e-9 \
fall_delay=1.0e-9 )
.model u2 d_cosim simulation="ivlng" lib_args=["libvvp", "ivlng"] \
sim_args=["dccount"]
.model u4 d_cosim simulation="ivlng" lib_args=["libvvp", "ivlng"] \
sim_args=["dctog"]
.model u3 dac_bridge(out_low=0.0 out_high=5.0 out_undef=0.5 t_rise=1.0e-9 \
t_fall=1.0e-9 )
.control
set width=1000
tran 10e-06 20e-03 0e-00
print allv > OUTFILE
.endc
.end
"""


@pytest.fixture
def model_library(tmp_path, monkeypatch):
    """A digital-model library holding both designs, laid out the way
    build_cosim leaves it: <root>/NgVeriCosim/<model>/{<model>.v,
    connection_info}. The d_cosim tree is a SIBLING of the legacy Ngveri tree,
    never inside it -- see CosimConfig.cosim_build_root."""
    root = tmp_path / "lib"
    sources = {
        "dccount": (COUNTER_V, ["clk input 1", "rst input 1",
                                "cnt output 4", "wrap output 1"]),
        "dctog": (TOGGLE_V, ["clk input 1", "rst input 1", "q output 2"]),
    }
    for name, (text, ports) in sources.items():
        folder = root / "NgVeriCosim" / name
        folder.mkdir(parents=True)
        (folder / (name + ".v")).write_text(text)
        (folder / "connection_info.txt").write_text("\n".join(ports) + "\n")
    monkeypatch.setattr(CosimConfig, "digital_model_root", lambda: str(root))
    return root


def test_three_blocks_of_two_models_run_in_one_simulation(
        tmp_path, model_library):
    from kicadtoNgspice.KicadtoNgspice import merge_dcosim_blocks

    lines = merge_dcosim_blocks(MULTI_NETLIST.splitlines(), str(tmp_path))

    # One device, one engine: the whole point.
    assert sum(1 for ln in lines
               if ln.strip().startswith(".model") and "d_cosim" in ln) == 1
    assert sum(1 for ln in lines
               if ln.strip().startswith("a_esim_cosim")) == 1
    assert (tmp_path / "esim_cosim_merged").is_file()

    names, rows = simulate(tmp_path, lines, "multi")

    # Counter A is released at 2 ms and counts from the 2 ms clock.
    assert [sample(names, rows, 2.05e-3 + k * 1e-3, BITS) for k in range(6)] \
        == [1, 2, 3, 4, 5, 6]
    # Counter B is the same model, placed again, released 3 ms later -- so it
    # must be 3 behind, not identical and not double-counting.
    b_bits = ["d3", "d2", "d1", "d0"]
    assert [sample(names, rows, 5.05e-3 + k * 1e-3, b_bits) for k in range(6)] \
        == [1, 2, 3, 4, 5, 6]
    assert sample(names, rows, 5.05e-3, BITS) == 4      # A is ahead of B
    # And the other model, on its own 2 bits, wrapping every 4 clocks.
    t_bits = ["t1", "t0"]
    assert [sample(names, rows, 2.05e-3 + k * 1e-3, t_bits) for k in range(6)] \
        == [1, 2, 3, 0, 1, 2]


def test_a_merged_block_still_strobes_for_exactly_one_clock(
        tmp_path, model_library):
    """The wrap strobe survives the merge: a wrapper that mixed up the output
    bit positions would leave it stuck or land it on the wrong pin."""
    from kicadtoNgspice.KicadtoNgspice import merge_dcosim_blocks

    lines = merge_dcosim_blocks(MULTI_NETLIST.splitlines(), str(tmp_path))
    names, rows = simulate(tmp_path, lines, "multistrobe")

    index = {n: i for i, n in enumerate(names)}
    edges, previous = [], 0
    for row in rows:
        level = 1 if row[index["w"]] > 2.5 else 0
        if level != previous:
            edges.append(row[index["time"]])
            previous = level

    assert len(edges) == 2, "expected one strobe, got %d edges" % len(edges)
    assert edges[1] - edges[0] == pytest.approx(1e-3, abs=5e-6)


# --- the operating point -------------------------------------------------
#
# A d_cosim block used to report every output as 0 at t=0 and for the whole of
# the first timestep, because the TIME == 0.0 branch of the code model pushed
# its inputs into the co-simulator without ever running it, and the ivlng
# bridge would not run VVP for a zero-length advance either. A design whose
# correct initial output is 1 was therefore wrong at the start of every
# simulation, unlike an equivalent NgVeri (Verilator) model of the same
# Verilog -- so the two co-simulation backends disagreed on identical sources.
#
# Fixed by patches/nghdl-simulator/0002; these tests are the gate. They fail
# against an unpatched simulator, which is the point.

# Two outputs that must both read 1 from t=0: one combinational (an inverter
# fed a low input) and one from an initial block. Between them they cover the
# two ways a design can be 1 before anything has happened.
INIT_V = """\
`timescale 1ns / 1ps
module dcinit (
    input  a,
    output y,
    output q
);
    reg qr;
    initial qr = 1'b1;

    assign y = ~a;
    assign q = qr;
endmodule
"""

# `a` is low until 5 ms and high from 6 ms, so `y` must be 1 at the operating
# point and 0 later. The late transition is deliberate: without it the test
# would also pass against a model whose outputs were stuck high for an
# unrelated reason.
INIT_NETLIST = """\
* d_cosim operating point
v1 a_a gnd pwl(0 0 5m 0 6m 5 20m 5)
a1 [a_a] [a_d] u1
a2 [a_d] [y_d q_d] u2
a3 [y_d q_d] [y q] u3
.model u1 adc_bridge(in_low=1.0 in_high=2.0 rise_delay=1.0e-9 \
fall_delay=1.0e-9 )
.model u2 d_cosim simulation="ivlng" lib_args=["libvvp", "ivlng"] \
sim_args=["dcinit"]
.model u3 dac_bridge(out_low=0.0 out_high=5.0 out_undef=0.5 t_rise=1.0e-9 \
t_fall=1.0e-9 )
.control
set width=1000
tran 10e-06 20e-03 0e-00
print allv > OUTFILE
.endc
.end
"""


@pytest.fixture(scope="module")
def init_vvp(tmp_path_factory):
    """dcinit behind the generated wrapper, as build_cosim compiles it."""
    workdir = tmp_path_factory.mktemp("dcinit")
    (workdir / "dcinit.v").write_text(INIT_V)
    ports = [("a", "input", 1), ("y", "output", 1), ("q", "output", 1)]
    (workdir / (COSIM_TOP_MODULE + ".v")).write_text(
        cosim_wrapper_source([("dcinit", "dcinit", ports)],
                             "`timescale 1ns / 1ps"))
    res = icarus.run_iverilog(
        IVERILOG, [COSIM_TOP_MODULE + ".v", "dcinit.v"],
        str(workdir / "dcinit"), cwd=str(workdir), timeout=300)
    assert res.ok, res.output
    return workdir / "dcinit"


def stage_init(tmp_path, init_vvp):
    (tmp_path / "dcinit").write_bytes(init_vvp.read_bytes())
    return INIT_NETLIST.splitlines()


def test_outputs_are_live_at_the_operating_point(tmp_path, init_vvp):
    """Both outputs read 1 at t=0, where the design says they are 1.

    Before the fix both read 0 here: the co-simulation had not been run, so
    d_cosim was still publishing the ZERO it writes during INIT.
    """
    names, rows = simulate(tmp_path, stage_init(tmp_path, init_vvp), "opinit")

    assert sample(names, rows, 0.0, ["y"]) == 1, "inverter output wrong at t=0"
    assert sample(names, rows, 0.0, ["q"]) == 1, "initial block lost at t=0"


def test_operating_point_value_is_not_just_a_stuck_output(
        tmp_path, init_vvp):
    """The t=0 reading is a live value, not a pin stuck high.

    `y` must follow its input down once `a` goes high, while `q` -- which
    nothing ever drives again -- must hold the 1 its initial block gave it.
    """
    names, rows = simulate(tmp_path, stage_init(tmp_path, init_vvp), "oplive")

    assert sample(names, rows, 4.0e-3, ["y"]) == 1
    assert sample(names, rows, 8.0e-3, ["y"]) == 0
    assert sample(names, rows, 8.0e-3, ["q"]) == 1


def test_co_simulator_time_base_starts_aligned(tmp_path, init_vvp):
    """No "impossible delay" warning.

    Deferring time zero to the first accepted timestep left the co-simulator's
    vtime a whole timestep behind SPICE, so the first output() computed a
    negative delay and said so. It is the same defect seen from the other
    side, and a cheap witness that the two clocks now start together.
    """
    _out, console = run_ngspice(
        tmp_path, stage_init(tmp_path, init_vvp), "opdelay")

    assert "impossible delay" not in console.lower(), console
