"""Characterization and skip-collector tests for the ngspice→Modelica
converter.

The converter had no tests and swallowed every unmappable parameter with a
bare ``except BaseException: pass``, so its output was silently incomplete.
These:

  * pin the current end-to-end translation of a known ``.cir.out`` fixture
    (a passive parallel-resonance RLC circuit), so a future refactor of this
    legacy file can't quietly change the generated Modelica, and
  * prove the new ``skipped`` collector records dropped parameters instead of
    discarding them.
"""
import os

import pytest

from ngspicetoModelica.NgspicetoModelica import NgMoConverter

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MAP = os.path.join(_REPO, "library", "ngspicetoModelica", "Mapping.json")
_NETLIST = os.path.join(
    _REPO, "Examples", "Parallel_Resonance", "Parallel_Resonance.cir.out")


@pytest.fixture
def converter():
    assert os.path.exists(_MAP), "Modelica mapping fixture missing"
    return NgMoConverter(_MAP)


def _run_pipeline(conv, dir_name):
    """Drive the same sequence ModelicaUI.callConverter uses, up to the point
    where the .mo body lines are assembled."""
    netlist = conv.readNetlist(_NETLIST)
    optionInfo, schematicInfo = conv.separateNetlistInfo(netlist)
    modelName, modelInfo, subcktName, paramInfo, transInfo, inbuilt = \
        conv.addModel(optionInfo)
    compInfo, _plotInfo = conv.separatePlot(schematicInfo)
    node, nodeDic, _pinInit, _pinProt = conv.nodeSeparate(
        compInfo, '0', [], subcktName, [])
    modelicaCompInit, numNodesSub = conv.compInit(
        compInfo, node, modelInfo, subcktName, dir_name, transInfo, inbuilt)
    connInfo = conv.connectInfo(
        compInfo, node, nodeDic, numNodesSub, subcktName)
    return modelicaCompInit, connInfo


def test_rlc_fixture_translation_is_stable(converter, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    comp, conn = _run_pipeline(converter, str(tmp_path))

    assert comp == [
        "Analog.Sources.ConstantVoltage v1(V = 1);",
        "Analog.Basic.Resistor r1(R = 100);",
        "Analog.Basic.Inductor l1(L = 100e-3);",
        "Analog.Basic.Capacitor c1(C = 10e-6);",
        "Analog.Basic.Resistor r2(R = 1000);",
        "Analog.Basic.Ground g;",
    ]
    assert conn == [
        "connect(r1.p,nout);",
        "connect(r1.n,ngnd);",
        "connect(l1.p,nout);",
        "connect(l1.n,ngnd);",
        "connect(c1.p,ngnd);",
        "connect(c1.n,nout);",
        "connect(v1.p,nin);",
        "connect(v1.n,ngnd);",
        "connect(r2.p,nout);",
        "connect(r2.n,nin);",
        "connect(g.p,ngnd);",
    ]
    # A fully-supported passive circuit skips nothing.
    assert converter.skipped == []


def test_record_skip_collects_dropped_params(converter):
    # Simulate the four param-mapping sites hitting an unmappable parameter.
    converter._record_skip("q1", "vaf", KeyError("vaf"))
    converter._record_skip("m1", "kp", ValueError("kp"))

    assert len(converter.skipped) == 2
    assert converter.skipped[0].startswith("q1.vaf")
    assert "KeyError" in converter.skipped[0]
    assert converter.skipped[1].startswith("m1.kp")
