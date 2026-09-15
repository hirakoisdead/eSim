import os
import sys
import weakref
from PyQt6 import QtCore, QtGui, QtWidgets

# Motion (button glows) is ON everywhere, Windows included. What made it a
# structural drag on Windows was not the glow itself but that EVERY button
# carried a permanent QGraphicsDropShadowEffect — Qt renders each one to an
# offscreen pixmap and gaussian-blurs it on the CPU (no compositor help on
# Windows), so N buttons meant N live blurs. The resting glow those blurs
# painted was alpha 14/255: invisible. Full price, nothing to show for it.
#
# Now the blur is created on the button under the cursor and torn down when the
# cursor leaves, so at most one exists at a time; the resting look comes from
# QSS (border + gradient), which the style engine paints for free. Accent
# buttons keep a permanent halo (see _PERSISTENT_GLOW_CLASSES) because there is
# only ever one per view.
_MOTION_DEFAULT = True

# How a popup gets its rounded corners, decided once per process.
#
#   "dwm"    Windows 11+. The compositor clips and antialiases the window
#            (theme_utils.apply_round_corners). Best result available here:
#            WA_TranslucentBackground is NOT usable on this path -- under
#            Fusion the popup window is never layered, and a screen grab
#            through the corner of a translucent popup reads #000000, not the
#            desktop behind it.
#   "mask"   Windows 10. Same lack of alpha, and DWM rejects the corner
#            attribute (it arrived in build 22000), so nothing rounds the
#            window at all and the popup ships as a white square with the QSS
#            border curving uselessly inside it. A 1-bit mask is a poor
#            rounding -- hard staircase, no partial coverage -- but it is the
#            only one left, and a stair-stepped curve beats a square.
#   "alpha"  Everything else: translucency rounds the corners properly, with
#            the mask kept as the fallback for alpha-less X11 surfaces.
_ROUND_MODE = None


def round_mode():
    global _ROUND_MODE
    if _ROUND_MODE is None:
        if sys.platform != "win32":
            _ROUND_MODE = "alpha"
        else:
            try:
                from frontEnd import theme_utils
                _ROUND_MODE = ("dwm" if theme_utils.dwm_rounds_popups()
                               else "mask")
            except Exception:
                _ROUND_MODE = "mask"
    return _ROUND_MODE


def _on_windows():
    return round_mode() in ("dwm", "mask")

# Buttons that keep a resting halo instead of only glowing under the cursor:
# the single call-to-action per view. Everything else stays calm — the QSS
# hierarchy is deliberate ("only ONE bold button per view"), and a screen where
# every button glows has no focal point at all.
_PERSISTENT_GLOW_CLASSES = ("primary", "danger")

# Resting halo for those accent buttons, and the hover/press halo for any
# button. Alpha is the only value the animation drives.
_GLOW_REST_ALPHA = 58
_GLOW_HOVER_ALPHA = 110
_GLOW_PRESS_ALPHA = 76

# Every TactileButtonFilter registers here so a theme change can stop all of
# their running glow animations before the global re-polish toggles the very
# graphics effects those animations are driving (a freed effect touched by a
# live animation = use-after-free → segfault). WeakSet so transient dialogs'
# filters don't leak.
_TACTILE_FILTERS = weakref.WeakSet()


# Depth counter, not a bool: a theme apply can overlap the deferred tail of the
# previous one (OS colorSchemeChanged storms, live Preferences toggling), so the
# freeze must stay up until the LAST apply's thaw runs. While frozen, no new glow
# animation starts and no glow effect is deleted -- for the full duration of a
# theme repolish (setStyleSheet + both graphics-effect refresh passes), which is
# exactly the window that tears down / toggles the QGraphicsDropShadowEffects a
# live hover animation drives. A freed effect touched by a running animation is a
# native use-after-free (0xc0000005) that no Python try/except can catch, so the
# only safe fix is to guarantee no such animation exists across that window.
# theme_utils.apply_theme owns the freeze/thaw pair.
_GLOW_FREEZE_DEPTH = 0


