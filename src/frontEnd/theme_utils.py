import os
import re
import sys
import json
import ctypes
from PyQt6 import QtGui, QtCore, QtWidgets
from configuration import paths

ACCENT_TOKENS = {
    "dark": ["#53D7FF", "#8BEAFF", "#18A8D8", "#0E7490", "#7CE3FF", "#1CB8E8", "#3B82F6", "#165982", "#1E88E5"],
    "light": ["#0077A8", "#00A4DC", "#005E86"],
}

SECONDARY_TOKENS = {
    "dark": ["#050812", "#070C18", "#070B14", "#111827"],
    "light": ["#F3F7FC", "#EEF4FB", "#F6F8FC", "#f4f5f7"],
}

INTERNAL_TOKENS = {
    "dark": ["#0E1728", "#08111F", "#09111F", "#0B1220", "#111B2D", "#101827", "#151F32", "#1A2740", "#0A1020"],
    "light": ["#FFFFFF", "#FBFDFF", "#F8FBFF", "#FBFCFE", "#EEF4FA", "#EEF3FA"],
}


# Whether the last apply_theme() resolved to dark. Read by the Show-time
# titlebar hook in motion.py so windows created AFTER a theme apply still get
# the right caption color.
_CURRENT_DARK = False

# Re-entrancy / coalescing guard for apply_theme. A full repolish (setPalette +
# setStyleSheet) can post events that re-enter apply_theme (a queued OS
# colorSchemeChanged, a Preferences live-apply), and running a second repolish
# on top of the first is both wasteful and a way to churn graphics effects while
# the first pass still holds pointers to them. _APPLYING serializes the work;
# _APPLY_PENDING remembers that a re-entrant request arrived so exactly one more
# apply runs after the current one settles (coalescing a storm into two passes).
_APPLYING = False
_APPLY_PENDING = False


def current_theme_is_dark():
    return _CURRENT_DARK


def defer_restyle(widget, slot, delay=0):
    """Run a theme-driven restyle one event-loop tick LATER, never inline.

    QApplication.setStyleSheet()/setPalette() repolish the whole app by walking
    a snapshot of the widget tree and delivering PaletteChange/StyleChange to
    every widget in it. A handler that restyles *inside* that walk -- calling
    setStyleSheet or setPalette, re-rasterising an icon, redrawing a canvas --
    re-enters Qt's style engine while the outer walk is still holding raw
    pointers into that snapshot. That is how eSim was dying on a zoom change:
    a 0xC0000005 (DEP/execute) fault on a freed C++ object, reached from inside
    ``theme_utils._apply_theme_impl -> app.setStyleSheet``, with no Python
    frame of its own to blame.

    Deferring is visually identical (the tick runs before the next paint) and
    touches only widgets that are still alive. The timer is parented to the
    widget so it cannot outlive it, and restarting an already-pending timer
    coalesces a storm of palette events into a single restyle.

    Use this from every ``changeEvent`` that reacts to a palette/style change.
    """
    attr = "_esim_deferred_" + getattr(slot, "__name__", "restyle")
    timer = getattr(widget, attr, None)
    if timer is None:
        timer = QtCore.QTimer(widget)
        timer.setSingleShot(True)
        timer.timeout.connect(slot)
        setattr(widget, attr, timer)
    timer.start(delay)


def apply_titlebar_theme(window, is_dark=None):
    """Windows-only: color the native titlebar to match the active theme.

    Qt never touches the titlebar — it is drawn by DWM, which follows the OS
    accent/light setting, so a dark-themed eSim kept a light (or accent-
    colored) caption bar that no stylesheet can reach. On Ubuntu the window
    manager themes the decoration itself, which is why this mismatch never
    shows there. DwmSetWindowAttribute is the only way in:

      20 DWMWA_USE_IMMERSIVE_DARK_MODE — dark caption (Win10 1809+)
      35 DWMWA_CAPTION_COLOR           — exact caption color (Win11+)
      36 DWMWA_TEXT_COLOR              — caption text color  (Win11+)

    The color attributes fail harmlessly (E_INVALIDARG) on Win10; the
    immersive flag alone still gets a dark bar there. Safe to call repeatedly
    and on any top-level widget; no-op off Windows or before the native
    window exists.
    """
    if sys.platform != "win32" or window is None or not window.isWindow():
        return
    if is_dark is None:
        is_dark = _CURRENT_DARK
    try:
        # Never force native-window creation here: winId() on a not-yet-shown
        # widget realizes the window early, which would defeat attributes that
        # must be set pre-creation (WA_TranslucentBackground) and re-open the
        # first-show flash. Windows without a handle get themed by the Show
        # hook in motion.py once they actually appear.
        if window.windowHandle() is None:
            return
        hwnd = int(window.winId())
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        dark_flag = ctypes.c_int(1 if is_dark else 0)
        dwm.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 20,
            ctypes.byref(dark_flag), ctypes.sizeof(dark_flag))

        # COLORREF is 0x00BBGGRR; match the QPalette Window/WindowText pair
        # so the caption reads as part of the app surface.
        def colorref(hex_color):
            c = QtGui.QColor(hex_color)
            return ctypes.c_uint32(
                (c.blue() << 16) | (c.green() << 8) | c.red())

        caption = colorref("#050812" if is_dark else "#F3F7FC")
        text = colorref("#F8FBFF" if is_dark else "#142033")
        dwm.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 35,
            ctypes.byref(caption), ctypes.sizeof(caption))
        dwm.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 36,
            ctypes.byref(text), ctypes.sizeof(text))
    except Exception:
        pass


def apply_round_corners(window):
    """Windows-only: have DWM round the window's corners in the compositor.

      33 DWMWA_WINDOW_CORNER_PREFERENCE / 2 DWMWCP_ROUND (Win11+)

    Qt cannot round a popup by itself here. Under the Fusion base style the
    popup's native window is never marked layered (WS_EX_LAYERED stays clear),
    so its raster backing store has nowhere to put alpha: everything outside
    the QSS border-radius flushes as OPAQUE BLACK. WA_TranslucentBackground
    therefore buys no transparency on this path and actively costs a black
    corner, and clipping those pixels off with setMask() only trades the black
    for a hard staircase -- a QRegion is 1-bit, so it cannot hold the partial
    coverage a smooth curve needs, and Qt scales the logical-pixel mask up to
    device pixels (x1.75 at 175% display scaling), which coarsens the steps
    further. That staircase is what the rounded menus actually looked like.

    DWM has the alpha the backing store lacks. It clips and antialiases the
    window after Qt has painted, so the corners come out smooth with no mask
    and no translucency. Requires the native window to exist -- call it on
    Show, not on create. Fails harmlessly (E_INVALIDARG) on Win10, which has
    no rounded corners to ask for -- and returns False there, so the caller
    can fall back to the mask instead of shipping square popups (which is what
    the Win10 build actually looked like).

    Returns True only when DWM accepted the attribute.
    """
    if sys.platform != "win32" or window is None:
        return False
    try:
        if window.windowHandle() is None:
            return False
        hwnd = int(window.winId())
        if not hwnd:
            return False
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 33,
            ctypes.byref(pref), ctypes.sizeof(pref))
        return hr == 0
    except Exception:
        return False


