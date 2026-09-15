# ==============================================================================
#  test_netlist_generation.py -- generate_netlist never destroys a good netlist.
#
#  Regenerating <proj>.cir from the schematic is an improvement layered on top
#  of a workflow that already worked, so every path where it cannot help must
#  leave the existing .cir exactly as it found it.
#
#  The case that made this urgent is real and shipped: a .kicad_sch can exist
#  and contain nothing. KiCad 6+ migration writes a sibling .kicad_sch beside a
#  legacy .sch, and several folders in eSim's own Subcircuit Library carry an
#  empty stub next to a perfectly good hand-made .cir (3_nor is one). kicad-cli
#  exports those happily -- returncode 0, valid XML, zero components -- so the
#  only thing standing between them and a wiped netlist is this guard.
# ==============================================================================
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kicadtoNgspice import KicadNetlister                        # noqa: E402

EXISTING_CIR = "* handcrafted\nu1 x in out port\nr1 in out 1k\n.end\n"

EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E"><components/><nets/></export>
"""

REAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components><comp ref="R1"><value>1k</value><fields/></comp></components>
  <nets>
    <net code="1" name="in"><node ref="R1" pin="1"/></net>
    <net code="2" name="out"><node ref="R1" pin="2"/></net>
  </nets>
</export>
"""

GROUND_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="R1"><value>1k</value><fields/></comp>
    <comp ref="R2"><value>2k</value><fields/></comp>
  </components>
  <nets>
    <net code="1" name="in"><node ref="R1" pin="1"/></net>
    <net code="2" name="eSim_GND"><node ref="R1" pin="2"/></net>
    <net code="3" name="GND"><node ref="R2" pin="1"/></net>
    <net code="4" name="out"><node ref="R2" pin="2"/></net>
  </nets>
</export>
"""


@pytest.fixture
def project(tmp_path):
    """A folder shaped like a migrated subcircuit: schematic, netlist, both."""
    (tmp_path / 'blk.kicad_sch').write_text('(kicad_sch)')
    (tmp_path / 'blk.cir').write_text(EXISTING_CIR)
    return tmp_path


def _fake_export(monkeypatch, xml_body, returncode=0):
    """Stand in for kicad-cli, writing the XML it would have produced."""
    class Result:
        pass

    def run(cmd, **kwargs):
        out = cmd[cmd.index('-o') + 1]
        if xml_body is not None:
            with open(out, 'w') as fh:
                fh.write(xml_body)
        res = Result()
        res.returncode = returncode
        res.stdout = ''
        res.stderr = 'boom' if returncode else ''
        return res

    monkeypatch.setattr(KicadNetlister.subprocess, 'run', run)
    monkeypatch.setattr(KicadNetlister, '_kicad_cli', lambda: 'kicad-cli')


def _cir(project):
    return (project / 'blk.cir').read_text()


# -- the guard ---------------------------------------------------------------

def test_an_empty_schematic_does_not_wipe_the_existing_netlist(project,
                                                               monkeypatch):
    _fake_export(monkeypatch, EMPTY_XML)
    ok, msg = KicadNetlister.generate_netlist(str(project), 'blk')
    assert ok is False
    assert 'no components' in msg
    assert _cir(project) == EXISTING_CIR


def test_an_empty_schematic_creates_nothing_when_there_is_no_netlist(
        tmp_path, monkeypatch):
    """Nothing to protect here, but an empty .cir would be worse than none: it
    would look like a converted subcircuit and fail later, further from the
    cause."""
    (tmp_path / 'blk.kicad_sch').write_text('(kicad_sch)')
    _fake_export(monkeypatch, EMPTY_XML)
    ok, _msg = KicadNetlister.generate_netlist(str(tmp_path), 'blk')
    assert ok is False
    assert not (tmp_path / 'blk.cir').exists()


def test_a_real_schematic_is_written(project, monkeypatch):
    """The guard must not block the case it exists to protect."""
    _fake_export(monkeypatch, REAL_XML)
    ok, _msg = KicadNetlister.generate_netlist(str(project), 'blk')
    assert ok is True
    assert 'r1 in out 1k' in _cir(project)


def test_esim_and_kicad_ground_names_become_spice_node_zero(tmp_path):
    xml = tmp_path / 'ground.xml'
    xml.write_text(GROUND_XML)

    lines = KicadNetlister.xml_to_spice_lines(str(xml), proj_dir=str(tmp_path))

    assert 'r1 in 0 1k' in lines
    assert 'r2 0 out 2k' in lines


# -- the other refusals ------------------------------------------------------

def test_no_schematic_leaves_the_netlist_alone(tmp_path, monkeypatch):
    """The shape of 460 subcircuits eSim ships: KiCad-4 .sch only."""
    (tmp_path / 'blk.sch').write_text('legacy')
    (tmp_path / 'blk.cir').write_text(EXISTING_CIR)
    _fake_export(monkeypatch, REAL_XML)
    ok, msg = KicadNetlister.generate_netlist(str(tmp_path), 'blk')
    assert ok is False
    assert 'No .kicad_sch' in msg
    assert (tmp_path / 'blk.cir').read_text() == EXISTING_CIR


def test_no_kicad_cli_leaves_the_netlist_alone(project, monkeypatch):
    monkeypatch.setattr(KicadNetlister, '_kicad_cli', lambda: None)
    ok, msg = KicadNetlister.generate_netlist(str(project), 'blk')
    assert ok is False
    assert 'kicad-cli not found' in msg
    assert _cir(project) == EXISTING_CIR


def test_a_failed_export_leaves_the_netlist_alone(project, monkeypatch):
    _fake_export(monkeypatch, None, returncode=1)
    ok, msg = KicadNetlister.generate_netlist(str(project), 'blk')
    assert ok is False
    assert 'export failed' in msg
    assert _cir(project) == EXISTING_CIR


def test_a_crash_leaves_the_netlist_alone(project, monkeypatch):
    monkeypatch.setattr(KicadNetlister, '_kicad_cli', lambda: 'kicad-cli')

    def boom(*a, **k):
        raise OSError('no such tool')

    monkeypatch.setattr(KicadNetlister.subprocess, 'run', boom)
    ok, msg = KicadNetlister.generate_netlist(str(project), 'blk')
    assert ok is False
    assert 'error' in msg.lower()
    assert _cir(project) == EXISTING_CIR


def test_the_intermediate_xml_is_always_cleaned_up(project, monkeypatch):
    _fake_export(monkeypatch, EMPTY_XML)
    KicadNetlister.generate_netlist(str(project), 'blk')
    assert not (project / 'blk.netlist.xml').exists()
