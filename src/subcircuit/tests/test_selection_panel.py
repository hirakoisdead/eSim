# ==============================================================================
#  test_selection_panel.py -- the Subcircuit panel says what it is working on.
#
#  The panel used to display nothing about its own state. The only name on
#  screen belonged to the open *project*, which the Subcircuit Builder never
#  touches, so a user could not tell which subcircuit Convert was about to
#  rebuild -- or whether anything was selected at all.
#
#  Selection is also per panel here. Appconfig keeps it in a class attribute
#  shared by every instance, so two projects with a Subcircuit tab open each
#  used to share one selection.
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

from PyQt6 import QtCore, QtWidgets, sip                         # noqa: E402
from configuration.Appconfig import Appconfig                    # noqa: E402
from subcircuit.Subcircuit import Subcircuit                     # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


@pytest.fixture(autouse=True)
def clean_selection():
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}
    yield
    Appconfig.current_subcircuit = {"SubcircuitName": None, "Stem": None}


def _destroy(*widgets):
    """Tear a panel down deterministically.

    deleteLater() alone only QUEUES the delete, and processEvents() does NOT
    drain DeferredDelete events -- the widget would outlive this module and die
    inside whichever later test happens to spin a real event loop. Post the
    delete and flush it here, while this module still owns the loop.
    """
    for w in widgets:
        w.close()
        w.setParent(None)
        w.deleteLater()
    _app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    _app.processEvents()


def _make_sub(root, name, files):
    d = os.path.join(str(root), name)
    os.makedirs(d, exist_ok=True)
    for f in files:
        with open(os.path.join(d, f), 'w') as fh:
            fh.write('* test\n')
    return d


@pytest.fixture
def panel():
    w = Subcircuit(None)
    yield w
    _destroy(w)


# -- empty state -------------------------------------------------------------

def test_the_panel_leaves_no_orphan_top_level_widget():
    """One construction, one top-level widget.

    The panel used to initialise its QWidget base twice, which on PyQt builds a
    second C++ widget and rebinds the Python wrapper to it. The abandoned one
    stayed on QApplication.topLevelWidgets() with nothing owning it, so anything
    that walks that list -- theme repolish, and _app_teardown at exit, which
    calls findChildren on every entry -- eventually read freed memory and took
    the process down with 0xc0000005 and no traceback.
    """
    def panels():
        # Count only this class: neighbouring tests leave their own top-level
        # widgets around, and a raw total would measure them instead.
        return [t for t in _app.topLevelWidgets()
                if isinstance(t, Subcircuit)]

    before = len(panels())
    w = Subcircuit(None)
    assert len(panels()) == before + 1
    _destroy(w)
    assert sip.isdeleted(w)
    assert len(panels()) == before


def test_empty_state_says_so_and_disables_convert(panel):
    assert 'No subcircuit selected' in panel.selection_label.text()
    assert not panel.convertbtn.isEnabled()
    assert 'Select a subcircuit first' in panel.convertbtn.toolTip()


def test_new_and_edit_stay_available_with_nothing_selected(panel):
    """Gating Convert must not strand the user: the two ways OUT of the empty
    state have to remain clickable."""
    assert panel.newbtn.isEnabled()
    assert panel.editbtn.isEnabled()
    assert panel.uploadbtn.isEnabled()


# -- populated state ---------------------------------------------------------

def test_selection_names_the_subcircuit_and_its_folder(panel, tmp_path):
    d = _make_sub(tmp_path, '2bitmul', ['half_adder.sub', 'half_adder.cir'])
    panel._select(d, 'half_adder')

    text = panel.selection_label.text()
    assert 'half_adder' in text
    assert d in text
    assert panel.convertbtn.isEnabled()


def test_selecting_publishes_folder_and_stem_together(panel, tmp_path):
    d = _make_sub(tmp_path, '2bitmul', ['half_adder.sub'])
    panel._select(d, 'half_adder')
    assert Appconfig.current_subcircuit == {
        "SubcircuitName": d, "Stem": 'half_adder'}


# -- per-panel scoping -------------------------------------------------------

def test_raising_a_panel_reclaims_the_shared_selection(tmp_path):
    """Two projects, a Subcircuit tab each. Whichever is on screen owns the
    selection Convert reads."""
    a = _make_sub(tmp_path, 'alpha', ['alpha.sub', 'alpha.cir'])
    b = _make_sub(tmp_path, 'beta', ['beta.sub', 'beta.cir'])

    panel_a = Subcircuit(None)
    panel_a._select(a, 'alpha')
    panel_b = Subcircuit(None)
    panel_b._select(b, 'beta')
    assert Appconfig.current_subcircuit['Stem'] == 'beta'

    panel_a.show()
    assert Appconfig.current_subcircuit['SubcircuitName'] == a
    assert Appconfig.current_subcircuit['Stem'] == 'alpha'
    assert 'alpha' in panel_a.selection_label.text()

    panel_b.show()
    assert Appconfig.current_subcircuit['Stem'] == 'beta'

    _destroy(panel_a, panel_b)


def test_a_new_panel_adopts_a_selection_made_before_it_existed(tmp_path):
    """A reopened tab must show what is actually active, not claim the user
    has selected nothing."""
    d = _make_sub(tmp_path, 'lm741', ['lm741.sub', 'lm741.cir'])
    Appconfig().set_current_subcircuit(d)

    panel = Subcircuit(None)
    assert panel._stem == 'lm741'
    assert 'lm741' in panel.selection_label.text()
    assert panel.convertbtn.isEnabled()
    _destroy(panel)


def test_a_stale_selection_pointing_nowhere_is_not_adopted(tmp_path):
    """A folder recorded in a previous session and since deleted must not come
    back as a live selection with Convert enabled."""
    Appconfig.current_subcircuit = {
        "SubcircuitName": str(tmp_path / 'deleted'), "Stem": 'deleted'}

    panel = Subcircuit(None)
    assert panel._stem is None
    assert not panel.convertbtn.isEnabled()
    _destroy(panel)


# -- honesty about what the buttons do ---------------------------------------

def test_upload_tooltip_explains_what_upload_actually_is(panel):
    tip = panel.uploadbtn.toolTip()
    assert '.sub' in tip
    assert 'Library' in tip
