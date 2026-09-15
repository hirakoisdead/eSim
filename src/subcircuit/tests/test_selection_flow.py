# ==============================================================================
#  test_selection_flow.py -- Edit and Convert must act on the same subcircuit.
#
#  A subcircuit folder legitimately ships the .sub of every subcircuit nested
#  inside it (2bitmul carries half_adder.sub beside its own). Edit and Convert
#  used to resolve that folder independently: Edit opened the one the user
#  picked, Convert re-derived the folder-name match and rebuilt a different
#  model -- no error, wrong .sub on disk.
#
#  These tests drive the real widgets headless and assert the two agree, plus
#  the error paths that must NOT silently guess.
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
from subcircuit import openSub as openSubMod                     # noqa: E402
from subcircuit import convertSub as convertSubMod               # noqa: E402
from subcircuit import newSub as newSubMod                       # noqa: E402
from kicadtoNgspice import KicadNetlister                        # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class FakeThread:
    """Stand-in for Worker.WorkerThread: records the command, spawns nothing."""

    launched = []

    def __init__(self, cmd):
        self.cmd = cmd

    def start(self):
        FakeThread.launched.append(self.cmd)


class FakeDock:
    """Captures what Convert hands to the KiCad-to-Ngspice editor."""

    def __init__(self):
        self.calls = []

    def kicadToNgspiceEditor(self, clarg1, clarg2=None, **kw):
        self.calls.append((clarg1, clarg2, kw))


@pytest.fixture(autouse=True)
def clean_selection(monkeypatch):
    """Every test starts with no subcircuit selected and no real processes.

    ``current_subcircuit`` is a CLASS attribute shared by every Appconfig
    instance, so a leaked selection would silently steer the next test.
    """
    FakeThread.launched = []
    monkeypatch.setattr(openSubMod, 'WorkerThread', FakeThread)
    monkeypatch.setattr(newSubMod.Worker, 'WorkerThread', FakeThread)
    # Convert regenerates the netlist first; these tests are about WHICH
    # subcircuit it acts on, so the generator is stubbed to the "cannot help,
    # use the existing .cir" answer it gives on a KiCad-4 folder.
    monkeypatch.setattr(KicadNetlister, 'generate_netlist',
                        lambda d, s: (False, 'stubbed'))
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}
    yield
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}


def _make_sub(root, folder, files):
    d = os.path.join(str(root), folder)
    os.makedirs(d, exist_ok=True)
    for name in files:
        with open(os.path.join(d, name), 'w') as fh:
            fh.write('* test\n')
    return d


def _convert(dock):
    """Click Convert and settle the background netlist step."""
    widget = convertSubMod.convertSub(dock)
    widget.createSub()
    job = widget._netlist_job
    if job is not None:
        assert job.wait(20000), 'netlist job did not finish'
        _app.processEvents()
    return widget


# -- the agreement -----------------------------------------------------------

def test_convert_rebuilds_the_subcircuit_that_edit_opened(tmp_path):
    """The defect this whole change exists for."""
    d = _make_sub(tmp_path, '2bitmul', [
        '2bitmul.sub', '2bitmul.cir', '2bitmul.kicad_sch',
        'half_adder.sub', 'half_adder.cir', 'half_adder.kicad_sch'])

    opener = openSubMod.openSub()
    assert opener.body(d, stem='half_adder') == 'half_adder'
    assert Appconfig.current_subcircuit['Stem'] == 'half_adder'
    assert 'half_adder.kicad_sch' in FakeThread.launched[-1]
    assert '2bitmul.kicad_sch' not in FakeThread.launched[-1]

    dock = FakeDock()
    _convert(dock)
    netlist, kind, kw = dock.calls[0]
    assert os.path.basename(netlist) == 'half_adder.cir'
    assert kind == 'sub'
    # ... and the converter tab is named for the subcircuit, not the project.
    assert kw['label'] == 'half_adder'


def test_folder_name_match_still_converts_silently(tmp_path):
    """152 shipped folders hold several .sub files with one named after the
    folder. They resolved without a prompt for years; they still must."""
    d = _make_sub(tmp_path, '2bitmul',
                  ['2bitmul.sub', '2bitmul.cir', 'half_adder.sub'])

    opener = openSubMod.openSub()
    # No stem passed and no chooser patched: a prompt here would hang/return
    # None, so reaching '2bitmul' proves nothing was asked.
    assert opener.body(d) == '2bitmul'

    dock = FakeDock()
    _convert(dock)
    assert os.path.basename(dock.calls[0][0]) == '2bitmul.cir'


