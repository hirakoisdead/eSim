"""Reusable painted widgets for the Aurora design language.

* GradientLabel   — paints its text with the cyan->violet accent gradient
                    (Qt QSS cannot gradient-fill text). Fixes the dead
                    `gradientTitle` / `heroGradient` QSS classes.
* AuroraHeroFrame — the diagonal accent->violet hero surface extracted
                    from the About dialog, reusable app-wide.

Native only: QPainter + QLinearGradient. No dependencies.
"""
from PyQt6 import QtCore, QtGui, QtWidgets

try:
    from frontEnd import tokens
except Exception:  # pragma: no cover
    import tokens


def _is_dark(widget) -> bool:
    return widget.palette().color(
        QtGui.QPalette.ColorRole.Window).lightness() < 128


_MONO_CACHE = None


def mono_family() -> str:
    """First installed cross-platform monospace family.

    'Consolas' is Windows-only; relying on it makes the editors render with a
    silent platform fallback on Linux/macOS. This picks the best available
    from a portable preference chain so the default looks identical anywhere.
    """
    global _MONO_CACHE
    if _MONO_CACHE:
        return _MONO_CACHE
    pref = ["JetBrains Mono", "Cascadia Mono", "Cascadia Code",
            "DejaVu Sans Mono", "Menlo", "Consolas", "Liberation Mono",
            "Courier New"]
    try:
        fams = set(QtGui.QFontDatabase.families())
    except Exception:
        fams = set()
    for f in pref:
        if f in fams:
            _MONO_CACHE = f
            return f
    _MONO_CACHE = "monospace"
    return _MONO_CACHE


class GradientLabel(QtWidgets.QLabel):
    """A QLabel whose text is filled with the accent gradient."""

    def __init__(self, text="", parent=None, weight=QtGui.QFont.Weight.Black):
        super().__init__(text, parent)
        self._weight = weight
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
            t = tokens.theme(_is_dark(self))
            grad = QtGui.QLinearGradient(0, 0, float(self.width()), 0)
            grad.setColorAt(0.0, QtGui.QColor(t["accent_hi"]))
            grad.setColorAt(0.5, QtGui.QColor(t["accent"]))
            grad.setColorAt(1.0, QtGui.QColor(t["accent_2_hi"]))
            f = self.font()
            f.setWeight(self._weight)
            p.setFont(f)
            p.setPen(QtGui.QPen(QtGui.QBrush(grad), 1))
            flags = int(self.alignment() | QtCore.Qt.TextFlag.TextSingleLine)
            p.drawText(self.rect(), flags, self.text())
        finally:
            p.end()


class AuroraHeroFrame(QtWidgets.QFrame):
    """Diagonal accent->violet hero gradient with a soft top-right orb.

    The single source of the 'About' look, reusable for the Welcome hero,
    Preferences header, and empty states.
    """

    def __init__(self, parent=None, radius=18):
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            t = tokens.theme(_is_dark(self))
            rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QtGui.QPainterPath()
            path.addRoundedRect(rect, self._radius, self._radius)

            g = QtGui.QLinearGradient(0.0, 0.0, float(self.width()), float(self.height()))
            g.setColorAt(0.0, QtGui.QColor(t["accent"]))
            g.setColorAt(0.45, QtGui.QColor(t["accent_lo"]))
            g.setColorAt(0.6, QtGui.QColor(t["accent_2_hi"]))
            g.setColorAt(1.0, QtGui.QColor(t["accent_2"]))
            p.fillPath(path, g)

            # soft radial orb, top-right
            p.setClipPath(path)
            orb = QtGui.QRadialGradient(
                QtCore.QPointF(self.width() - 40, 30),
                max(self.width(), self.height()) * 0.7)
            hi = QtGui.QColor(255, 255, 255, 70)
            orb.setColorAt(0.0, hi)
            orb.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), orb)
        finally:
            p.end()


