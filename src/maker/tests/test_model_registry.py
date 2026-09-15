"""One model name means one model, and eSim now says so BEFORE it builds.

A schematic value resolves to a model by filename alone (Processing indexes
library/modelParamXML/**/<value>.xml), so two libraries holding the same
<name>.xml make that lookup ambiguous. The rule itself is old; what is tested
here is the part that was missing:

* the check is answerable from a directory listing, so it can run before a
  build instead of after one -- the previous check lived inside KiCad symbol
  creation, i.e. after iverilog (d_cosim) or after verilator plus a full
  ngspice rebuild (NgVeri), and the half-built model stayed on disk;
* a clash has an ANSWER (build under a free name) rather than only a refusal,
  which is possible because the model name and the module name are separate
  things -- so nothing in the user's code is renamed;
* the two Verilog backends are not a clash at all: that is the same design
  moving between backends, which NgVeri.py already offers to do.
"""
import os

import pytest

from maker import model_registry as reg


@pytest.fixture
def xml_loc(tmp_path):
    """A modelParamXML tree with one model in each library that matters."""
    root = tmp_path / "modelParamXML"
    for sub in ("Ngveri", "NgVeriCosim", "Nghdl", "Digital"):
        (root / sub).mkdir(parents=True)
    (root / "Nghdl" / "nand_gate.xml").write_text("<x/>")
    (root / "Ngveri" / "counter.xml").write_text("<x/>")
    (root / "NgVeriCosim" / "or_gate.xml").write_text("<x/>")
    (root / "Digital" / "d_nand.xml").write_text("<x/>")
    (root / "adc_bridge_1.xml").write_text("<x/>")
    return str(root)


def test_owner_names_the_library_holding_the_model(xml_loc):
    assert reg.owner_of(xml_loc, "nand_gate") == "Nghdl"
    assert reg.owner_of(xml_loc, "counter") == "Ngveri"
    assert reg.owner_of(xml_loc, "or_gate") == "NgVeriCosim"
    assert reg.owner_of(xml_loc, "d_nand") == "Digital"


def test_a_primitive_in_the_root_is_reported_as_built_in(xml_loc):
    assert reg.owner_of(xml_loc, "adc_bridge_1") == "__builtin__"
    assert "built-in" in reg.library_label("__builtin__")


def test_an_unused_name_is_owned_by_nobody(xml_loc):
    assert reg.owner_of(xml_loc, "half_adder") == ""
    assert not reg.is_taken(xml_loc, "half_adder")


def test_ownership_is_case_insensitive(xml_loc):
    """Windows compares filenames case-insensitively, so "Nand_Gate" and
    "nand_gate" are the same file there. Answering "free" for one of them is
    how a build lands on top of a live model."""
    assert reg.owner_of(xml_loc, "Nand_Gate") == "Nghdl"
    assert reg.owner_of(xml_loc, "  NAND_GATE  ") == "Nghdl"


def test_blank_name_owns_nothing(xml_loc):
    assert reg.owner_of(xml_loc, "") == ""
    assert reg.owner_of(xml_loc, "   ") == ""
    assert reg.free_name(xml_loc, "") == ""


def test_missing_tree_is_not_an_error(tmp_path):
    """A fresh install has no modelParamXML subdirectories yet. The preflight
    runs on every convert, so it must answer "free", not raise."""
    assert reg.owner_of(str(tmp_path / "nope"), "counter") == ""
    assert reg.owner_of("", "counter") == ""


def test_free_name_suffixes_until_it_finds_a_gap(xml_loc):
    assert reg.free_name(xml_loc, "nand_gate") == "nand_gate_v"
    # ... and steps past its own suggestion when that is taken too.
    (open(os.path.join(xml_loc, "Nghdl", "nand_gate_v.xml"), "w")
     .write("<x/>"))
    assert reg.free_name(xml_loc, "nand_gate") == "nand_gate_v2"


def test_free_name_returns_a_name_no_library_owns(xml_loc):
    alt = reg.free_name(xml_loc, "counter")
    assert alt and not reg.is_taken(xml_loc, alt)


def test_verilog_backends_are_listed_as_switchable(xml_loc):
    """NgVeri <-> d_cosim is a backend switch, not a collision: the caller
    checks membership of VERILOG_DIRS to tell the two situations apart."""
    assert reg.owner_of(xml_loc, "counter") in reg.VERILOG_DIRS
    assert reg.owner_of(xml_loc, "or_gate") in reg.VERILOG_DIRS
    assert reg.owner_of(xml_loc, "nand_gate") not in reg.VERILOG_DIRS


def test_labels_are_written_for_humans():
    """The dialog says "NGHDL (VHDL)", never "the Nghdl directory"."""
    assert reg.library_label("Nghdl") == "NGHDL (VHDL)"
    assert "Icarus" in reg.library_label("NgVeriCosim")
    assert "Verilator" in reg.library_label("Ngveri")
