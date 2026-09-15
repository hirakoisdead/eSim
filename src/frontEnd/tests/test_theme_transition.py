"""The light<->dark flip lands in one frame, not widget by widget.

A theme apply repolishes the whole widget tree, and with painting live the
window turns dark in pieces over the length of that walk. theme_utils freezes
painting on every visible window for the duration and cross-dissolves a
snapshot of the old look away afterwards. These tests pin the contract that
matters when it goes wrong: painting is ALWAYS handed back, even if the
repolish blows up mid-way, and a window is never left frozen or wearing a
stale snapshot.
"""
import pytest

from PyQt6 import QtCore, QtGui, QtWidgets

from frontEnd import theme_utils


def _distinct_colors(pixmap):
    image = pixmap.toImage()
    seen = set()
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            seen.add(image.pixel(x, y))
    return len(seen)


@pytest.fixture
def window(qapp):
    """A window with actual content, so a snapshot of it has actual colors."""
    w = QtWidgets.QWidget()
    w.setStyleSheet("QWidget { background: #202020; }")
    layout = QtWidgets.QVBoxLayout(w)
    layout.addWidget(QtWidgets.QPushButton("plain"))
    shadowed = QtWidgets.QPushButton("shadowed")
    effect = QtWidgets.QGraphicsDropShadowEffect(shadowed)
    effect.setBlurRadius(24)
    effect.setColor(QtGui.QColor("#53D7FF"))
    shadowed.setGraphicsEffect(effect)
    layout.addWidget(shadowed)
    w.resize(300, 160)
    w.show()
    QtWidgets.QApplication.processEvents()
    yield w
    theme_utils._discard_overlay(getattr(w, "_esim_theme_overlay", None))
    w.hide()
    w.deleteLater()


def _pump(ms=0):
    """Run the event loop long enough for the queued finish to land."""
    deadline = QtCore.QElapsedTimer()
    deadline.start()
    while deadline.elapsed() < ms:
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 10)
    QtWidgets.QApplication.processEvents()


def test_begin_freezes_painting_and_snapshots(qapp, window):
    state = theme_utils._begin_theme_transition(qapp, animate=True)

    assert not window.updatesEnabled()      # nothing reaches the screen now
    overlay = window._esim_theme_overlay
    assert isinstance(overlay, theme_utils._ThemeFadeOverlay)
    assert overlay.geometry() == window.rect()
    assert overlay._opacity == 1.0          # fully covering the old look
    assert (window, overlay) in state["windows"]

    theme_utils._finish_theme_transition(state, fade=False)
    assert window.updatesEnabled()


def test_reduced_motion_freezes_without_a_snapshot(qapp, window):
    """Motion off is a hard cut: still atomic, but no dissolve."""
    state = theme_utils._begin_theme_transition(qapp, animate=False)

    assert not window.updatesEnabled()
    assert getattr(window, "_esim_theme_overlay", None) is None

    theme_utils._finish_theme_transition(state, fade=False)
    assert window.updatesEnabled()


def test_finish_is_idempotent(qapp, window):
    """The settle timer and the watchdog both call it; the second must no-op
    rather than re-enable a window the user has since frozen for other work."""
    state = theme_utils._begin_theme_transition(qapp, animate=True)
    theme_utils._finish_theme_transition(state, fade=False)
    assert state["finished"]

    window.setUpdatesEnabled(False)
    theme_utils._finish_theme_transition(state, fade=True)
    assert not window.updatesEnabled()


def test_hidden_windows_are_left_alone(qapp):
    hidden = QtWidgets.QWidget()
    try:
        state = theme_utils._begin_theme_transition(qapp, animate=True)
        assert all(w is not hidden for w, _ in state["windows"])
        assert hidden.updatesEnabled()
        theme_utils._finish_theme_transition(state, fade=False)
    finally:
        hidden.deleteLater()


