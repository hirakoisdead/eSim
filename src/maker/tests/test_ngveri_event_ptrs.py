"""Correctness of the C that the NgVeri backend generates.

Three defects are pinned here, all of which used to produce a model that
BUILT, RAN, reported "Simulation Completed Successfully" and gave wrong
numbers with no diagnostic anywhere:

1. ``cm_event_get_ptr(tag, timepoint)`` takes two ORTHOGONAL arguments -- the
   tag selects the port's storage block, the timepoint says how far back in
   the rotating state history to look (0 current, 1 previous). The generator
   carried a second counter that tracked the tag index instead of resetting,
   so port 0 got (0,0)/(0,1) but port 1 got (1,1)/(1,2), port 2 (2,2)/(2,3)
   and so on. Every port after the first then wrote into a stale block and
   compared against one that aliased it, so it froze after its first
   transition. Regression witness: the universal counter's `wraps` pulse,
   which must rise at 9.000 ms AND fall at 10.000 ms.

2. ``int2arr``/``arr2int`` took and returned ``int``. Verilator ports are
   unsigned, so a 32-bit output with its top bit set arrived negative, the
   loop's ``num>=0`` guard failed immediately, and the array kept the previous
   timestep's bits.

3. ``inout`` and >64-bit ports cannot be represented by this backend at all
   and are now refused by name instead of silently mis-built.
"""
import os
import re

import pytest

from maker import ModelGeneration


def _mg(tmp_path, inputs, outputs, stem="counter", input_list=None):
    """A ModelGeneration bare enough to run the file writers. ``__new__``
    bypasses the Qt/config-heavy constructor: these writers only read
    model_stem/modelpath/input_port/output_port (and input_list, for the
    inout check, which getPortInfo would have populated)."""
    cls = ModelGeneration.ModelGeneration
    mg = cls.__new__(cls)
    mg.model_stem = stem
    mg.modelpath = str(tmp_path) + os.sep
    mg.input_port = list(inputs)
    mg.output_port = list(outputs)
    mg.input_list = input_list if input_list is not None else [
        [p.split(':')[0], "input", p.split(':')[1]] for p in inputs]
    return mg


def _cfunc(tmp_path, inputs, outputs, stem="counter"):
    mg = _mg(tmp_path, inputs, outputs, stem)
    mg.cfuncmod()
    with open(os.path.join(str(tmp_path), "cfunc.mod")) as fh:
        return fh.read()


# --------------------------------------------------------------- defect 1

def test_every_output_port_uses_timepoint_0_and_1(tmp_path):
    """The whole bug in one assertion: the timepoint must be 0/1 for EVERY
    tag, never climb with it."""
    text = _cfunc(
        tmp_path, ["clk:1"],
        ["min_val:8", "max_val:8", "rms_val:8", "update_pls:1"])

    for tag, name in enumerate(
            ["min_val", "max_val", "rms_val", "update_pls"]):
        assert ("_op_%s = (Digital_State_t *) cm_event_get_ptr(%d,0);"
                % (name, tag)) in text
        assert ("_op_%s_old = (Digital_State_t *) cm_event_get_ptr(%d,1);"
                % (name, tag)) in text

    # And nothing anywhere in the file asks for a timepoint past 1.
    timepoints = {int(m) for m in
                  re.findall(r"cm_event_get_ptr\(\s*\d+\s*,\s*(\d+)\s*\)",
                             text)}
    assert timepoints <= {0, 1}, (
        "cm_event_get_ptr timepoint must be 0 (current) or 1 (previous); "
        "found %s" % sorted(timepoints))


def test_the_exact_indices_that_shipped_broken_are_gone(tmp_path):
    """Named explicitly so a reintroduction is unmistakable in the diff.

    Note (1,1) is legitimate here -- it is tag 1's PREVIOUS timestep, which is
    exactly what _op_wraps_old wants. What shipped broken is (1,1) bound to
    the CURRENT-value pointer and (1,2) existing at all.
    """
    text = _cfunc(tmp_path, ["clk:1"], ["cnt_val:8", "wraps:2"])
    assert ("_op_wraps = (Digital_State_t *) cm_event_get_ptr(1,1);"
            not in text)
    assert "cm_event_get_ptr(1,2)" not in text
    assert "_op_wraps = (Digital_State_t *) cm_event_get_ptr(1,0);" in text
    assert ("_op_wraps_old = (Digital_State_t *) cm_event_get_ptr(1,1);"
            in text)