def freeze_glow():
    global _GLOW_FREEZE_DEPTH
    _GLOW_FREEZE_DEPTH += 1


def unfreeze_glow():
    global _GLOW_FREEZE_DEPTH
    if _GLOW_FREEZE_DEPTH > 0:
        _GLOW_FREEZE_DEPTH -= 1


def glow_frozen():
    return _GLOW_FREEZE_DEPTH > 0


def stop_all_glow():
    """Stop every button glow animation across all installed filters. Call
    before re-applying the theme (setStyleSheet + effect toggling)."""
    for f in list(_TACTILE_FILTERS):
        try:
            f.stop_all_glow()
        except RuntimeError:
            pass


def is_dark_widget(widget):
    return widget.palette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128


def accent_qcolor(widget):
    c = widget.palette().color(QtGui.QPalette.ColorRole.Highlight)
    if not c.isValid():
        c = QtGui.QColor("#53D7FF" if is_dark_widget(widget) else "#0077A8")
    return c


def set_shadow(widget, blur=24, x=0, y=8, alpha=70, color=None):
    eff = widget.graphicsEffect()
    if not isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
        eff = QtWidgets.QGraphicsDropShadowEffect(widget)
        widget.setGraphicsEffect(eff)
    eff.setBlurRadius(blur)
    eff.setOffset(x, y)
    c = QtGui.QColor(color) if color else QtGui.QColor(0, 0, 0)
    c.setAlpha(alpha)
    eff.setColor(c)
    return eff


def apply_panel_depth(widget, blur=28, y=8, alpha=76):
    return set_shadow(widget, blur=blur, y=y, alpha=alpha)


def apply_popup_depth(widget):
    return set_shadow(widget, blur=42, y=14, alpha=128)


def apply_accent_glow(widget, blur=22, alpha=74):
    return set_shadow(widget, blur=blur, y=0, alpha=alpha, color=accent_qcolor(widget))


def make_menu_rounded(menu):
    """Give a QMenu genuinely transparent corners.

    The menu QSS uses ``border-radius`` to round the frame, but a QMenu's
    top-level window is an opaque rectangle by default, so the four corners
    OUTSIDE the rounded frame paint as solid (black) squares — the "black
    corners" gap between the rounding and the squared window. Marking the
    window translucent makes those corners transparent so only the rounded
    frame shows. Set this on a freshly-created menu BEFORE it is first shown
    (the native window must be created with the translucent attribute), so
    call it right after ``QMenu(...)`` / ``addMenu(...)``.

    Windows is the exception on both of its paths (see round_mode): the popup
    never gets an alpha surface there, so asking for translucency would only
    paint the corners black. Nothing to do at create time — DWM and the mask
    both need the native window, so the rounding is applied on Show.
    """
    if menu is None or _on_windows():
        return menu
    try:
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Windows gives every popup window the legacy CS_DROPSHADOW class
        # style: a hard-edged native shadow drawn around the WINDOW, not the
        # rounded frame, so it reads as a dark outline hugging the menu.
        # Linux compositors never draw it, which is why the same build looks
        # clean on Ubuntu. Opting out must happen before the native window is
        # created, same as the translucency attribute.
        menu.setWindowFlag(
            QtCore.Qt.WindowType.NoDropShadowWindowHint, True)
    except Exception:
        pass
    return menu