def test_a_frozen_grab_is_a_flat_slab(qapp, window):
    """The trap this whole ordering exists to avoid, pinned as a fact.

    QWidget.grab() on a window with painting disabled does not render the
    children -- it returns one flat rectangle of the window background. Taking
    the new-look snapshot before thawing therefore dissolves the UI into solid
    white (light) or solid black (dark) and then snaps it back to life.
    """
    assert _distinct_colors(window.grab()) > 1

    window.setUpdatesEnabled(False)
    try:
        assert _distinct_colors(window.grab()) == 1
        assert theme_utils._snapshot_is_degenerate(window.grab())
    finally:
        window.setUpdatesEnabled(True)

    assert not theme_utils._snapshot_is_degenerate(window.grab())


def test_the_new_look_snapshot_has_real_content(qapp, window):
    """Pixel truth on the dissolve's destination: whatever the fade lands on
    has to be the actual repainted UI, not a slab."""
    state = theme_utils._begin_theme_transition(qapp, animate=True)
    theme_utils._finish_theme_transition(state, fade=True)

    overlay = window._esim_theme_overlay
    assert overlay._after is not None
    assert _distinct_colors(overlay._after) > 1
    assert _distinct_colors(overlay._before) > 1


def _mean_luminance(pixmap):
    image = pixmap.toImage()
    total = count = 0
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            color = QtGui.QColor(image.pixel(x, y))
            total += color.lightness()
            count += 1
    return total / max(1, count)


def test_end_to_end_flip_dissolves_light_into_dark(qapp, monkeypatch):
    """The whole pipeline on a real apply: the snapshot the fade lands on must
    be the window as the NEW theme paints it. Luminance is the check that
    catches a snapshot taken too early -- one grabbed before the repolish
    settled still shows the outgoing theme, and the dissolve goes nowhere."""
    mode = {"theme_mode": "Dark"}
    transition = {"on": False}
    monkeypatch.setattr(theme_utils, "get_preferences", lambda *a, **k: mode)
    monkeypatch.setattr(theme_utils, "_transition_enabled",
                        lambda app: transition["on"])
    monkeypatch.setattr(theme_utils, "_THEME_APPLIED_ONCE", True, raising=False)

    plain = QtWidgets.QWidget()     # palette-driven, so the theme reaches it
    layout = QtWidgets.QVBoxLayout(plain)
    layout.addWidget(QtWidgets.QLabel("hello"))
    plain.resize(300, 160)
    plain.show()
    QtWidgets.QApplication.processEvents()

    try:
        # Land in dark for real first, so the outgoing snapshot is a dark
        # window rather than a fake flag.
        theme_utils._apply_theme_impl(qapp)
        _pump(120)
        assert _mean_luminance(plain.grab()) < 128

        mode["theme_mode"] = "Light"
        transition["on"] = True
        theme_utils._apply_theme_impl(qapp)     # dark -> light
        _pump(120)                              # past the settle, mid-fade

        overlay = plain._esim_theme_overlay
        assert overlay._after is not None
        assert _distinct_colors(overlay._after) > 1     # not a flat slab
        # The old look is the dark one, the new look is the light one.
        assert _mean_luminance(overlay._after) > \
            _mean_luminance(overlay._before) + 40

        _pump(400)                              # let the dissolve finish
        assert getattr(plain, "_esim_theme_overlay", None) is None
    finally:
        theme_utils._discard_overlay(getattr(plain, "_esim_theme_overlay", None))
        plain.hide()
        plain.deleteLater()


def test_a_degenerate_snapshot_falls_back_to_a_hard_cut(qapp, window,
                                                        monkeypatch):
    """If the grab comes back unusable for any reason -- a native surface, a
    driver handing back an empty buffer -- dissolving would show a solid
    rectangle where the UI is. Cut instead."""
    monkeypatch.setattr(theme_utils, "_snapshot_is_degenerate",
                        lambda pixmap: True)
    state = theme_utils._begin_theme_transition(qapp, animate=True)
    overlay = window._esim_theme_overlay

    theme_utils._finish_theme_transition(state, fade=True)

    assert overlay._after is None
    assert getattr(overlay, "_esim_fade_anim", None) is None   # never faded
    assert getattr(window, "_esim_theme_overlay", None) is None
    assert window.updatesEnabled()


