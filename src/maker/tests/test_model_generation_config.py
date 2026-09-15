import importlib
import os

import pytest
from PyQt6 import QtWidgets

from maker import CosimConfig, ModelGeneration


def test_constructor_survives_missing_nghdl_config(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(
        str(tmp_path / "counter.v"), terminal)

    assert model.nghdl_home == ""
    assert model.release_dir == ""
    assert model.src_home == ""
    assert model.digital_home == os.path.join(
        str(tmp_path), ".nghdl", "DigitalModelLibrary", "Ngveri")
    assert model.require_legacy_toolchain() is False
    assert "toolchain not configured" in terminal.toPlainText()


def test_constructor_accepts_partial_nghdl_config(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    config_dir = tmp_path / ".nghdl"
    config_dir.mkdir()
    (config_dir / "config.ini").write_text(
        "[NGHDL]\nNGHDL_HOME=/opt/nghdl\n"
    )
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(
        str(tmp_path / "counter.v"), terminal)

    assert model.nghdl_home == "/opt/nghdl"
    assert model.release_dir == ""
    assert model.require_legacy_toolchain() is False


def test_verilog_parse_keeps_wire_reg_in_identifiers(qapp, tmp_path,
                                                     monkeypatch):
    """The wire/reg keyword strip must not punch holes in identifiers
    that merely CONTAIN 'wire'/'reg' (out_reg, wire_en, data_reg). A bare
    substring replace mangled the module name (parse then fails to match)
    and the port names; a word-boundary regex leaves them intact."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    # Module and port names each contain 'reg'/'wire' as a sub-token.
    verilog = (
        "module out_reg(clk, wire_en, data_reg, q);\n"
        "input clk, wire_en;\n"
        "output reg data_reg;\n"
        "output reg q;\n"
        "endmodule\n"
    )
    (tmp_path / "out_reg.v").write_text(verilog)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(
        str(tmp_path / "out_reg.v"), terminal)
    model.modelpath = str(tmp_path) + os.sep

    # Module name "out_reg" survives -> the parse matches -> "No Error".
    assert model.verilogParse(make_symbol=False) == "No Error"

    conn = (tmp_path / "connection_info.txt").read_text()
    # Every port identifier lands intact, un-mangled.
    for port in ("clk", "wire_en", "data_reg", "q"):
        assert port in conn
    # The old substring replace would have left the truncated stems instead.
    assert "data_ " not in conn
    assert "_en" not in conn.replace("wire_en", "")


@pytest.mark.parametrize("fname, expected_stem, valid", [
    ("counter.v", "counter", True),    # plain single extension
    ("fir.v1.v", "fir.v1", False),     # dotted stem: unified, then refused
    ("counter", "counter", True),      # no extension at all
    ("Model.V", "model", True),        # uppercase name + uppercase extension
])
def test_model_stem_is_unified_and_validated(qapp, tmp_path, monkeypatch,
                                             fname, expected_stem, valid):
    """One os.path.splitext-based stem drives every derived artifact (model
    dir, cfunc, ifspec, sim_main, modpath), so a dotted name can't split-brain
    the build the way split('.')[0] did. The stem is then validated as a bare
    identifier -- 'fir.v1' unifies correctly but is refused up front, since it
    would otherwise reach cmpp/make as the invalid C name cm_fir.v1."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(tmp_path / fname), terminal)

    assert model.model_stem == expected_stem
    assert model._stem_is_valid(model.model_stem) is valid


def test_convert_on_a_fresh_tree_creates_the_model_dir(qapp, tmp_path,
                                                       monkeypatch):
    """The digital-model root is built lazily (the remove dialog or a
    previous build makes it), so on a fresh install verilogfile's os.mkdir hit
    a MISSING PARENT and raised FileNotFoundError. The generic handler then
    told the user only "Error in Ngspice code model generation", naming
    nothing. os.makedirs(exist_ok=True) builds the whole chain instead."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    src = tmp_path / "counter.v"
    src.write_text(
        "module counter(clk, q);\ninput clk;\noutput q;\nendmodule\n")

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(src), terminal)
    # The fresh-install state: nothing under ~/.nghdl exists yet.
    assert not os.path.exists(model.digital_home)

    assert model.verilogfile() == "No Error"
    assert os.path.isdir(model.modelpath)
    assert os.path.isfile(os.path.join(model.modelpath, "counter.v"))


def test_modpathlst_on_a_fresh_tree_creates_the_list(qapp, tmp_path,
                                                     monkeypatch):
    """modpath.lst was opened 'r' before it -- or its directory -- existed.
    It is now created on demand, exactly as the remove dialog already did."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(tmp_path / "counter.v"),
                                            terminal)
    assert not os.path.exists(model.digital_home)

    model.modpathlst()                       # must not raise

    assert os.path.isfile(os.path.join(model.digital_home, "modpath.lst"))


def test_modpathlst_appends_built_model_once(qapp, tmp_path, monkeypatch):
    """The entry survives the follow-up prune only when its build dir has an
    ifspec.ifs (what cmpp needs), and a second convert must not duplicate it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(tmp_path / "counter.v"),
                                            terminal)
    build = os.path.join(model.digital_home, "counter")
    os.makedirs(build)
    open(os.path.join(build, "ifspec.ifs"), "w").close()

    model.modpathlst()
    model.modpathlst()

    listed = open(os.path.join(model.digital_home, "modpath.lst")).read()
    assert listed.split() == ["counter"]


def test_modpathlst_does_not_glue_onto_an_unterminated_last_line(
        qapp, tmp_path, monkeypatch):
    """A hand-edited list whose final line lacks '\n' used to swallow the new
    name into "oldmodelcounter" -- one ghost entry like that makes cmpp abort
    the ENTIRE Ngveri.cm build, for every model."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(tmp_path / "counter.v"),
                                            terminal)
    for name in ("oldmodel", "counter"):
        build = os.path.join(model.digital_home, name)
        os.makedirs(build)
        open(os.path.join(build, "ifspec.ifs"), "w").close()
    mp = os.path.join(model.digital_home, "modpath.lst")
    with open(mp, "w") as fh:
        fh.write("oldmodel")                 # no trailing newline

    model.modpathlst()

    assert open(mp).read().split() == ["oldmodel", "counter"]


