"""A taken model name is answered BEFORE the build, and with a way forward.

Two defects, one cause. eSim enforces "one name, one model" inside KiCad symbol
creation -- the last step of a convert. So:

* the refusal arrived after iverilog had compiled (d_cosim), or after verilator
  and a full ngspice rebuild (NgVeri): minutes spent to be told something a
  directory listing knew up front;
* the half-built model stayed on disk, which is how a FAILED convert still put
  an entry in Remove Models -- for a block that was never placeable, because
  the symbol is exactly what did not get made.

And the refusal itself was a dead end: "rename your Verilog module/file and add
it again". The model name is not the module name (ModelGeneration keeps
``model_stem`` and ``top_module`` apart -- the wrapper instantiates the module,
the model name only labels the block), so eSim can simply build under a free
name and change nothing in the user's code.
"""
import os

import pytest

from configuration import Dialogs
from maker import model_registry as reg


class FakeModel:
    """Only the two attributes the preflight touches."""

    def __init__(self, stem):
        self.model_stem = stem
        self.renamed_to = None

    def rename_model(self, stem):
        self.renamed_to = stem
        self.model_stem = stem
        return True


@pytest.fixture
def convert(qapp, tmp_path):
    from maker import NgVeri
    w = NgVeri.NgVeri(0)
    root = tmp_path / "modelParamXML"
    for sub in ("Ngveri", "NgVeriCosim", "Nghdl"):
        (root / sub).mkdir(parents=True)
    w._xml_loc = str(root)
    yield w
    w.close()
    w.deleteLater()


@pytest.fixture
def clicks(monkeypatch):
    """Drive the decision dialog: record it, and click whatever the test says.

    ``choice`` is "alternative" (take the offered free name) or "cancel"."""
    state = {"shown": 0, "choice": "cancel", "text": "", "buttons": []}

    def fake_show(box):
        state["shown"] += 1
        state["text"] = box.text() + " " + box.informativeText()
        state["buttons"] = [b.text() for b in box.buttons()]
        if state["choice"] == "alternative":
            for b in box.buttons():
                if b.text().startswith("Build as"):
                    box.setDefaultButton(b)
                    # QMessageBox.clickedButton() is what the caller reads.
                    b.click()
                    return 0
        for b in box.buttons():
            if "Cancel" in b.text():
                b.click()
                break
        return 0

    monkeypatch.setattr(Dialogs, "show_modal", fake_show)
    return state


def _xml(convert, sub, name):
    open(os.path.join(convert._xml_loc, sub, name + ".xml"), "w").write("<x/>")


def test_a_free_name_builds_without_asking_anything(convert, clicks):
    model = FakeModel("half_adder")
    assert convert._preflight_model_name("cosim", model) is True
    assert clicks["shown"] == 0
    assert model.renamed_to is None


def test_the_other_verilog_backend_is_not_a_clash(convert, clicks):
    """NgVeri <-> d_cosim is the same design changing backend, which
    _switch_backends_if_needed already offers. Two dialogs for one decision
    would be worse than none."""
    _xml(convert, "Ngveri", "counter")
    model = FakeModel("counter")
    assert convert._preflight_model_name("cosim", model) is True
    assert clicks["shown"] == 0


def test_rebuilding_the_same_backends_model_is_not_a_clash(convert, clicks):
    _xml(convert, "NgVeriCosim", "or_gate")
    model = FakeModel("or_gate")
    assert convert._preflight_model_name("cosim", model) is True
    assert clicks["shown"] == 0


def test_a_vhdl_model_of_the_same_name_is_reported_before_building(convert,
                                                                   clicks):
    _xml(convert, "Nghdl", "nand_gate")
    clicks["choice"] = "cancel"
    model = FakeModel("nand_gate")

    assert convert._preflight_model_name("cosim", model) is False

    assert clicks["shown"] == 1
    assert "NGHDL (VHDL)" in clicks["text"]
    # It says where the name can be freed, instead of only refusing.
    assert "Remove Models" in clicks["text"]
    assert model.renamed_to is None


def test_the_offered_alternative_builds_under_a_free_name(convert, clicks):
    _xml(convert, "Nghdl", "nand_gate")
    clicks["choice"] = "alternative"
    model = FakeModel("nand_gate")

    assert convert._preflight_model_name("cosim", model) is True

    assert model.renamed_to == "nand_gate_v"
    assert model.model_stem == "nand_gate_v"
    assert not reg.is_taken(convert._xml_loc, "nand_gate_v")
    assert any(b.startswith("Build as") for b in clicks["buttons"])


def test_the_alternative_steps_past_names_that_are_also_taken(convert, clicks):
    _xml(convert, "Nghdl", "nand_gate")
    _xml(convert, "Ngveri", "nand_gate_v")
    clicks["choice"] = "alternative"
    model = FakeModel("nand_gate")

    convert._preflight_model_name("cosim", model)

    assert model.renamed_to == "nand_gate_v2"


def test_a_builtin_primitive_cannot_be_freed_and_says_so(convert, clicks):
    open(os.path.join(convert._xml_loc, "adc_bridge_1.xml"), "w").write("<x/>")
    clicks["choice"] = "cancel"
    model = FakeModel("adc_bridge_1")

    assert convert._preflight_model_name("ngveri", model) is False
    assert "cannot be freed" in clicks["text"]


def test_a_blank_name_is_left_to_the_existing_validation(convert, clicks):
    """resolve_identity/verilogfile own the "is this a usable name" question;
    the preflight only answers "is it taken"."""
    assert convert._preflight_model_name("cosim", FakeModel("")) is True
    assert clicks["shown"] == 0
