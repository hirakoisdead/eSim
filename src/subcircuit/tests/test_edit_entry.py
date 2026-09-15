# ==============================================================================
#  test_edit_entry.py -- what the Edit button asks, and what it does with the
#  answer.
#
#  Edit now opens the library picker first and falls through to the original
#  folder dialog on Browse. The paths that matter: a chosen subcircuit is
#  opened AND recorded (so Convert rebuilds that one), Browse still works, and
#  cancelling anywhere changes nothing.
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

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class FakeThread:
    launched = []

    def __init__(self, cmd):
        self.cmd = cmd

    def start(self):
        FakeThread.launched.append(self.cmd)


class FakePicker:
    """Stands in for SubcircuitPicker: answers, then reports it was closed."""

    def __init__(self, accepted=True, chosen=None, browse=False):
        self._accepted = accepted
        self.chosen = chosen
        self.browse = browse
        self.deleted = False

    def exec(self):
        return (QtWidgets.QDialog.DialogCode.Accepted if self._accepted
                else QtWidgets.QDialog.DialogCode.Rejected)

    def deleteLater(self):
        self.deleted = True


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    FakeThread.launched = []
    monkeypatch.setattr(openSubMod, 'WorkerThread', FakeThread)
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}
    yield
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}


def _install(monkeypatch, picker):
    import subcircuit.subPicker as mod
    monkeypatch.setattr(mod, 'SubcircuitPicker', lambda *a, **k: picker)
    return picker


def _make_sub(root, name, files):
    d = os.path.join(str(root), name)
    os.makedirs(d, exist_ok=True)
    for f in files:
        with open(os.path.join(d, f), 'w') as fh:
            fh.write('* test\n')
    return d


# -- the picker path ---------------------------------------------------------

def test_a_picked_subcircuit_is_opened_and_recorded(tmp_path, monkeypatch):
    d = _make_sub(tmp_path, '74HC123',
                  ['multivibrator.sub', 'multivibrator.kicad_sch'])
    _install(monkeypatch, FakePicker(chosen=(d, 'multivibrator')))

    assert openSubMod.openSub().body() == 'multivibrator'
    assert Appconfig.current_subcircuit == {
        "SubcircuitName": d, "Stem": 'multivibrator'}
    assert 'multivibrator.kicad_sch' in FakeThread.launched[-1]


def test_the_picker_is_destroyed_after_use(tmp_path, monkeypatch):
    """A dialog left alive per Edit click would accumulate a full library scan
    each time."""
    d = _make_sub(tmp_path, 'lm741', ['lm741.sub', 'lm741.kicad_sch'])
    picker = _install(monkeypatch, FakePicker(chosen=(d, 'lm741')))
    openSubMod.openSub().body()
    assert picker.deleted


def test_cancelling_the_picker_changes_nothing(monkeypatch):
    _install(monkeypatch, FakePicker(accepted=False))
    assert openSubMod.openSub().body() is None
    assert Appconfig.current_subcircuit['SubcircuitName'] is None
    assert FakeThread.launched == []


# -- the browse escape hatch -------------------------------------------------

def test_browse_falls_through_to_the_folder_dialog(tmp_path, monkeypatch):
    """The original behaviour has to stay reachable: a subcircuit kept outside
    the library was openable before and must remain so."""
    d = _make_sub(tmp_path, 'outside', ['outside.sub', 'outside.sch'])
    _install(monkeypatch, FakePicker(browse=True))
    monkeypatch.setattr(openSubMod.openSub, '_browseForFolder',
                        lambda self: d)

    assert openSubMod.openSub().body() == 'outside'
    assert Appconfig.current_subcircuit['SubcircuitName'] == d
    assert 'outside.sch' in FakeThread.launched[-1]


def test_cancelling_the_folder_dialog_after_browse_changes_nothing(
        monkeypatch):
    _install(monkeypatch, FakePicker(browse=True))
    monkeypatch.setattr(openSubMod.openSub, '_browseForFolder',
                        lambda self: '')
    assert openSubMod.openSub().body() is None
    assert Appconfig.current_subcircuit['SubcircuitName'] is None


def test_browsing_to_an_ambiguous_folder_still_asks(tmp_path, monkeypatch):
    """Browse can reach a folder the picker refuses to open; the stem prompt
    is what resolves it, and cancelling that opens nothing."""
    d = _make_sub(tmp_path, 'TCA965', ['a.sub', 'b.sub'])
    _install(monkeypatch, FakePicker(browse=True))
    monkeypatch.setattr(openSubMod.openSub, '_browseForFolder',
                        lambda self: d)
    asked = []
    monkeypatch.setattr(openSubMod.openSub, '_chooseSubcircuit',
                        lambda self, stems: asked.append(stems) or 'b')

    assert openSubMod.openSub().body() == 'b'
    assert asked == [['a', 'b']]
    assert Appconfig.current_subcircuit['Stem'] == 'b'
