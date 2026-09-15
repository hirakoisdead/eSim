"""Named elevation scale — replaces the scattered per-widget shadow magic
numbers across motion.py / Welcome.py / ProjectExplorer.py / dialogs.py.

One scale, two alpha tracks (dark vs light), and light-mode shadows are
tinted blue-grey so they read as soft ambient occlusion on white instead
of an invisible black smudge.

Native only: QGraphicsDropShadowEffect.

Two ways to spend it:

``elevate()``          puts the effect ON the widget. Cheapest, but it costs
                       that widget's TEXT its subpixel antialiasing — see
                       ``elevate_backdrop`` — so it is only for widgets whose
                       text is transient or absent.
``elevate_backdrop()`` puts the effect on an empty sibling behind the widget.
                       Same shadow, and the widget itself keeps painting
                       straight into the window's opaque backing store, so its
                       text stays ClearType-sharp. Use this for anything that
                       displays text permanently.
"""
from PyQt6 import QtCore, QtWidgets, QtGui

try:
    from frontEnd import tokens
except Exception:  # pragma: no cover - import when run as a script
    import tokens

# level: (blur, dx, dy, alpha_dark, alpha_light)
_SCALE = {
    "e1": (16, 0, 3,  60,  30),   # resting buttons / list rows
    "e2": (24, 0, 6,  90,  42),   # cards, tree, inputs, panels
    "e3": (34, 0, 10, 120, 58),   # docks, toolbars
    "e4": (46, 0, 16, 150, 72),   # dialogs, popped-out windows
    "e5": (60, 0, 22, 180, 92),   # modal / About / Preferences
}


def is_dark(widget) -> bool:
    return widget.palette().color(
        QtGui.QPalette.ColorRole.Window).lightness() < 128


def elevate(widget, level="e2", tint=None):
    """Apply (or update) a layered drop shadow at a named elevation.

    ``tint`` optionally colours the shadow with an accent for a 'glow'.
    Light mode otherwise uses a blue-grey tinted shadow (premium ambient
    occlusion) rather than pure black.
    """
    if level not in _SCALE:
        level = "e2"
    blur, dx, dy, ad, al = _SCALE[level]
    eff = widget.graphicsEffect()
    if not isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
        eff = QtWidgets.QGraphicsDropShadowEffect(widget)
        widget.setGraphicsEffect(eff)
    eff.setBlurRadius(blur)
    eff.setOffset(dx, dy)
    dark = is_dark(widget)
    if tint:
        c = QtGui.QColor(tint)
    else:
        r, g, b = tokens.theme(dark)["shadow_rgb"]
        c = QtGui.QColor(r, g, b)
    c.setAlpha(ad if dark else al)
    eff.setColor(c)
    return eff