def test_ifspec_output_ports_go_through_out_port_table(qapp, tmp_path,
                                                       monkeypatch):
    """The output loop appended to in_port_table, leaving the later
    "for item in out_port_table" writer dead. The file came out right purely
    because one list preserved the order, so any edit touching only
    out_port_table silently did nothing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(tmp_path / "counter.v"),
                                            terminal)
    model.modelpath = str(tmp_path) + os.sep
    model.input_port = ["clk:0", "d:3"]
    model.output_port = ["q:3"]

    model.ifspecwrite()
    ifs = (tmp_path / "ifspec.ifs").read_text()

    # Every port still lands, with the right direction and in the right order
    # (the cfunc argument order follows this file).
    assert ifs.count("PORT_TABLE:") == 3
    assert ifs.count("Direction:\tin\n") == 2
    assert ifs.count("Direction:\tout\n") == 1
    assert ifs.index("Port_Name:\tclk") < ifs.index("Port_Name:\tq")

    # Decisive: the blank line the writer emits BETWEEN the two tables now
    # falls after the last INPUT block. While both loops fed in_port_table it
    # was stranded after the output block instead, since the second writer
    # loop had nothing to iterate.
    assert ifs.count("no\n\n\nPORT_TABLE:") == 1


def test_ifspec_description_names_the_verilog_toolchain(qapp, tmp_path,
                                                        monkeypatch):
    """This ifspec is generated from Verilog by Verilator, but the
    NAME_TABLE description was copy-pasted from the GHDL generator. It is
    echoed back in ngspice's own error messages, so it misdirects debugging."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)

    terminal = QtWidgets.QTextEdit()
    model = ModelGeneration.ModelGeneration(str(tmp_path / "counter.v"),
                                            terminal)
    model.modelpath = str(tmp_path) + os.sep
    model.input_port = ["clk:0"]
    model.output_port = ["q:0"]

    model.ifspecwrite()
    ifs = (tmp_path / "ifspec.ifs").read_text()

    assert "ghdl" not in ifs.lower()
    assert "Model generated from Verilog code counter.v" in ifs