def test_fade_dissolves_between_two_snapshots(qapp, window):
    """The dissolve must run pixmap-to-pixmap. Fading a translucent snapshot
    over the live tree repaints every widget under it on every frame, which is
    what made the first version run at ~10fps; with the new look captured too
    the overlay is opaque and Qt clips the widgets out of the fade entirely."""
    state = theme_utils._begin_theme_transition(qapp, animate=True)
    overlay = window._esim_theme_overlay

    theme_utils._finish_theme_transition(state, fade=True)

    assert overlay._after is not None       # new look captured, not live
    assert overlay.testAttribute(
        QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)
    assert window.updatesEnabled()          # painting back before the fade
    assert overlay.isVisible()              # old look still on top


def test_fade_removes_the_snapshot(qapp, window):
    state = theme_utils._begin_theme_transition(qapp, animate=True)
    overlay = window._esim_theme_overlay

    theme_utils._finish_theme_transition(state, fade=True)
    assert window.updatesEnabled()          # painting back before the fade
    assert overlay.isVisible()              # old look still on top

    anim = overlay._esim_fade_anim
    assert anim.state() == QtCore.QAbstractAnimation.State.Running
    assert anim.duration() == theme_utils._FADE_MS
    # Drive the dissolve to its end rather than waiting on wall-clock frames,
    # so a loaded machine cannot make this test lie.
    anim.setCurrentTime(anim.duration())
    assert overlay._opacity == 0.0
    # The region goes back to the real widgets before the overlay dies, so
    # there is no uncovered frame between the last fade step and the handover.
    assert not overlay.testAttribute(
        QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent)

    _pump(50)                               # let the deleteLater land
    assert getattr(window, "_esim_theme_overlay", None) is None


def test_painting_is_restored_when_the_repolish_raises(qapp, window,
                                                       monkeypatch):
    """The finish is queued before the repolish for exactly this case: a theme
    apply that dies half way must not leave every window painting-frozen for
    the rest of the session."""
    monkeypatch.setattr(theme_utils, "_transition_enabled", lambda app: True)
    monkeypatch.setattr(theme_utils, "_CURRENT_DARK", False, raising=False)
    monkeypatch.setattr(theme_utils, "_THEME_APPLIED_ONCE", True, raising=False)
    monkeypatch.setattr(theme_utils, "get_preferences",
                        lambda *a, **k: {"theme_mode": "Dark"})

    def boom(*args, **kwargs):
        raise RuntimeError("repolish exploded")
    monkeypatch.setattr(theme_utils, "build_qss", boom)

    with pytest.raises(RuntimeError):
        theme_utils._apply_theme_impl(qapp)
    assert not window.updatesEnabled()       # frozen at the point it died

    # zero-tick + settle + the full fade, with room to spare.
    _pump(800)
    assert window.updatesEnabled()
    assert getattr(window, "_esim_theme_overlay", None) is None


def test_only_a_real_flip_transitions(qapp, window, monkeypatch):
    """Zoom re-applies and accent changes run the same repolish. Freezing paint
    through those would stall the zoom slider for no visible gain."""
    monkeypatch.setattr(theme_utils, "_transition_enabled", lambda app: True)
    monkeypatch.setattr(theme_utils, "_THEME_APPLIED_ONCE", True, raising=False)
    monkeypatch.setattr(theme_utils, "get_preferences",
                        lambda *a, **k: {"theme_mode": "Light"})
    monkeypatch.setattr(theme_utils, "_CURRENT_DARK", False, raising=False)

    began = []
    monkeypatch.setattr(theme_utils, "_begin_theme_transition",
                        lambda app, animate=True: began.append(animate))

    theme_utils._apply_theme_impl(qapp)     # light -> light: no flip
    assert began == []

    monkeypatch.setattr(theme_utils, "_CURRENT_DARK", True, raising=False)
    theme_utils._apply_theme_impl(qapp)     # dark -> light: flip
    assert len(began) == 1

    _pump(50)


