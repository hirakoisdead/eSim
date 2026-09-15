"""The two app-wide event filters merged into one, gated on event type.

PopupMotionFilter (menu/combo/tree rounding) and EffectShowRefreshFilter
(drop-shadow revalidate on Show) were both installed application-wide, so every
event in the process crossed C++->Python twice and ran isinstance checks. They
are now one AppWideMotionFilter that bails on anything but Polish/Show first.

These pin that the gate short-circuits and that BOTH merged behaviours survive.
"""
from unittest import mock

import pytest
from PyQt6 import QtCore, QtWidgets

from frontEnd import motion, theme_utils

_WA_TRANSLUCENT = QtCore.Qt.WidgetAttribute.WA_TranslucentBackground


def test_gate_ignores_non_polish_show_events(qapp):
    filt = motion.AppWideMotionFilter(None)
    menu = QtWidgets.QMenu()
    # A Timer event (stand-in for the mouse/paint/timer flood) must be dropped
    # without touching the object.
    ev = QtCore.QEvent(QtCore.QEvent.Type.Timer)
    assert filt.eventFilter(menu, ev) is False
    assert not menu.testAttribute(_WA_TRANSLUCENT)


@pytest.mark.skipif(
    motion.round_mode() != "alpha",
    reason="Windows rounds via DWM or a mask, not translucency")
def test_polish_still_rounds_menus(qapp):
    filt = motion.AppWideMotionFilter(None)
    menu = QtWidgets.QMenu()
    filt.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Polish))
    assert menu.testAttribute(_WA_TRANSLUCENT)


@pytest.mark.skipif(motion.round_mode() == "alpha", reason="Windows-only path")
def test_polish_leaves_menus_opaque_on_windows(qapp):
    """The corners must NOT be asked for translucency on Windows.

    Under Fusion the popup window is never layered, so the attribute yields no
    alpha -- it only makes the pixels outside the QSS border-radius flush as
    opaque black. Rounding is DWM's job here (test below).
    """
    filt = motion.AppWideMotionFilter(None)
    menu = QtWidgets.QMenu()
    filt.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Polish))
    assert not menu.testAttribute(_WA_TRANSLUCENT)


@pytest.mark.skipif(motion.round_mode() != "dwm",
                    reason="Windows 11 compositor path only")
def test_show_rounds_menus_via_dwm_and_sets_no_mask(qapp):
    """Show hands the menu to DWM, and leaves no 1-bit mask behind.

    A mask is what produced the staircase edges, so its absence is the fix.
    """
    filt = motion.AppWideMotionFilter(None)
    menu = QtWidgets.QMenu()
    menu.addAction("Open")

    rounded = []

    def accept(popup):
        rounded.append(popup)
        return True                     # DWM took it

    with mock.patch.object(
            theme_utils, "apply_round_corners", side_effect=accept):
        filt.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Show))

    assert rounded == [menu]
    assert menu.mask().isEmpty()


def test_a_refused_dwm_call_falls_back_to_the_mask(qapp, monkeypatch):
    """The build-number check is a prediction; DWM's answer is the fact.

    If the compositor refuses the corner attribute the popup would otherwise
    ship as a plain white square -- the exact failure seen on the Windows 10
    machine -- so a refusal has to downgrade the process to the mask path.
    """
    monkeypatch.setattr(motion, "_ROUND_MODE", "dwm")
    filt = motion.AppWideMotionFilter(None)
    menu = QtWidgets.QMenu()
    menu.addAction("Open")
    menu.resize(180, 120)

    with mock.patch.object(theme_utils, "apply_round_corners",
                           return_value=False):
        filt.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Show))

    assert not menu.mask().isEmpty(), "refused DWM left the corners square"
    assert not menu.mask().contains(QtCore.QPoint(0, 0))
    assert motion._ROUND_MODE == "mask", "the downgrade must stick"


def test_windows_10_falls_back_to_a_mask(qapp, monkeypatch):
    """Without DWM rounding the popup must still get a rounded window.

    Windows 10 has neither the compositor attribute (it landed in build 22000)
    nor a layered popup surface, so before this fallback the menu shipped as a
    plain white square with the QSS border curving inside it -- which is what
    the installed build looked like on a Windows 10 box.
    """
    monkeypatch.setattr(motion, "_ROUND_MODE", "mask")
    filt = motion.AppWideMotionFilter(None)
    menu = QtWidgets.QMenu()
    menu.addAction("Open")
    menu.resize(180, 120)

    filt.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Polish))
    assert not menu.testAttribute(_WA_TRANSLUCENT), (
        "translucency on this path only blackens the corners")

    filt.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Show))
    assert not menu.mask().isEmpty(), "no mask means square corners"
    # The mask must actually cut the corner off, not just cover the rect.
    assert not menu.mask().contains(QtCore.QPoint(0, 0))


def test_dwm_corner_override_matches_the_clip_radius(qapp):
    """On the DWM path the sheet's popup radius must equal DWM's own.

    The window paints an opaque rectangle, so the QSS radius only curves the
    BORDER -- the fill still reaches the square edge and DWM clips it at 8px.
    A larger sheet radius therefore shows as fill spilling outside the outline
    at each corner.
    """
    if not theme_utils.dwm_rounds_popups():
        pytest.skip("Windows 11 compositor path only")
    qss = theme_utils.build_qss("style_light.qss", False, "default", "system",
                                "system", 100)
    tail = qss[qss.rindex("QMenu { border-radius:"):]
    assert "%dpx" % theme_utils.DWM_CORNER_RADIUS_PX in tail


def test_popup_corner_override_is_not_zoom_scaled(qapp):
    """DWM's radius is a compositor constant, not a UI metric.

    It must not ride the zoom curve the rest of the sheet does, or the border
    drifts off the clip the moment the user leaves 100%.
    """
    if not theme_utils.dwm_rounds_popups():
        pytest.skip("Windows 11 compositor path only")
    r = "border-radius: %dpx" % theme_utils.DWM_CORNER_RADIUS_PX
    for zoom in (60, 100, 150):
        qss = theme_utils.build_qss("style_light.qss", False, "default",
                                    "system", "system", zoom)
        assert qss.rstrip().endswith("}")
        assert r in qss[qss.rindex("QMenu { border-radius:"):]


def test_show_revalidates_drop_shadow_without_error(qapp):
    filt = motion.AppWideMotionFilter(None)
    w = QtWidgets.QWidget()
    eff = QtWidgets.QGraphicsDropShadowEffect(w)
    w.setGraphicsEffect(eff)
    # Merged filter schedules a deferred off/on toggle on Show; flush the
    # singleShot and confirm the effect ends enabled (net no-op, no crash).
    filt.eventFilter(w, QtCore.QEvent(QtCore.QEvent.Type.Show))
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.Timer)
    assert eff.isEnabled()


def test_install_app_motion_registers_single_filter(qapp):
    motion.install_app_motion(qapp)
    assert isinstance(
        qapp._esim_app_motion_filter, motion.AppWideMotionFilter)