# DWM clips DWMWCP_ROUND windows at a radius it owns; measured at 8 logical px
# (a screen grab through a popup's corner shows desktop at 3px in and menu body
# at 7px in, at both 1x and 1.75x scaling). It is a compositor constant, so it
# does NOT move with the app's zoom the way a QSS metric does.
DWM_CORNER_RADIUS_PX = 8


def dwm_rounds_popups():
    """True when this Windows build rounds windows in the compositor.

    Rounded corners arrived with Windows 11 (build 22000); on Windows 10
    DwmSetWindowAttribute rejects DWMWA_WINDOW_CORNER_PREFERENCE, so popups
    stay square unless something else rounds them.
    """
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


# Windows-with-DWM only: pull the popup frames' own radius onto the radius DWM
# will clip them at.
#
# These windows paint an OPAQUE rectangle -- translucency is not available on
# this path (a grab of a WA_TranslucentBackground popup here reads #000000 in
# the corners, the documented failure). So the QSS border-radius does not
# actually cut the corner off: the body still fills the full square and only
# the 1px BORDER follows the curve. With the sheet at 14px and DWM clipping at
# 8px the two disagree, and what is left on screen is a rounded outline with
# white fill spilling past it into each corner -- reported as "the outline is
# nicely rounded but inside is not filled up to the rounded corners".
#
# Matching the sheet to DWM makes the border land exactly on the clip, so the
# outline and the edge of the fill are the same curve. Appended AFTER the zoom
# pass precisely because it must not be scaled with it.
_POPUP_CORNER_OVERRIDE = """
QMenu { border-radius: %(r)dpx; }
QComboBox QAbstractItemView { border-radius: %(r)dpx; }
""" % {"r": DWM_CORNER_RADIUS_PX}


def replace_tokens(qss, tokens, value):
    for token in tokens:
        qss = qss.replace(token, value)
    return qss


# "&File" is five characters and four glyphs: with a mnemonic flag set, Qt
# eats the '&' and underlines the letter after it ("&&" is a literal '&').
# Measuring the raw string therefore overstates the drawn width by an
# ampersand -- ~14px at menu-bar size, which was enough to "not fit" every
# top-level menu title into the rect the style had just sized for it and
# elide "File" to "F...".
_MNEMONIC_RE = re.compile(r"&(.)")
_MNEMONIC_FLAGS = (int(QtCore.Qt.TextFlag.TextShowMnemonic)
                   | int(QtCore.Qt.TextFlag.TextHideMnemonic))


def drawn_text(text, flags):
    """``text`` as the style will actually paint it, mnemonic markers removed."""
    if text and (int(flags) & _MNEMONIC_FLAGS):
        return _MNEMONIC_RE.sub(r"\1", text)
    return text


def elide_to_fit(fm, text, flags, width):
    """``text`` shortened with an ellipsis if it cannot fit in ``width``.

    Returned unchanged when it fits, when it is empty, when it is multi-line,
    or when the caller asked for word wrap -- in all of those the layout has
    already accounted for the size and truncating would lose content.

    The fit is measured against the *drawn* string (see drawn_text), not the
    source string, so mnemonic ampersands do not count toward the width.
    Text that fits is returned exactly as it came in, ampersands intact, so
    the underline survives; only the elided branch loses it, and there the
    letter it marked may well have been truncated away anyway.
    """
    if not text or width <= 0:
        return text
    if "\n" in text or (int(flags) & int(QtCore.Qt.TextFlag.TextWordWrap)):
        return text
    shown = drawn_text(text, flags)
    if fm.horizontalAdvance(shown) <= width:
        return text
    return fm.elidedText(shown, QtCore.Qt.TextElideMode.ElideRight, width)


class ComboPopupStyle(QtWidgets.QProxyStyle):
    """Fusion with the macOS-flavoured combo popup turned off.

    Fusion answers SH_ComboBox_Popup = 1, which makes QComboBox treat its
    popup as a *menu*: QComboBoxPrivateContainer paints PE_PanelMenu (an
    opaque square panel with a 1px border) behind the item view, insets the
    view by the menu's vertical margins, and positions the popup so the
    current item lands on top of the combo instead of dropping below it. Our
    sheet then draws its own rounded border on the view inside all that, so
    every dropdown reads as a rounded card floating in a square one, opening
    in the wrong place.

    Answering 0 puts QComboBox back on the plain drop-down path: no menu
    panel, no margins, popup anchored under the combo. The container is still
    an opaque top-level window, so it would show square corners behind the
    view's border-radius -- polish() makes it translucent and frameless, which
    leaves the item view as the only thing that paints.
    """

    _POLISH_FLAG = "_esim_combo_popup_polished"

    def drawItemText(self, painter, rect, flags, palette, enabled, text,
                     textRole=QtGui.QPalette.ColorRole.NoRole):
        """Elide style-drawn text that no longer fits instead of clipping it.

        Every label a QStyle draws for a control -- push buttons, tool buttons,
        checkboxes, the closed combo box -- comes through here with the exact
        rect it is allowed to occupy. Qt's default is to draw the string anyway
        and let it run past both edges, which is what "the text just goes out
        of the button and gets cropped left and right" looks like: raise the
        zoom, the font grows, the container it sits in does not, and the label
        spills.

        Eliding is the honest failure mode. "Remove Mod..." is readable and
        obviously truncated; a label sheared off mid-glyph at both ends is
        neither. Text that fits is returned unchanged, so this costs one width
        measurement and changes nothing in the common case.

        Multi-line and word-wrapped text is left alone -- eliding it to one
        line would lose content the layout has already made room for.
        """
        try:
            text = elide_to_fit(painter.fontMetrics(), text, flags,
                                rect.width())
        except Exception:
            pass
        super().drawItemText(painter, rect, flags, palette, enabled, text,
                             textRole)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QtWidgets.QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        if hint == QtWidgets.QStyle.StyleHint.SH_ComboBox_PopupFrameStyle:
            return int(QtWidgets.QFrame.Shape.NoFrame)
        return super().styleHint(hint, option, widget, returnData)

    def polish(self, target):
        # QStyle::polish is overloaded on QWidget/QApplication/QPalette and
        # PyQt routes all three here; the QPalette one has to return its
        # argument or Qt reads a null palette back.
        if isinstance(target, QtGui.QPalette):
            return super().polish(target)

        # setWindowFlag() reparents the container, which re-polishes it, so
        # this would recurse without the flag.
        if (isinstance(target, QtWidgets.QWidget)
                and target.metaObject().className()
                == "QComboBoxPrivateContainer"
                and not target.property(self._POLISH_FLAG)):
            target.setProperty(self._POLISH_FLAG, True)
            target.setWindowFlag(
                QtCore.Qt.WindowType.FramelessWindowHint, True)
            target.setWindowFlag(
                QtCore.Qt.WindowType.NoDropShadowWindowHint, True)
            target.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        super().polish(target)


# Process-lifetime cache of fully-resolved stylesheets, keyed by everything
# that affects the output: (qss file, accent, secondary, internal, zoom). The
# build step reads the file, rewrites image urls, runs three token-replace
# passes, an rgba() recolor regex and a per-metric px-scale regex over a large
# sheet -- doing that on every theme toggle (the user flipping Light/Dark back
# and forth, or the OS colorScheme signal firing) is pure waste when the inputs
# repeat. There are only a handful of distinct combinations in a session, so an
# unbounded dict here stays tiny.
_QSS_CACHE = {}