def test_titlebar_waits_for_the_middle_of_the_dissolve(qapp, window,
                                                       monkeypatch):
    """DWM owns the caption and cannot fade, only cut. Cutting it at the top
    of the apply -- where the icon loop used to -- lights the titlebar up in
    the new theme while the client area below is still the old one, for the
    whole freeze plus the whole fade."""
    captions = []
    monkeypatch.setattr(theme_utils, "apply_titlebar_theme",
                        lambda w, is_dark=None: captions.append(w))

    state = theme_utils._begin_theme_transition(qapp, animate=True)
    theme_utils._finish_theme_transition(state, fade=True)
    assert captions == []                   # not at the start of the fade

    _pump(theme_utils._FADE_MS)
    assert window in captions               # ...but partway through it


def test_hard_cut_still_switches_the_titlebar(qapp, window, monkeypatch):
    """No dissolve to sync to (motion off, failed grab, watchdog): the caption
    has to switch right there or the window keeps the outgoing theme's bar."""
    captions = []
    monkeypatch.setattr(theme_utils, "apply_titlebar_theme",
                        lambda w, is_dark=None: captions.append(w))

    state = theme_utils._begin_theme_transition(qapp, animate=False)
    theme_utils._finish_theme_transition(state, fade=False)
    assert window in captions


def test_frozen_windows_keep_the_apply_loop_off_their_caption(qapp, window,
                                                              monkeypatch):
    """A window the transition passed over (minimized, hidden) must still be
    themed by the apply loop -- only the frozen ones defer."""
    monkeypatch.setattr(theme_utils, "_transition_enabled", lambda app: True)
    monkeypatch.setattr(theme_utils, "_THEME_APPLIED_ONCE", True, raising=False)
    monkeypatch.setattr(theme_utils, "_CURRENT_DARK", False, raising=False)
    monkeypatch.setattr(theme_utils, "get_preferences",
                        lambda *a, **k: {"theme_mode": "Dark"})
    captions = []
    monkeypatch.setattr(theme_utils, "apply_titlebar_theme",
                        lambda w, is_dark=None: captions.append(w))

    hidden = QtWidgets.QWidget()
    try:
        theme_utils._apply_theme_impl(qapp)
        assert window not in captions       # frozen -> the dissolve owns it
        assert hidden in captions           # never frozen -> themed inline
        _pump(500)
    finally:
        hidden.deleteLater()


def test_frozen_windows_skip_the_synchronous_effect_refresh(qapp, window,
                                                            monkeypatch):
    """The effect refresh repairs what is on screen. While the flip holds the
    windows frozen nothing is on screen, and the deferred pass (queued ahead of
    the transition's settle) still runs before the freeze lifts -- so the
    synchronous walk of every widget must stay off the freeze's critical path.
    """
    monkeypatch.setattr(theme_utils, "_transition_enabled", lambda app: True)
    monkeypatch.setattr(theme_utils, "_THEME_APPLIED_ONCE", True, raising=False)
    monkeypatch.setattr(theme_utils, "_CURRENT_DARK", False, raising=False)
    monkeypatch.setattr(theme_utils, "get_preferences",
                        lambda *a, **k: {"theme_mode": "Dark"})
    refreshes = []
    monkeypatch.setattr(theme_utils, "_refresh_graphics_effects",
                        lambda app: refreshes.append(app))

    theme_utils._apply_theme_impl(qapp)
    assert refreshes == []                  # nothing walked while frozen
    assert theme_utils.transition_active()

    _pump(400)
    assert refreshes                        # the deferred pass still ran
    assert not theme_utils.transition_active()
    assert window.updatesEnabled()


def test_first_apply_never_transitions(qapp, window, monkeypatch):
    """The opening apply runs before any window is built and would read as a
    flip off the False default; it must not fade the splash away."""
    monkeypatch.setattr(theme_utils, "_transition_enabled", lambda app: True)
    monkeypatch.setattr(theme_utils, "_THEME_APPLIED_ONCE", False,
                        raising=False)
    monkeypatch.setattr(theme_utils, "_CURRENT_DARK", False, raising=False)
    monkeypatch.setattr(theme_utils, "get_preferences",
                        lambda *a, **k: {"theme_mode": "Dark"})

    began = []
    monkeypatch.setattr(theme_utils, "_begin_theme_transition",
                        lambda app, animate=True: began.append(animate))

    theme_utils._apply_theme_impl(qapp)
    assert began == []
    assert theme_utils._THEME_APPLIED_ONCE

    _pump(50)
