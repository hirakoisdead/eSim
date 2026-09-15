"""Custom rounded tooltip for the eSim 'Aurora' design system.

Qt's native ``QToolTip`` is a top-level window whose corners are NOT clipped by
a stylesheet ``border-radius`` — the radius only draws an inset rounded border
*inside* a square window, leaving the squared outer corners visible. That is
the "ugly square blue box" the QSS ``QToolTip`` rule could never fully fix.

This module replaces it application-wide with a frameless, translucent,
painted-rounded card that honours the active theme and carries a soft drop
shadow. Install once via :func:`install_tooltips`; an app-level event filter
then intercepts every ``QEvent.ToolTip``, suppresses the native tip and shows
ours instead.

No project imports — safe to import in headless contexts.
"""
from PyQt6 import QtCore, QtGui, QtWidgets


def _is_dark(app):
    try:
        return app.palette().color(
            QtGui.QPalette.ColorRole.Window).lightness() < 128
    except Exception:
        return True


def _tip_colors(app):
    """(background, text, border) as QSS-ready strings, accent-tinted border.

    Both themes use a dark navy card with light text — a dark tooltip over a
    light UI is a deliberate, legible contrast, and matches the prior intent of
    the QSS ``QToolTip`` rule."""
    dark = _is_dark(app)
    acc = app.palette().color(QtGui.QPalette.ColorRole.Highlight)
    if not acc.isValid():
        acc = QtGui.QColor("#53D7FF" if dark else "#0077A8")
    bg = "rgba(13,23,40,0.98)" if dark else "rgba(16,27,46,0.98)"
    text = "#EAF3FF"
    border = "rgba(%d,%d,%d,0.42)" % (acc.red(), acc.green(), acc.blue())
    return bg, text, border


class AuroraToolTip(QtWidgets.QWidget):
    """Frameless translucent tooltip with a painted rounded card + shadow.

    A transparent outer widget reserves ``_PAD`` px of breathing room on every
    side so the inner card's drop shadow has somewhere to fall; the visible card
    is the inner ``QFrame`` whose rounded corners are genuine (the window is
    translucent, so its own square corners are invisible)."""

    _PAD = 16  # transparent margin around the card for the shadow blur

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            QtCore.Qt.WindowType.ToolTip
            | QtCore.Qt.WindowType.FramelessWindowHint
            # Windows draws a hard native CS_DROPSHADOW around the whole
            # (padded, mostly transparent) window — a floating square outline
            # detached from the card, which paints its own soft shadow.
            | QtCore.Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("auroraTipCard")
        self._label = QtWidgets.QLabel(self._card)
        self._label.setTextFormat(QtCore.Qt.TextFormat.AutoText)
        self._label.setWordWrap(True)
        from frontEnd.theme_utils import zoom_px
        self._label.setMaximumWidth(zoom_px(380))

        card_lay = QtWidgets.QVBoxLayout(self._card)
        card_lay.setContentsMargins(13, 9, 13, 10)
        card_lay.addWidget(self._label)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(self._PAD, self._PAD, self._PAD, self._PAD)
        outer.addWidget(self._card)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QtGui.QColor(0, 0, 0, 160))
        self._card.setGraphicsEffect(shadow)

        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_text(self, text, global_pos, app, owner=None):
        # Wayland popup surfaces need a transient parent before they are
        # shown. Keep QWidget ownership independent so closing an editor
        # does not delete the application-wide cached tooltip.
        owner = owner or app.activeWindow()
        if isinstance(owner, QtWidgets.QWidget):
            owner = owner.window()
            owner.winId()
            self.winId()
            handle = self.windowHandle()
            if handle.transientParent() is not owner.windowHandle():
                self.hide()
                handle.setTransientParent(owner.windowHandle())
        bg, fg, border = _tip_colors(app)
        self._card.setStyleSheet(
            "QFrame#auroraTipCard{"
            "background:%s;border:1px solid %s;border-radius:11px;}" % (bg, border)
        )
        self._label.setStyleSheet(
            "color:%s;font-size:12px;font-weight:500;"
            "background:transparent;border:none;" % fg
        )
        self._label.setText(text)
        self.adjustSize()
        self._place(global_pos)
        self.show()
        self.raise_()
        # Safety-net auto-hide; the Leave/press handlers normally dismiss first.
        self._hide_timer.start(min(15000, 4000 + len(text) * 55))

    def _place(self, gpos):
        screen = (QtWidgets.QApplication.screenAt(gpos)
                  or QtWidgets.QApplication.primaryScreen())
        geo = screen.availableGeometry()
        sz = self.size()
        pad = self._PAD
        # Offset the visible card from the cursor; the transparent pad cancels
        # so the card (not the window) sits at the intended offset.
        x = gpos.x() + 16 - pad
        y = gpos.y() + 22 - pad
        # Flip above the cursor if it would overflow the bottom edge.
        if y + sz.height() - pad > geo.bottom():
            y = gpos.y() - sz.height() + pad - 6
        x = max(geo.left() - pad, min(x, geo.right() - sz.width() + pad))
        y = max(geo.top() - pad, min(y, geo.bottom() - sz.height() + pad))
        self.move(x, y)