def test_tag_matches_the_allocation_order(tmp_path):
    """The tag passed to get_ptr must be the one cm_event_alloc used for that
    port, i.e. its index in output_port."""
    text = _cfunc(tmp_path, ["clk:1"], ["a:4", "b:2", "c:1"])
    for tag, (name, width) in enumerate([("a", 4), ("b", 2), ("c", 1)]):
        assert ("cm_event_alloc(%d,%d*sizeof(Digital_State_t));"
                % (tag, width)) in text
        assert "_op_%s = (Digital_State_t *) cm_event_get_ptr(%d,0);" % (
            name, tag) in text


def test_init_branch_still_pairs_current_with_current(tmp_path):
    """In the INIT pass there is no previous timestep -- ngspice returns an
    error for timepoint > 0 -- so both pointers must come from (tag,0)."""
    text = _cfunc(tmp_path, ["clk:1"], ["cnt_val:8", "wraps:2"])
    for tag, name in enumerate(["cnt_val", "wraps"]):
        assert ("_op_%s = _op_%s_old = (Digital_State_t *) "
                "cm_event_get_ptr(%d,0);" % (name, name, tag)) in text


def test_single_output_model_is_unchanged(tmp_path):
    """Port 0 was always correct; the fix must not disturb it."""
    text = _cfunc(tmp_path, ["a:1", "b:1"], ["y:1"])
    assert "_op_y = (Digital_State_t *) cm_event_get_ptr(0,0);" in text
    assert "_op_y_old = (Digital_State_t *) cm_event_get_ptr(0,1);" in text


def test_vhdl_generator_agrees_with_the_verilog_one():
    """nghdl/src/model_generation.py carries a second copy of this loop. It
    drove the same freeze for VHDL models and must stay fixed too."""
    here = os.path.dirname(os.path.abspath(ModelGeneration.__file__))
    root = os.path.dirname(os.path.dirname(here))
    src = os.path.join(root, "nghdl", "src", "model_generation.py")
    if not os.path.isfile(src):
        pytest.skip("nghdl generator not present in this tree")
    with open(src) as fh:
        code = fh.read()
    assert "els_evt_count2" not in code, (
        "the coupled timepoint counter is back in the VHDL generator")
    assert 'str(tag) + ",0);"' in code
    assert 'str(tag) + ",1);"' in code


# --------------------------------------------------------------- defect 2

def _sim_main(tmp_path, inputs, outputs, stem="counter"):
    mg = _mg(tmp_path, inputs, outputs, stem)
    mg.sim_main_header()
    mg.sim_main()
    with open(os.path.join(str(tmp_path), "sim_main_" + stem + ".cpp")) as fh:
        return fh.read()


def test_converters_are_unsigned_and_64_bit(tmp_path):
    cpp = _sim_main(tmp_path, ["clk:1"], ["frac_out:32"])
    assert "void int2arrcounter(uint64_t num, int array[], int n)" in cpp
    assert "uint64_t arr2intcounter(const int array[], int n)" in cpp
    assert "#include <cstdint>" in cpp
    # The guard that stopped the loop dead on a negative value is gone.
    assert "num>=0" not in cpp
    assert "num /= 2" not in cpp