def test_folder_with_only_a_netlist_converts(tmp_path):
    """The 25-folder regression, end to end through the button."""
    d = _make_sub(tmp_path, 'Logic_Gates',
                  ['and2.sub', 'or2.sub', 'Logic_Gates.cir'])
    Appconfig().set_current_subcircuit(d)

    dock = FakeDock()
    _convert(dock)
    assert os.path.basename(dock.calls[0][0]) == 'Logic_Gates.cir'


def test_new_subcircuit_is_selected_and_convertible_after_drawing(tmp_path,
                                                                  monkeypatch):
    """New -> draw -> Convert must work on the first pass, before any .sub
    exists (Convert is what creates it)."""
    lib = tmp_path / 'library' / 'SubcircuitLibrary'
    lib.mkdir(parents=True)
    monkeypatch.setattr(newSubMod.paths, 'library_path',
                        lambda *parts: os.path.join(str(lib), *parts[1:]))

    newSubMod.NewSub().createSubcircuit('my_block')
    sel = Appconfig.current_subcircuit
    assert sel['Stem'] == 'my_block'
    assert os.path.isdir(sel['SubcircuitName'])
    assert 'my_block.kicad_sch' in FakeThread.launched[-1]

    # The user draws and exports a netlist in eeschema.
    with open(os.path.join(sel['SubcircuitName'], 'my_block.cir'), 'w') as fh:
        fh.write('* netlist\n')

    dock = FakeDock()
    _convert(dock)
    assert os.path.basename(dock.calls[0][0]) == 'my_block.cir'


# -- the refusals ------------------------------------------------------------

def test_convert_without_a_selection_reports_and_does_nothing(monkeypatch):
    shown = []
    monkeypatch.setattr(convertSubMod.convertSub, '_error',
                        lambda self, m: shown.append(m))
    dock = FakeDock()
    _convert(dock)
    assert dock.calls == []
    assert 'select the subcircuit first' in shown[0]


def test_ambiguous_folder_is_refused_not_guessed(tmp_path, monkeypatch):
    """Several .sub files, none matching the folder, no netlist: there is no
    honest answer, so Convert explains instead of building the wrong model."""
    d = _make_sub(tmp_path, 'TCA965', ['a.sub', 'b.sub'])
    Appconfig().set_current_subcircuit(d)
    shown = []
    monkeypatch.setattr(convertSubMod.convertSub, '_error',
                        lambda self, m: shown.append(m))

    dock = FakeDock()
    _convert(dock)
    assert dock.calls == []
    assert 'several subcircuits' in shown[0]


def test_missing_netlist_is_refused(tmp_path, monkeypatch):
    d = _make_sub(tmp_path, 'drawn_only', ['drawn_only.kicad_sch'])
    Appconfig().set_current_subcircuit(d)
    shown = []
    monkeypatch.setattr(convertSubMod.convertSub, '_error',
                        lambda self, m: shown.append(m))

    dock = FakeDock()
    _convert(dock)
    assert dock.calls == []
    assert 'Kicad netlist file' in shown[0]


def test_failed_creation_leaves_the_previous_selection_alone(tmp_path,
                                                             monkeypatch):
    """A subcircuit that could not be created must not become the selection --
    the next Convert would report a missing netlist instead of the permission
    problem the user actually hit."""
    good = _make_sub(tmp_path, 'good', ['good.sub', 'good.cir'])
    Appconfig().set_current_subcircuit(good)

    lib = tmp_path / 'lib'
    lib.mkdir()
    monkeypatch.setattr(newSubMod.paths, 'library_path',
                        lambda *parts: os.path.join(str(lib), *parts[1:]))
    monkeypatch.setattr(newSubMod.os, 'mkdir',
                        lambda p: (_ for _ in ()).throw(PermissionError('ro')))
    monkeypatch.setattr(newSubMod.Dialogs, 'critical',
                        lambda *a, **k: None)

    newSubMod.NewSub().createSubcircuit('doomed')
    assert Appconfig.current_subcircuit['SubcircuitName'] == good
    assert Appconfig.current_subcircuit['Stem'] == 'good'


def test_cancelled_folder_dialog_changes_nothing():
    opener = openSubMod.openSub()
    assert opener.body('') is None
    assert Appconfig.current_subcircuit['SubcircuitName'] is None
