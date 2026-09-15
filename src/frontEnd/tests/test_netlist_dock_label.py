"""The KiCad-to-Ngspice tab names what it is actually converting.

The converter is opened from two places. A project conversion passes its own
project through and the tab is named after it. A *subcircuit* conversion passes
nothing, so the tab fell back to the open project's name -- a converter titled
"Netlist-my_amplifier-1" while it rebuilt ``half_adder.sub``, with the
subcircuit's name appearing nowhere on screen.

The dock still belongs to the open project for cleanup (Close Project has to
reap the tab), so ownership and label are deliberately separate concerns here.
"""
import pytest
from PyQt6 import QtWidgets

from frontEnd.DockArea import DockArea


@pytest.fixture
def dock(qapp, monkeypatch, tmp_path):
    """A DockArea with the heavy converter window stubbed out."""
    monkeypatch.setattr(
        'kicadtoNgspice.KicadtoNgspice.MainWindow',
        lambda *a, **k: QtWidgets.QLabel('converter'))
    da = DockArea()
    da.obj_appconfig.current_project = {
        "ProjectName": str(tmp_path / 'my_amplifier'), "ProjName": None}
    da.obj_appconfig.dock_dict = {}
    yield da
    da.deleteLater()
    qapp.processEvents()


def _netlist_dock_names(da):
    return [k for k in da._docks if k.startswith('Netlist-')]


def test_project_conversion_is_named_after_the_project(dock, tmp_path):
    dock.kicadToNgspiceEditor(
        str(tmp_path / 'my_amplifier' / 'my_amplifier.cir'),
        projDir=str(tmp_path / 'my_amplifier'), projName='my_amplifier')
    assert _netlist_dock_names(dock) == ['Netlist-my_amplifier-1']


def test_subcircuit_conversion_is_named_after_the_subcircuit(dock, tmp_path):
    dock.kicadToNgspiceEditor(
        str(tmp_path / '2bitmul' / 'half_adder.cir'), 'sub',
        label='half_adder')
    assert _netlist_dock_names(dock) == ['Netlist-half_adder-1']


def test_a_labelled_conversion_still_belongs_to_the_open_project(dock,
                                                                 tmp_path):
    """Ownership is unchanged: Close Project must still reap the tab, so the
    dock stays registered under the project even though it is named for the
    subcircuit."""
    proj = str(tmp_path / 'my_amplifier')
    dock.kicadToNgspiceEditor(
        str(tmp_path / '2bitmul' / 'half_adder.cir'), 'sub',
        label='half_adder')
    registered = dock.obj_appconfig.dock_dict.get(proj, [])
    assert len(registered) == 1
    assert registered[0] is dock._docks['Netlist-half_adder-1']


def test_no_label_keeps_the_previous_behaviour(dock, tmp_path):
    """Callers that pass no label are unaffected."""
    dock.kicadToNgspiceEditor(str(tmp_path / 'x.cir'))
    assert _netlist_dock_names(dock) == ['Netlist-my_amplifier-1']


def test_converter_module_is_the_one_stubbed():
    """Guards the stub target: if MainWindow moves, these tests would silently
    run against the real (heavy) converter window instead of the stub."""
    import kicadtoNgspice.KicadtoNgspice as mod
    assert hasattr(mod, 'MainWindow')