class RailDragGrip(QtWidgets.QWidget):
    """A draggable grip for the left rail, mounted at the BOTTOM.

    Qt's native QToolBar handle always sits at the leading edge (the TOP of a
    vertical toolbar), where it broke the seamless inverted-L corner with the
    top toolbar. So the rail's native handle is disabled and this grip is added
    at the bottom instead. Dragging it re-docks the rail to the Left or Right
    side (kept vertical) — the same "move the whole bar" affordance, relocated.
    """

    def __init__(self, main_window, toolbar):
        super().__init__()
        self._mw = main_window
        self._tb = toolbar
        from frontEnd.theme_utils import zoom_px
        self.setFixedHeight(zoom_px(26))
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move this toolbar to the left or right edge")
        self._press = None
        self._cur_area = None

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            dark = _is_dark(self)
            col = QtGui.QColor("#5F728D" if dark else "#9AAABE")
            if self.underMouse():
                col = QtGui.QColor("#8BEAFF" if dark else "#0077A8")
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(col)
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            for row in range(2):
                y = cy - 3 + row * 6
                for i in range(3):
                    p.drawEllipse(QtCore.QPointF(cx - 6 + i * 6, y), 1.5, 1.5)
        finally:
            p.end()

    def enterEvent(self, _e):
        self.update()

    def leaveEvent(self, _e):
        self.update()

    def _target_area(self, global_pt):
        r = self._mw.frameGeometry()
        center_x = r.x() + r.width() / 2.0
        return (QtCore.Qt.ToolBarArea.RightToolBarArea
                if global_pt.x() > center_x
                else QtCore.Qt.ToolBarArea.LeftToolBarArea)

    def _dock_to(self, area):
        if area == self._cur_area:
            return
        self._cur_area = area
        try:
            self._mw.addToolBar(area, self._tb)
            self._tb.setOrientation(QtCore.Qt.Orientation.Vertical)
            self._tb.show()
            # keep the opaque top bar above the rail's shadow after re-layout
            if hasattr(self._mw, "topToolbar"):
                self._mw.topToolbar.raise_()
        except Exception:
            pass

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            try:
                self._cur_area = self._mw.toolBarArea(self._tb)
            except Exception:
                self._cur_area = QtCore.Qt.ToolBarArea.LeftToolBarArea
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        # Live re-dock: the rail follows to whichever side the cursor is on,
        # so the drag visibly moves the bar (no native handle needed).
        if self._press is None:
            return
        gp = event.globalPosition().toPoint()
        if (gp - self._press).manhattanLength() < 8:
            return
        self._dock_to(self._target_area(gp))

    def mouseReleaseEvent(self, event):
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self._press = None


def _is_wayland() -> bool:
    """True on a Wayland session.

    Wayland is the one platform that forbids both programmatic top-level
    ``move()`` and querying the global cursor position, and delivers NO events
    to the client during a compositor ``startSystemMove``. Several docking
    decisions branch on this: free-window movement is always handed to the
    compositor via ``startSystemMove``, but the *redock* gesture has to differ
    (hover-to-dock is impossible on Wayland → double-click instead).
    """
    try:
        return QtGui.QGuiApplication.platformName().lower().startswith("wayland")
    except Exception:
        return False


