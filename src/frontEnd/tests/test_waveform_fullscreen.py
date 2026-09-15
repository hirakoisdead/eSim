"""A fullscreen panel must never hide the panel eSim moves the user to.

Fullscreen here is not a window state on the main window: FullScreenToggle
reparents a dock's content into a frameless top-level window that covers the
screen. Anything that then opens or raises another dock does so *behind* that
window, where the user cannot see it. Two reported bugs were exactly this:

* simulate from a fullscreen Verify panel and the waveform tab opened behind
  it -- the run looked like it had produced nothing, and the user had to leave
  fullscreen and click the tab by hand;
* press "Back to Verify" on a fullscreen waveform and nothing appeared to
  happen -- the click worked, the editor was raised, and the fullscreen
  waveform stayed on top of it.

The fix is that fullscreen follows the user: it is handed to the panel being
shown, and handed back on the way out. These tests pin that hand-off.
"""
import pytest
from PyQt6 import QtCore, QtWidgets, sip

from frontEnd import FullScreen
from frontEnd.DockArea import DockArea
from frontEnd.FullScreen import (FullScreenToggle, exit_fullscreen,
                                 go_fullscreen, handover, is_fullscreen)


def _fs_window(dock):
    """The live fullscreen window holding ``dock``'s panel, or None."""
    toggle = FullScreen._ACTIVE.get(FullScreen._key(dock))
    return None if toggle is None else toggle._win


def _panel_with_toggle():
    """A tool panel carrying a fullscreen control in its own header."""
    panel = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(panel)
    lay.addWidget(FullScreenToggle())
    lay.addWidget(QtWidgets.QLabel("content"))
    return panel


@pytest.fixture
def area(qapp):
    da = DockArea()
    yield da
    for dock in list(da.findChildren(QtWidgets.QDockWidget)):
        FullScreen.exit_fullscreen(dock)
    # A test that kills a window's owner on purpose leaves that window with
    # nothing able to close it. Left behind it is a screen-sized visible
    # top-level widget, which every later test that walks topLevelWidgets()
    # then has to grab and paint -- the theme-transition tests both slowed to
    # a crawl and started failing. Reap them here, not in the product.
    for tlw in list(qapp.topLevelWidgets()):
        if getattr(tlw, "_esim_fs_dock", None) is not None:
            tlw.hide()
            tlw.deleteLater()
    da.deleteLater()
    qapp.processEvents()


def _mounted_dock(area, title="Model Creation-p-1"):
    dock = QtWidgets.QDockWidget(title)
    area.apply_fullscreen_feature(dock, _panel_with_toggle())
    area.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, dock)
    return dock


# --- the registry itself -------------------------------------------------- #

def test_fullscreen_state_is_observable_and_reversible(area, qapp):
    dock = _mounted_dock(area)
    assert not is_fullscreen(dock)

    assert go_fullscreen(dock)
    assert is_fullscreen(dock)
    # The content really did leave the dock for the fullscreen window.
    assert dock.widget() is None or dock.widget().parent() is not dock

    assert exit_fullscreen(dock)
    qapp.processEvents()
    assert not is_fullscreen(dock)
    assert dock.widget() is not None


def test_exit_is_a_no_op_when_not_fullscreen(area):
    dock = _mounted_dock(area)
    assert exit_fullscreen(dock) is False


def test_go_fullscreen_needs_a_toggle(area):
    dock = QtWidgets.QDockWidget("Plain-1")
    area.apply_fullscreen_feature(dock, QtWidgets.QLabel("no toggle here"))
    assert go_fullscreen(dock) is False
    assert not is_fullscreen(dock)


# --- waveform opening from a fullscreen editor ---------------------------- #

class _Flow:
    """Stand-in for the Flow Navigator; records the stage jump."""

    def __init__(self):
        self.verified = 0

    def goto_verify(self):
        self.verified += 1


def test_waveform_takes_over_fullscreen_from_the_editor(area, qapp):
    source = _mounted_dock(area)
    flow = _Flow()
    go_fullscreen(source)
    assert is_fullscreen(source)

    plot = _panel_with_toggle()
    area._show_waveform_dock(plot, source, flow)
    qapp.processEvents()

    wave = area._wave_docks[source]
    assert not is_fullscreen(source), "the editor must yield fullscreen"
    assert is_fullscreen(wave), "the waveform must take it, not open behind it"


def test_waveform_stays_docked_when_the_editor_was_not_fullscreen(area, qapp):
    source = _mounted_dock(area)
    area._show_waveform_dock(_panel_with_toggle(), source, _Flow())
    qapp.processEvents()

    wave = area._wave_docks[source]
    assert not is_fullscreen(wave)
    # isVisible() is False while the (never-shown) main window is hidden; what
    # matters is that the dock was not left explicitly hidden.
    assert not wave.isHidden()


