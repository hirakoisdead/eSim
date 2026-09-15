"""The whole journey a user actually takes: paste a design, press Convert.

This is the scenario the Verilog flow used to make impossible. Open eSim, get a
nand gate from somewhere, paste it into the editor, press Convert -- and get
"File name and module name are not same", because the design had silently
inherited the name of whatever file was open (usually ``counter.v``, from the
Verify stage's default template). Nothing in the UI could fix it from there:
renaming the tab only changed a label, Save could not create a file, and the
design's home was assigned once and never revisited. The only way through was
to write a correctly-named .v in a different editor and open that instead.

These tests drive the real widgets end to end, so they fail if any single link
in that chain regresses -- the naming, the autosave, the mirrored path slot, or
the model the converter would build.
"""
import os

import pytest

from maker import Maker, verilog_library
from maker.DesignBus import DesignBus

NAND = ("module nand_gate(input a, input b, output y);\n"
        "  assign y = ~(a & b);\n"
        "endmodule\n")


@pytest.fixture
def author(qapp):
    """The Author stage on its own bus, as the Flow Navigator builds it."""
    bus = DesignBus(0)
    w = Maker.Maker(0, bus=bus)
    yield w, bus
    w.close()
    bus.close()
    w.deleteLater()


def _paste(author, text):
    """Type into the Author editor exactly as a paste would."""
    w, bus = author
    w.entry_var[1].setText(text)
    return bus.flush_autosave()


def test_paste_then_convert_builds_the_pasted_module(author, qapp):
    w, bus = author
    home = _paste(author, NAND)

    # 1. The design got a home, named after its module, with no Save pressed.
    assert home.endswith(os.path.join("nand_gate", "nand_gate.v"))
    assert open(home).read() == NAND

    # 2. Convert reads Maker.verilogFile[filecount]; the bus mirrors it, so
    #    the converter is pointed at the design that is on screen.
    assert Maker.verilogFile[0] == home

    # 3. And the model that would be built carries the module's name.
    from maker import ModelGeneration
    from PyQt6 import QtWidgets
    model = ModelGeneration.ModelGeneration(home, QtWidgets.QTextEdit())
    assert model.resolve_identity() == "No Error"
    assert model.model_stem == "nand_gate"


def test_pasting_over_a_previous_design_retargets_convert(author, qapp):
    """The failure the old code produced: paste design B over design A and
    Convert still built A, because the path was assigned once and kept."""
    counter = ("module counter(input clk, output reg q);\n"
               "  always @(posedge clk) q <= ~q;\n"
               "endmodule\n")
    first = _paste(author, counter)
    assert Maker.verilogFile[0] == first

    second = _paste(author, NAND)
    assert os.path.basename(second) == "nand_gate.v"
    assert Maker.verilogFile[0] == second, \
        "Convert is still pointed at the design that was replaced"
    assert os.path.isfile(first), "the replaced design must not be deleted"


def test_a_design_appears_in_the_library_panel(author, qapp):
    w, _bus = author
    _paste(author, NAND)
    w.refresh_library_list()
    names = [w.libraryList.item(i).text()
             for i in range(w.libraryList.count())]
    assert "nand_gate" in names


def test_edit_in_makerchip_opens_materialized_design_through_bridge(
        author, qapp, monkeypatch):
    """One click creates a simulatable copy and opens the plugin bridge."""
    w, _bus = author
    home = _paste(author, NAND)
    opened = []

    class FakeBridge:
        def __init__(self, filename):
            self.filename = filename
            self.stopped = False

        def start(self):
            return "http://127.0.0.1:43210/session/test/"

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(Maker, "makerchipTOSAccepted", lambda *_a: True)
    monkeypatch.setattr(
        Maker.Dialogs, "warning",
        lambda *_a, **_k: pytest.fail("Makerchip must not show a mode dialog"))
    monkeypatch.setattr(Maker, "MakerchipBridge", FakeBridge)
    monkeypatch.setattr(
        Maker.QtGui.QDesktopServices, "openUrl",
        staticmethod(lambda url: opened.append(url.toString()) or True))

    w.runmakerchip()

    assert isinstance(w._makerchip_bridge, FakeBridge)
    wrapper = os.path.splitext(home)[0] + ".tlv"
    assert w._makerchip_bridge.filename == wrapper
    generated = open(wrapper, encoding="utf-8").read()
    assert "/* verilator lint_off */" not in generated
    assert "assign a = cyc_cnt[0];" in generated
    assert "assign b = cyc_cnt[1];" in generated
    assert "assign passed = cyc_cnt > 32'd20;" in generated
    assert "assign failed = 1'b0;" in generated
    assert opened == ["http://127.0.0.1:43210/session/test/"]


