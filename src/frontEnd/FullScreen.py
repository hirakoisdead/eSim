# =========================================================================
#             FILE: FullScreen.py
#
#      DESCRIPTION: A small, contextual "go fullscreen" control for a docked
#                   panel. It is meant to live in the panel's OWN header
#                   (the Makerchip flow strip, the Plotting toolbar, the
#                   KicadToNgspice tab corner) -- never a global toolbar -- so
#                   the affordance sits where the user is actually working and
#                   reads as "fullscreen THIS, then dock it back".
#
#                   On activation it reparents the host dock's content into a
#                   frameless top-level window and shows it *truly* fullscreen
#                   (the whole screen, not merely the app's work area). The
#                   same button flips to an exit affordance; Esc and F11 also
#                   exit. Docking back returns the content to its QDockWidget,
#                   which keeps its original tab slot.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================
from PyQt6 import QtCore, QtGui, QtWidgets, sip
from frontEnd.icon_paths import fullscreen_icon, dock_back_icon

#: Docks whose panel is CURRENTLY fullscreen -> the toggle holding it, keyed by
#: the dock's C++ pointer. A fullscreen panel lives in a frameless top-level
#: window covering the screen, so anything that opens or raises another dock
#: behind it is invisible to the user -- which is exactly how "the waveform
#: never appears" and "Back to Verify does nothing" happened. Code that moves
#: the user between docks consults this and hands the fullscreen state over
#: (see :func:`is_fullscreen` / :func:`exit_fullscreen` / :func:`go_fullscreen`).
_ACTIVE = {}


def _key(dock):
    try:
        return sip.unwrapinstance(dock)
    except Exception:
        return None


def _purge(toggle=None):
    """Drop registry entries whose toggle is no longer fullscreen.

    Keys are raw C++ pointers, which Qt recycles, so a stale entry could make
    a brand-new dock look fullscreen. Every read and write prunes first.

    The TOGGLE itself is checked too, not just its window: a panel can be torn
    down while it is fullscreen (a re-simulate replaces the plot inside the
    live waveform tab, taking the button that owns the window with it), and a
    deleted button keeps its Python attributes -- ``t._win`` still reads back
    the live window -- so an owner-is-gone entry looked perfectly healthy."""
    for k, t in list(_ACTIVE.items()):
        dead = t is toggle
        if not dead:
            try:
                dead = (sip.isdeleted(t) or t._win is None
                        or sip.isdeleted(t._win))
            except (RuntimeError, AttributeError):
                dead = True
        if dead:
            del _ACTIVE[k]


def _fs_window_of(widget):
    """The fullscreen wrapper hosting ``widget``, or None.

    Walks the parent chain looking for the marker stamped on the wrapper by
    :meth:`FullScreenToggle._enter`. Used to recover ownership of a window
    whose toggle died under it -- at that point the registry entry is already
    purged, so the window can only be found from the inside."""
    node = widget
    while node is not None:
        try:
            if getattr(node, "_esim_fs_dock", None) is not None:
                return node
            node = node.parentWidget()
        except RuntimeError:
            return None
    return None


def _own_window(toggle, win, dock, content):
    """Point ``toggle`` at ``win`` and make it the registry's owner."""
    toggle._win, toggle._dock, toggle._content = win, dock, content
    win._esim_fs_dock, win._esim_fs_content = dock, content
    # The close handler is bound to a toggle, so it moves with ownership --
    # otherwise Esc/F11/the window close still call the OLD button.
    win.closeEvent = toggle._make_close_handler()
    if _key(dock) is not None:
        _ACTIVE[_key(dock)] = toggle
    toggle._set_state(full=True)


def transfer(dock, toggle):
    """Hand a live fullscreen window to ``dock``'s NEW toggle.

    The panel inside a fullscreen window can be rebuilt underneath it: a
    re-simulate swaps a fresh plot into the live waveform tab, and the plot
    carries the toggle in its own toolbar. The button that owned the window
    then dies with the outgoing plot, leaving the window owned by a deleted
    object -- its close handler raises instead of docking back (so the user is
    stranded in an empty fullscreen window), the incoming panel's button does
    nothing, and the next Back-to-Verify hand-off raises too.

    Call this right after replacing content that may be fullscreen. Returns
    False when there was no fullscreen window to move."""
    old = _ACTIVE.get(_key(dock))
    if old is None or toggle is None or sip.isdeleted(toggle):
        return False
    win = getattr(old, "_win", None)
    if win is None or sip.isdeleted(win):
        _purge()
        return False
    win_dock, content = old._dock, old._content
    if not sip.isdeleted(old):
        old._win = old._dock = old._content = None
        old._set_state(full=False)
    _own_window(toggle, win, win_dock, content)
    return True


def is_fullscreen(dock):
    """True when ``dock``'s panel is showing as a fullscreen window."""
    _purge()
    return _key(dock) in _ACTIVE