class _ShadowBackdrop(QtWidgets.QWidget):
    """An empty rounded rect that carries a sibling widget's drop shadow.

    WHY THIS EXISTS
    ---------------
    ``QGraphicsEffect`` does not composite in place. Qt renders the effect's
    source widget into an offscreen ARGB pixmap, blurs a copy of it, then
    paints both back. Subpixel antialiasing (ClearType) needs to know the
    opaque pixels it is blending against, so Qt cannot use it on a translucent
    buffer and silently downgrades every glyph in that widget to grayscale AA.

    The result is text that is not *wrong*, just soft — which is exactly how it
    was described: "not so pixely, but subtly not sharp". It reproduced on a
    1080p panel at 100% scaling and not on a 175% laptop, because at 1.75x
    device pixels there are simply enough of them to hide the missing hinting
    and subpixel coverage.

    So: the shadow moves off the widget and onto this. It paints one flat
    rounded rect and no text, sits directly behind the real widget at the same
    geometry, and takes the blur. The real widget then paints normally into the
    window's opaque backing store and keeps its subpixel AA. Visually
    identical; the text is sharp again.

    The fill colour matters more than it looks like it should. The widget
    covers this completely and only the blurred *silhouette* escapes past its
    edges — but a source whose stylesheet background is translucent (the
    welcome hero is ``rgba(255,255,255,0.96)``) composites over whatever this
    paints, so a wrong fill tints the whole panel. It therefore has to be the
    colour that would have been *behind* the source anyway; see _fill_colour.
    """

    def __init__(self, source, radius):
        super().__init__(source.parentWidget())
        self._source = source
        # Design-pixel radius. Resolved against the live zoom at paint time
        # rather than stored pre-scaled, because the QSS border-radius it has
        # to match is itself rescaled on every zoom change, and the backdrop
        # is never rebuilt on that path -- a baked radius would drift out of
        # step with its source the first time the user moved the slider.
        self._radius = radius
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

    def _scaled_radius(self):
        """The design radius taken through the same zoom curve as the QSS.

        ``scale_qss_px`` rescales every ``border-radius`` in the sheet, so a
        backdrop drawn at the unscaled radius stops matching its source as
        soon as the zoom leaves 100% -- square backdrop corners poke out from
        behind a rounded panel.
        """
        if self._radius <= 0:
            return 0
        try:
            from frontEnd import theme_utils
            return theme_utils.zoom_px(self._radius)
        except Exception:
            return self._radius

    def _fill_colour(self):
        """The opaque colour to paint under the source.

        Only a *solid, fully opaque* source background may be copied. Two cases
        rule the source's own Window brush out:

        * a gradient background (``QFrame#welcomeHero``) — QStyleSheetStyle puts
          the gradient in the Window brush, and ``QBrush.color()`` on a gradient
          brush is black, which showed through the hero's 4% translucency as a
          grey veil over the whole panel;
        * a translucent background — copying it stacks two translucent layers
          and darkens the result.

        In both cases the honest answer is what was behind the source before a
        backdrop existed: the parent's background.
        """
        for widget in (self._source, self.parentWidget()):
            try:
                if widget is None:
                    continue
                brush = widget.palette().brush(
                    QtGui.QPalette.ColorRole.Window)
                if brush.style() != QtCore.Qt.BrushStyle.SolidPattern:
                    continue
                col = brush.color()
                if col.alpha() == 255:
                    return col
            except RuntimeError:        # C++ side already freed
                continue
        app = QtWidgets.QApplication.instance()
        if app is not None:
            return app.palette().color(QtGui.QPalette.ColorRole.Window)
        return QtGui.QColor(0, 0, 0)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            col = self._fill_colour()
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = QtCore.QRectF(self.rect())
            radius = self._scaled_radius()
            if radius > 0:
                p.drawRoundedRect(r, radius, radius)
            else:
                p.drawRect(r)
        finally:
            p.end()


class _BackdropSync(QtCore.QObject):
    """Keeps a _ShadowBackdrop glued to its source's geometry and visibility.

    The backdrop is deliberately NOT in the parent's layout — a layout would
    reserve space for it and push the real widget aside. Tracking the source's
    Move/Resize/Show/Hide is what keeps a free-floating child in the right
    place instead.
    """

    _EVENTS = frozenset((
        QtCore.QEvent.Type.Resize,
        QtCore.QEvent.Type.Move,
        QtCore.QEvent.Type.Show,
        QtCore.QEvent.Type.Hide,
        QtCore.QEvent.Type.ParentChange,
    ))

    def __init__(self, source, backdrop):
        super().__init__(backdrop)
        self._source = source
        self._backdrop = backdrop
        source.installEventFilter(self)
        # A backdrop whose source is gone is a floating rectangle with a blur
        # on it. Tie their lifetimes together.
        source.destroyed.connect(backdrop.deleteLater)
        self.sync()

    def sync(self):
        try:
            src, bd = self._source, self._backdrop
            if src.parentWidget() is not bd.parentWidget():
                bd.setParent(src.parentWidget())
            bd.setGeometry(src.geometry())
            # stackUnder, not lower(): lower() would drop the backdrop to the
            # bottom of the whole parent, where the central widget would paint
            # over the shadow spill. stackUnder puts it exactly one level below
            # its source and nothing else.
            bd.stackUnder(src)
            bd.setVisible(src.isVisible())
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        if obj is self._source and event.type() in self._EVENTS:
            self.sync()
        return False


class _DeferredBackdrop(QtCore.QObject):
    """Re-runs elevate_backdrop once its target actually has a parent."""

    def __init__(self, widget, level, radius, tint, spec):
        super().__init__(widget)
        self._args = (level, radius, tint, spec)
        self._widget = widget
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (obj is self._widget
                and event.type() == QtCore.QEvent.Type.ParentChange
                and self._widget.parentWidget() is not None):
            level, radius, tint, spec = self._args
            self._widget.removeEventFilter(self)
            elevate_backdrop(self._widget, level, radius, tint, spec)
            self.deleteLater()
        return False