def apply_menu_rounded_mask(menu, radius=14):
    """Clip a QMenu's window to a rounded-rect region so its corners are round
    on EVERY surface.

    ``WA_TranslucentBackground`` only produces transparent corners when the
    popup's surface has an alpha channel. Over a QWebEngineView (Makerchip /
    User Manual) or the plotting widgets that surface has no alpha, so the
    squared window's corners paint solid black around the QSS ``border-radius``.
    A mask physically removes those corner pixels from the window — no alpha or
    compositor needed — so the rounding shows everywhere. Re-applied on each
    Show because a QMenu sizes to its content (the mask must match its size).
    The radius matches the QMenu QSS ``border-radius`` (14px).

    Windows does NOT come through here — it rounds via DWM instead (see
    theme_utils.apply_round_corners). A mask is a poor way to round anything:
    it is 1-bit, so the curve it cuts is all-or-nothing per pixel and lands as
    a visible staircase, and Qt scales it from logical to device pixels, so at
    175% display scaling each of those steps arrives ~2 physical pixels tall.
    DWM antialiases in the compositor and has none of that. The mask survives
    only for the surfaces with no better option: a compositor-less X11, where
    an alpha-less surface would otherwise paint the corners solid black.

    Antialiasing is deliberately NOT enabled on the painter below: a QBitmap
    is monochrome, so it cannot store the partial coverage antialiasing
    produces, and QPainter dithers it instead — turning the smooth edge into a
    stipple of holes. A hard edge is the best a 1-bit mask can do, so ask for
    exactly that.
    """
    if menu is None:
        return
    try:
        size = menu.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        bmp = QtGui.QBitmap(size)
        bmp.fill(QtCore.Qt.GlobalColor.color0)          # color0 = clipped out
        p = QtGui.QPainter(bmp)
        p.setPen(QtCore.Qt.GlobalColor.color1)          # color1 = kept
        p.setBrush(QtCore.Qt.GlobalColor.color1)
        p.drawRoundedRect(0, 0, size.width(), size.height(), radius, radius)
        p.end()
        menu.setMask(QtGui.QRegion(bmp))
    except Exception:
        pass


def _round_popup_via_dwm(popup):
    """Windows path for apply_menu_rounded_mask: round the popup in DWM.

    Called on Show because DWM addresses the window by HWND, which does not
    exist before then. Re-applying on every Show is harmless (it is a plain
    window attribute, not an animation) and covers popups whose native window
    Qt has destroyed and rebuilt in between.

    If DWM refuses the attribute, this permanently downgrades the process to
    the mask path and rounds this popup with it. The build-number check in
    round_mode() is a prediction; this is the answer. They disagree whenever
    something other than the Windows version is what stopped the compositor
    from rounding -- and the failure mode being guarded against here (a menu
    shipping as a plain white square) is exactly what an over-confident
    prediction produced on the user's second machine.
    """
    if popup is None:
        return
    global _ROUND_MODE
    from frontEnd import theme_utils
    if not theme_utils.apply_round_corners(popup):
        _ROUND_MODE = "mask"
        # The sheet is already carrying the DWM override on this path (it is
        # emitted for exactly the builds that took it), so the mask has to cut
        # at the radius the border is drawn at, not at the mask path's own.
        apply_menu_rounded_mask(
            popup, radius=theme_utils.DWM_CORNER_RADIUS_PX)


def rest_alpha(widget):
    """Resting glow alpha for a button: the one accent call-to-action per view
    keeps its halo lit; every other button rests at 0 and carries no effect at
    all until the cursor reaches it."""
    if widget.property("noMotion") or widget.property("dockPopButton"):
        return 0
    if widget.property("cssClass") in _PERSISTENT_GLOW_CLASSES:
        return _GLOW_REST_ALPHA
    if isinstance(widget, QtWidgets.QPushButton) and widget.isDefault():
        return _GLOW_REST_ALPHA
    return 0


def _ensure_glow(widget):
    """The button's drop-shadow, created (transparent) if it has none yet.

    Creating on demand is the whole point: a QGraphicsDropShadowEffect costs a
    CPU gaussian blur on every repaint of its widget, so one must exist only
    while it is actually painting something visible."""
    eff = widget.graphicsEffect()
    if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
        return eff
    if eff is not None:
        return None                      # some other effect — leave it alone
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(18)
    eff.setOffset(0, 4)
    c = accent_qcolor(widget)
    c.setAlpha(0)
    eff.setColor(c)
    widget.setGraphicsEffect(eff)
    return eff


def _drop_glow(widget):
    """Remove a fully-faded halo so the button goes back to costing nothing.
    Skipped for buttons whose resting state is lit."""
    # Deleting an effect (setGraphicsEffect(None) frees the C++ object) during a
    # theme apply is exactly the free that races the repolish. Leave every effect
    # alive while frozen; the next fade-out after the apply reclaims it.
    if glow_frozen():
        return
    if rest_alpha(widget) > 0:
        return
    try:
        eff = widget.graphicsEffect()
        if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
            widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


