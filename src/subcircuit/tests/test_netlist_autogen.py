# ==============================================================================
#  test_netlist_autogen.py -- Convert regenerates the subcircuit's netlist.
#
#  KiCad >= 7 rewrote `--format spice` around its Simulation Model system, and
#  every eSim symbol (no Sim.* model) comes out with its connectivity stripped:
#  "U2 __U2", one placeholder node, no nets. eSim's project converter stopped
#  using it and regenerates <proj>.cir from the generic `kicadxml` netlist
#  instead. The subcircuit converter was never wired to that, so building a
#  subcircuit on a modern KiCad meant hand-exporting a netlist that had already
#  lost its nets.
#
#  These tests cover the wiring (which folder/stem the generator is handed, and
#  that every failure mode still falls through to the existing .cir) and the
#  compatibility claim underneath it: that a netlist produced by eSim's own
#  generator still carries the PORT line .sub creation depends on.
# ==============================================================================
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6 import QtWidgets                                      # noqa: E402
from configuration.Appconfig import Appconfig                    # noqa: E402
from subcircuit import convertSub as convertSubMod               # noqa: E402
from kicadtoNgspice import KicadNetlister                        # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class FakeDock:
    def __init__(self):
        self.calls = []

    def kicadToNgspiceEditor(self, clarg1, clarg2=None, **kw):
        self.calls.append((clarg1, clarg2, kw))


@pytest.fixture(autouse=True)
def clean_selection():
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}
    yield
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}


def _make_sub(root, name, files):
    d = os.path.join(str(root), name)
    os.makedirs(d, exist_ok=True)
    for f in files:
        with open(os.path.join(d, f), 'w') as fh:
            fh.write('* existing\n')
    return d


def _convert(dock):
    widget = convertSubMod.convertSub(dock)
    widget.createSub()
    job = widget._netlist_job
    if job is not None:
        assert job.wait(20000), 'netlist job did not finish'
        _app.processEvents()
    return widget


# -- wiring ------------------------------------------------------------------

def test_convert_regenerates_the_netlist_for_the_selected_subcircuit(
        tmp_path, monkeypatch):
    d = _make_sub(tmp_path, '2bitmul',
                  ['half_adder.kicad_sch', 'half_adder.cir', '2bitmul.sub'])
    Appconfig().set_current_subcircuit(d, 'half_adder')

    seen = []

    def fake(proj_dir, proj_name):
        seen.append((proj_dir, proj_name))
        return True, 'generated'

    monkeypatch.setattr(KicadNetlister, 'generate_netlist', fake)

    dock = FakeDock()
    _convert(dock)
    assert seen == [(d, 'half_adder')]
    assert os.path.basename(dock.calls[0][0]) == 'half_adder.cir'


def test_generation_failure_still_opens_the_existing_netlist(tmp_path,
                                                             monkeypatch):
    """The legacy path must survive every reason the generator can decline:
    no .kicad_sch (the 460 KiCad-4 subcircuits eSim ships) or no kicad-cli."""
    d = _make_sub(tmp_path, 'legacy', ['legacy.sch', 'legacy.cir'])
    Appconfig().set_current_subcircuit(d)
    monkeypatch.setattr(KicadNetlister, 'generate_netlist',
                        lambda a, b: (False, 'No .kicad_sch found'))

    dock = FakeDock()
    _convert(dock)
    assert os.path.basename(dock.calls[0][0]) == 'legacy.cir'


def test_a_raising_generator_still_opens_the_existing_netlist(tmp_path,
                                                              monkeypatch):
    """Auto-generation is an improvement layered on the old workflow; a crash
    inside it must never be worse than not having it."""
    d = _make_sub(tmp_path, 'legacy', ['legacy.sch', 'legacy.cir'])
    Appconfig().set_current_subcircuit(d)

    def boom(a, b):
        raise RuntimeError('kicad-cli exploded')

    monkeypatch.setattr(KicadNetlister, 'generate_netlist', boom)

    dock = FakeDock()
    _convert(dock)
    assert os.path.basename(dock.calls[0][0]) == 'legacy.cir'


def test_a_kicad4_subcircuit_netlist_is_left_untouched(tmp_path, monkeypatch):
    """Byte-identity check on the shipped-library shape: no .kicad_sch means
    the real generator declines before writing anything."""
    d = _make_sub(tmp_path, 'legacy', ['legacy.sch'])
    cir = os.path.join(d, 'legacy.cir')
    original = '* handcrafted netlist\nr1 in out 1k\n.end\n'
    with open(cir, 'w') as fh:
        fh.write(original)
    Appconfig().set_current_subcircuit(d)

    dock = FakeDock()
    _convert(dock)

    with open(cir) as fh:
        assert fh.read() == original
    assert os.path.basename(dock.calls[0][0]) == 'legacy.cir'