# ── Zoom: two scales, not one ────────────────────────────────────────────
#
# Zoom used to be a single linear multiplier applied to every ``px`` in the
# sheet -- including ``font-size``. That works going up and falls apart going
# down, because layout and text do not degrade at the same rate. A 32px button
# at 60% is a 19px button: smaller, still perfectly usable. A 14px label at 60%
# is an 8px label: not small, *unreadable*. That single scale is why the same
# build was reported as "60% zoom looks great... the font size is a bit small"
# -- the reporter was reading the layout, which was fine, and the text, which
# was not.
#
# So zoom now drives two curves off one number:
#
#   layout  linear, unchanged -- zoom/100.
#   text    linear at and above 100%, compressed below it, and floored.
#
# Below 100% the exponent pulls text back toward its design size (0.6 ** 0.55
# = 0.76, so 14px lands on 11px rather than 8px) and the floor stops the small
# roles falling off the legibility cliff entirely. At and above 100% the curve
# is deliberately the identity: someone who zooms to 200% is asking for big
# text and must get exactly that, and keeping the top half linear means this
# change cannot regress any zoom level anyone has already tuned by eye.
#
# Text/layout ratio is a *design* choice at 100% and stays untouched there; the
# compression only buys back legibility in the range where the linear ratio was
# giving the user something they could not read.
_FONT_EXP = 0.55

# A 14px body label at 60% zoom must still be readable, so text stops shrinking
# here even when the curve would take it lower. Two tiers: the small roles
# (badges, captions, the status bar) are already at their own floor by design
# and would look wrong pushed up to the body floor.
_FONT_FLOOR_PX = 11
_FONT_FLOOR_SMALL_PX = 10
_FONT_SMALL_MAX_PX = 11

# Set by _apply_theme_impl so widget code can ask for the live zoom without a
# JSON read per call. Falls back to the stored preference when the theme has
# not been applied yet (early startup, tests).
_CURRENT_ZOOM = None


def current_zoom():
    """The zoom percentage now in effect, as an int."""
    if _CURRENT_ZOOM is not None:
        return _CURRENT_ZOOM
    try:
        z = get_preferences().get("zoom_level", 100)
        return z if isinstance(z, int) and 50 <= z <= 300 else 100
    except Exception:
        return 100


def zoom_scale(zoom_level=None):
    """Layout scale factor: linear across the whole range."""
    if zoom_level is None:
        zoom_level = current_zoom()
    return zoom_level / 100.0


def font_scale(zoom_level=None):
    """Text scale factor: linear at/above 100%, compressed below it.

    See the _FONT_EXP note above for why this is not simply zoom_scale().
    """
    if zoom_level is None:
        zoom_level = current_zoom()
    z = zoom_level / 100.0
    if z >= 1.0:
        return z
    return z ** _FONT_EXP


def _font_floor(base_px):
    """The smallest px this role is allowed to shrink to.

    Never above the role's own design size -- a role that ships at 9px is
    already deliberately tiny and must not be *grown* by its own floor.
    """
    floor = (_FONT_FLOOR_SMALL_PX if base_px <= _FONT_SMALL_MAX_PX
             else _FONT_FLOOR_PX)
    return min(base_px, floor)


def scale_font_px(base_px, zoom_level=None):
    """Scale one design-size font metric through the text curve + floor."""
    scaled = int(round(base_px * font_scale(zoom_level)))
    return max(scaled, _font_floor(base_px))


def zoom_px(px, zoom_level=None):
    """Scale one design-size *layout* metric (widths, heights, spacing).

    Use this for every pixel constant set from Python -- setFixedHeight,
    setMinimumWidth, setIconSize, layout margins. build_qss() rewrites the px
    metrics inside the .qss file, but it cannot see a number that lives in
    Python, and a container frozen at its 100% width is exactly how a button's
    label ends up clipped at 150% zoom.
    """
    scaled = int(round(px * zoom_scale(zoom_level)))
    return max(1, scaled) if px > 0 else scaled


# Widgets that asked to be re-measured when the zoom changes. zoom_px() is
# evaluated once, at construction, so a panel built at 90% keeps its 90% sizes
# if the user then dials the pill to 150% -- the QSS metrics around it move and
# its own do not. Long-lived surfaces register here to stay in step; short-lived
# ones (dialogs, popups) are rebuilt at the new zoom anyway and do not need to.
_ZOOM_HOOKS = []


def on_zoom_changed(widget, fn):
    """Run ``fn(zoom)`` now, and again after every zoom change.

    The hook is dropped as soon as ``widget`` is gone, so registering costs
    nothing after the surface that owns it closes.
    """
    import weakref
    try:
        fn(current_zoom())
    except Exception:
        pass
    _ZOOM_HOOKS.append((weakref.ref(widget), fn))


def reapply_zoom_metrics(zoom_level=None):
    """Re-run every registered zoom hook. Called on the settled zoom change.

    Deliberately NOT called from inside _apply_theme_impl: these hooks set
    size constraints, and doing that in the middle of an app-wide repolish
    re-enters the layout/style engine while it is still walking a snapshot of
    the widget tree -- the exact shape of the 0xC0000005 this codebase has been
    hardened against. The caller runs it after the repolish has settled.
    """
    if zoom_level is None:
        zoom_level = current_zoom()
    live = []
    for ref, fn in _ZOOM_HOOKS:
        widget = ref()
        if widget is None:
            continue
        try:
            fn(zoom_level)
        except RuntimeError:
            # Underlying C++ widget already freed -- drop the hook.
            continue
        except Exception:
            pass
        live.append((ref, fn))
    _ZOOM_HOOKS[:] = live


def scale_font(font, zoom_level=None):
    """Return a copy of ``font`` with its size taken through the text curve.

    Point sizes are converted through the same curve as px so a QFont set in
    Python tracks the QSS type scale instead of staying frozen.
    """
    if zoom_level is None:
        zoom_level = current_zoom()
    out = QtGui.QFont(font)
    if zoom_level == 100:
        # Exactly the design size -- no pt<->px round trip, so callers can rely
        # on this being a true no-op rather than a 0.25pt drift.
        return out
    if out.pixelSize() > 0:
        out.setPixelSize(scale_font_px(out.pixelSize(), zoom_level))
    else:
        pt = out.pointSizeF()
        if pt > 0:
            # Floors are expressed in px; 1pt ~= 1.333px at Qt's 96dpi
            # reference, so convert, scale, and convert back.
            px = pt * 4.0 / 3.0
            out.setPointSizeF(scale_font_px(px, zoom_level) * 3.0 / 4.0)
    return out


# Matches a font-size declaration, a max-height declaration, or a bare px
# metric. Alternation is left-to-right at each scan position, so
# `font-size: 14px` is consumed whole by the first branch before the scanner
# can reach its digits -- which is what keeps text off the layout curve.
_PX_RE = re.compile(
    r'(font-size\s*:\s*)(\d+(?:\.\d+)?)px'
    r'|(max-height\s*:\s*)(\d+(?:\.\d+)?)px'
    r'|(\d+(?:\.\d+)?)px'
)