def exit_fullscreen(dock):
    """Dock ``dock``'s panel back if it is fullscreen. True if it was."""
    toggle = _ACTIVE.get(_key(dock))
    if toggle is None:
        return False
    try:
        toggle._exit()
    except RuntimeError:
        _ACTIVE.pop(_key(dock), None)
    return True


def handover(src_dock, dst_dock):
    """Move the LIVE fullscreen window from one dock's panel to another's.

    The obvious way to follow the user between panels -- exit fullscreen on the
    one they are leaving, enter it on the one they are going to -- is visibly
    wrong: the covering window is destroyed, the docked main window flashes up
    for a frame, and a brand-new window then grows into fullscreen. What should
    read as "the waveform is now on screen" reads as a stutter.

    So the window is never torn down. Its content is swapped: the old panel
    goes home to its dock, the new one takes its place, and ownership moves to
    the new panel's own toggle so Esc and the button still work. Nothing ever
    uncovers the screen, so there is nothing to see.

    Returns False when the hand-off is not possible (no live fullscreen, or the
    target has no toggle to own the window); the caller can fall back to
    exit + enter."""
    _purge()
    src = _ACTIVE.get(_key(src_dock))
    if src is None or dst_dock is None or sip.isdeleted(dst_dock):
        return False
    dst_toggle = dst_dock.findChild(FullScreenToggle)
    dst_content = dst_dock.widget()
    if dst_toggle is None or dst_content is None:
        return False

    win = src._win
    if win is None or sip.isdeleted(win):
        return False
    layout = win.layout()

    # 1. the outgoing panel goes back to its own dock (still hidden behind
    #    the window that is about to hold the incoming one)
    content = src._content
    if content is not None and not sip.isdeleted(content):
        layout.removeWidget(content)
        if src_dock is not None and not sip.isdeleted(src_dock):
            src_dock.setWidget(content)
            src_dock.show()
    src._win = src._dock = src._content = None
    src._set_state(full=False)
    _ACTIVE.pop(_key(src_dock), None)

    # 2. the incoming panel takes the same window, and its toggle takes
    #    ownership -- including the close handler, so Esc/F11 dock IT back
    layout.addWidget(dst_content)
    win.setWindowTitle(dst_dock.windowTitle())
    _own_window(dst_toggle, win, dst_dock, dst_content)
    win.raise_()
    return True


def go_fullscreen(dock):
    """Put ``dock``'s panel fullscreen, if it carries a toggle to do it with.

    Used to hand fullscreen *over* to a panel the user is being moved to, so
    the mode follows them instead of stranding them behind a covered window.
    """
    if dock is None or sip.isdeleted(dock) or is_fullscreen(dock):
        return False
    toggle = dock.findChild(FullScreenToggle)
    if toggle is None:
        return False
    toggle._enter()
    return is_fullscreen(dock)


