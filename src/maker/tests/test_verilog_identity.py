"""A model is named after the MODULE in the design, not after the file.

The rule these pin down: eSim copies a design into its own build tree, so the
copy can be called whatever the pipeline needs. The user's file name is then
irrelevant, and the old "File name and module name are not same" refusal has
nothing left to refuse.

That refusal was the single worst thing about this flow. Paste a nand gate into
the editor and press Convert and it failed, because the design had been given
the name of whatever file happened to be open (often ``counter.v``, from the
default template). Renaming the tab did nothing -- it only changed a label --
so there was no way out of it from inside eSim at all. The only route that
worked was to write a correctly-named .v in some other editor and open that.

Three cases still take the name from the file, and each is deliberate:
``.tlv`` (sandpiper has not run yet, and always emits ``module top``), a top
module literally called ``top``, and a source no parser can read.
"""
import importlib
import os

import pytest
from PyQt6 import QtWidgets

from maker import CosimConfig, ModelGeneration


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private HOME so the build tree lands under tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))   # Windows expanduser
    importlib.reload(CosimConfig)
    return tmp_path


def _model(path, text):
    with open(path, "w") as fh:
        fh.write(text)
    return ModelGeneration.ModelGeneration(str(path), QtWidgets.QTextEdit())


NAND = ("module nand_gate(input a, input b, output y);\n"
        "  assign y = ~(a & b);\n"
        "endmodule\n")


def test_the_module_name_wins_over_the_file_name(qapp, home):
    """The exact case that used to be unescapable: a design pasted from
    somewhere else, sitting in a file named after something entirely
    different."""
    m = _model(home / "pasted_from_ai.v", NAND)
    assert m.model_stem == "pasted_from_ai"        # before: from the file
    assert m.resolve_identity() == "No Error"
    assert m.model_stem == "nand_gate"             # after: from the module
    assert m.fname == "nand_gate.v"
    assert m.top_module == "nand_gate"


def test_the_build_dir_and_copy_take_the_module_name(qapp, home):
    m = _model(home / "whatever.v", NAND)
    m.resolve_identity()
    os.makedirs(m.digital_home, exist_ok=True)
    assert m.verilogfile() == "No Error"
    assert os.path.basename(os.path.dirname(m.modelpath)) == "nand_gate"
    assert sorted(os.listdir(m.modelpath)) == ["nand_gate.v"]


def test_ports_are_read_without_any_name_matching(qapp, home):
    m = _model(home / "whatever.v", NAND)
    m.resolve_identity()
    os.makedirs(m.digital_home, exist_ok=True)
    m.verilogfile()
    assert m.verilogParse(make_symbol=False) == "No Error"
    conn = open(m.modelpath + "connection_info.txt").read()
    assert "a" in conn and "b" in conn and "y" in conn


def test_the_users_own_file_is_never_touched(qapp, home):
    src = home / "pasted_from_ai.v"
    m = _model(src, NAND)
    m.resolve_identity()
    os.makedirs(m.digital_home, exist_ok=True)
    m.verilogfile()
    assert src.exists(), "eSim must not rename or move the user's file"
    assert src.read_text() == NAND


def test_a_case_mixed_module_still_gets_one_canonical_id(qapp, home):
    """Everything downstream (KiCad symbol, vvp id, modpath line) keys off a
    lowercase id, so the model stem is lowercased -- but the declared case is
    kept for verilator's --top-module."""
    m = _model(home / "x.v", "module NAND_Gate(input a, output y);\nendmodule\n")
    m.resolve_identity()
    assert m.model_stem == "nand_gate"
    assert m.top_module == "NAND_Gate"


MULTI = ("module half_adder(input a, input b, output s);\nendmodule\n"
         "module full_adder(input a, input b, output s);\n"
         "  half_adder u0(.a(a), .b(b), .s(s));\n"
         "endmodule\n")


def test_a_multi_module_design_is_named_after_its_top(qapp, home):
    m = _model(home / "adders.v", MULTI)
    m.resolve_identity()
    assert m.model_stem == "full_adder"