def scale_qss_px(qss_content, zoom_level):
    """Apply the layout curve to metrics and the text curve to font sizes.

    ``max-height`` is the one layout metric that gets a guard. It is a hard
    cap: if it lands under the height the text needs, Qt clips the glyphs
    rather than growing the control. Below 100% the layout curve falls faster
    than the text curve by design, so a cap taken straight down the layout
    curve would crush the very text the text curve just protected -- a 28px cap
    holding 13px type becomes a 17px cap holding 11px type. Capping it at
    whichever curve is *gentler* keeps the box able to hold its own contents.
    At and above 100% the two curves are identical, so nothing changes there.

    Minimums and paddings need no such guard: they can only push a control
    bigger, never clip it. Horizontal overflow is handled by eliding the label
    (see ComboPopupStyle.drawItemText), which is the right answer for width --
    there is no equivalent for height, so height gets the floor.
    """
    if zoom_level == 100:
        return qss_content
    scale = zoom_scale(zoom_level)
    cap_scale = max(scale, font_scale(zoom_level))

    def repl(match):
        if match.group(1) is not None:
            base = float(match.group(2))
            return "%s%dpx" % (match.group(1), scale_font_px(base, zoom_level))
        if match.group(3) is not None:
            base = float(match.group(4))
            if base <= 2:
                return match.group(0)
            return "%s%dpx" % (match.group(3), int(round(base * cap_scale)))
        val = float(match.group(5))
        # Keep 1-2px hairline borders crisp; only scale real metrics.
        if val <= 2:
            return match.group(0)
        return "%dpx" % int(round(val * scale))

    return _PX_RE.sub(repl, qss_content)


# The UI font stack, resolved per platform at stylesheet-build time.
#
# eSim bundles the Ubuntu family (Application.py registers the three static
# weights) so it reads the same on both platforms. On Ubuntu that is exactly
# right. On Windows it is not: Ubuntu's hinting instructions are authored for
# FreeType, and DirectWrite ignores nearly all of them, so at the 12-14px the
# UI actually uses the glyphs come out soft and muddy -- the "fonts look
# low-res" report, and why it only reproduced on a 1x 1080p panel (at 175%
# scaling the extra device pixels hide the missing hinting).
#
# Segoe UI Variable Text is Windows 11's own UI face at text sizes and is
# hinted for the renderer that will actually draw it; Segoe UI covers Windows
# 10. Ubuntu stays in the stack below them, so a Windows box without Segoe
# still gets the bundled face rather than a system fallback.
_FONT_STACK_WIN = ('"Segoe UI Variable Text", "Segoe UI", "Ubuntu", '
                   '"Noto Sans", sans-serif')
_FONT_STACK_OTHER = ('"Ubuntu", "Segoe UI Variable", "Segoe UI", '
                     '"Noto Sans", sans-serif')

# The stack as written in the .qss files, replaced with the per-platform one.
_FONT_STACK_QSS = ('"Ubuntu", "Segoe UI Variable", "Segoe UI", '
                   '"Noto Sans", sans-serif')


def ui_font_stack():
    """The CSS font-family list the UI should use on this platform."""
    return _FONT_STACK_WIN if sys.platform == "win32" else _FONT_STACK_OTHER


def ui_font_families():
    """``ui_font_stack()`` as a list of family names, best first.

    For the handful of places that must build a QFont in Python: hand this to
    QFont.setFamilies() so they resolve through the same stack as the QSS.
    """
    return [f.strip().strip('"') for f in ui_font_stack().split(",")
            if f.strip().strip('"') != "sans-serif"]


def build_qss(qss_name, is_dark, accent_color, secondary_color,
              internal_bg_color, zoom_level):
    """Return the fully-resolved stylesheet string for the given inputs,
    memoized. Pure function of its arguments (plus the on-disk .qss, which does
    not change during a run), so it is safe to cache for the process lifetime."""
    key = (qss_name, accent_color, secondary_color, internal_bg_color,
           zoom_level)
    cached = _QSS_CACHE.get(key)
    if cached is not None:
        return cached

    qss_path = os.path.join(os.path.dirname(__file__), qss_name)
    if not os.path.exists(qss_path):
        _QSS_CACHE[key] = ""
        return ""
    with open(qss_path, 'r') as f:
        qss_content = f.read()

    # Resolve the relative ``url("images/...")`` references in the QSS to an
    # absolute path next to this module. Previously these only worked because
    # the launcher does ``cd src/frontEnd`` first; from any other working
    # directory (or a frozen PyInstaller build) the dock/tab icons silently
    # failed to load. This makes them CWD-independent.
    img_dir = os.path.join(os.path.dirname(__file__), 'images')
    img_dir = img_dir.replace(os.sep, '/')
    qss_content = qss_content.replace('url("images/', 'url("%s/' % img_dir)

    mode_key = "dark" if is_dark else "light"

    if accent_color != "default":
        qss_content = replace_tokens(
            qss_content, ACCENT_TOKENS[mode_key], accent_color)
        # Also recolor the rgba() glows/borders so the accent fully propagates.
        qss_content = recolor_accent_rgba(qss_content, mode_key, accent_color)

    if secondary_color != "system":
        qss_content = replace_tokens(
            qss_content, SECONDARY_TOKENS[mode_key], secondary_color)

    if internal_bg_color != "system":
        qss_content = replace_tokens(
            qss_content, INTERNAL_TOKENS[mode_key], internal_bg_color)

    # Swap the shipped stack for the platform-appropriate one BEFORE the px
    # pass, so the substituted text is a plain family list with no metrics in
    # it either way.
    stack = ui_font_stack()
    if stack != _FONT_STACK_QSS:
        qss_content = qss_content.replace(_FONT_STACK_QSS, stack)

    qss_content = scale_qss_px(qss_content, zoom_level)

    if dwm_rounds_popups():
        qss_content += _POPUP_CORNER_OVERRIDE

    _QSS_CACHE[key] = qss_content
    return qss_content


def recolor_accent_rgba(qss, mode_key, accent_hex):
    """Recolor every ``rgba(<default-accent>, a)`` glow to the chosen accent.

    The old token-replace step only swapped a handful of *solid* hexes, so a
    custom accent left ~200 hard-coded ``rgba(83,215,255,a)`` (dark) /
    ``rgba(0,119,168,a)`` (light) borders, hovers and glows the original cyan.
    This recolors all of them so the accent truly propagates across the UI.
    """
    try:
        from frontEnd import tokens as _tok
    except Exception:
        import tokens as _tok
    import re
    r0, g0, b0 = _tok.DEFAULT_ACCENT_RGB[mode_key]
    nr, ng, nb = _tok.hex_to_rgb(accent_hex)
    if (r0, g0, b0) == (nr, ng, nb):
        return qss
    pattern = re.compile(
        r"rgba\(\s*%d\s*,\s*%d\s*,\s*%d\s*," % (r0, g0, b0))
    return pattern.sub("rgba(%d,%d,%d," % (nr, ng, nb), qss)


# The UI's px metrics were hand-tuned against a workspace this many *logical*
# pixels tall and wide -- i.e. the screen size at which zoom_level 100 is the
# right answer. Derived from the one hand-calibrated data point we have: a
# 1646x1029 logical workspace (a 2880x1800 panel at 175% Windows scaling) was
# tuned by eye to 90%, so 1029 / 0.90 ~= 1150 and 1646 / 0.90 ~= 1830.
_DESIGN_WORKSPACE_H = 1150
_DESIGN_WORKSPACE_W = 1830

# Never auto-pick a value the user would immediately have to undo. Below 60%
# the chrome itself stops working -- toolbar hit targets get fiddly and the
# dock tabs crowd -- and above 150% we would be overriding the deliberate "I
# want a small UI" choice the user already expressed in their OS display
# settings. (Readability at the bottom of the range is no longer part of this
# bound: text stops shrinking on its own via the font curve and floors above,
# which is what made a calibrated 60% usable on a 1280x720 workspace instead
# of merely small.)
_CALIBRATION_FLOOR = 60
_CALIBRATION_CEILING = 150


