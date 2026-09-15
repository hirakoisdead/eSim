"""Two naming problems eSim used to leave for the compiler, or for the user.

**A module named after the language.** ``module nand`` is a redeclaration of a
built-in gate primitive. iverilog reports it as "syntax error" on the module
line -- wording that describes the symptom, not the cause, and sends people
looking for a typo in code that has none. Renaming the module fixes it, which
is exactly the sort of thing a tool can say out loud.

**A design that changed its name.** A design is named after its top module, so
renaming the module renames the design. Every rename used to leave the previous
folder behind, so one design became several near-identical folders and the user
had to work out which was real. The move is deliberately conservative: it
declines whenever the folder holds anything eSim did not write.
"""
import os

from maker import verilog_library as lib
from maker.hdl.ports import (TB_PROVENANCE_MARKER, generate_stub_testbench,
                             is_generated_testbench, reserved_modules,
                             reserved_name_reason)

NAND_GATE = ("module nand_gate(input a, input b, output y);\n"
             "  assign y = ~(a & b);\n"
             "endmodule\n")


# --------------------------------------------------------------------------- #
#  Names the language has already taken
# --------------------------------------------------------------------------- #
def test_a_gate_primitive_is_refused_by_name():
    reason = reserved_name_reason("nand")
    assert reason
    assert "gate primitive" in reason
    # Says what to do, not just what is wrong.
    assert "nand_gate" in reason


def test_every_gate_primitive_is_covered():
    for name in ("and", "or", "nor", "xor", "xnor", "buf", "not", "nand"):
        assert reserved_name_reason(name), name


def test_a_keyword_is_refused_too():
    assert "reserved Verilog keyword" in reserved_name_reason("always")


def test_a_normal_name_is_not_refused():
    assert reserved_name_reason("nand_gate") == ""
    assert reserved_name_reason("counter") == ""
    assert reserved_name_reason("") == ""


def test_the_check_is_case_insensitive():
    """Verilog keywords are lowercase, but a design calling itself ``NAND``
    hits the same redeclaration."""
    assert reserved_name_reason("NAND")


def test_reserved_modules_finds_the_offender_in_a_source():
    code = "module nand(input a, output y);\nendmodule\n"
    assert reserved_modules(code) == ["nand"]
    assert reserved_modules(NAND_GATE) == []


def test_a_reserved_word_in_a_comment_is_not_a_module():
    code = "// module nand is not allowed\n" + NAND_GATE
    assert reserved_modules(code) == []


# --------------------------------------------------------------------------- #
#  Testbench provenance
# --------------------------------------------------------------------------- #
def test_a_generated_testbench_says_so():
    tb = generate_stub_testbench("nand_gate", [("input", "a", ""),
                                               ("output", "y", "")])
    assert tb.startswith(TB_PROVENANCE_MARKER)
    assert is_generated_testbench(tb)


def test_a_testbench_without_the_marker_is_the_users():
    """Deleting the marker line is a legitimate way to claim the file; from
    then on eSim reports a mismatch instead of replacing it."""
    tb = generate_stub_testbench("nand_gate", [("input", "a", "")])
    mine = "\n".join(tb.splitlines()[1:])
    assert not is_generated_testbench(mine)
    assert not is_generated_testbench("module tb_x; endmodule\n")
    assert not is_generated_testbench("")


# --------------------------------------------------------------------------- #
#  A design folder follows its module
# --------------------------------------------------------------------------- #
def _design(root, module, tb=None, extra=None):
    lib.write_text(lib.design_path(module, root), NAND_GATE)
    if tb is not None:
        lib.write_text(lib.sibling_path(module, "tb_%s.v" % module, root), tb)
    if extra:
        lib.write_text(lib.sibling_path(module, extra, root), "x")


def test_rename_moves_the_folder(tmp_path):
    root = str(tmp_path)
    _design(root, "nand_gate")
    out = lib.rename_design("nand_gate", "nandg", root)
    assert out == lib.design_path("nandg", root)
    assert os.path.isfile(out)
    assert not os.path.exists(lib.design_dir("nand_gate", root))


def test_rename_carries_a_generated_testbench_with_it(tmp_path):
    root = str(tmp_path)
    tb = generate_stub_testbench("nand_gate", [("input", "a", "")])
    _design(root, "nand_gate", tb=tb)
    lib.rename_design("nand_gate", "nandg", root)
    assert os.path.isfile(lib.sibling_path("nandg", "tb_nandg.v", root))


def test_rename_keeps_the_name_the_user_gave_their_testbench(tmp_path):
    """A testbench the user wrote keeps its filename: eSim renames its own
    files, not theirs."""
    root = str(tmp_path)
    _design(root, "nand_gate", tb="module tb_nand_gate; endmodule\n")
    lib.rename_design("nand_gate", "nandg", root)
    assert os.path.isfile(lib.sibling_path("nandg", "tb_nand_gate.v", root))
    assert not os.path.exists(lib.sibling_path("nandg", "tb_nandg.v", root))


def test_rename_declines_when_the_user_put_something_there(tmp_path):
    """Anything eSim did not write means the folder is the user's, and it
    stays where they left it."""
    root = str(tmp_path)
    _design(root, "nand_gate", extra="notes.txt")
    assert lib.rename_design("nand_gate", "nandg", root) == ""
    assert os.path.isfile(lib.design_path("nand_gate", root))


def test_rename_never_overwrites_an_existing_design(tmp_path):
    root = str(tmp_path)
    _design(root, "nand_gate")
    _design(root, "nandg")
    assert lib.rename_design("nand_gate", "nandg", root) == ""
    assert os.path.isfile(lib.design_path("nand_gate", root))
    assert os.path.isfile(lib.design_path("nandg", root))


def test_rename_refuses_path_bearing_or_blank_names(tmp_path):
    root = str(tmp_path)
    _design(root, "nand_gate")
    for bad in ("", "  ", "..", "../escape", "sub/dir"):
        assert lib.rename_design("nand_gate", bad, root) == ""
        assert lib.rename_design(bad, "nandg", root) == ""
    assert os.path.isfile(lib.design_path("nand_gate", root))


def test_rename_of_a_missing_design_is_a_no_op(tmp_path):
    assert lib.rename_design("ghost", "nandg", str(tmp_path)) == ""


def test_history_travels_with_the_design(tmp_path):
    root = str(tmp_path)
    _design(root, "nand_gate")
    lib.snapshot("nand_gate", NAND_GATE, root, stamp="20260101-000000")
    lib.rename_design("nand_gate", "nandg", root)
    history = os.path.join(lib.design_dir("nandg", root), lib.HISTORY_DIRNAME)
    assert os.path.isdir(history)
    assert os.listdir(history)