class _ToolTipFilter(QtCore.QObject):
    """App-level filter: show the Aurora tooltip, suppress the native one."""

    _DISMISS = frozenset((
        QtCore.QEvent.Type.Leave,
        QtCore.QEvent.Type.WindowDeactivate,
        QtCore.QEvent.Type.FocusOut,
        QtCore.QEvent.Type.Wheel,
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QEvent.Type.KeyPress,
    ))

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self._tip = None

    def _ensure(self):
        if self._tip is None:
            self._tip = AuroraToolTip()
        return self._tip

    def _hide(self):
        if self._tip is not None and self._tip.isVisible():
            self._tip.hide()

    @staticmethod
    def _ancestor(global_pos, cls):
        """Nearest ``cls`` at/above the widget under ``global_pos`` (or None)."""
        w = QtWidgets.QApplication.widgetAt(global_pos)
        while w is not None and not isinstance(w, cls):
            w = w.parent()
        return w if isinstance(w, cls) else None

    @classmethod
    def _item_tip(cls, global_pos):
        """ToolTipRole of the item-view row under ``global_pos`` (or "")."""
        view = cls._ancestor(global_pos, QtWidgets.QAbstractItemView)
        if view is None:
            return ""
        try:
            pos = view.viewport().mapFromGlobal(global_pos)
            idx = view.indexAt(pos)
        except RuntimeError:
            # PyQt6 refuses (some) virtual calls on views it did not create
            # (Qt-internal C++ views such as a combo box's popup list); treat
            # those as having no item tip and let the widget fallback run.
            return ""
        if not idx.isValid():
            return ""
        data = idx.data(QtCore.Qt.ItemDataRole.ToolTipRole)
        return data or ""

    @classmethod
    def _tab_tip(cls, global_pos):
        """Tooltip of the tab under ``global_pos`` (or "").

        Tab tips are not widget tips: ``QTabBar`` stores one per tab and paints
        the native square box from its *own* ``QEvent.ToolTip`` handler, which
        the widget-level lookups never see. That is why the dock strip at the
        bottom (Netlist, Simulation, …) kept the ugly box while everything else
        got the Aurora card. Qt fills these in itself for tabified docks
        (tabToolTip == the dock title)."""
        bar = cls._ancestor(global_pos, QtWidgets.QTabBar)
        if bar is None:
            return ""
        try:
            idx = bar.tabAt(bar.mapFromGlobal(global_pos))
        except RuntimeError:
            return ""
        if idx < 0:
            return ""
        return bar.tabToolTip(idx) or ""

    @classmethod
    def _header_tip(cls, global_pos):
        """ToolTipRole of the header section under ``global_pos`` (or "").

        ``QHeaderView`` is an item view whose ``indexAt`` is always invalid, so
        it needs the section-based lookup instead of :meth:`_item_tip`."""
        hdr = cls._ancestor(global_pos, QtWidgets.QHeaderView)
        if hdr is None:
            return ""
        model = hdr.model()
        if model is None:
            return ""
        try:
            pos = hdr.viewport().mapFromGlobal(global_pos)
            sec = hdr.logicalIndexAt(pos)
        except RuntimeError:
            return ""
        if sec < 0:
            return ""
        data = model.headerData(sec, hdr.orientation(),
                                QtCore.Qt.ItemDataRole.ToolTipRole)
        return data or ""

    @classmethod
    def _menu_tip(cls, global_pos):
        """Active menu action's tooltip, but only where Qt would show one."""
        menu = cls._ancestor(global_pos, QtWidgets.QMenu)
        if menu is None or not menu.toolTipsVisible():
            return ""
        act = menu.activeAction()
        return (act.toolTip() or "") if act is not None else ""

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QtCore.QEvent.Type.ToolTip:
            gpos = event.globalPos()
            # Sub-widget tips first: these live on a tab / row / section, not on
            # the widget, and each one is painted by its own Qt handler as the
            # native square box unless we claim the event here. They are more
            # specific than any widget-level tip on the same widget.
            text = (self._tab_tip(gpos)
                    or self._item_tip(gpos)
                    or self._header_tip(gpos)
                    or self._menu_tip(gpos))
            if not text and isinstance(obj, QtWidgets.QWidget):
                text = obj.toolTip()
            if not text:
                # Fall back to whatever bare widget sits under the cursor.
                w = QtWidgets.QApplication.widgetAt(event.globalPos())
                if isinstance(w, QtWidgets.QWidget):
                    text = w.toolTip()
            if text:
                owner = (obj if isinstance(obj, QtWidgets.QWidget)
                         else QtWidgets.QApplication.widgetAt(gpos))
                self._ensure().show_text(text, gpos, self._app, owner)
                return True   # suppress the native square tooltip
            self._hide()
            return False
        if et in self._DISMISS and self._tip is not None:
            # Never dismiss on events delivered to the tooltip itself.
            if obj is not self._tip and not (
                isinstance(obj, QtWidgets.QWidget)
                and self._tip.isAncestorOf(obj)
            ):
                self._hide()
        return False


def install_tooltips(app):
    """Install the Aurora tooltip filter on ``app`` (idempotent)."""
    if getattr(app, "_esim_tooltip_filter", None) is not None:
        return app._esim_tooltip_filter
    filt = _ToolTipFilter(app)
    app._esim_tooltip_filter = filt
    app.installEventFilter(filt)
    return filt