def test_resimulate_reuses_the_tab_and_keeps_fullscreen(area, qapp):
    source = _mounted_dock(area)
    flow = _Flow()
    go_fullscreen(source)
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    first = area._wave_docks[source]

    # Second run while the waveform is fullscreen: same tab, still fullscreen.
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    assert area._wave_docks[source] is first
    assert is_fullscreen(first)


# --- back to verify ------------------------------------------------------- #

def test_back_to_verify_leaves_fullscreen_and_restores_the_editor(area, qapp):
    source = _mounted_dock(area)
    flow = _Flow()
    go_fullscreen(source)
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]
    assert is_fullscreen(wave)

    area._return_to_verify(source, flow, wave)
    qapp.processEvents()

    assert not is_fullscreen(wave), "the waveform must stop covering the screen"
    assert is_fullscreen(source), "the editor gets the fullscreen back"
    assert flow.verified == 1


def test_a_docked_run_never_throws_the_editor_into_fullscreen(area, qapp):
    """The reported bug, in order:

    fullscreen Verify -> Simulate -> Back  (editor fullscreen again)
    -> Esc                                  (user goes back to docked)
    -> Simulate -> Back                     (everything docked)

    The last step used to fullscreen the editor out of nowhere: the waveform
    tab still carried "I was opened from fullscreen" from the FIRST run, and
    the return path trusted that remembered flag instead of looking at what
    was actually on screen."""
    source = _mounted_dock(area)
    flow = _Flow()

    # Run 1, from fullscreen.
    go_fullscreen(source)
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]
    area._return_to_verify(source, flow, wave)
    qapp.processEvents()
    assert is_fullscreen(source)

    # The user leaves fullscreen.
    exit_fullscreen(source)
    qapp.processEvents()
    assert not is_fullscreen(source)

    # Run 2, fully docked. The same waveform tab is reused.
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    assert area._wave_docks[source] is wave
    assert not is_fullscreen(wave), "a docked run must not open fullscreen"

    area._return_to_verify(source, flow, wave)
    qapp.processEvents()
    assert not is_fullscreen(source), (
        "coming back from a docked waveform fullscreened the editor")


def test_a_manually_fullscreened_waveform_hands_fullscreen_back(area, qapp):
    """Mirror of the above: the state that counts is the CURRENT one. If the
    user fullscreens the waveform themselves, Back keeps them in fullscreen --
    on the editor -- rather than dumping them to the desktop."""
    source = _mounted_dock(area)
    flow = _Flow()
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]

    go_fullscreen(wave)                 # the user's own choice, not inherited
    qapp.processEvents()

    area._return_to_verify(source, flow, wave)
    qapp.processEvents()
    assert is_fullscreen(source) and not is_fullscreen(wave)


def test_back_to_verify_from_a_docked_waveform_changes_no_fullscreen(area,
                                                                    qapp):
    source = _mounted_dock(area)
    flow = _Flow()
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]

    area._return_to_verify(source, flow, wave)
    qapp.processEvents()

    assert not is_fullscreen(wave) and not is_fullscreen(source)
    assert flow.verified == 1


def test_back_to_verify_survives_a_dead_source_dock(area, qapp):
    """Closing Model Creation first must not make the plot's Back button
    touch a freed dock."""
    source = _mounted_dock(area)
    flow = _Flow()
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]

    area._destroy_dock(source)
    qapp.processEvents()

    area._return_to_verify(source, flow, wave)      # must not raise


# --- seamlessness: the window is never torn down ------------------------- #
# Exiting fullscreen on one panel and entering it on the next is functionally
# correct and visibly wrong: the covering window dies, the docked window
# flashes for a frame, and a new window grows into fullscreen. The hand-off
# keeps ONE window and swaps its content, so nothing uncovers the screen.

def test_waveform_reuses_the_editors_fullscreen_window(area, qapp):
    source = _mounted_dock(area)
    go_fullscreen(source)
    win = _fs_window(source)
    assert win is not None

    area._show_waveform_dock(_panel_with_toggle(), source, _Flow())
    qapp.processEvents()

    wave = area._wave_docks[source]
    assert _fs_window(wave) is win, "a new fullscreen window was created"
    assert win.isVisible(), "the screen was uncovered during the hand-off"


def test_back_to_verify_hands_the_same_window_back(area, qapp):
    source = _mounted_dock(area)
    flow = _Flow()
    go_fullscreen(source)
    win = _fs_window(source)
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]

    area._return_to_verify(source, flow, wave)
    qapp.processEvents()

    assert _fs_window(source) is win, "the round trip rebuilt the window"
    assert _fs_window(wave) is None
    assert win.isVisible()