class FullScreenToggle(QtWidgets.QToolButton):
    """Per-panel fullscreen toggle. Drop one into any panel's header; it finds
    its host QDockWidget at click time, so no wiring is needed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._win = None
        self._dock = None
        self._content = None
        self.setAutoRaise(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        # Icon-only left users hunting for an unlabelled glyph. Show the label
        # beside the icon so the control reads as "[⛶ Fullscreen]" -- the
        # affordance is now self-explanatory instead of relying on a tooltip.
        self.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setStyleSheet(
            "QToolButton { border:none; background:transparent; padding:2px 8px; }")
        self._set_state(full=False)
        self.clicked.connect(self.toggle)

    # ------------------------------------------------------------------ #
    def _set_state(self, full):
        # The button can be gone while the window it owned is still up (the
        # panel was replaced or destroyed mid-fullscreen). This runs from the
        # close path, so raising here left the window on screen with its
        # content already docked back -- an empty, unclosable fullscreen
        # rectangle -- and popped the unhandled-exception dialog.
        if sip.isdeleted(self):
            return
        # Purpose-built, theme-aware SVGs (icon_paths) rather than the OS
        # SP_TitleBar* pixmap, which rasterised mushy and read as a window
        # control, not "fullscreen this panel".
        if full:
            self.setIcon(dock_back_icon())
            self.setText("Exit Fullscreen")
            self.setToolTip("Exit fullscreen  (Esc)")
        else:
            self.setIcon(fullscreen_icon())
            self.setText("Fullscreen")
            self.setToolTip("Fullscreen this panel  (Esc to exit)")

    def changeEvent(self, event):
        # The SVG icon colour is baked in at build time, so a live light/dark
        # theme switch would leave the glyph the old theme's colour. Rebuild it
        # (state preserved: _win set == currently fullscreen) on PaletteChange.
        # Deferred by a tick: rasterising an SVG icon inside the PaletteChange
        # handler re-enters the polish that delivered the event (same rule as
        # ProjectExplorer._scheduleIconRefresh; see theme_utils.defer_restyle).
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            from frontEnd.theme_utils import defer_restyle
            defer_restyle(self, self._retint_icon)
        super().changeEvent(event)

    def _retint_icon(self):
        """Deferred icon rebuild; state preserved (_win set == fullscreen)."""
        try:
            self._set_state(full=self._win is not None)
        except RuntimeError:
            pass    # button torn down between the palette event and this tick

    def showEvent(self, event):
        super().showEvent(event)
        self._adopt_if_orphaned()

    def _adopt_if_orphaned(self):
        """Take over a fullscreen window whose owning toggle has died.

        Safety net for content rebuilt inside a fullscreen window without the
        rebuild site calling :func:`transfer`: a freshly shown toggle that
        finds itself inside an ownerless wrapper claims it, so the button, Esc
        and the close path all work again instead of leaving the user in a
        window nothing can dismiss."""
        if self._win is not None:
            return
        win = _fs_window_of(self)
        if win is None:
            return
        dock = getattr(win, "_esim_fs_dock", None)
        content = getattr(win, "_esim_fs_content", None)
        if (dock is None or sip.isdeleted(dock)
                or content is None or sip.isdeleted(content)):
            return
        owner = _ACTIVE.get(_key(dock))
        if owner is not None and not sip.isdeleted(owner):
            return          # a live toggle already owns it
        _own_window(self, win, dock, content)

    def _resolve_host(self):
        """Walk up to the enclosing QDockWidget; the widget just beneath it is
        the content to reparent."""
        content = self
        node = self.parentWidget()
        while node is not None:
            if isinstance(node, QtWidgets.QDockWidget):
                return node, content
            content = node
            node = node.parentWidget()
        return None, None

    # ------------------------------------------------------------------ #
    def toggle(self):
        if self._win is not None:
            self._exit()
        else:
            self._enter()

    def _enter(self):
        dock, content = self._resolve_host()
        if dock is None or content is None:
            # No dock above us: either this panel is not in one, or it is
            # already inside a fullscreen wrapper whose owner died. The latter
            # is recoverable and is exactly the state that made the button
            # look broken.
            self._adopt_if_orphaned()
            return
        self._dock, self._content = dock, content

        win = QtWidgets.QWidget()
        win.setWindowTitle(dock.windowTitle())
        lay = QtWidgets.QVBoxLayout(win)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(content)          # reparents content out of the dock

        # Esc / F11 (and an external Alt+F4) all route through the close path.
        for key in ("Escape", "F11"):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), win)
            sc.activated.connect(win.close)
        # Marks the wrapper so a toggle inside it can find it again if this
        # one is destroyed while the window is still up (see _fs_window_of).
        _own_window(self, win, dock, content)

        # Size the window to the screen BEFORE showing it. A fresh QWidget has
        # a small default geometry, and showFullScreen() on an unshown widget
        # lets the window manager animate from that default out to the screen
        # -- the panel visibly "grows" into fullscreen instead of just being
        # there. Presetting the geometry gives the animation nothing to do.
        screen = dock.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            win.setGeometry(screen.geometry())
        win.showFullScreen()

    def _make_close_handler(self):
        def _on_close(event):
            # Keep a LOCAL reference to the fullscreen window for the whole
            # handler. ``content`` is a child of ``win``; if the only reference
            # to ``win`` (``self._win``) were dropped first, sip would delete
            # win -- and content with it -- so the setWidget below touched a
            # freed QWidget (RuntimeError) and left the dock's tab blank. The
            # local ref keeps win, hence content, alive until we reparent.
            win = self._win
            if win is not None:
                self._win = None      # re-entrant close is now a no-op
                dock, content = self._dock, self._content
                self._dock = None
                self._content = None
                _purge(self)

                content_alive = (content is not None
                                 and not sip.isdeleted(content))
                # The host dock can be destroyed WHILE its panel is fullscreen
                # (Close Project / closing the now-empty tab), so verify it too
                # before setWidget/show/raise_ on a possibly-gone QDockWidget.
                dock_alive = dock is not None and not sip.isdeleted(dock)
                if dock_alive and content_alive:
                    # Reparent BEFORE win dies -- back into the dock, which kept
                    # its tab slot all along.
                    dock.setWidget(content)
                    dock.show()
                    dock.raise_()
                elif content_alive:
                    # Dock is gone: drop the orphaned panel rather than leaving
                    # it floating parentless for the rest of the session.
                    content.setParent(None)
                    content.deleteLater()

                self._set_state(full=False)
                # Reap the now-empty fullscreen wrapper. deleteLater defers the
                # delete until after this closeEvent unwinds, so win is never
                # deleted from inside its own event.
                win.deleteLater()
            event.accept()
        return _on_close

    def _exit(self):
        win = self._win
        if win is None:
            return
        if sip.isdeleted(win):
            # Wrapper already reaped elsewhere; drop the dangling state.
            self._win = self._dock = self._content = None
            _purge(self)
            self._set_state(full=False)
            return
        win.close()