def test_an_explicit_top_overrides_the_guess(qapp, home):
    """The automatic pick is a heuristic. A user who can see it guessed wrong
    needs a way to say so that does not involve rearranging their code."""
    m = _model(home / "adders.v", MULTI)
    m.resolve_identity(prefer="half_adder")
    assert m.model_stem == "half_adder"
    assert m.top_module == "half_adder"


def test_an_override_naming_a_module_that_is_not_there_is_ignored(qapp, home):
    """A stale choice (left over from a design that has since been replaced)
    must fall back to the guess, not name the model after something the source
    does not define."""
    m = _model(home / "adders.v", MULTI)
    m.resolve_identity(prefer="something_else")
    assert m.model_stem == "full_adder"


# --------------------------------------------------------------------------- #
# The three deliberate fallbacks to the file name
# --------------------------------------------------------------------------- #
def test_tlv_keeps_the_file_name(qapp, home):
    """sandpiper has not run yet and what it emits is always `module top`, so
    there is no authored name to read. Naming from the file is correct here."""
    m = _model(home / "mydesign.tlv", "\\TLV_version 1d: tl-x.org\n")
    assert m.resolve_identity() == "No Error"
    assert m.model_stem == "mydesign"
    assert m.fname == "mydesign.tlv"


def test_a_module_called_top_keeps_the_file_name(qapp, home):
    """`top` names nothing -- it is the conventional wrapper name and what TLV
    produces -- so the file still decides, and verilogfile's `top` -> stem
    rewrite stays meaningful."""
    m = _model(home / "mydesign.sv", "module top(input a, output y);\nendmodule\n")
    m.resolve_identity()
    assert m.model_stem == "mydesign"
    assert m._rename_top_to_stem is True


def test_an_unparseable_design_keeps_the_file_name(qapp, home):
    """Reporting a broken design is verilogParse's job, where the message can
    talk about ports. Failing here would only trade one confusing error for
    another."""
    m = _model(home / "broken.v", "this is not verilog at all\n")
    assert m.resolve_identity() == "No Error"
    assert m.model_stem == "broken"


def test_a_named_sv_module_is_not_mangled_by_the_top_rewrite(qapp, home):
    """The `top` -> stem rewrite exists for sandpiper output. Applied to a
    design that names its own top, it would rename an unrelated identifier in
    the user's code."""
    text = ("module alu(input a, output y);\n"
            "  wire top;\n"
            "  assign top = a;\n"
            "  assign y = top;\n"
            "endmodule\n")
    m = _model(home / "alu.sv", text)
    m.resolve_identity()
    assert m._rename_top_to_stem is False
    os.makedirs(m.digital_home, exist_ok=True)
    m.verilogfile()
    written = open(m.modelpath + m.fname).read()
    assert "wire top;" in written, "the user's own `top` signal was renamed"


def test_verilator_output_names_are_pinned_to_the_model_stem(qapp, home):
    """Verilator names its output after the top module AS DECLARED, while the
    make step looks for V<stem>. Without --prefix those drift apart for any
    mixed-case module -- invisible on Windows, fatal on Linux."""
    m = _model(home / "x.v", "module NAND_Gate(input a, output y);\nendmodule\n")
    m.resolve_identity()
    m.modelpath = str(home) + os.sep

    seen = {}

    def fake_run(cmd, title, cwd=None, env=None):
        seen["cmd"] = cmd
        return True

    m._run = fake_run
    m._verilator_binary = lambda: "verilator"
    if not m.parser.has_section("NGHDL"):
        m.parser.add_section("NGHDL")
    m.parser.set("NGHDL", "RELEASE", str(home))
    m.run_verilator()
    cmd = seen["cmd"]
    assert "--prefix" in cmd
    assert cmd[cmd.index("--prefix") + 1] == "Vnand_gate"
    # ...and the module elaborated is the one the ifspec was generated from,
    # in its declared case.
    assert cmd[cmd.index("--top-module") + 1] == "NAND_Gate"