class DockTitleBar(QtWidgets.QWidget):
    """Custom dock title bar with a two-mode drag, picked by float-state.

    The window manager only ever exposes two reliable cross-surface gestures
    (this is true on Wayland AND Windows/X11/macOS), so each is used for the
    half of the problem it can actually solve:

    1. **Undock — drag-and-drop.** While the tool is *docked*, dragging the bar
       starts a ``QDrag``: a ghost follows the cursor and the dock area shows a
       drop placeholder. Drop OUTSIDE → undock (float); drop ON the placeholder
       → stay docked. DnD is used here because reparenting a docked widget into
       a new top-level window and *then* moving it races the compositor's
       async window-map on Wayland (an earlier dead-end); a drag never
       reparents mid-gesture, so it can't race.

    2. **Move the floated window — ``startSystemMove``.** Once the tool IS a
       free top-level window, dragging the bar hands the move to the
       compositor/WM via ``QWindow.startSystemMove()`` — the only way to move a
       top-level on Wayland, and the native move loop on Windows/X11/macOS.
       The window is already mapped, so there is no async-map race. This is the
       fix for the "undocked window freezes / can't be moved" bug.

    Redock:
    - **double-click** the bar → toggle dock/undock (works everywhere; the
      only redock gesture Wayland can offer, since it delivers no events during
      a system move and forbids querying the cursor / window position).
    - on **non-Wayland**, a cursor watch additionally auto-redocks when the
      floated window is dragged back over the dock area (the "hover it back
      over the placeholder" flow), which Wayland physically cannot detect.

    All ``setFloating`` calls happen via ``QTimer.singleShot(0, ...)`` — never
    inside a mouse/drop handler's nested event loop, which would re-enter Qt's
    drag state machine and freeze the window.
    """

    MIME = "application/x-esim-dock"

    def __init__(self, dock, main_window, title_text, parent=None):
        super().__init__(parent)
        self._dock = dock
        self._mw = main_window
        self._press = None
        self._dragging = False
        self._watch_timer = None
        self._watch_elapsed = 0
        self.setObjectName("dockTitleBar")
        lay = QtWidgets.QHBoxLayout(self)
        # Slim drag strip: it now carries only the draggable tool name. The
        # Fullscreen/Close buttons moved off this bar and onto the tool card's
        # top-right corner (see DockArea.apply_fullscreen_feature), so this strip
        # is just tall enough to grab and read the title.
        lay.setContentsMargins(14, 2, 8, 2)
        lay.setSpacing(6)
        self._label = QtWidgets.QLabel(title_text)
        self._label.setObjectName("dockCardTitle")
        self._label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._label)
        lay.addStretch()
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setToolTip(
            "Drag out to undock · drag a floating window to move it anywhere · "
            "double-click to dock / undock")

    def sizeHint(self):
        return QtCore.QSize(10, 26)

    def add_action_widget(self, w):
        """Place a trailing control on the title row (right-aligned)."""
        self.layout().addWidget(w)

    def _make_ghost(self):
        """A scaled, translucent snapshot of the tool as the drag image."""
        src = self._dock.widget() or self._dock
        pm = None
        try:
            pm = src.grab()
        except Exception:
            pm = None
        if pm is None or pm.isNull():
            pm = QtGui.QPixmap(280, 70)
            pm.fill(QtGui.QColor(20, 30, 50))
        if pm.width() > 300:
            pm = pm.scaledToWidth(300, QtCore.Qt.TransformationMode.SmoothTransformation)
        if pm.height() > 210:
            pm = pm.copy(0, 0, pm.width(), 210)
        ghost = QtGui.QPixmap(pm.size())
        ghost.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(ghost)
        p.setOpacity(0.82)
        p.drawPixmap(0, 0, pm)
        p.setOpacity(1.0)
        pen = QtGui.QPen(QtGui.QColor(83, 215, 255, 200))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, ghost.width() - 2, ghost.height() - 2, 10, 10)
        p.end()
        return ghost

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._dragging = False
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None or self._dragging:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < 10:
            return
        self._dragging = True
        if self._dock.isFloating():
            # Already a free top-level window → move the REAL window with the
            # compositor / WM. No reparent here, so none of the async window-map
            # races that broke the old "float then move" undock path.
            self._start_system_move()
        else:
            # Docked → undock via drag-and-drop (a ghost the compositor routes
            # everywhere). Drop outside floats it; drop on the zone keeps it.
            self._start_drag()

    def _start_system_move(self):
        """Hand the floated window's move to the window manager.

        ``QWindow.startSystemMove()`` is the only top-level move that works on
        Wayland and is the native move loop on Windows/X11/macOS. ``QDockWidget``
        has no ``createWinId`` in this PyQt6, so ``winId()`` forces native
        realization before ``windowHandle()``.
        """
        win = self._dock.window()
        handle = None
        try:
            win.winId()
            handle = win.windowHandle()
        except Exception:
            handle = None
        if handle is not None:
            try:
                handle.startSystemMove()
            except Exception:
                pass
        # On every platform except Wayland we can see the cursor, so watch for
        # the window being dropped back over the dock area and auto-redock it
        # ("hover it back over the placeholder"). Wayland delivers no events
        # during the compositor move and forbids QCursor.pos(), so there the
        # redock gesture is double-click (see mouseDoubleClickEvent).
        if not _is_wayland():
            self._begin_redock_watch()

    def _begin_redock_watch(self):
        """Non-Wayland: poll the global cursor while the floated window is being
        dragged; highlight the dock zone and redock if released over it."""
        if self._mw is not None and hasattr(self._mw, "begin_dock_drag"):
            try:
                self._mw.begin_dock_drag(self._dock)
            except Exception:
                pass
        self._watch_elapsed = 0
        if self._watch_timer is None:
            self._watch_timer = QtCore.QTimer(self)
            self._watch_timer.setInterval(60)
            self._watch_timer.timeout.connect(self._redock_watch_tick)
        self._watch_timer.start()

    def _end_redock_watch(self):
        if self._watch_timer is not None:
            self._watch_timer.stop()
        if self._mw is not None and hasattr(self._mw, "end_dock_drag"):
            try:
                self._mw.end_dock_drag()
            except Exception:
                pass
        self._dragging = False

    def _redock_watch_tick(self):
        self._watch_elapsed += 60
        try:
            gp = QtGui.QCursor.pos()
            buttons = QtWidgets.QApplication.mouseButtons()
            over = bool(self._mw is not None
                        and hasattr(self._mw, "point_over_dock_area")
                        and self._mw.point_over_dock_area(gp))
            ov = getattr(self._mw, "_dock_drop_overlay", None)
            if ov is not None:
                ov._hover = over
                ov.update()
            released = not (buttons & QtCore.Qt.MouseButton.LeftButton)
            if released or self._watch_elapsed > 8000:
                self._end_redock_watch()
                if released and over and self._dock.isFloating():
                    QtCore.QTimer.singleShot(
                        0, lambda: self._apply_float_result(
                            QtCore.Qt.DropAction.MoveAction))
        except Exception:
            self._end_redock_watch()

    def mouseReleaseEvent(self, _event):
        self._press = None
        self._dragging = False
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, _event):
        self._press = None
        # Defer: on Wayland synchronous setFloating inside a mouse-event
        # handler corrupts the compositor window state → frozen window.
        QtCore.QTimer.singleShot(0, self._toggle_float)

    def _toggle_float(self):
        """Float/dock toggle — called deferred, outside any mouse-event stack."""
        try:
            was_floating = self._dock.isFloating()
            self._dock.setFloating(not was_floating)
            if was_floating:
                self._dock.raise_()
                if self._mw is not None and hasattr(self._mw, "enable_tab_close_buttons"):
                    self._mw.enable_tab_close_buttons()
        except RuntimeError:
            pass  # dock torn down before deferred call fired

    def _start_drag(self):
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(self.MIME, b"1")
        drag.setMimeData(mime)
        ghost = self._make_ghost()
        drag.setPixmap(ghost)
        drag.setHotSpot(QtCore.QPoint(ghost.width() // 2, 16))

        # Show the dock-area drop placeholder for the whole drag (a raised,
        # drop-accepting overlay → Wayland delivers the DnD to it reliably).
        if self._mw is not None and hasattr(self._mw, "begin_dock_drag"):
            self._mw.begin_dock_drag(self._dock)

        result = drag.exec(QtCore.Qt.DropAction.MoveAction)

        if self._mw is not None and hasattr(self._mw, "end_dock_drag"):
            self._mw.end_dock_drag()
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self._press = None
        self._dragging = False

        # Defer setFloating via singleShot(0): on Wayland calling it
        # synchronously here (still inside mouseMoveEvent's call stack
        # after exec returns) corrupts the compositor window state →
        # the new floating window is frozen and unresponsive.
        # Never setFloating inside a drag/drop/mouse handler.
        QtCore.QTimer.singleShot(0, lambda r=result: self._apply_float_result(r))

    def _apply_float_result(self, result):
        """Re-parent AFTER drag, deferred outside any mouse-event stack."""
        try:
            if result == QtCore.Qt.DropAction.IgnoreAction:
                if not self._dock.isFloating():
                    self._dock.setFloating(True)
                    self._dock.raise_()
            else:
                if self._dock.isFloating():
                    self._dock.setFloating(False)
                    self._dock.show()
                    self._dock.raise_()
                    if self._mw is not None and hasattr(self._mw, "enable_tab_close_buttons"):
                        self._mw.enable_tab_close_buttons()
        except RuntimeError:
            pass  # dock torn down before deferred call fired


class DockDropOverlay(QtWidgets.QWidget):
    """Translucent "drop to dock" placeholder shown over the dock area while a
    tool is being drag-docked. It is a raised, drop-accepting child of the dock
    area, so on Wayland the compositor delivers the DnD enter/move/drop straight
    to it (no global-cursor / window-position queries needed).

    It only ACCEPTS the drop (so QDrag.exec returns MoveAction); the actual
    setFloating(False) re-dock is done by DockTitleBar AFTER exec returns, never
    inside this drop handler (which runs in the drag's nested event loop)."""

    def __init__(self, dock_area):
        super().__init__(dock_area)
        self.setObjectName("dockDropOverlay")
        self.setAcceptDrops(True)
        # Paint-through child: never clear to opaque, blend over the dock
        # content already in the backing store.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._hover = False
        self.hide()

    def show_active(self):
        self._hover = False
        self.show()
        self.raise_()
        self.update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(DockTitleBar.MIME):
            e.setDropAction(QtCore.Qt.DropAction.MoveAction)
            e.accept()
            self._hover = True
            self.update()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(DockTitleBar.MIME):
            e.setDropAction(QtCore.Qt.DropAction.MoveAction)
            e.accept()
        else:
            e.ignore()

    def dragLeaveEvent(self, _e):
        self._hover = False
        self.update()

    def dropEvent(self, e):
        if e.mimeData().hasFormat(DockTitleBar.MIME):
            e.setDropAction(QtCore.Qt.DropAction.MoveAction)
            e.accept()        # DockTitleBar re-docks after exec returns
        else:
            e.ignore()
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        acc = self.palette().color(QtGui.QPalette.ColorRole.Highlight)
        if not acc.isValid():
            acc = QtGui.QColor("#53D7FF")
        r = self.rect().adjusted(10, 10, -10, -10)
        fill = QtGui.QColor(acc)
        fill.setAlpha(46 if self._hover else 26)
        p.setBrush(fill)
        pen = QtGui.QPen(acc)
        pen.setWidth(3 if self._hover else 2)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r, 18, 18)
        p.setPen(acc)
        f = self.font()
        f.setPointSizeF(max(12.0, f.pointSizeF() + 3))
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, QtCore.Qt.AlignmentFlag.AlignCenter,
                   "Drop here to dock")
        p.end()