def calibrate_default_zoom(screen=None):
    """Pick a sensible first-run zoom for the screen eSim is starting on.

    Qt has already divided the OS scale factor out of these numbers, so what
    we read is the *logical* workspace: a 1920x1080 panel at 150% Windows
    scaling reports 1280x720, and genuinely has only that much room for UI.
    eSim's chrome (menu bar, top toolbar, left rail, dock tabs, status bar) is
    a fixed logical-pixel cost, so on a short workspace it eats a far larger
    share of the window. That -- not the panel's resolution or its DPI -- is
    why the same build reads as "great at 60%" on one machine and "great at
    90%" on another, and why a single hard-coded default cannot serve both.

    Height is the binding constraint on every 16:9 / 16:10 display; the width
    term only bites on unusually narrow screens (e.g. 1280x1024), where the
    left rail would otherwise crowd the canvas.
    """
    if screen is None:
        screen = QtGui.QGuiApplication.primaryScreen()
    if screen is None:
        return 100
    # availableGeometry, not geometry: the taskbar/dock is space eSim will
    # never get, and a machine with less of it should start smaller.
    avail = screen.availableGeometry()
    if avail.height() <= 0 or avail.width() <= 0:
        return 100
    ratio = min(avail.height() / _DESIGN_WORKSPACE_H,
                avail.width() / _DESIGN_WORKSPACE_W)
    # Land on the same 10% grid the -/+ buttons step through, so the value the
    # user sees in the pill is one they could have dialled in themselves.
    zoom = int(round(ratio * 10)) * 10
    return max(_CALIBRATION_FLOOR, min(_CALIBRATION_CEILING, zoom))


def ensure_zoom_calibrated(screen=None):
    """Seed zoom_level from the screen on first run, then never touch it again.

    Once the key exists -- because we wrote it here, or because the user
    touched the zoom pill -- it is the user's preference and is left alone,
    including if they later move the window to a different monitor. Returns
    the zoom level now in effect.
    """
    prefs = get_preferences()
    existing = prefs.get("zoom_level")
    if isinstance(existing, int) and 50 <= existing <= 300:
        return existing
    zoom = calibrate_default_zoom(screen)
    prefs["zoom_level"] = zoom
    try:
        paths.write_json_atomic(
            paths.esim_config_path("preferences.json"), prefs)
    except Exception:
        # A read-only config dir must never block startup -- the calibrated
        # value still applies to this session, we just recompute next launch.
        pass
    return zoom


def get_preferences(user_home=None):
    prefs = {"theme_mode": "System", "accent_color": "default", "secondary_accent_color": "system"}
    try:
        path = (os.path.join(user_home, ".esim", "preferences.json")
                if user_home else paths.esim_config_path("preferences.json"))
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                prefs.update(data)
    except Exception as e:
        print("Error loading preferences: ", str(e))
    return prefs


def _refresh_graphics_effects(app):
    """Invalidate cached QGraphicsEffect renders after a theme change.

    A QGraphicsDropShadowEffect keeps a cached pixmap of its source widget.
    A stylesheet/palette swap repaints the widget but leaves the effect cache
    stale, so the widget (e.g. a themed button) can render blank until a hover
    forces it dirty. Toggling enabled off/on re-validates the source and
    triggers an immediate repaint. Cheap: theme changes are rare.
    """
    from PyQt6 import QtWidgets
    for tlw in app.topLevelWidgets():
        try:
            targets = [tlw] + tlw.findChildren(QtWidgets.QWidget)
        except Exception:
            continue
        # Guard per WIDGET, not per window: toggling an effect repaints, and a
        # repaint can retire a widget further down this snapshot. One dead entry
        # used to abandon every remaining widget in that window, leaving their
        # shadows stale for the rest of the session.
        for w in targets:
            try:
                eff = w.graphicsEffect()
                if eff is not None and eff.isEnabled():
                    eff.setEnabled(False)
                    eff.setEnabled(True)
            except RuntimeError:
                continue    # widget (or its effect) died mid-walk
            except Exception:
                continue
        try:
            tlw.update()
        except RuntimeError:
            pass


# --- Light <-> dark transition ---------------------------------------------
#
# A theme flip is one logical event, but Qt delivers it as thousands of small
# ones: setPalette/setStyleSheet walk the widget tree, every widget repolishes
# and repaints when its turn comes, and the per-widget changeEvent handlers
# restyle a tick later still (see defer_restyle). With painting live the whole
# time, the user watches the window turn dark in pieces -- toolbar, then tree,
# then editor -- over the ~0.5-1s the walk takes.
#
# Two mechanisms fix that, in order of importance:
#
#   1. Freeze painting on every visible window for the duration of the walk
#      (setUpdatesEnabled(False)). Widgets still repolish; nothing reaches the
#      screen until updates come back, so the switch lands in ONE frame instead
#      of leaking out widget by widget. This is the part that removes the
#      staggered reveal, and it is what a hard-cut theme switch should always
#      do.
#
#   2. Hold a snapshot of the pre-flip window on top while that happens, then
#      cross-dissolve it out. The freeze alone still shows a stall on the old
#      colors followed by a hard cut; the dissolve turns the stall into a
#      deliberate-looking 200ms transition. Skipped when motion is off (the
#      app's reduce-motion switch) -- then it is just the atomic cut.
#
# The snapshot is drawn by our own paintEvent at a painter opacity, NOT via a
# QGraphicsOpacityEffect: a theme apply already toggles and frees graphics
# effects across the whole app, and adding one more effect into that window is
# how this module used to crash (see _apply_theme_impl's glow freeze).
#
# Only a real light<->dark flip transitions. Zoom re-applies and accent-only
# changes go through the same repolish but are left alone.
_FADE_MS = 220
_SETTLE_MS = 60
_TRANSITION_WATCHDOG_MS = 4000

# Whether apply_theme has run at least once. The first apply happens before any
# window exists (and would "flip" from the False default), so it never fades.
_THEME_APPLIED_ONCE = False

# True while at least one window is painting-frozen for a flip. Read by
# _apply_theme_impl to skip work that only exists to fix what is on screen.
_TRANSITION_ACTIVE = False


def transition_active():
    return _TRANSITION_ACTIVE


# Set ESIM_THEME_DEBUG=1 to trace why a flip dissolved or cut, per window, into
# ~/.esim/theme_debug.log. Off by default and costs one env lookup per flip.
_DEBUG = bool(os.environ.get("ESIM_THEME_DEBUG"))


def _dbg(message):
    if not _DEBUG:
        return
    try:
        path = os.path.join(os.path.expanduser("~"), ".esim", "theme_debug.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("%.3f %s\n" % (
                QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0, message))
    except Exception:
        pass


def _dbg_name(widget):
    try:
        return "%s/%s %dx%d" % (type(widget).__name__, widget.objectName(),
                                widget.width(), widget.height())
    except RuntimeError:
        return "<deleted>"


