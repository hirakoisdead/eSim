# ==============================================================================
#  test_subcircuit_result.py -- what Convert reports after building a .sub.
#
#  The ngspice model is the entire point of the Subcircuit Builder, and its
#  creation was reported only to stdout. Worse, the generic "conversion
#  completed successfully!" dialog fired BEFORE the .sub was written, so a
#  schematic with no PORT element announced success and then immediately raised
#  an error about the file it had not produced.
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
from kicadtoNgspice import KicadtoNgspice                        # noqa: E402
from configuration import Dialogs                                # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# The PORT line as it REALLY appears in a .cir.out: commented out.
# Processing.convertICintoBasicBlocks rewrites every u-component it cannot
# expand as "* <line>", and PORT is not a real spice device, so it always
# arrives here behind a comment marker. An earlier version of this fixture
# used an uncommented line -- which no eSim netlist ever contains -- and that
# is exactly why these tests passed while every real conversion failed with
# "No PORT component found in the schematic".
CIR_OUT = """* half_adder
* u1 in_a in_b sum carry port
r1 in_a sum 1k
.tran 1m 10m
.end
"""

#: The same schematic if the marker were ever absent. Both forms must yield
#: the same interface.
CIR_OUT_UNCOMMENTED = CIR_OUT.replace("* u1 ", "u1 ")


@pytest.fixture
def window():
    """An uninitialised MainWindow: createSubFile only needs the two
    attributes it sets itself."""
    return KicadtoNgspice.MainWindow.__new__(KicadtoNgspice.MainWindow)


@pytest.fixture
def shown(monkeypatch):
    """Capture every dialog raised, in order."""
    seen = []
    for kind in ('information', 'critical', 'warning'):
        monkeypatch.setattr(
            Dialogs, kind,
            lambda parent, title, text, *a, **k: seen.append(
                (title, text, k.get('informative_text', ''))))
    return seen


def _stem(tmp_path, name='half_adder', body=CIR_OUT):
    base = os.path.join(str(tmp_path), name)
    with open(base + '.cir.out', 'w') as fh:
        fh.write(body)
    return base


# -- createSubFile reports its outcome ---------------------------------------

def test_a_written_model_reports_success(window, tmp_path, shown):
    base = _stem(tmp_path)
    assert window.createSubFile(base) is True
    assert os.path.isfile(base + '.sub')


def test_the_port_line_is_found_with_or_without_its_comment_marker(
        window, tmp_path):
    """The regression this file exists to prevent.

    Both forms must produce the same interface -- and the uncommented one must
    not drop its first net, which the original index arithmetic would have
    done had it ever matched.
    """
    a = _stem(tmp_path, name='commented')
    b = _stem(tmp_path, name='plain', body=CIR_OUT_UNCOMMENTED)
    assert window.createSubFile(a) is True
    assert window.createSubFile(b) is True
    ports_a = window._subcktHeader(a + '.sub').split()[2:]
    ports_b = window._subcktHeader(b + '.sub').split()[2:]
    assert ports_a == ['in_a', 'in_b', 'sum', 'carry']
    assert ports_a == ports_b


def test_a_schematic_without_a_port_reports_failure(window, tmp_path, shown):
    base = _stem(tmp_path, body='r1 a b 1k\n.end\n')
    assert window.createSubFile(base) is False
    assert not os.path.isfile(base + '.sub')
    assert 'Subcircuit creation failed' in shown[0][0]


def test_a_missing_netlist_reports_failure(window, tmp_path, shown):
    assert window.createSubFile(os.path.join(str(tmp_path), 'absent')) is False
    assert 'Subcircuit creation failed' in shown[0][0]


# -- the report itself -------------------------------------------------------

def test_the_report_names_the_file_and_its_ports(window, tmp_path, shown):
    base = _stem(tmp_path)
    window.createSubFile(base)
    window._reportSubcircuitBuilt(base)

    title, text, detail = shown[-1]
    assert title == 'Subcircuit built'
    assert 'half_adder.sub' in text
    assert base + '.sub' in detail
    # The .subckt header is echoed so the port list can be checked against the
    # parent circuit's symbol without opening anything.
    assert '.subckt half_adder' in detail
    assert '4 ports' in detail
    assert 'in_a, in_b, sum, carry' in detail


def test_the_report_survives_a_deleted_model_file(window, tmp_path, shown):
    """The dialog is about reassurance; it must not become a second failure if
    the file vanished between writing and reporting."""
    base = _stem(tmp_path)
    window.createSubFile(base)
    os.remove(base + '.sub')
    window._reportSubcircuitBuilt(base)
    assert shown[-1][0] == 'Subcircuit built'


def test_a_single_port_is_not_pluralised(window, tmp_path, shown):
    base = _stem(tmp_path, name='one', body='* u1 only port\n.end\n')
    window.createSubFile(base)
    window._reportSubcircuitBuilt(base)
    assert '1 port:' in shown[-1][2]


# -- the interface warning ---------------------------------------------------

def test_a_changed_port_count_is_a_warning_not_a_success(window, tmp_path,
                                                         shown):
    """A subcircuit's port count is its interface. Rebuilding with a different
    one silently mis-wires every schematic already using the block, and this is
    the only place eSim can say so. It happens for real: a few library
    subcircuits ship a .kicad_sch that is a different revision from the .sub
    beside it (74HC157 goes 14 -> 16 on an honest rebuild).
    """
    base = _stem(tmp_path)
    window.createSubFile(base)
    window._reportSubcircuitBuilt(base, previous_ports=2)

    title, text, detail = shown[-1]
    assert title == 'Subcircuit ports changed'
    assert 'now has 4 ports; it had 2' in text
    assert 'will need its symbol and connections updated' in detail
    # The header is still there: the warning adds context, it does not replace
    # the report.
    assert '.subckt half_adder' in detail


def test_an_unchanged_port_count_stays_a_plain_success(window, tmp_path,
                                                       shown):
    base = _stem(tmp_path)
    window.createSubFile(base)
    window._reportSubcircuitBuilt(base, previous_ports=4)
    assert shown[-1][0] == 'Subcircuit built'


def test_a_first_build_is_not_a_change(window, tmp_path, shown):
    """No previous model means no interface to break."""
    base = _stem(tmp_path)
    window.createSubFile(base)
    window._reportSubcircuitBuilt(base, previous_ports=None)
    assert shown[-1][0] == 'Subcircuit built'


def test_the_outgoing_port_count_is_read_before_the_rebuild(window, tmp_path):
    """The comparison only works if the OLD model is measured before
    createSubFile overwrites it."""
    base = _stem(tmp_path)
    with open(base + '.sub', 'w') as fh:
        fh.write('.subckt half_adder a b\n.ends half_adder\n')
    assert window._subcktPortCount(base + '.sub') == 2
    window.createSubFile(base)
    assert window._subcktPortCount(base + '.sub') == 4


def test_port_count_of_a_missing_model_is_none(window, tmp_path):
    assert window._subcktPortCount(str(tmp_path / 'nope.sub')) is None