def test_converters_round_trip_every_bit_pattern(tmp_path):
    """Compile the emitted helpers and check them against Python, including
    the 32-bit values that used to freeze the port."""
    cc = _find_cxx()
    if not cc:
        pytest.skip("no C++ compiler available")
    cpp = _sim_main(tmp_path, ["clk:1"], ["frac_out:32"])
    # Search for the end marker FROM the start marker: the extern "C"
    # declaration of foo_counter appears earlier in the file than the
    # converters do, and slicing to it yields an empty body.
    start = cpp.index("void int2arrcounter")
    end = cpp.index("int foo_counter", start)
    body = cpp[start:end]

    prog = tmp_path / "conv.cpp"
    prog.write_text(
        "#include <cstdint>\n#include <cstdio>\n" + body + """
int main() {
    const uint64_t vals[] = {0u, 1u, 0x7FFFFFFFu, 0x80000000u,
                             0xC0000000u, 0xFFFFFFFFu};
    for (unsigned k = 0; k < 6; ++k) {
        int a[64];
        for (int i = 0; i < 64; ++i) a[i] = 1;   /* stale bits from last step */
        int2arrcounter(vals[k], a, 32);
        printf("%llu %llu\\n", (unsigned long long)vals[k],
               (unsigned long long)arr2intcounter(a, 32));
    }
    return 0;
}
""")
    import subprocess
    # The bundled MinGW g++ finds cc1plus and its runtime DLLs through PATH,
    # so put its own bin directory first rather than assuming the caller's
    # environment already has it.
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(cc) + os.pathsep + env.get("PATH", "")

    exe = str(tmp_path / "conv.exe")
    build = subprocess.run([cc, "-O2", "-o", exe, str(prog)],
                           capture_output=True, text=True, env=env)
    if build.returncode != 0:
        pytest.skip("C++ compiler unusable here: " +
                    (build.stderr.strip() or "no diagnostic"))
    out = subprocess.run([exe], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    for line in out.stdout.strip().splitlines():
        want, got = line.split()
        assert want == got, (
            "int2arr/arr2int lost bits: gave %s, got %s back" % (want, got))


def _find_cxx():
    import shutil
    for name in ("g++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    bundled = r"C:\FOSSEE\eSim\tools\msys64\mingw64\bin\g++.exe"
    return bundled if os.path.isfile(bundled) else None


def test_trace_format_matches_the_argument_type(tmp_path):
    """ESIM_TRACE printed a possibly-64-bit port with %d."""
    cpp = _sim_main(tmp_path, ["clk:1"], ["wide:64"])
    assert '=%d\\n"' not in cpp
    assert '=%llu\\n", (unsigned long long)(' in cpp


# --------------------------------------------------------------- defect 3
#
# validate_ports() is PARKED: it is proven below, but nothing calls it, because
# refusing a build eSim 2.5 accepted is a maintainer decision
# (docs/UPSTREAM_DECISIONS.md items 2 and 3). The first test guards the
# parking; the rest keep the evidence alive for whoever makes that call.

def test_validate_ports_is_not_wired_into_the_build(tmp_path):
    """NgVeri must build exactly what 2.5 built -- no refusal, no warning, no
    terminal note. If someone wires the gate back in, this fails and they have
    to update UPSTREAM_DECISIONS.md deliberately rather than by accident."""
    import inspect
    from maker import NgVeri

    source = inspect.getsource(NgVeri.NgVeri.addverilog)
    assert "validate_ports()" not in source.replace(
        "# NOTE: model.validate_ports() is deliberately NOT called here.", "")


def test_inout_port_is_refused_by_name(tmp_path):
    mg = _mg(tmp_path, ["clk:1", "sda:1"], ["y:1"],
             input_list=[["clk", "input", "1"], ["sda", "inout", "1"]])
    err = mg.validate_ports()
    assert err and "sda" in err and "inout" in err


def test_port_wider_than_64_bits_is_refused_by_name(tmp_path):
    mg = _mg(tmp_path, ["clk:1"], ["big:128"])
    err = mg.validate_ports()
    assert err and "big" in err and "128" in err


def test_ordinary_model_passes_validation(tmp_path):
    mg = _mg(tmp_path, ["clk:1", "sample:8"],
             ["min_val:8", "max_val:8", "update_pls:1"])
    assert mg.validate_ports() is None


def test_64_bit_port_is_allowed(tmp_path):
    """The boundary is inclusive: QData carries exactly 64 bits."""
    mg = _mg(tmp_path, ["clk:1"], ["q:64"])
    assert mg.validate_ports() is None
