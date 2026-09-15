# ==============================================================================
#  test_sub_picker.py -- the Edit dialog.
#
#  Edit opened a bare OS folder dialog over a library of 700+ folders: no
#  search, no way to see which subcircuit a folder holds (119 are named
#  differently from their .sub), and no way to tell a finished model from a
#  schematic somebody started and never converted.
#
#  These tests cover what the list reports, that filtering matches on both the
#  subcircuit and the folder, that an unidentifiable folder is shown but not
#  openable, and that the original folder dialog is still reachable.
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

from PyQt6 import QtCore, QtWidgets                             # noqa: E402
from subcircuit.subPicker import SubcircuitPicker               # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _write(path, text='* test\n'):
    with open(path, 'w') as fh:
        fh.write(text)


@pytest.fixture
def library(tmp_path):
    """A library with one folder of each shape the real one contains."""
    root = tmp_path / 'SubcircuitLibrary'
    root.mkdir()

    built = root / 'lm741'
    built.mkdir()
    _write(built / 'lm741.kicad_sch')
    _write(built / 'lm741.cir')
    _write(built / 'lm741.sub',
           '* Subcircuit lm741\n.subckt lm741 in out vcc\nr1 in out 1k\n'
           '.ends lm741\n')

    # 119 shipped folders look like this: the .sub is not named after them.
    renamed = root / '74HC123'
    renamed.mkdir()
    _write(renamed / 'multivibrator.kicad_sch')
    _write(renamed / 'multivibrator.cir')
    _write(renamed / 'multivibrator.sub',
           '.subckt multivibrator a b\n.ends multivibrator\n')

    drawn = root / 'work_in_progress'
    drawn.mkdir()
    _write(drawn / 'work_in_progress.kicad_sch')

    ambiguous = root / 'TCA965'
    ambiguous.mkdir()
    _write(ambiguous / 'a.sub', '.subckt a x\n.ends a\n')
    _write(ambiguous / 'b.sub', '.subckt b y\n.ends b\n')

    return str(root)


@pytest.fixture
def picker(library):
    p = SubcircuitPicker(library)
    yield p
    p.close()
    p.setParent(None)
    p.deleteLater()
    _app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    _app.processEvents()


def _rows(picker):
    return {picker.table.topLevelItem(i).text(0): picker.table.topLevelItem(i)
            for i in range(picker.table.topLevelItemCount())}


# -- what the list reports ---------------------------------------------------

def test_lists_the_subcircuit_not_the_folder(picker):
    """The folder is called 74HC123; the subcircuit inside it is
    multivibrator. The folder dialog could only ever show the former."""
    rows = _rows(picker)
    assert 'multivibrator' in rows
    assert rows['multivibrator'].text(4) == '74HC123'


def test_reports_ports_netlist_and_model(picker):
    row = _rows(picker)['lm741']
    assert row.text(1) == '3'        # in out vcc
    assert row.text(2) == 'yes'      # netlist
    assert row.text(3) == 'yes'      # model


def test_an_unconverted_subcircuit_is_visibly_unfinished(picker):
    """A drawn-but-never-converted subcircuit is exactly what a student comes
    back to; it must be distinguishable at a glance."""
    row = _rows(picker)['work_in_progress']
    assert row.text(2) == '—'
    assert row.text(3) == '—'
    assert row.text(1) == '—'


def test_every_folder_is_listed_including_the_unidentifiable_one(picker):
    assert len(_rows(picker)) == 4


# -- filtering ---------------------------------------------------------------

def test_filter_matches_the_subcircuit_name(picker):
    picker.search.setText('multi')
    rows = _rows(picker)
    assert not rows['multivibrator'].isHidden()
    assert rows['lm741'].isHidden()


def test_filter_also_matches_the_folder_name(picker):
    """Users search for the part number they know, which may be the folder."""
    picker.search.setText('74HC')
    assert not _rows(picker)['multivibrator'].isHidden()


def test_filter_is_case_insensitive(picker):
    picker.search.setText('LM741')
    assert not _rows(picker)['lm741'].isHidden()


def test_clearing_the_filter_restores_everything(picker):
    picker.search.setText('nothing matches this')
    assert all(i.isHidden() for i in _rows(picker).values())
    picker.search.setText('')
    assert not any(i.isHidden() for i in _rows(picker).values())


def test_summary_counts_what_is_shown(picker):
    assert '4 of 4' in picker.summary.text()
    picker.search.setText('lm741')
    assert '1 of 4' in picker.summary.text()


# -- choosing ----------------------------------------------------------------

def test_choosing_returns_the_folder_and_the_stem(picker, library):
    picker.table.setCurrentItem(_rows(picker)['multivibrator'])
    picker._accept()
    folder, stem = picker.chosen
    assert stem == 'multivibrator'
    assert os.path.basename(folder) == '74HC123'


def test_an_unidentifiable_folder_cannot_be_opened(picker):
    """Several .sub files, none named after the folder: the reason sits on the
    disabled button instead of arriving as an error after the click."""
    picker.table.setCurrentItem(_rows(picker)['TCA965'])
    assert not picker.open_btn.isEnabled()
    assert 'Browse' in picker.open_btn.toolTip()
    picker._accept()
    assert picker.chosen is None


def test_browse_hands_back_to_the_folder_dialog(picker):
    """The original path stays available, so a subcircuit kept outside the
    library is still reachable exactly as it was."""
    picker._browse()
    assert picker.browse is True
    assert picker.chosen is None


def test_an_empty_library_does_not_break_the_dialog(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    p = SubcircuitPicker(str(empty))
    try:
        assert p.table.topLevelItemCount() == 0
        assert not p.open_btn.isEnabled()
        assert '0 of 0' in p.summary.text()
    finally:
        p.close()
        p.deleteLater()
        _app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_a_missing_library_does_not_break_the_dialog(tmp_path):
    p = SubcircuitPicker(str(tmp_path / 'nope'))
    try:
        assert p.table.topLevelItemCount() == 0
    finally:
        p.close()
        p.deleteLater()
        _app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
