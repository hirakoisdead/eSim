"""Every design written in eSim gets a home, without the user asking for one.

Before this, a design authored in eSim had nowhere to live: the Author editor
could not create a file at all (Save had nothing to name one after, and said
"please check if it is chosen"), and Convert had no path to build from. The
only designs that survived a session were the ones written in some other
editor and opened read-only.

Two halves are tested here. ``verilog_library`` owns the layout rules and is
pure stdlib. ``DesignBus`` owns *when* a write happens -- debounced off the one
method every stage edits through, so Author and Verify get it for free and
``collect_into_bus`` can stay purely in-memory (see test_flow_sync).

The safety properties matter as much as the feature: an autosave must never
overwrite a file of the user's own, never discard a home they picked
themselves, and never litter the library with half-typed code.
"""
import os

import pytest

from maker import verilog_library as lib
from maker.DesignBus import DesignBus

NAND = ("module nand_gate(input a, input b, output y);\n"
        "  assign y = ~(a & b);\n"
        "endmodule\n")
COUNTER = ("module counter(input clk, output reg [3:0] q);\n"
           "  always @(posedge clk) q <= q + 1;\n"
           "endmodule\n")


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "VerilogLibrary")


@pytest.fixture
def bus(qapp):
    b = DesignBus(0)
    yield b
    b.close()


# --------------------------------------------------------------------------- #
# What is worth writing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", [
    "",
    "   \n",
    "// just a comment\n",
    "module n",                      # mid-word: the name is still being typed
    "module nand_gate(input a,",     # header not closed
    "module nand_gate(input a, output y);",   # never reaches endmodule
])
def test_half_written_code_is_not_saveable(code):
    """A design being typed one character at a time must not earn a folder per
    keystroke ('n/', 'na/', 'nan/'). Until it is saveable the text is perfectly
    safe -- it lives in the bus, in memory."""
    assert lib.is_saveable(code) is False


@pytest.mark.parametrize("code", [NAND, COUNTER])
def test_a_complete_module_is_saveable(code):
    assert lib.is_saveable(code) is True


def test_a_module_named_only_in_a_comment_does_not_count():
    assert lib.is_saveable("// module ghost\n// endmodule\n") is False


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def test_a_design_is_saved_under_its_own_module_name(root):
    path = lib.save_design(NAND, root)
    assert path == os.path.join(root, "nand_gate", "nand_gate.v")
    assert open(path).read() == NAND


def test_each_design_gets_its_own_folder(root):
    """One folder per design, not one flat pile: designs bring testbenches and
    helper modules with them, and two unrelated designs that each define a
    `mux` helper would otherwise overwrite each other."""
    lib.save_design(NAND, root)
    lib.save_design(COUNTER, root)
    assert sorted(os.listdir(root)) == ["counter", "nand_gate"]


def test_the_testbench_sits_beside_the_design(root):
    lib.save_design(NAND, root)
    tb = lib.write_text(
        lib.sibling_path("nand_gate", "tb_nand_gate.v", root), "module tb;\n")
    assert os.path.dirname(tb) == lib.design_dir("nand_gate", root)


def test_unsaveable_code_writes_nothing(root):
    assert lib.save_design("module half", root) == ""
    assert not os.path.exists(root)


# --------------------------------------------------------------------------- #
# Listing and removal
# --------------------------------------------------------------------------- #
def test_designs_are_listed_most_recent_first(root):
    lib.save_design(COUNTER, root)
    os.utime(lib.design_path("counter", root), (1000, 1000))
    lib.save_design(NAND, root)
    os.utime(lib.design_path("nand_gate", root), (2000, 2000))
    assert [name for name, _p, _m in lib.list_designs(root)] == \
        ["nand_gate", "counter"]


def test_a_folder_with_no_design_file_is_not_listed(root):
    lib.save_design(NAND, root)
    os.makedirs(os.path.join(root, "leftover"))
    assert [name for name, _p, _m in lib.list_designs(root)] == ["nand_gate"]


def test_remove_takes_the_whole_design_folder(root):
    lib.save_design(NAND, root)
    lib.write_text(lib.sibling_path("nand_gate", "tb_nand_gate.v", root), "x")
    assert lib.remove_design("nand_gate", root) is True
    assert lib.list_designs(root) == []