def test_the_handed_over_panel_owns_esc(area, qapp):
    """After the hand-off the NEW panel's toggle owns the window, so Esc and
    its own button dock the waveform back -- not the editor it came from."""
    source = _mounted_dock(area)
    go_fullscreen(source)
    area._show_waveform_dock(_panel_with_toggle(), source, _Flow())
    qapp.processEvents()
    wave = area._wave_docks[source]

    exit_fullscreen(wave)               # what Esc does
    qapp.processEvents()

    assert not is_fullscreen(wave) and not is_fullscreen(source)
    assert wave.widget() is not None, "the waveform panel did not come back"
    assert source.widget() is not None, "the editor panel was left orphaned"


# --- the owner of the window can die under it ----------------------------- #
# The toggle lives INSIDE the panel it fullscreens (the plot's own toolbar), so
# replacing that panel destroys the button that owns the window. The window
# survives: with a deleted owner its close handler raised instead of docking
# back, leaving an empty fullscreen rectangle over the whole screen that
# nothing could dismiss, and the next hand-off raised
# "wrapped C/C++ object of type FullScreenToggle has been deleted".

def _kill(widget):
    """Destroy a widget now -- what deleteLater does once the loop turns."""
    widget.setParent(None)
    sip.delete(widget)


def test_a_dead_owner_stops_reporting_fullscreen(area):
    dock = _mounted_dock(area)
    go_fullscreen(dock)
    _kill(FullScreen._ACTIVE[FullScreen._key(dock)])

    # A deleted QToolButton keeps its Python attributes, so the registry entry
    # still read back a live window and looked perfectly healthy.
    assert not is_fullscreen(dock)
    assert exit_fullscreen(dock) is False


def test_a_new_toggle_adopts_an_ownerless_fullscreen_window(area, qapp):
    dock = _mounted_dock(area)
    go_fullscreen(dock)
    win = _fs_window(dock)
    content = win.layout().itemAt(0).widget()
    _kill(FullScreen._ACTIVE[FullScreen._key(dock)])
    assert not is_fullscreen(dock)

    fresh = FullScreenToggle()
    content.layout().addWidget(fresh)
    fresh.show()

    assert is_fullscreen(dock), "the rebuilt panel's button did not take over"
    assert _fs_window(dock) is win, "adoption must not build a second window"
    exit_fullscreen(dock)               # the way out works again
    qapp.processEvents()
    assert not is_fullscreen(dock)
    assert dock.widget() is not None


def test_resimulate_hands_the_window_to_the_new_plots_button(area, qapp):
    source = _mounted_dock(area)
    flow = _Flow()
    go_fullscreen(source)
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]
    win = _fs_window(wave)

    second = _panel_with_toggle()
    area._show_waveform_dock(second, source, flow)
    qapp.processEvents()

    assert (FullScreen._ACTIVE[FullScreen._key(wave)]
            is second.findChild(FullScreenToggle)), "the new plot's button"
    assert _fs_window(wave) is win, "the screen was uncovered mid-run"

    exit_fullscreen(wave)
    qapp.processEvents()
    assert not is_fullscreen(wave)
    assert wave.widget() is not None, "the waveform panel did not come back"
    assert sip.isdeleted(win) or not win.isVisible(), (
        "the emptied fullscreen window was left covering the screen")


def test_back_to_verify_after_a_resimulate_does_not_raise(area, qapp):
    """The reported sequence: fullscreen Verify -> Simulate -> Simulate again
    -> Back to Verify. The second run killed the window's owner, so Back went
    through handover into a deleted button."""
    source = _mounted_dock(area)
    flow = _Flow()
    go_fullscreen(source)
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()
    wave = area._wave_docks[source]
    area._show_waveform_dock(_panel_with_toggle(), source, flow)
    qapp.processEvents()

    area._return_to_verify(source, flow, wave)      # used to raise
    qapp.processEvents()

    assert is_fullscreen(source), "the editor gets the fullscreen back"
    assert not is_fullscreen(wave)


def test_handover_declines_when_there_is_nothing_to_hand_over(area):
    source = _mounted_dock(area)
    target = _mounted_dock(area, "Waveform-x-2")
    assert handover(source, target) is False      # source is not fullscreen


def test_handover_declines_when_the_target_has_no_toggle(area, qapp):
    source = _mounted_dock(area)
    plain = QtWidgets.QDockWidget("Plain-2")
    area.apply_fullscreen_feature(plain, QtWidgets.QLabel("no toggle"))
    area.addDockWidget(QtCore.Qt.DockWidgetArea.TopDockWidgetArea, plain)
    go_fullscreen(source)

    assert handover(source, plain) is False
    assert is_fullscreen(source), "a declined hand-off must change nothing"
