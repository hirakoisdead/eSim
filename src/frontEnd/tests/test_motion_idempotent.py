"""Regression: install_button_motion must be idempotent.

apply_fullscreen_feature calls install_button_motion(self) on EVERY dock open.
It used to build a fresh TactileButtonFilter each call and installEventFilter it
onto every button under the root; installing a *different* filter object stacks
(it never replaces), so after N dock opens each button carried N filters and
every hover fired N glow animations -- the "gets laggy over the session" bug.

These pin that a second call reuses the one filter and re-wires nothing.

They also pin the on-demand halo: a neutral button carries NO drop-shadow until
the cursor reaches it (a permanent one costs a CPU gaussian blur per repaint,
and the resting glow it painted was invisible anyway), while the one accent
call-to-action per view keeps its halo lit.
"""
from PyQt6 import QtCore, QtWidgets

from frontEnd import motion


def _primary(text, parent):
    btn = QtWidgets.QPushButton(text, parent)
    btn.setProperty("cssClass", "primary")
    return btn


def test_install_button_motion_reuses_filter_and_skips_wired_buttons(qapp):
    motion._motion_enabled_cache = True          # force glows on, no file read
    try:
        root = QtWidgets.QWidget()
        btn = _primary("go", root)               # accent => resting halo

        motion.install_button_motion(root)
        filt1 = root._esim_press_motion_filter
        eff1 = btn.graphicsEffect()
        assert btn.property("_esim_motion_installed") is True
        assert filt1 is not None
        assert eff1 is not None

        # A second dock-open equivalent must NOT stack a new filter or a new
        # shadow effect onto the already-wired button.
        motion.install_button_motion(root)
        assert root._esim_press_motion_filter is filt1   # same filter reused
        assert btn.graphicsEffect() is eff1              # shadow not recreated
    finally:
        motion._motion_enabled_cache = None


def test_neutral_button_carries_no_effect_at_rest(qapp):
    """The N-blurs-always bug: every button used to get a permanent
    QGraphicsDropShadowEffect at install, painting an alpha-14 (invisible)
    glow. Neutral buttons must now install effect-free."""
    motion._motion_enabled_cache = True
    try:
        root = QtWidgets.QWidget()
        btn = QtWidgets.QPushButton("quiet", root)
        motion.install_button_motion(root)
        assert btn.property("_esim_motion_installed") is True
        assert btn.graphicsEffect() is None
    finally:
        motion._motion_enabled_cache = None


def test_accent_and_default_buttons_rest_lit(qapp):
    root = QtWidgets.QWidget()
    neutral = QtWidgets.QPushButton("quiet", root)
    primary = _primary("run", root)
    danger = QtWidgets.QPushButton("delete", root)
    danger.setProperty("cssClass", "danger")
    dflt = QtWidgets.QPushButton("ok", root)
    dflt.setDefault(True)
    opted_out = QtWidgets.QPushButton("arrow", root)
    opted_out.setProperty("noMotion", True)

    assert motion.rest_alpha(neutral) == 0
    assert motion.rest_alpha(opted_out) == 0
    for lit in (primary, danger, dflt):
        assert motion.rest_alpha(lit) == motion._GLOW_REST_ALPHA


def test_hover_creates_halo_and_leave_frees_it(qapp):
    """At most one blurred button at a time: the halo is built on Enter and
    dropped once it has faded, so idle screens carry zero blurs."""
    motion._motion_enabled_cache = True
    try:
        root = QtWidgets.QWidget()
        btn = QtWidgets.QPushButton("go", root)
        motion.install_button_motion(root)
        filt = root._esim_press_motion_filter
        assert btn.graphicsEffect() is None

        filt.eventFilter(btn, QtCore.QEvent(QtCore.QEvent.Type.Enter))
        eff = btn.graphicsEffect()
        assert isinstance(eff, QtWidgets.QGraphicsDropShadowEffect)

        # Cursor gone: the fade-out lands on _drop_glow, which frees the blur.
        filt.eventFilter(btn, QtCore.QEvent(QtCore.QEvent.Type.Leave))
        motion._drop_glow(btn)
        assert btn.graphicsEffect() is None
    finally:
        motion._motion_enabled_cache = None


def test_drop_glow_keeps_the_accent_halo(qapp):
    """_drop_glow must never strip the resting halo off the call-to-action."""
    motion._motion_enabled_cache = True
    try:
        root = QtWidgets.QWidget()
        btn = _primary("run", root)
        motion.install_button_motion(root)
        eff = btn.graphicsEffect()
        assert eff is not None
        motion._drop_glow(btn)
        assert btn.graphicsEffect() is eff
    finally:
        motion._motion_enabled_cache = None


def test_motion_disabled_installs_nothing(qapp):
    motion._motion_enabled_cache = False
    try:
        root = QtWidgets.QWidget()
        btn = QtWidgets.QPushButton("go", root)
        motion.install_button_motion(root)
        assert not btn.property("_esim_motion_installed")
        assert getattr(root, "_esim_press_motion_filter", None) is None
    finally:
        motion._motion_enabled_cache = None


def test_invalidate_motion_cache_forces_reread(qapp):
    motion._motion_enabled_cache = True
    motion.invalidate_motion_cache()
    assert motion._motion_enabled_cache is None


def test_motion_default_is_on_everywhere(qapp, monkeypatch, tmp_path):
    # With no preferences file, motion_enabled() falls back to ON -- Windows
    # included. The Windows drag was the N permanent blurs, not the glow; those
    # are gone, so the platform no longer changes the default. The Preferences
    # toggle still overrides it.
    from configuration import paths
    monkeypatch.setattr(
        paths, "esim_config_path", lambda *p: str(tmp_path / "absent.json"))
    motion.invalidate_motion_cache()
    try:
        assert motion.motion_enabled() is True
    finally:
        motion.invalidate_motion_cache()