class TactileButtonFilter(QtCore.QObject):
    """Button hover/press feedback via shadow glow only.
    Position animation removed — conflicts with Qt layouts inside toolbars.
    Press depth comes from QSS padding-top/padding-bottom shift instead.

    The halo is created when the cursor enters and destroyed once it has faded
    out, so at most one blurred button exists at a time no matter how many are
    on screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glow_anims = {}
        _TACTILE_FILTERS.add(self)

    def stop_all_glow(self):
        for anim in list(self._glow_anims.values()):
            try:
                anim.stop()
            except RuntimeError:
                pass
        self._glow_anims.clear()

    def eventFilter(self, obj, event):
        if not isinstance(obj, (QtWidgets.QPushButton, QtWidgets.QToolButton)) or not obj.isEnabled():
            return False
        if obj.property("noMotion"):
            return False

        # A theme apply is tearing effects down: never spawn a glow animation
        # onto an effect that is about to be toggled/deleted mid-repolish. The
        # pointing-hand cursor was set at install time, so hover feedback still
        # reads fine without the halo for this brief window.
        if glow_frozen():
            return False

        is_dock = bool(obj.property("dockPopButton"))
        et = event.type()

        if et == QtCore.QEvent.Type.Enter:
            obj.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            if not is_dock:
                self._animate_glow(obj, 22, 5, _GLOW_HOVER_ALPHA)
        elif et == QtCore.QEvent.Type.Leave:
            if not is_dock:
                self._animate_glow(obj, 18, 4, rest_alpha(obj))
        elif et == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.MouseButton.LeftButton:
            if not is_dock:
                self._animate_glow(obj, 14, 1, _GLOW_PRESS_ALPHA)
        elif et == QtCore.QEvent.Type.MouseButtonRelease:
            if not is_dock:
                target = _GLOW_HOVER_ALPHA if obj.underMouse() else rest_alpha(obj)
                self._animate_glow(obj, 18, 4, target)
        return False

    def _animate_glow(self, obj, blur, y, alpha):
        """Smoothly transition the drop-shadow glow color on a button."""
        # Never start a glow while a theme apply is churning graphics effects --
        # the animation would drive an effect the repolish may free underneath it
        # (native use-after-free). The freeze is lifted once the apply finishes.
        if glow_frozen():
            return
        # The previous animation was started DeleteWhenStopped, so once it has
        # finished Qt has freed its C++ object — calling stop() on the stale
        # Python ref then raises "wrapped C/C++ object … deleted". That storm of
        # exceptions fired during the global re-polish a theme change triggers
        # and could touch a freed graphics effect (use-after-free → segfault).
        # Guard the stop and drop the stale entry.
        old = self._glow_anims.pop(obj, None)
        if old is not None:
            try:
                old.stop()
            except RuntimeError:
                pass
        eff = _ensure_glow(obj)
        if eff is None:
            return
        acc = accent_qcolor(obj)
        try:
            current_alpha = eff.color().alpha()
        except RuntimeError:
            return

        anim = QtCore.QVariantAnimation(obj)
        anim.setDuration(140)
        anim.setStartValue(current_alpha / 255.0)
        anim.setEndValue(alpha / 255.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        def _apply_alpha(val):
            # Re-fetch the live effect off the widget every tick rather than
            # closing over `eff`: a captured Python ref to a C++ effect that
            # setGraphicsEffect(None)/a repolish has freed is a dangling pointer,
            # and calling into it is a native use-after-free that no try/except
            # can catch. graphicsEffect() always returns the current effect (or
            # None) -- never a stale wrapper -- so this can only touch live memory.
            try:
                live = obj.graphicsEffect()
                if not isinstance(live, QtWidgets.QGraphicsDropShadowEffect):
                    return
                new_c = QtGui.QColor(acc)
                new_c.setAlpha(int(val * 255))
                live.setColor(new_c)
            except RuntimeError:
                pass
        anim.valueChanged.connect(_apply_alpha)

        def _settled(o=obj, target=alpha):
            self._glow_anims.pop(o, None)
            # Faded to nothing and the cursor has moved on: free the blur.
            # Re-check underMouse rather than trusting `target` — a new Enter
            # may have landed while this fade-out was still running.
            if target <= 0:
                try:
                    if not o.underMouse():
                        _drop_glow(o)
                except RuntimeError:
                    pass
        # Drop our reference the instant it stops, so a later stop() can never
        # reach a DeleteWhenStopped-freed animation.
        anim.finished.connect(_settled)
        self._glow_anims[obj] = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

        try:
            eff.setBlurRadius(blur)
            eff.setOffset(0, y)
        except RuntimeError:
            pass


_motion_enabled_cache = None


def motion_enabled():
    """True when animated button glows are enabled (default on).

    Hover/press glows drive continuous repaints + a per-button drop-shadow.
    They're on by default so the effect is discoverable, with a Preferences
    toggle to turn them off (reduce motion / save power). The prefs file is
    read once and cached (this is called on every dock open and every button
    wire-up); Preferences save invalidates the cache via
    :func:`invalidate_motion_cache`. Reading the file keeps this module free of
    an Appconfig import; an absent/unreadable file falls back to the default.
    """
    global _motion_enabled_cache
    if _motion_enabled_cache is not None:
        return _motion_enabled_cache
    import json
    from configuration import paths
    try:
        path = paths.esim_config_path("preferences.json")
        with open(path) as fh:
            val = bool(json.load(fh).get("enable_motion", _MOTION_DEFAULT))
    except Exception:
        val = _MOTION_DEFAULT
    _motion_enabled_cache = val
    return val


def invalidate_motion_cache():
    """Drop the cached enable_motion value so the next read re-hits the file.

    Call after Preferences writes preferences.json."""
    global _motion_enabled_cache
    _motion_enabled_cache = None


def install_button_motion(root):
    # Single gate for every call site: when motion is off, install nothing so
    # no glow animations or extra graphics effects are ever created.
    if not motion_enabled():
        return
    # Reuse ONE filter per root across repeated calls. install_button_motion
    # runs on every dock open; a fresh TactileButtonFilter each time would
    # STACK on every button (installEventFilter with a new object appends, it
    # never replaces), so after N dock opens each button carried N filters and
    # every hover fired N glow animations -- the "gets laggy over a session"
    # signature, since the DockArea lives for the whole app lifetime.
    filt = getattr(root, "_esim_press_motion_filter", None)
    if filt is None:
        filt = TactileButtonFilter(root)
        root._esim_press_motion_filter = filt
    for w in root.findChildren((QtWidgets.QPushButton, QtWidgets.QToolButton)):
        if isinstance(w.parent(), QtWidgets.QToolBar):
            continue
        # Idempotent per button: one already wired in a previous pass keeps its
        # single filter and its one base shadow -- skip it so neither stacks.
        if w.property("_esim_motion_installed"):
            continue
        w.setProperty("_esim_motion_installed", True)
        w.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        w.installEventFilter(filt)
        # Only the accent call-to-action gets a halo up front; the rest stay
        # effect-free until hovered (the filter builds one on Enter and frees it
        # on Leave). noMotion / dockPopButton buttons opt out entirely — small
        # chrome controls (e.g. the verifier's move arrows) use it so the neon
        # halo never bleeds over their neighbours. rest_alpha() encodes all of
        # that.
        alpha = rest_alpha(w)
        if alpha > 0:
            eff = _ensure_glow(w)
            if eff is not None:
                c = accent_qcolor(w)
                c.setAlpha(alpha)
                eff.setColor(c)


class TabMotionFilter(QtCore.QObject):
    """Cursor feedback for tab bars: hand cursor, glow on press."""

    def eventFilter(self, obj, event):
        if not isinstance(obj, QtWidgets.QTabBar):
            return False
        if event.type() == QtCore.QEvent.Type.Enter:
            obj.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        elif event.type() == QtCore.QEvent.Type.MouseButtonPress:
            obj.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            apply_accent_glow(obj, blur=20, alpha=60)
        elif event.type() in (QtCore.QEvent.Type.MouseButtonRelease, QtCore.QEvent.Type.Leave):
            obj.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            if event.type() == QtCore.QEvent.Type.Leave:
                eff = obj.graphicsEffect()
                if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
                    c = eff.color()
                    c.setAlpha(0)
                    eff.setColor(c)
        return False


def install_tab_kinetics(root):
    filt = TabMotionFilter(root)
    root._esim_tab_kinetic_filter = filt
    for bar in root.findChildren(QtWidgets.QTabBar):
        bar.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        bar.installEventFilter(filt)


class PopupMotionFilter(QtCore.QObject):
    """Make every QMenu translucent so QSS border-radius corners are genuine.

    No opacity fade animation — animating ``windowOpacity`` on a QMenu can
    cause the native window to re-create mid-show, which generates a second
    Show event and makes the menu flash open/closed every other click.
    The rounding alone (WA_TranslucentBackground + QSS border-radius) is
    enough for the polished look.
    """

    def eventFilter(self, obj, event):
        et = event.type()

        # Cheap gate FIRST: this filter only reacts to Polish and Show. As an
        # app-wide filter it sees every event in the process (MouseMove, Paint,
        # Timer, ...), each crossing C++->Python; bail on the ~99% we ignore
        # before doing any isinstance / type-name work.
        if et not in (QtCore.QEvent.Type.Polish, QtCore.QEvent.Type.Show):
            return False

        # Smooth expand/collapse for every tree (project tree, device-model
        # grouping, etc.). Set once, when the view is first polished — Qt has a
        # built-in animated transition; we just have to opt in.
        if isinstance(obj, QtWidgets.QTreeView) and et == QtCore.QEvent.Type.Polish:
            try:
                obj.setAnimated(True)
            except Exception:
                pass
            return False

        # ComboBox dropdowns share the menu problem: the popup *container* is a
        # square top-level window, so the rounded QSS on the inner item-view used
        # to sit on sharp black corners. Same fix as menus -- translucent surface
        # before the native window exists, plus a rounded mask on show for the
        # no-compositor / over-QWebEngineView case. Radius matches the item-view
        # QSS (10px).
        # Windows: theme the native titlebar of every real window as it
        # appears (main window, dialogs, plot windows, ...). Popups/tooltips
        # have no caption, so only Window/Dialog types matter. Re-applied on
        # every Show — three cheap dwmapi calls — so windows re-shown after a
        # theme toggle pick up the new caption color.
        if (sys.platform == "win32"
                and et == QtCore.QEvent.Type.Show
                and isinstance(obj, QtWidgets.QWidget)
                and obj.isWindow()
                and obj.windowType() in (
                    QtCore.Qt.WindowType.Window,
                    QtCore.Qt.WindowType.Dialog)):
            from frontEnd import theme_utils
            theme_utils.apply_titlebar_theme(obj)

        if type(obj).__name__ == "QComboBoxPrivateContainer":
            mode = round_mode()
            if mode == "dwm":
                if et == QtCore.QEvent.Type.Show:
                    _round_popup_via_dwm(obj)
                return False
            if mode == "mask":
                # Windows 10: no compositor rounding and no alpha. Mask only —
                # setting translucency here would blacken the corners it is
                # supposed to remove.
                if et == QtCore.QEvent.Type.Show:
                    apply_menu_rounded_mask(obj, radius=10)
                    QtCore.QTimer.singleShot(
                        0, lambda c=obj: apply_menu_rounded_mask(c, radius=10))
                return False
            if et == QtCore.QEvent.Type.Polish:
                if not obj.testAttribute(
                        QtCore.Qt.WidgetAttribute.WA_TranslucentBackground):
                    obj.setAttribute(
                        QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
                obj.setWindowFlag(
                    QtCore.Qt.WindowType.NoDropShadowWindowHint, True)
            elif et == QtCore.QEvent.Type.Show:
                apply_menu_rounded_mask(obj, radius=10)
                QtCore.QTimer.singleShot(
                    0, lambda c=obj: apply_menu_rounded_mask(c, radius=10))
            return False

        if isinstance(obj, QtWidgets.QMenu):
            mode = round_mode()
            # Windows 11: no translucency (it would only blacken the corners)
            # and no mask (it would only stair-step them) — DWM rounds the
            # window itself once it exists, which is Show, not Polish.
            if mode == "dwm":
                if et == QtCore.QEvent.Type.Show:
                    _round_popup_via_dwm(obj)
                return False
            if mode == "mask":
                # Windows 10: DWM will not round it and there is no alpha to
                # round it with, so the mask is the only thing standing
                # between the user and a square white popup.
                if et == QtCore.QEvent.Type.Show:
                    apply_menu_rounded_mask(obj)
                    QtCore.QTimer.singleShot(
                        0, lambda m=obj: apply_menu_rounded_mask(m))
                return False
            if et == QtCore.QEvent.Type.Polish:
                # Set translucency BEFORE the native popup window is created.
                # A post-show attribute change (or setMask) is ignored once the
                # window is realized as an opaque rectangle — which is why menus
                # built by QWebEngineView (Makerchip) / the plotting module kept
                # black corners while our own menus (rounded at creation) did
                # not. Polish fires before window creation, so the alpha-rounded
                # corners now work for every menu, on any compositor (incl.
                # Wayland, where window-shape masks are not honored at all).
                if not obj.testAttribute(
                        QtCore.Qt.WidgetAttribute.WA_TranslucentBackground):
                    obj.setAttribute(
                        QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
                obj.setWindowFlag(
                    QtCore.Qt.WindowType.NoDropShadowWindowHint, True)
            elif et == QtCore.QEvent.Type.Show:
                # X11-without-compositor fallback: clip the corners with a
                # rounded mask for any surface that still lacks alpha. Harmless
                # where translucency already rounded them; does NOT recreate the
                # native window (so no every-other-click flash). Re-applied next
                # tick so the mask matches the menu's final laid-out size.
                apply_menu_rounded_mask(obj)
                QtCore.QTimer.singleShot(0, lambda m=obj: apply_menu_rounded_mask(m))
        return False


def install_popup_motion(app):
    filt = PopupMotionFilter(app)
    app._esim_popup_motion_filter = filt
    app.installEventFilter(filt)


class EffectShowRefreshFilter(QtCore.QObject):
    """Re-validate a widget's drop-shadow cache whenever it is shown.

    A QGraphicsDropShadowEffect caches a render of its source. When a widget
    is hidden then shown again (QStackedWidget page switch, tab change) — most
    visibly while a window is maximized/fullscreen, where the expose/repaint
    path differs — that cache can stay stale and the widget paints blank until
    a hover marks it dirty. Toggling the effect off/on on Show forces a clean
    repaint. Installed application-wide so every effect-bearing widget is
    covered without per-site wiring.
    """

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Show and isinstance(obj, QtWidgets.QWidget):
            eff = obj.graphicsEffect()
            if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect) and eff.isEnabled():
                # Defer the toggle to the next tick: a Show can be delivered
                # mid-paint, and toggling the effect synchronously would force
                # a reentrant repaint ("paint device that is being painted").
                QtCore.QTimer.singleShot(0, lambda e=eff: self._revalidate(e))
        return False

    @staticmethod
    def _revalidate(eff):
        try:
            if eff.isEnabled():
                eff.setEnabled(False)
                eff.setEnabled(True)
        except RuntimeError:
            # underlying effect/widget was deleted before the tick fired
            pass


def install_effect_refresh(app):
    filt = EffectShowRefreshFilter(app)
    app._esim_effect_refresh_filter = filt
    app.installEventFilter(filt)


class AppWideMotionFilter(PopupMotionFilter):
    """The single app-wide filter: PopupMotionFilter's popup/tree rounding PLUS
    EffectShowRefreshFilter's drop-shadow revalidation on Show.

    Merged into one object so each of the process's events crosses the
    C++->Python boundary once, not twice (two separate app-wide filters each
    ran an eventFilter per event). The Polish/Show gate inherited from
    PopupMotionFilter still short-circuits everything else first.
    """

    def eventFilter(self, obj, event):
        et = event.type()
        # Same cheap gate as the base; keep it here so the added Show work below
        # is never reached for the events we ignore.
        if et not in (QtCore.QEvent.Type.Polish, QtCore.QEvent.Type.Show):
            return False
        # Popup rounding + tree animation (base handles Polish and Show).
        super().eventFilter(obj, event)
        # Effect revalidation is Show-only.
        if et == QtCore.QEvent.Type.Show and isinstance(obj, QtWidgets.QWidget):
            eff = obj.graphicsEffect()
            if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect) \
                    and eff.isEnabled():
                QtCore.QTimer.singleShot(
                    0, lambda e=eff: EffectShowRefreshFilter._revalidate(e))
        return False


def install_app_motion(app):
    """Install the single merged app-wide motion filter (replaces the old
    install_popup_motion + install_effect_refresh pair)."""
    filt = AppWideMotionFilter(app)
    app._esim_app_motion_filter = filt
    app.installEventFilter(filt)


def install_context_menu_motion(root):
    filt = PopupMotionFilter(root)
    root._esim_context_motion_filter = filt
    root.installEventFilter(filt)


def apply_toolbar_depth(window):
    """Floating-toolbar shadows on both bars for 3D inverted-L.

    Both toolbars share the same opaque fill (QSS), so they read as one
    piece. The left rail is added AFTER the top bar, giving it higher
    z-order — its opaque background paints OVER the top bar's downward
    shadow at the joint, hiding the seam. The left rail's own shadow is
    pushed slightly DOWN (y=6) so its blur does not bleed upward into
    the corner.

    The shadow goes on an empty backdrop behind each bar, NOT on the bar
    itself. A QGraphicsEffect renders its source into an offscreen ARGB pixmap,
    and Qt cannot run subpixel antialiasing against a translucent buffer — so
    an effect directly on the toolbar quietly downgraded every glyph in it
    (the zoom pill, the menu-bar labels) to grayscale AA. That is the "fonts
    look subtly low-res" report: invisible on a 175%-scaled panel, plain at 1x
    on 1080p. See elevation._ShadowBackdrop.
    """
    from frontEnd.elevation import elevate_backdrop

    # Offsets tuned to hide the seam where the two bars meet, so they stay
    # verbatim rather than snapping to a named elevation level.
    specs = {
        "topToolbar": (34, 0, 5, 82),
        "leftToolBar": (24, 4, 6, 72),
    }
    for name, (blur, x, y, alpha) in specs.items():
        tb = window.findChild(QtWidgets.QToolBar, name)
        if not tb:
            continue
        elevate_backdrop(tb, radius=0, tint=QtGui.QColor(0, 0, 0),
                         spec=(blur, x, y, alpha, alpha))


def install_menu_depth(root):
    """Pre-install depth shadows on menu bars for consistent 3D presence.

    Windows is excluded, and gets a sharper menu for it. A QGraphicsEffect on
    a QMenu forces the whole popup — every item label in it — through an
    offscreen ARGB buffer, which costs it ClearType. On Windows that buys
    nothing: make_menu_rounded() returns early there, so the popup keeps the
    platform's own window shadow (and its DWM-rounded corners), and this effect
    was only ever painting a second shadow on top of it. Elsewhere the popup
    is already translucent (WA_TranslucentBackground), so its text is on
    grayscale AA either way and the effect is the only shadow there is.
    """
    if _on_windows():
        return
    for menu in root.findChildren(QtWidgets.QMenu):
        eff = QtWidgets.QGraphicsDropShadowEffect(menu)
        eff.setBlurRadius(34)
        eff.setOffset(0, 12)
        eff.setColor(QtGui.QColor(0, 0, 0, 120))
        menu.setGraphicsEffect(eff)