def test_no_netlist_anywhere_is_reported_not_silently_converted(tmp_path,
                                                                monkeypatch):
    d = _make_sub(tmp_path, 'drawn', ['drawn.kicad_sch'])
    Appconfig().set_current_subcircuit(d)
    monkeypatch.setattr(KicadNetlister, 'generate_netlist',
                        lambda a, b: (False, 'kicad-cli not found'))
    shown = []
    monkeypatch.setattr(convertSubMod.convertSub, '_error',
                        lambda self, m: shown.append(m))

    dock = FakeDock()
    _convert(dock)
    assert dock.calls == []
    assert 'Kicad netlist file' in shown[0]


def test_a_second_click_while_exporting_is_ignored(tmp_path, monkeypatch):
    """kicad-cli can take 5-15 s on a cold Windows boot. A second Convert must
    not start a competing export over the same files."""
    import threading
    release = threading.Event()

    def slow(a, b):
        release.wait(20)
        return True, 'generated'

    d = _make_sub(tmp_path, 'slow', ['slow.kicad_sch', 'slow.cir'])
    Appconfig().set_current_subcircuit(d)
    monkeypatch.setattr(KicadNetlister, 'generate_netlist', slow)

    dock = FakeDock()
    widget = convertSubMod.convertSub(dock)
    widget.createSub()
    first = widget._netlist_job
    widget.createSub()
    assert widget._netlist_job is first

    release.set()
    assert first.wait(20000)
    _app.processEvents()
    assert len(dock.calls) == 1


def test_editor_buffers_are_flushed_before_converting(tmp_path, monkeypatch):
    """A subcircuit edited in eSim's own text editor used to be converted from
    its previous contents: the project path flushed dirty buffers, this one
    never did."""
    d = _make_sub(tmp_path, 'legacy', ['legacy.sch', 'legacy.cir'])
    Appconfig().set_current_subcircuit(d)
    monkeypatch.setattr(KicadNetlister, 'generate_netlist',
                        lambda a, b: (False, 'stub'))

    flushed = []
    import codeEditor.EditorWindow as EW
    monkeypatch.setattr(EW, 'flush_all_dirty',
                        lambda: flushed.append(True))

    _convert(FakeDock())
    assert flushed == [True]


# -- the compatibility claim -------------------------------------------------

PORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="U1"><value>PORT</value><fields/></comp>
    <comp ref="R1"><value>1k</value><fields/></comp>
  </components>
  <nets>
    <net code="1" name="in">
      <node ref="U1" pin="1"/><node ref="R1" pin="1"/>
    </net>
    <net code="2" name="out">
      <node ref="U1" pin="2"/><node ref="R1" pin="2"/>
    </net>
  </nets>
</export>
"""


def _generated_lines(tmp_path):
    xml = tmp_path / 'sub.netlist.xml'
    xml.write_text(PORT_XML)
    return KicadNetlister.xml_to_spice_lines(
        str(xml), title='half_adder', proj_dir=str(tmp_path))


def test_generated_netlist_keeps_the_port_line_sub_creation_needs(tmp_path):
    """createSubFile finds a subcircuit's ports by scanning .cir.out for a line
    whose first word starts with 'u' and whose last word is 'port'. Processing
    lowercases every line on the way to .cir.out, so the generator's job is to
    emit the PORT component with its nets intact and its 'u' prefix unchanged.
    """
    lines = [line.lower() for line in _generated_lines(tmp_path)]

    port_lines = [line for line in lines
                  if line.split() and line.split()[0].startswith('u')
                  and line.split()[-1] == 'port']
    assert len(port_lines) == 1, lines

    # .subckt takes the nets between the ref and the PORT value, in pin order.
    words = port_lines[0].split()
    assert words[1:-1] == ['in', 'out']


def test_port_is_not_mangled_into_a_subcircuit_instance(tmp_path):
    """A component whose value names a real .sub gets an 'x' prefix so ngspice
    instantiates it. PORT is an eSim marker with no .sub, so it must keep its
    'u' prefix -- an 'xu1' line would make the port undetectable."""
    lines = _generated_lines(tmp_path)
    assert any(line.startswith('u1 ') for line in lines), lines
    assert not any(line.startswith('xu1') for line in lines), lines


def test_generated_netlist_preserves_connectivity(tmp_path):
    """The whole reason for not using KiCad's spice exporter: every part keeps
    a net per pin instead of being degraded to a single placeholder node."""
    lines = _generated_lines(tmp_path)
    r1 = [line for line in lines if line.startswith('r1 ')]
    assert r1 == ['r1 in out 1k'], lines
