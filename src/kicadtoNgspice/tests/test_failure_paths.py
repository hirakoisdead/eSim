import os
import sys

import pytest
from PyQt6 import QtWidgets


HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _path in (SRC, PKG):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from kicadtoNgspice import KicadtoNgspice  # noqa: E402
from kicadtoNgspice.Convert import Convert  # noqa: E402
from kicadtoNgspice.Processing import (  # noqa: E402
    PrcocessNetlist,
    UndefinedParametersError,
)


_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _model_xml(path, split="None"):
    path.write_text(
        "<model>"
        "<node_number>1</node_number>"
        "<title>Test model</title>"
        "<name>test_model</name>"
        "<type>Analog</type>"
        f"<split>{split}</split>"
        "</model>"
    )


def test_malformed_model_xml_raises_runtime_error(tmp_path, monkeypatch):
    (tmp_path / "broken.xml").write_text("<model>")
    monkeypatch.setattr(PrcocessNetlist, "modelxmlDIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="broken.*component 'u1'"):
        PrcocessNetlist().convertICintoBasicBlocks(
            ["u1 in out broken"], [], [], []
        )


def test_invalid_vector_details_raise_runtime_error(tmp_path, monkeypatch):
    _model_xml(tmp_path / "bad_vector.xml", split="malformed")
    monkeypatch.setattr(PrcocessNetlist, "modelxmlDIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="bad_vector.*component 'u1'"):
        PrcocessNetlist().convertICintoBasicBlocks(
            ["u1 in bad_vector"], [], [], []
        )


def test_missing_analysis_file_raises_instead_of_exiting(tmp_path):
    window = KicadtoNgspice.MainWindow.__new__(KicadtoNgspice.MainWindow)
    QtWidgets.QWidget.__init__(window)
    window.kicadFile = str(tmp_path / "project.cir")
    window.optionInfo = []
    window.outputOption = []

    with pytest.raises(RuntimeError, match="Analysis file could not be created"):
        window.createNetlistFile([], [])


def test_unreadable_analysis_file_raises_runtime_error(tmp_path, monkeypatch):
    window = KicadtoNgspice.MainWindow.__new__(KicadtoNgspice.MainWindow)
    QtWidgets.QWidget.__init__(window)
    window.kicadFile = str(tmp_path / "project.cir")
    analysis_path = tmp_path / "analysis"
    analysis_path.write_text(".op\n")
    window.optionInfo = []
    window.outputOption = []

    real_open = open

    def fail_for_analysis(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(analysis_path):
            raise OSError("read denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_for_analysis)

    with pytest.raises(RuntimeError, match="Analysis file could not be read"):
        window.createNetlistFile([], [])


def test_undefined_parameters_are_aggregated_without_prompting(monkeypatch):
    def stdin_must_not_be_used(*args, **kwargs):
        raise AssertionError("preprocessing must never read stdin")

    monkeypatch.setattr("builtins.input", stdin_must_not_be_used)

    with pytest.raises(UndefinedParametersError) as caught:
        PrcocessNetlist().preprocessNetlist(
            ["title", "r1 in out {missing_a}", "v1 in 0 {missing_b}",
             "r2 out 0 {missing_a}"],
            {},
        )

    assert caught.value.parameters == ("missing_a", "missing_b")
    assert "define them with a .param directive" in str(caught.value)


def test_defined_parameters_are_replaced_inside_expressions():
    netlist, title = PrcocessNetlist().preprocessNetlist(
        ["Title", "r1 in out {resistance}", "b1 out 0 v={gain}*v(in)"],
        {"resistance": "10k", "gain": "2"},
    )

    assert title == "title"
    assert netlist == ["r1 in out 10k", "b1 out 0 v=2*v(in)"]


def test_source_errors_are_collected_and_abort_conversion():
    converter = Convert(
        [[0, "sine", 0, 4]],
        [],
        ["v1 in 0 sine(0 1 1k)"],
        "project.cir",
    )

    assert converter.addSourceParameter() == ["v1 in 0 sine(0 1 1k)"]
    assert len(converter.errors) == 1
    assert converter.errors[0].startswith("v1 in 0")
    with pytest.raises(RuntimeError, match=r"Some components[\s\S]*v1 in 0"):
        converter.raise_for_errors()


def test_reference_name_falls_back_and_records_broken_xml(tmp_path):
    (tmp_path / "device.xml").write_text("<model></model>")
    converter = Convert(None, None, [], "project.cir")

    assert converter.getReferenceName("device.lib", str(tmp_path)) == "device"
    assert len(converter.errors) == 1
    assert "ref_model is missing" in converter.errors[0]