def elevate_backdrop(widget, level="e2", radius=0, tint=None, spec=None):
    """Elevate ``widget`` WITHOUT costing its text subpixel antialiasing.

    Same shadow as ``elevate()``, drawn by an empty sibling behind the widget
    (see _ShadowBackdrop for the full why). Use this on anything that shows
    text permanently — toolbars, trees, cards, panels. Idempotent: calling it
    again on the same widget re-tunes the existing backdrop.

    ``radius`` should match the widget's QSS ``border-radius`` so the shadow
    follows its corners; 0 for square panels.

    ``spec`` is an explicit ``(blur, dx, dy, alpha_dark, alpha_light)`` tuple
    for the handful of surfaces whose shadow is tuned to something the named
    scale does not cover (the two toolbars, whose offsets exist to hide the
    seam where they meet). It overrides ``level``.

    Returns the backdrop's effect, or None if a backdrop could not be created
    (a top-level widget has no sibling to host one — use ``elevate()`` or the
    platform's own window shadow there).
    """
    if widget is None:
        return None
    if widget.parentWidget() is None:
        # Called before the widget was added to a layout -- the common shape is
        # ``card = Card(); shadow(card); layout.addWidget(card)``. There is no
        # sibling to host a backdrop yet, so wait for the parent to arrive
        # rather than silently falling back to an on-widget effect, which is
        # the exact thing this function exists to avoid.
        _DeferredBackdrop(widget, level, radius, tint, spec)
        return None
    if spec is not None:
        blur, dx, dy, ad, al = spec
    else:
        if level not in _SCALE:
            level = "e2"
        blur, dx, dy, ad, al = _SCALE[level]

    backdrop = getattr(widget, "_esim_shadow_backdrop", None)
    try:
        alive = backdrop is not None and backdrop.parentWidget() is not None
    except RuntimeError:            # C++ side already freed
        alive = False
    if not alive:
        backdrop = _ShadowBackdrop(widget, radius)
        widget._esim_shadow_backdrop = backdrop
        # Parented to the backdrop, so it dies with it.
        widget._esim_shadow_sync = _BackdropSync(widget, backdrop)
        # Anything that walked the tree looking for "the widget with the
        # shadow" (refresh_effects, the theme thaw pass) still finds it, and
        # anything looking for a stale effect ON the widget finds none.
        clear(widget)
    else:
        backdrop._radius = radius

    eff = backdrop.graphicsEffect()
    if not isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
        eff = QtWidgets.QGraphicsDropShadowEffect(backdrop)
        backdrop.setGraphicsEffect(eff)
    eff.setBlurRadius(blur)
    eff.setOffset(dx, dy)
    dark = is_dark(widget)
    if tint:
        c = QtGui.QColor(tint)
    else:
        r, g, b = tokens.theme(dark)["shadow_rgb"]
        c = QtGui.QColor(r, g, b)
    c.setAlpha(ad if dark else al)
    eff.setColor(c)
    widget._esim_shadow_sync.sync()
    return eff


def backdrop_effect(widget):
    """The drop shadow behind ``widget``, wherever it happens to live.

    Callers that animate a shadow (hover glows) must not assume it is on the
    widget itself once ``elevate_backdrop`` has moved it.
    """
    backdrop = getattr(widget, "_esim_shadow_backdrop", None)
    if backdrop is not None:
        try:
            eff = backdrop.graphicsEffect()
        except RuntimeError:
            eff = None
        if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
            return eff
    eff = widget.graphicsEffect()
    return eff if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect) else None


def clear(widget):
    """Remove any drop shadow."""
    eff = widget.graphicsEffect()
    if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
        widget.setGraphicsEffect(None)


def refresh_effects(root):
    """Re-validate cached QGraphicsEffect renders within ``root`` + children.

    A QGraphicsDropShadowEffect caches a pixmap of its source. After a
    hide->show (QStackedWidget page switch, tab change) — especially while a
    window is maximized/fullscreen, where the expose/repaint path differs —
    or a theme swap, that cache can stay stale so the widget paints blank
    until a hover marks it dirty. Toggling each effect off/on forces an
    immediate clean repaint.
    """
    if root is None:
        return
    try:
        targets = [root] + root.findChildren(QtWidgets.QWidget)
        for w in targets:
            eff = w.graphicsEffect()
            if eff is not None and eff.isEnabled():
                eff.setEnabled(False)
                eff.setEnabled(True)
        root.update()
    except Exception:
        pass