@pytest.mark.parametrize("name", ["", "   ", "..", os.path.join("a", "b")])
def test_remove_refuses_a_name_that_could_escape_the_library(root, name):
    """os.path.join(base, "") is base itself -- an rmtree there would take
    every design the user has."""
    lib.save_design(NAND, root)
    assert lib.remove_design(name, root) is False
    assert lib.list_designs(root) != []


def test_snapshot_lands_in_history(root):
    lib.save_design(NAND, root)
    snap = lib.snapshot("nand_gate", NAND, root, stamp="20260729-2214")
    assert snap == os.path.join(root, "nand_gate", ".history",
                                "nand_gate-20260729-2214.v")
    assert open(snap).read() == NAND


# --------------------------------------------------------------------------- #
# Autosave: when the write happens, and what it must never do
# --------------------------------------------------------------------------- #
def test_a_pasted_design_is_filed_under_its_module(bus):
    bus.set_content(NAND)
    home = bus.flush_autosave()
    assert home.endswith(os.path.join("VerilogLibrary", "nand_gate",
                                      "nand_gate.v"))
    assert open(home).read() == NAND


def test_replacing_the_design_moves_it_and_keeps_the_old_one(bus):
    """The old rule set a path once and only if there wasn't one, so a design
    stayed filed under the first name it ever had however many times it was
    replaced -- which is what made Convert build 'counter' out of a nand gate.
    Now the home follows the module, and nothing is deleted on the way."""
    bus.set_content(COUNTER)
    first = bus.flush_autosave()
    bus.set_content(NAND)
    second = bus.flush_autosave()

    assert os.path.basename(first) == "counter.v"
    assert os.path.basename(second) == "nand_gate.v"
    assert os.path.isfile(first), "an autosave must never lose earlier work"
    assert bus.path == second


def test_half_typed_content_writes_nothing(bus):
    bus.set_content("module nand_ga")
    assert bus.flush_autosave() == ""
    assert bus.path == ""


def test_a_home_the_user_picked_is_not_hijacked(bus, tmp_path):
    """Save As is a decision. Autosave keeps writing exactly there, and stops
    renaming the file after the module."""
    chosen = str(tmp_path / "my_project" / "design.v")
    bus.set_content(COUNTER)
    bus.save_to_disk(chosen)

    bus.set_content(NAND)
    assert bus.flush_autosave() == chosen
    assert open(chosen).read() == NAND
    assert not os.path.exists(
        os.path.join(os.path.dirname(chosen), "nand_gate"))


def test_an_imported_file_is_never_written_by_autosave(bus, tmp_path):
    """eSim works on a library copy of a file the user opened, so nothing in
    the background can rewrite something sitting in their project folder."""
    original = tmp_path / "their_project" / "counter.v"
    original.parent.mkdir()
    original.write_text(COUNTER)

    bus.load_from_disk(str(original), imported=True)
    bus.set_content(NAND)
    bus.flush_autosave()
    bus.materialize()

    assert original.read_text() == COUNTER, "the user's own file was rewritten"
    assert bus.origin_path == str(original)
    assert bus.path.endswith(os.path.join("nand_gate", "nand_gate.v"))


def test_an_explicit_save_does_mirror_back_to_the_original(bus, tmp_path):
    original = tmp_path / "their_project" / "counter.v"
    original.parent.mkdir()
    original.write_text(COUNTER)

    bus.load_from_disk(str(original), imported=True)
    bus.set_content(NAND)
    bus.flush_autosave()
    assert bus.mirror_to_origin() == str(original)
    assert original.read_text() == NAND


def test_starting_a_new_design_does_not_inherit_the_old_home(bus):
    bus.set_content(COUNTER)
    old = bus.flush_autosave()
    bus.start_new(NAND)
    new = bus.flush_autosave()
    assert new != old
    assert os.path.isfile(old), "the design being replaced must be kept"
    assert bus.origin_path == ""


def test_close_flushes_a_design_still_inside_the_quiet_period(qapp):
    """The design is in memory until the debounce fires; closing eSim would
    otherwise beat the timer to it."""
    b = DesignBus(0)
    b.set_content(NAND)          # arms the timer, writes nothing yet
    assert b.path == ""
    b.close()
    assert b.path.endswith("nand_gate.v")
    assert os.path.isfile(b.path)
