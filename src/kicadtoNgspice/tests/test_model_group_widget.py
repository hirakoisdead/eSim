# ==============================================================================
#  test_model_group_widget.py -- behaviour tests for ModelGroupWidget.
#
#  Runs headless via the Qt 'offscreen' platform (no display needed). These
#  exercise the fan-out / inherit / override / reset / derive-on-reload logic
#  through the public API.
#
#  Run:  QT_QPA_PLATFORM=offscreen python3 \
#            src/kicadtoNgspice/tests/test_model_group_widget.py
#        (pytest also works; the platform is forced below.)
# ==============================================================================
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                       # .../src/kicadtoNgspice
for _p in (HERE, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6 import QtCore, QtWidgets                 # noqa: E402
from PyQt6.QtTest import QTest                      # noqa: E402
import ModelGroupWidget as mgw                      # noqa: E402
from ModelGroupWidget import ModelGroupWidget, InstanceRow  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _rows(refs, texts=None):
    rows = []
    for i, ref in enumerate(refs):
        edit = QtWidgets.QLineEdit()
        if texts:
            edit.setText(texts[i])
        rows.append(InstanceRow(ref, edit))
    return rows


def _widget(refs, texts=None, log=None):
    resolve = (lambda ref, path: log.append((ref, path))) if log is not None \
        else None
    return ModelGroupWidget("eSim_NPN (transistor)", _rows(refs, texts),
                            resolve_fn=resolve)


# -- fan-out -------------------------------------------------------------------

def test_group_path_fans_out_to_all_instances():
    log = []
    w = _widget(["q1", "q2", "q3"], log=log)
    w.set_group_path("/lib/bc547.lib")
    assert w.resolved() == {
        "q1": "/lib/bc547.lib",
        "q2": "/lib/bc547.lib",
        "q3": "/lib/bc547.lib",
    }
    # resolve_fn fired once per instance with the group path.
    assert set(log) == {("q1", "/lib/bc547.lib"),
                        ("q2", "/lib/bc547.lib"),
                        ("q3", "/lib/bc547.lib")}


def test_override_then_group_change_leaves_override_alone():
    w = _widget(["q1", "q2", "q3"])
    w.set_group_path("/lib/a.lib")
    w.override("q2", "/lib/special.lib")
    assert w.is_overridden("q2")
    # Change the group again: q1/q3 follow, q2 stays put.
    w.set_group_path("/lib/b.lib")
    assert w.resolved() == {
        "q1": "/lib/b.lib",
        "q2": "/lib/special.lib",
        "q3": "/lib/b.lib",
    }


def test_reset_reattaches_to_group():
    w = _widget(["q1", "q2"])
    w.set_group_path("/lib/a.lib")
    w.override("q1", "/lib/x.lib")
    w.reset_row_by_ref("q1")
    assert not w.is_overridden("q1")
    assert w.resolved()["q1"] == "/lib/a.lib"


def test_user_keystroke_marks_override():
    # textEdited is what the GUI emits on typing; simulate it directly.
    w = _widget(["q1", "q2"])
    w.set_group_path("/lib/a.lib")
    row1 = w._row("q1")
    row1.path_edit.setText("/typed/by/hand.lib")
    row1.path_edit.textEdited.emit("/typed/by/hand.lib")
    assert w.is_overridden("q1")
    # Group change no longer touches the hand-edited row.
    w.set_group_path("/lib/c.lib")
    assert w.resolved()["q1"] == "/typed/by/hand.lib"
    assert w.resolved()["q2"] == "/lib/c.lib"


def test_programmatic_settext_does_not_mark_override():
    # Fan-out uses setText(); that must NOT look like a manual override.
    w = _widget(["q1", "q2"])
    w.set_group_path("/lib/a.lib")
    assert not w.is_overridden("q1")
    assert not w.is_overridden("q2")


# -- derive initial state from restored values --------------------------------

def test_uniform_restored_values_become_group_default():
    w = _widget(["q1", "q2", "q3"],
                texts=["/lib/x.lib", "/lib/x.lib", "/lib/x.lib"])
    assert w.group_path() == "/lib/x.lib"
    assert not any(w.is_overridden(r) for r in ("q1", "q2", "q3"))
    assert not w.is_expanded()


def test_mixed_restored_values_show_overrides_and_expand():
    w = _widget(["q1", "q2", "q3"],
                texts=["/lib/x.lib", "/lib/y.lib", ""])
    assert w.group_path() == ""
    assert w.is_overridden("q1")
    assert w.is_overridden("q2")
    assert not w.is_overridden("q3")     # blank -> still inheriting
    assert w.is_expanded()               # user must see the conflict


def test_all_blank_restored_is_clean_inherit():
    w = _widget(["q1", "q2"], texts=["", ""])
    assert w.group_path() == ""
    assert not w.is_overridden("q1")
    assert not w.is_expanded()


def test_expand_collapse_toggle():
    w = _widget(["q1", "q2"])
    assert not w.is_expanded()
    w.set_expanded(True)
    assert w.is_expanded()
    w.set_expanded(False)
    assert not w.is_expanded()


# -- the disclosure control ----------------------------------------------------

def test_clicking_the_header_toggles():
    w = _widget(["q1", "q2"])
    QTest.mouseClick(w._toggle, QtCore.Qt.MouseButton.LeftButton)
    assert w.is_expanded()
    QTest.mouseClick(w._toggle, QtCore.Qt.MouseButton.LeftButton)
    assert not w.is_expanded()


def test_body_reaches_its_final_state_without_an_event_loop():
    # No motion / not on screen: the slide is skipped, so visibility and the
    # height cap must be final the moment set_expanded returns.
    # isHidden, not isVisible: nothing here has been shown, so isVisible is
    # False either way -- what matters is the explicit hide flag the layout
    # reads.
    w = _widget(["q1", "q2"])
    w.set_expanded(True)
    assert not w._clip.isHidden()
    assert w._clip.maximumHeight() == mgw._UNCAPPED
    w.set_expanded(False)
    assert w._clip.isHidden()


def test_clipped_body_never_squashes_the_rows():
    # The regression the clip box exists for: capping the visible height must
    # leave every instance row at its natural size and just cut off what does
    # not fit -- not re-lay the rows out into the smaller box.
    w = _widget(["q1", "q2", "q3"])
    w.resize(600, 400)
    w.set_expanded(True)
    natural = w._content.height()
    row_heights = [r.path_edit.height() for r in w._rows]
    assert natural > 0 and all(h > 0 for h in row_heights)

    w._clip.setMaximumHeight(natural // 3)
    w._clip.resize(w._clip.width(), natural // 3)
    assert w._content.height() == natural
    assert [r.path_edit.height() for r in w._rows] == row_heights


def test_open_body_sets_a_floor_the_tab_layout_must_respect():
    # The tab divides its height between the cards, so an open card has to
    # claim its rows as a minimum -- otherwise the layout shrinks it and the
    # clip quietly cuts rows off instead of the tab scrolling.
    w = _widget(["q1", "q2", "q3"])
    w.resize(600, 400)
    w.set_expanded(True)
    assert w._clip.minimumSizeHint().height() == w._content.sizeHint().height()
    # ...but a capped (mid-slide) box must still be free to shrink to nothing,
    # which Qt gets by bounding the hint with maximumSize.
    w._clip.setMaximumHeight(0)
    assert w._clip.minimumSizeHint().boundedTo(
        w._clip.maximumSize()).height() == 0


def test_fade_effect_is_disabled_while_idle():
    # A live QGraphicsEffect costs a repaint-to-pixmap on every paint; it is
    # only meant to be on for the length of a slide.
    w = _widget(["q1", "q2"])
    assert not w._fade.isEnabled()
    w.set_expanded(True)
    assert not w._fade.isEnabled()
    assert w._fade.opacity() == 1.0


def test_group_height_tracks_the_body():
    w = _widget(["q1", "q2", "q3"])
    closed = w.sizeHint().height()
    w.set_expanded(True)
    assert w.sizeHint().height() > closed
    w.set_expanded(False)
    assert w.sizeHint().height() == closed


def test_header_splits_model_name_from_kind():
    assert mgw._split_title("eSim_NPN  (Transistor)") == \
        ("eSim_NPN", "Transistor")
    assert mgw._split_title("lm_741 (Subcircuit)") == ("lm_741", "Subcircuit")
    assert mgw._split_title("plain") == ("plain", "")


def test_header_chip_truncates_long_groups():
    assert mgw._chip_text(["q1", "q2"]) == "q1 · q2"
    assert mgw._chip_text(["q1", "q2", "q3", "q4", "q5"]) == "q1 · q2 · q3 · +2"


def test_slide_duration_scales_with_distance():
    # A one-row slide must not spend its last frames moving under a pixel, and
    # a tall body must not drag; hence the clamped, distance-driven duration.
    short = mgw._duration(40, True)
    tall = mgw._duration(600, True)
    assert 110 <= short <= tall <= 190
    assert mgw._duration(600, False) < mgw._duration(600, True)


# -- standalone runner ---------------------------------------------------------
def _main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS  " + fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL  " + fn.__name__ + "  " + str(e))
        except Exception as e:                       # noqa: BLE001
            failed += 1
            print("ERROR " + fn.__name__ + "  " + repr(e))
    print("\n==== %d / %d PASS ====" % (len(fns) - failed, len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