class _ThemeFadeOverlay(QtWidgets.QWidget):
    """Cross-dissolves a snapshot of the old theme into one of the new.

    Both sides are *pixmaps*, and that is the whole point. Fading a
    translucent snapshot over the live widget tree makes Qt repaint every
    widget under it on every frame of the fade -- on a populated session that
    is a full-app repaint 60 times a second, which is why the first version of
    this ran at about 10fps. Once the new look is a pixmap too, the overlay is
    opaque, Qt clips the widgets underneath out of the paint entirely, and a
    frame costs two blits regardless of how many widgets the app has.
    """

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self._before = pixmap
        self._after = None
        self._opacity = 1.0     # opacity of the OLD look: 1 -> 0 over the fade
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setGeometry(parent.rect())

    def set_after(self, pixmap):
        """Hand over the new-theme snapshot; from here the overlay is opaque.

        WA_OpaquePaintEvent is what actually buys the frame rate: it tells Qt
        this widget fills every pixel it owns, so the repaint of a covered
        sibling never happens while the dissolve runs.
        """
        self._after = pixmap
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.update()

    def set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        # Nearest-neighbour: the snapshots are already at the window's device
        # pixel ratio, so there is nothing to interpolate and the smooth path
        # would only cost time per frame.
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        # drawPixmap at a point (not into rect()) uses the pixmap's own device
        # pixel ratio, so HiDPI lands 1:1 instead of going through a rescale.
        if self._after is not None:
            painter.drawPixmap(0, 0, self._after)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._before)

    def release_opaque(self):
        """Stop claiming the region, so the real widgets paint again."""
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, False)


def _has_web_surface(widget):
    """True when the window hosts a QWebEngineView (Makerchip / User Manual).

    WebEngine paints through its own compositing surface, which a sibling
    overlay cannot cover and QWidget.grab() captures as an empty rectangle --
    a snapshot would blank that pane for the length of the fade. Such windows
    get the paint freeze only. Never imports the module: if WebEngine was
    never loaded this session, no window can be holding a view.
    """
    module = sys.modules.get("PyQt6.QtWebEngineWidgets")
    if module is None:
        return False
    try:
        return widget.findChild(module.QWebEngineView) is not None
    except Exception:
        return True     # unsure -> no snapshot, freeze only


def _snapshot_is_degenerate(pixmap):
    """True when a grab came back as a flat slab (or not at all).

    A window snapshot that holds exactly one color did not render its
    children -- the window background is all there is. Dissolving into that
    shows a solid white/black rectangle where the UI should be, so the caller
    falls back to a hard cut instead. This is the guard for the whole class of
    "the grab did not work here": painting frozen, a native surface, a driver
    that hands back an empty buffer. Sampled on a coarse grid, so the cost
    does not scale with window size.
    """
    if pixmap is None or pixmap.isNull():
        return True
    try:
        image = pixmap.toImage()
        step = max(8, min(image.width(), image.height()) // 24)
        first = None
        for y in range(0, image.height(), step):
            for x in range(0, image.width(), step):
                pixel = image.pixel(x, y)
                if first is None:
                    first = pixel
                elif pixel != first:
                    return False
        return True
    except Exception:
        return True


def _discard_overlay(overlay):
    if overlay is None:
        return
    try:
        owner = getattr(overlay, "_esim_owner", None)
        if owner is not None and getattr(owner, "_esim_theme_overlay", None) is overlay:
            owner._esim_theme_overlay = None
        # A second flip during the dissolve discards this overlay mid-fade;
        # stop its animation rather than let it keep driving a widget that is
        # already on its way out.
        anim = getattr(overlay, "_esim_fade_anim", None)
        if anim is not None:
            anim.stop()
        overlay.hide()
        overlay.deleteLater()
    except RuntimeError:
        pass


def _set_overlay_opacity(overlay, value):
    try:
        overlay.set_opacity(value)
    except RuntimeError:
        pass


def _end_fade(overlay):
    """Hand the region back to the real widgets, then drop the overlay.

    Order matters: the last frame of the dissolve is pixel-identical to what
    the widgets paint, so releasing the opaque claim first lets them repaint
    underneath before the overlay goes away -- no uncovered frame in between.
    """
    try:
        overlay.release_opaque()
        owner = getattr(overlay, "_esim_owner", None)
        if owner is not None:
            owner.update()
    except RuntimeError:
        pass
    _discard_overlay(overlay)


def _fade_out_overlay(overlay):
    anim = QtCore.QVariantAnimation(overlay)
    anim.setDuration(_FADE_MS)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    # Symmetric ease: a dissolve that starts and ends gently reads as one
    # movement, where OutCubic front-loads it and looks like a jump-cut.
    anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
    anim.valueChanged.connect(lambda v: _set_overlay_opacity(overlay, v))
    anim.finished.connect(lambda: _end_fade(overlay))
    # Parented to the overlay, so it dies with it and never outlives the
    # widget it is driving.
    overlay._esim_fade_anim = anim
    anim.start()


def _sync_titlebar_to_fade(window):
    """Recolor the native caption partway through the dissolve.

    DWM owns the titlebar: it cannot fade, it can only cut. Cutting it at the
    top of _apply_theme_impl (where the icon loop used to) put the new caption
    over a client area still showing the old theme -- a bright bar over a dark
    app for the whole freeze plus the whole fade. Cutting it at the dissolve's
    halfway point instead puts the switch where the client area is already
    halfway there, and the eye reads the two as one event.
    """
    def _recolor():
        try:
            apply_titlebar_theme(window)
        except RuntimeError:
            pass        # window closed mid-dissolve
    QtCore.QTimer.singleShot(max(0, int(_FADE_MS * 0.45)), _recolor)


def _begin_theme_transition(app, animate=True):
    """Freeze painting on every visible window (and snapshot it, if animating).

    Returns the transition state, which also carries its own completion: the
    finish is queued HERE, before the repolish that could raise, so a failed
    theme apply can never strand a window with painting switched off.
    """
    state = {"windows": [], "finished": False}
    _dbg("--- begin transition animate=%s ---" % animate)
    for tlw in app.topLevelWidgets():
        try:
            if not tlw.isVisible() or tlw.isMinimized():
                continue
            if tlw.width() <= 0 or tlw.height() <= 0:
                continue
        except RuntimeError:
            continue
        overlay = None
        if animate and not _has_web_surface(tlw):
            try:
                _discard_overlay(getattr(tlw, "_esim_theme_overlay", None))
                started = QtCore.QElapsedTimer()
                started.start()
                pixmap = tlw.grab()
                _dbg("  %s before-grab null=%s %dms" % (
                    _dbg_name(tlw), pixmap.isNull(), started.elapsed()))
                if not pixmap.isNull():
                    overlay = _ThemeFadeOverlay(tlw, pixmap)
                    overlay._esim_owner = tlw
                    tlw._esim_theme_overlay = overlay
                    overlay.show()
                    overlay.raise_()
                    # Get the snapshot onto the screen NOW: the repolish below
                    # blocks the event loop, so a merely-posted paint would not
                    # be served until after it, leaving the window uncovered
                    # for the frame the new theme lands in.
                    overlay.repaint()
            except Exception as exc:
                _dbg("  %s before-grab RAISED %r" % (_dbg_name(tlw), exc))
                overlay = None
        elif animate:
            _dbg("  %s skipped: web surface" % _dbg_name(tlw))
        try:
            tlw.setUpdatesEnabled(False)
            # Tells the icon loop in _apply_theme_impl to leave this window's
            # native caption alone -- the dissolve schedules it instead.
            tlw._esim_theme_frozen = True
        except RuntimeError:
            _discard_overlay(overlay)
            continue
        state["windows"].append((tlw, overlay))

    if not state["windows"]:
        return state

    global _TRANSITION_ACTIVE
    _TRANSITION_ACTIVE = True

    # Two hops on purpose. The repolish runs to completion before the event
    # loop turns again, so a delay armed now would already be overdue when the
    # loop resumes and would fire ahead of the deferred per-widget restyles.
    # The zero-timer only tells us the loop is live again; the settle delay is
    # measured from there, so it really is 60ms of quiet.
    QtCore.QTimer.singleShot(0, lambda: _arm_theme_transition(state))
    QtCore.QTimer.singleShot(
        _TRANSITION_WATCHDOG_MS,
        lambda: _finish_theme_transition(state, fade=False))
    return state


def _arm_theme_transition(state):
    if state.get("finished"):
        return
    QtCore.QTimer.singleShot(
        _SETTLE_MS, lambda: _finish_theme_transition(state, fade=True))


def _finish_theme_transition(state, fade=True):
    """Restore painting, then dissolve the snapshots away. Idempotent."""
    if state.get("finished"):
        return
    state["finished"] = True
    _dbg("--- finish fade=%s (%d windows) ---" % (fade, len(state["windows"])))
    global _TRANSITION_ACTIVE
    _TRANSITION_ACTIVE = False
    for tlw, overlay in state["windows"]:
        try:
            # Painting comes back FIRST, and the new-look snapshot is taken
            # after it. QWidget.grab() on a window with updates disabled does
            # not render the children at all -- it hands back a single flat
            # slab of the window background. Grabbing while still frozen is
            # what made the dissolve fade into solid white (or solid black)
            # and then snap to life when the overlay was dropped. Measured:
            # 78 distinct colors live, 1 frozen.
            #
            # Nothing reaches the screen in between: the un-freeze only POSTS
            # a repaint, and this function does not return to the event loop
            # until the overlay is back in place covering the window.
            tlw.setUpdatesEnabled(True)
            if overlay is not None and fade:
                # The overlay has to step out of the way for the grab: it
                # renders children too, and it is holding the old theme.
                overlay.hide()
                started = QtCore.QElapsedTimer()
                started.start()
                after = tlw.grab()
                degenerate = _snapshot_is_degenerate(after)
                _dbg("  %s after-grab null=%s degenerate=%s %dms" % (
                    _dbg_name(tlw), after.isNull(), degenerate,
                    started.elapsed()))
                if not degenerate:
                    overlay.set_after(after)
                overlay.show()
                overlay.raise_()
            if overlay is None or overlay._after is None:
                # No snapshot to dissolve from (or the grab failed): the new
                # theme has to reach the backing store right now, because it
                # is what the user is about to see -- either bare, or through
                # a translucent overlay.
                tlw.repaint()
            tlw._esim_theme_frozen = False
        except RuntimeError:
            _discard_overlay(overlay)
            continue
        if overlay is not None and fade and overlay._after is not None:
            # Caption lands mid-dissolve.
            _dbg("  %s -> FADE" % _dbg_name(tlw))
            _sync_titlebar_to_fade(tlw)
            _fade_out_overlay(overlay)
        else:
            _dbg("  %s -> CUT (overlay=%s fade=%s after=%s)" % (
                _dbg_name(tlw), overlay is not None, fade,
                overlay is not None and overlay._after is not None))
            # Hard cut (motion off, grab failed, watchdog): the caption has to
            # switch with it, or the window keeps the outgoing theme's bar.
            try:
                apply_titlebar_theme(tlw)
            except RuntimeError:
                pass
            _discard_overlay(overlay)


def _transition_enabled(app):
    """Off on the headless platforms tests run under: grabbing and fading
    every window there buys nothing and only makes tests time-dependent."""
    try:
        return app.platformName() not in ("offscreen", "minimal", "")
    except Exception:
        return False


def system_is_dark():
    """True when the OS prefers a dark color scheme.

    QStyleHints.colorScheme() only exists on Qt >= 6.5; Ubuntu 24.04 LTS ships
    Qt 6.4, where calling it raises AttributeError (which used to silently
    disable all theming at startup and crash the theme toggle). Fall back to
    GNOME's color-scheme setting, then to palette lightness.
    """
    hints = QtGui.QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme"):
        return hints.colorScheme() == QtCore.Qt.ColorScheme.Dark
    try:
        import subprocess
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2).stdout
        if "dark" in out.lower():
            return True
        if out.strip():
            return False
    except Exception:
        pass
    win = QtGui.QGuiApplication.palette().color(QtGui.QPalette.ColorRole.Window)
    return win.isValid() and win.lightness() < 128