class FloatingDockHost(QtWidgets.QWidget):
    """Transparent host that paints a faint soft shadow behind one rounded
    ``dockCard`` child, so a docked tool window reads as a floating panel.

    The gap between this host's edge and the card (the layout margins) reveals
    the workspace background, and the painted shadow sits in that gap — the
    same 'floating' language the toolbars use.

    The shadow is drawn with QPainter (stacked translucent rounded rects whose
    coverage accumulates near the card edge), NOT a QGraphicsDropShadowEffect:
    a graphics effect on an ancestor of a QWebEngineView (Makerchip / User
    Manual) blanks the web surface. Painting it ourselves keeps every tool —
    web views included — rendering while still casting the soft shadow.
    """

    def __init__(self, card, margins=(18, 14, 18, 20), radius=16,
                 spread=11, y_offset=4, parent=None):
        super().__init__(parent)
        self.setObjectName("dockFloatHost")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._card = card
        self._radius = radius
        self._spread = spread
        self._yoff = y_offset
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(*margins)
        lay.setSpacing(0)
        lay.addWidget(card)

    def resizeEvent(self, _event):
        # Card geometry changes with the host; repaint so the shadow tracks it.
        self.update()

    def paintEvent(self, _event):
        if self._card is None:
            return
        r = QtCore.QRectF(self._card.geometry())
        if r.width() <= 0 or r.height() <= 0:
            return
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            sr, sg, sb = tokens.theme(_is_dark(self))["shadow_rgb"]
            # Low per-layer alpha; coverage stacks up near the card edge and
            # thins toward the rim → a soft ambient falloff. Card paints over
            # the centre (children draw after the parent), so only the rim
            # shows. Kept faint so it reads as ambient depth, not a hard halo —
            # and the host margins exceed the shadow reach so it never cuts off
            # against the host edge (which looked like a smudge, not a shadow).
            per = 3 if _is_dark(self) else 2
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            for i in range(self._spread, 0, -1):
                p.setBrush(QtGui.QColor(sr, sg, sb, per))
                rad = self._radius + i * 0.6
                rect = r.adjusted(-i, -i + self._yoff, i, i + self._yoff)
                p.drawRoundedRect(rect, rad, rad)
        finally:
            p.end()