def test_new_module_starts_a_named_design(author, qapp, monkeypatch):
    from PyQt6 import QtWidgets
    w, bus = author
    _paste(author, NAND)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("half_adder", True)))
    w.new_module()
    assert "module half_adder" in bus.get_content()
    assert bus.flush_autosave().endswith(
        os.path.join("half_adder", "half_adder.v"))


def test_new_module_refuses_a_name_that_cannot_be_a_model(author, qapp,
                                                          monkeypatch):
    """The module name becomes a C function and a make target, so it has to be
    a bare identifier. Caught here, where the message can be about the name --
    not four layers down in cmpp."""
    from PyQt6 import QtWidgets
    w, bus = author
    warned = []
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("2bit adder", True)))
    monkeypatch.setattr(Maker.Dialogs, "warning",
                        lambda *a, **k: warned.append(a))
    w.new_module()
    assert warned, "an unusable module name must be refused up front"
    assert bus.get_content() == ""


@pytest.fixture
def convert(qapp):
    """The Convert stage on its own, as the Flow Navigator builds it."""
    from maker import NgVeri
    w = NgVeri.NgVeri(0)
    yield w
    w.close()
    w.deleteLater()


def test_convert_says_what_it_will_build(author, convert, qapp):
    """This stage used to say nothing at all: the model's name and its ports
    were only revealed by the build log afterwards -- or, when something was
    wrong, by an error about a file the user had never deliberately named.

    It says it on ONE line, beside the heading. Vertical space here is not
    decoration: the page sits in a dock behind a scroll area, and rows spent on
    description are rows that push the build progress bar below the fold."""
    _paste(author, NAND)
    convert.refresh_subject()
    said = convert.subjectLabel.text()
    assert "nand_gate" in said
    assert "2 in" in said and "1 out" in said
    assert "<br" not in said, "the subject line must stay one line"


def test_convert_keeps_the_source_path_in_the_tooltip(author, convert, qapp):
    """The path is reference information -- the answer to "which file is
    this?", asked far less often than this page is looked at -- so it lives in
    the tooltip and in the build log rather than on a second line."""
    path = _paste(author, NAND)
    convert.refresh_subject()
    assert path in convert.subjectLabel.toolTip()


def test_convert_says_so_when_there_is_nothing_to_build(convert, qapp):
    Maker.verilogFile[0] = ""
    convert.refresh_subject()
    assert "No design yet" in convert.subjectLabel.text()
    assert "Author" in convert.subjectLabel.toolTip()


def test_the_top_module_picker_stays_hidden_for_one_module(author, convert,
                                                           qapp):
    """The automatic pick is right for essentially every design, so offering a
    choice implies a decision the user does not normally have to make."""
    _paste(author, NAND)
    convert.refresh_subject()
    assert convert.topRow.isVisible() is False
    assert convert.selected_top_module() is None


def test_the_top_module_picker_appears_for_a_multi_module_design(author,
                                                                 convert,
                                                                 qapp):
    _paste(author, ("module half_adder(input a, output s);\nendmodule\n"
                    "module full_adder(input a, output s);\n"
                    "  half_adder u0(.a(a), .s(s));\n"
                    "endmodule\n"))
    convert.show()
    convert.refresh_subject()
    assert convert.topRow.isVisible() is True
    items = [convert.topModuleBox.itemText(i)
             for i in range(convert.topModuleBox.count())]
    assert items == ["half_adder", "full_adder"]
    # The guess is described until the user overrides it.
    assert "full_adder" in convert.subjectLabel.text()

    # The box shows what will be built, so it starts on the guess.
    assert convert.topModuleBox.currentText() == "full_adder"

    convert.topModuleBox.setCurrentText("half_adder")
    assert convert.selected_top_module() == "half_adder"
    assert "half_adder" in convert.subjectLabel.text()

    # The choice survives leaving the stage and coming back...
    convert.refresh_subject()
    assert convert.selected_top_module() == "half_adder"

    # ...and heals itself when the design no longer contains it.
    _paste(author, NAND)
    convert.refresh_subject()
    assert convert.topRow.isVisible() is False
    assert "nand_gate" in convert.subjectLabel.text()


def test_the_library_lives_under_the_chosen_workspace(qapp, tmp_path,
                                                      monkeypatch):
    """Not a hardcoded ~/eSim-Workspace: designs belong beside the projects
    they are built for, and must follow the user's workspace choice."""
    monkeypatch.setattr(verilog_library.paths, "read_workspace",
                        lambda *a, **k: ("0", str(tmp_path / "chosen")))
    assert verilog_library.library_root() == \
        os.path.join(str(tmp_path / "chosen"), "VerilogLibrary")