def apply_theme(app):
    """Serialized entry point. Coalesces re-entrant/stacked calls so only one
    repolish runs at a time; the heavy work lives in _apply_theme_impl."""
    global _APPLYING, _APPLY_PENDING
    if _APPLYING:
        # A repaint or a queued OS colorSchemeChanged re-entered mid-apply.
        # Don't stack a second repolish; remember it and run once when we settle.
        _APPLY_PENDING = True
        return
    _APPLYING = True
    try:
        _apply_theme_impl(app)
    finally:
        _APPLYING = False


def _apply_theme_impl(app):
    prefs = get_preferences()
    theme_mode = prefs.get("theme_mode", "System")
    accent_color = prefs.get("accent_color", "default")
    secondary_color = prefs.get("secondary_accent_color", "system")
    internal_bg_color = prefs.get("internal_bg_color", "system")

    # Freeze glow motion and stop every running button-glow animation before we
    # re-polish: setStyleSheet + _refresh_graphics_effects() below toggle (and
    # _drop_glow deletes) the very QGraphicsDropShadowEffect objects a live
    # animation drives, and a freed effect touched by a running animation is a
    # use-after-free that segfaults (0xc0000005) during the theme change. The
    # freeze holds until the deferred refresh pass runs (see _thaw), so NO new
    # glow can start and NO effect is deleted across the whole repolish window --
    # not just at this instant. stop_all_glow() alone left a gap: hover events
    # and the deferred pass after this function returned could still spin up an
    # animation onto an effect being torn down.
    try:
        from frontEnd import motion
        motion.freeze_glow()
        motion.stop_all_glow()
    except Exception:
        pass

    # Queue the thaw NOW, before the repolish that could (in theory) raise, so a
    # theme-apply failure can never strand the freeze and kill glows for the rest
    # of the session. It runs on the next event-loop tick -- after this fully
    # synchronous apply completes -- does the second effect-refresh pass, lifts
    # the freeze, then services any coalesced apply that arrived meanwhile.
    def _thaw():
        try:
            _refresh_graphics_effects(app)
        finally:
            try:
                from frontEnd import motion as _m
                _m.unfreeze_glow()
            except Exception:
                pass
            global _APPLY_PENDING
            if _APPLY_PENDING:
                _APPLY_PENDING = False
                QtCore.QTimer.singleShot(0, lambda: apply_theme(app))
    QtCore.QTimer.singleShot(0, _thaw)

    is_dark = False
    if theme_mode == "Dark":
        is_dark = True
    elif theme_mode == "Light":
        is_dark = False
    else:
        is_dark = system_is_dark()

    global _CURRENT_DARK, _THEME_APPLIED_ONCE
    was_dark = _CURRENT_DARK
    _CURRENT_DARK = is_dark

    # Nothing below has repainted anything yet, so this is the last point where
    # the window on screen still shows the OLD theme -- where a snapshot is
    # worth taking. Only a real light<->dark flip transitions; a zoom re-apply
    # or an accent change repolishes just the same but is not what the eye is
    # tracking, and freezing paint through those would cost responsiveness on
    # the zoom slider for nothing.
    _dbg("apply: once=%s was_dark=%s is_dark=%s enabled=%s" % (
        _THEME_APPLIED_ONCE, was_dark, is_dark, _transition_enabled(app)))
    if _THEME_APPLIED_ONCE and was_dark != is_dark and _transition_enabled(app):
        try:
            from frontEnd import motion as _motion
            animate = _motion.motion_enabled()
        except Exception:
            animate = True
        try:
            _begin_theme_transition(app, animate=animate)
        except Exception:
            pass
    _THEME_APPLIED_ONCE = True

    if is_dark:
        qss_name = 'style_dark.qss'
    else:
        qss_name = 'style_light.qss'

    # Build (or fetch from cache) the fully-resolved sheet. Toggling theme back
    # and forth now re-reads nothing and re-runs no regex once each combination
    # has been seen once.
    zoom_level = prefs.get("zoom_level", 100)
    # Publish it so zoom_px()/scale_font_px() callers in widget code read the
    # same number this sheet was built with, without a JSON read per call.
    global _CURRENT_ZOOM
    _CURRENT_ZOOM = (zoom_level if isinstance(zoom_level, int)
                     and 50 <= zoom_level <= 300 else 100)
    qss_content = build_qss(qss_name, is_dark, accent_color, secondary_color,
                            internal_bg_color, zoom_level)

    # Install the palette BEFORE the stylesheet. QApplication.setPalette()
    # propagates unreliably while an app stylesheet is active (documented Qt
    # caveat: style sheets and setPalette don't mix), so widgets whose QSS
    # rules leave the background to the palette (e.g. the dock-area backdrop
    # behind Welcome) kept the *previous* theme's palette when the palette was
    # set after the sheet — light mode showed a dark dock. Setting the palette
    # first means the full repolish that setStyleSheet() triggers resolves
    # every widget against the new palette in one pass. (The old code got away
    # with sheet-then-palette only because the unconditional setStyle("Fusion")
    # afterwards forced a second full repolish.)
    if is_dark:
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#050812"))
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#F8FBFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#08111F"))
        palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#0E1728"))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor("#0E1728"))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor("#F8FBFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("#F8FBFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#0E1728"))
        palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#F8FBFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Link, QtGui.QColor("#53D7FF"))
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(accent_color if accent_color != "default" else "#53D7FF"))
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#FFFFFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Mid, QtGui.QColor("#1D2B45"))
        palette.setColor(QtGui.QPalette.ColorRole.Midlight, QtGui.QColor("#30415F"))
        palette.setColor(QtGui.QPalette.ColorRole.PlaceholderText, QtGui.QColor("#94A8C3"))
        app.setPalette(palette)
    else:
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#F3F7FC"))
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#142033"))
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#FBFDFF"))
        palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#EDF4FA"))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor("#142033"))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor("#F8FBFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("#142033"))
        palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#FFFFFF"))
        palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#142033"))
        palette.setColor(QtGui.QPalette.ColorRole.Link, QtGui.QColor("#0077A8"))
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(accent_color if accent_color != "default" else "#0077A8"))
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#FFFFFF"))
        palette.setColor(QtGui.QPalette.ColorRole.Mid, QtGui.QColor("#D6E1EE"))
        palette.setColor(QtGui.QPalette.ColorRole.Midlight, QtGui.QColor("#AFC0D3"))
        palette.setColor(QtGui.QPalette.ColorRole.PlaceholderText, QtGui.QColor("#6B7F99"))
        app.setPalette(palette)

    app.setStyleSheet(qss_content)

    # Set the base widget style exactly once per application. setStyle() is
    # not a no-op when the style is already Fusion: every call constructs a
    # fresh QStyle and re-polishes every widget in the process — a second
    # full-app repolish on top of the one setStyleSheet() above already did.
    # On a populated session (docks + editors + plot windows, thousands of
    # widgets) that redundant pass alone costs ~0.7s of the theme-toggle
    # freeze. The active style never changes after startup, so gate it.
    # (Can't compare app.style().objectName(): with an app stylesheet
    # installed the active style is a QStyleSheetStyle whose name is "".)
    #
    # setStyle() takes ownership and deletes the outgoing style, so the proxy
    # has to be constructed at the call rather than cached and reused; the
    # gate makes that a single instance living as long as the QApplication.
    if not getattr(app, "_esim_base_style_set", False):
        app.setStyle(ComboPopupStyle("Fusion"))
        app._esim_base_style_set = True

    # Re-theming (setStyleSheet + setPalette) does NOT invalidate the cached
    # render of a QGraphicsDropShadowEffect, so every widget that carries one
    # (all motion-installed buttons, toolbars, the project tree, Welcome cards,
    # Verilog panels) can paint blank after a theme switch until a hover forces
    # a repaint. Toggling each effect off/on marks its source dirty.
    #
    # Run it now AND again on the next event-loop tick: per-widget changeEvent
    # handlers (SpiceEditor / ProjectExplorer) re-apply their own stylesheets in
    # response to the QEvent.PaletteChange that this setPalette posts, which can
    # land *after* the synchronous pass and re-stale their effect — the deferred
    # pass mops that up.
    # Synchronous pass now; the deferred pass runs in _thaw (queued at the top),
    # which also lifts the glow freeze once effects have settled.
    #
    # Unless a flip transition is holding the windows painting-frozen: this
    # pass exists to fix what is ON SCREEN, and nothing is reaching the screen
    # right now. _thaw's pass runs before the freeze lifts (it is queued ahead
    # of the transition's settle timer), so the effects are still valid by the
    # time anything is visible -- and skipping this one takes a full walk of
    # every widget in every window off the length of the freeze.
    if not _TRANSITION_ACTIVE:
        _refresh_graphics_effects(app)

    from frontEnd.icon_paths import workspace_icon, timeline_icon, help_icon, dev_docs_icon, settings_icon, home_icon
    for widget in app.topLevelWidgets():
        # Keep every open window's native titlebar in step with the theme
        # (windows shown later are handled by the Show hook in motion.py).
        # A window the transition froze owns its own caption timing instead,
        # and cuts it at the middle of the dissolve: DWM cannot fade, and
        # recoloring it here would light the titlebar up while the client area
        # below is still showing the outgoing theme. Windows the transition
        # passed over (minimized, hidden) are still themed right here.
        if not getattr(widget, "_esim_theme_frozen", False):
            apply_titlebar_theme(widget, is_dark)
        if hasattr(widget, 'home_action'):
            widget.home_action.setIcon(home_icon())
        if hasattr(widget, 'wrkspce'):
            widget.wrkspce.setIcon(workspace_icon())
        if hasattr(widget, 'timeline_action'):
            widget.timeline_action.setIcon(timeline_icon())
        if hasattr(widget, 'helpfile'):
            widget.helpfile.setIcon(help_icon())
        if hasattr(widget, 'devdocs'):
            widget.devdocs.setIcon(dev_docs_icon())
        if hasattr(widget, 'preferences_action'):
            widget.preferences_action.setIcon(settings_icon())
