"""Welcome screen — the empty-state dashboard shown when no project is open.

Built with native Qt widgets (no HTML) so it inherits the active Qt
Style Sheet, plays nicely with High-DPI scaling, and exposes proper
keyboard / focus navigation. Ported from the Aurora design; the tool
tiles dispatch to the real QActions on our MainWindow, so the card
``attr_name`` values must match the attribute names in Application.py.
"""
from PyQt6 import QtCore, QtGui, QtWidgets
import os

try:
    from frontEnd.widgets import GradientLabel
except Exception:  # pragma: no cover
    GradientLabel = None


# Repo root: src/browser/Welcome.py -> ../.. -> repo root, where images/ lives.
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
INIT_PATH = _BASE_DIR + os.sep


# --------------------------------------------------------------------- helpers
def _is_dark_theme() -> bool:
    """True when the dark theme is active.

    Deliberately NOT ``widget.palette().color(Window).lightness() < 128``: once
    the app stylesheet gives a widget a *gradient* background (as
    ``QFrame#welcomeHero`` has), QStyleSheetStyle puts that gradient in the
    widget's Window brush, and ``QBrush.color()`` on a gradient brush is black
    — so the lightness test reported "dark" while the light theme was active.
    That is what kept the hero links on their pale dark-mode colour in light
    mode. theme_utils owns the real answer; the app palette (never rewritten by
    a widget's stylesheet) is the fallback.
    """
    try:
        from frontEnd.theme_utils import current_theme_is_dark
        return current_theme_is_dark()
    except Exception:  # pragma: no cover - theme_utils always present in-app
        app = QtWidgets.QApplication.instance()
        if app is None:
            return False
        return app.palette().color(
            QtGui.QPalette.ColorRole.Window).lightness() < 128


def _rounded_pixmap(path: str, size: int, radius_ratio: float = 0.18) -> QtGui.QPixmap:
    """Load an icon and return it as a rounded pixmap.

    Falls back to a 1x1 transparent pixmap when the source file is
    missing, so a missing asset never crashes the welcome screen.
    """
    raw = QtGui.QPixmap(path)
    if raw.isNull():
        return QtGui.QPixmap(size, size)

    scaled = raw.scaled(
        size, size,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QtGui.QPixmap(size, size)
    canvas.fill(QtCore.Qt.GlobalColor.transparent)

    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    radius = int(size * radius_ratio)
    path_obj = QtGui.QPainterPath()
    path_obj.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path_obj)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return canvas


# --------------------------------------------------------------------- hover mixin
class HoverSurfaceMixin:
    def _init_hover_anim(self):
        self._hover_progress = 0.0
        self._hover_anim = QtCore.QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def getHoverProgress(self):
        return self._hover_progress

    def setHoverProgress(self, value):
        self._hover_progress = float(value)
        self.update()

        # The shadow lives on a backdrop behind the tile now (see
        # Welcome._apply_tile_shadow), so ask elevation where it is instead of
        # assuming it is on this widget -- otherwise the hover glow silently
        # animates nothing.
        try:
            from frontEnd.elevation import backdrop_effect
            eff = backdrop_effect(self)
        except Exception:
            eff = self.graphicsEffect()
        if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
            dark = _is_dark_theme()

            # Base shadow vs Glow shadow
            base_a = 48
            if dark:
                glow_c = QtGui.QColor(83, 215, 255, 160)
            else:
                glow_c = QtGui.QColor(0, 119, 168, 120)

            r = int(0 + (glow_c.red() - 0) * value)
            g = int(0 + (glow_c.green() - 0) * value)
            b = int(0 + (glow_c.blue() - 0) * value)
            a = int(base_a + (glow_c.alpha() - base_a) * value)

            eff.setColor(QtGui.QColor(r, g, b, a))
            eff.setBlurRadius(26 + int(20 * value))
            eff.setOffset(0, 6 - int(6 * value))

    hoverProgress = QtCore.pyqtProperty(float, fget=getHoverProgress, fset=setHoverProgress)

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        if hasattr(super(), 'enterEvent'):
            super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        if hasattr(super(), 'leaveEvent'):
            super().leaveEvent(event)


# --------------------------------------------------------------------- card
class ToolCard(HoverSurfaceMixin, QtWidgets.QFrame):
    # Must track the border-radius of QFrame#welcomeCard in the .qss files --
    # the hover glow and the shadow backdrop are both drawn against it.
    RADIUS = 16

    def __init__(
        self,
        name: str,
        icon_path: str,
        description: str,
        attr_name: str,
        trigger_callback,
    ):
        super().__init__()
        self.attr_name = attr_name
        self.trigger_callback = trigger_callback

        self.setObjectName('welcomeCard')
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        from frontEnd.theme_utils import zoom_px
        self.setMinimumHeight(zoom_px(96))
        self._press_origin = None
        self._press_anim = None
        self._release_anim = None

        self._init_hover_anim()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        icon_label = QtWidgets.QLabel()
        _icon_px = zoom_px(56)
        icon_label.setPixmap(_rounded_pixmap(icon_path, _icon_px, 0.18))
        icon_label.setFixedSize(_icon_px, _icon_px)
        icon_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        icon_label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(icon_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        # Title + description form one optically centred block: the stretches
        # above *and* below keep the pair vertically centred against the 56px
        # icon whatever the description wraps to (one line or two), instead of
        # being pinned to the top of the card as a single trailing stretch did.
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(2)
        text.setContentsMargins(0, 0, 0, 0)
        text.addStretch(1)
        title = QtWidgets.QLabel(name)
        title.setProperty('cssClass', 'welcomeTitle')
        title.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        title.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        desc = QtWidgets.QLabel(description)
        desc.setProperty('cssClass', 'welcomeDesc')
        desc.setWordWrap(True)
        desc.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        # A word-wrapping QLabel reports a height-for-width, but the parent
        # QVBoxLayout only honours it when the policy says so — without this the
        # two-line descriptions clip instead of growing the block.
        desc.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        desc.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text.addWidget(title)
        text.addWidget(desc)
        text.addStretch(1)
        layout.addLayout(text, 1)

        chevron = QtWidgets.QLabel('>')
        chevron.setProperty('cssClass', 'subtle')
        chevron.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(chevron, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hover_progress <= 0:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = QtGui.QColor(83, 215, 255, int(42 * self._hover_progress))
        painter.setBrush(color)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        # Full rect at the *live* zoomed radius, not rect().adjusted(1,1,-1,-1)
        # at a baked 16. build_qss rescales the card's QSS border-radius on
        # every zoom change, so a hardcoded 16 draws a tighter corner than the
        # card itself above 100% -- the card's own background then showed as a
        # white crescent outside the glow (and a 1px hairline down the straight
        # edges, from the inset). Both track the same curve now.
        from frontEnd.theme_utils import zoom_px
        radius = zoom_px(self.RADIUS)
        painter.drawRoundedRect(QtCore.QRectF(self.rect()), radius, radius)

    # ------------------------------------------------------------------ events
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press_origin = self.pos()
            anim = QtCore.QPropertyAnimation(self, b"pos", self)
            anim.setDuration(70)
            anim.setEndValue(self.pos() + QtCore.QPoint(0, 1))
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
            self._press_anim = anim
            anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        fire = False
        if hasattr(self, "_press_origin") and self._press_origin:
            anim = QtCore.QPropertyAnimation(self, b"pos", self)
            anim.setDuration(150)
            anim.setEndValue(self._press_origin)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
            self._release_anim = anim
            anim.start()
            # Fire only if the release lands inside the card (drag-away cancels),
            # and only on left-button release.
            if (event.button() == QtCore.Qt.MouseButton.LeftButton
                    and self.rect().contains(event.position().toPoint())):
                fire = True
        super().mouseReleaseEvent(event)
        if fire:
            self.trigger_callback(self.attr_name)

    def keyPressEvent(self, event):
        if event.key() in (
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Space,
        ):
            self.trigger_callback(self.attr_name)
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------- hero
class HeroBanner(QtWidgets.QFrame):
    """A wide, gradient hero panel used at the top of the welcome page."""

    # Must track the border-radius of QFrame#welcomeHero in the .qss files,
    # otherwise the orb overlay paints square corners over the rounded panel.
    RADIUS = 18

    def __init__(self):
        super().__init__()
        self.setObjectName('welcomeHero')
        from frontEnd.theme_utils import zoom_px
        self.setMinimumHeight(zoom_px(160))

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        # eSim logo (if available), otherwise a soft monogram
        logo_label = QtWidgets.QLabel()
        logo_path = os.path.join(_BASE_DIR, 'images', 'logo.png')
        _logo_px = zoom_px(64)
        if os.path.exists(logo_path):
            logo_pix = QtGui.QPixmap(logo_path).scaled(
                _logo_px, _logo_px,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(logo_pix)
        logo_label.setFixedSize(_logo_px, _logo_px)
        layout.addWidget(logo_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        # Title + subtitle
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(6)
        # Formal solid-colour heading (no gradient text) — colour comes from
        # the #welcomeHeroTitle QSS rule so it stays theme-correct.
        title = QtWidgets.QLabel('Welcome to eSim')
        title.setObjectName('welcomeHeroTitle')
        subtitle = QtWidgets.QLabel(
            'Open-source EDA for circuit design, simulation, and PCB layout.'
        )
        subtitle.setObjectName('welcomeHeroSubtitle')
        subtitle.setWordWrap(True)

        about_label = QtWidgets.QLabel()
        about_label.setWordWrap(True)
        about_label.setOpenExternalLinks(True)
        about_label.setContentsMargins(0, 8, 0, 0)
        about_label.setProperty("cssClass", "muted")
        self.about_label = about_label
        self._apply_about_text()

        text.addWidget(title)
        text.addWidget(subtitle)
        text.addWidget(about_label)
        text.addStretch(1)
        layout.addLayout(text, 1)

    # ------------------------------------------------------------------ about
    # {link} is filled per theme by _apply_about_text(). The colour is inlined
    # on every <a> instead of left to QPalette.Link because the app stylesheet
    # is what actually paints this label, and the palette link colour that
    # reaches it in light mode renders far too pale to read against the near-
    # white hero gradient.
    ABOUT_HTML = (
        "It is an integrated tool built using open source softwares such as "
        "<a style='color:{link};' href='https://www.kicad.org/'>KiCad</a>, "
        "<a style='color:{link};' href='https://ngspice.sourceforge.io/'>Ngspice</a>, "
        "<a style='color:{link};' href='http://ghdl.free.fr'>GHDL</a>, "
        "<a style='color:{link};' href='https://www.veripool.org/verilator/'>Verilator</a>, "
        "<a style='color:{link};' href='https://www.makerchip.com/'>Makerchip IDE</a>, and "
        "<a style='color:{link};' href='https://skywater-pdk.rtfd.io/'>SkyWater SKY130 PDK</a>. "
        "eSim source is released under GNU General Public License.<br><br>"
        "Developed by the eSim Team at FOSSEE, IIT Bombay. "
        "Visit: <a style='color:{link};' href='https://esim.fossee.in/'>esim.fossee.in</a> | "
        "Source: <a style='color:{link};' href='https://github.com/FOSSEE/eSim'>github.com/FOSSEE/eSim</a>"
    )

    # Light: 7.3:1 against the white hero, comfortably past WCAG AA.
    # Dark: the theme's own accent, which already reads well on #050812.
    LINK_LIGHT = "#005B80"
    LINK_DARK = "#53D7FF"

    def _apply_about_text(self):
        link = self.LINK_DARK if _is_dark_theme() else self.LINK_LIGHT
        self.about_label.setText(self.ABOUT_HTML.format(link=link))

    def changeEvent(self, event):
        """Re-colour the about-text links on a live light/dark toggle.

        The colour is baked into the HTML at build time, so without this the
        links keep the previous theme's colour after a toggle.
        """
        super().changeEvent(event)
        # Deferred by a tick: rebuilding the rich text inside the handler
        # re-enters the polish that delivered the event (theme_utils.defer_restyle).
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            try:
                from frontEnd.theme_utils import defer_restyle
                defer_restyle(self, self._apply_about_text)
            except Exception:  # pragma: no cover - theme_utils always present in-app
                self._apply_about_text()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # The orb is deliberately theme-independent. It reads as a soft cyan
        # glow over whichever hero gradient the stylesheet painted, and this is
        # the pair the hero has always shown on both themes: the old
        # palette-lightness test here could only ever answer "dark", because
        # QFrame#welcomeHero's Window brush is a gradient (see _is_dark_theme).
        # Only the about-text links below are theme-aware.
        accent = QtGui.QColor("#53D7FF")
        violet = QtGui.QColor("#9B7CFF")
        orb = QtGui.QRadialGradient(QtCore.QPointF(rect.right() - 40, rect.top() + 30), max(rect.width(), rect.height()) * 0.65)
        accent.setAlpha(64)
        violet.setAlpha(54)
        orb.setColorAt(0.0, accent)
        orb.setColorAt(0.45, violet)
        orb.setColorAt(1.0, QtCore.Qt.GlobalColor.transparent)
        clip = QtGui.QPainterPath()
        # Zoomed radius, same reason as ToolCard.paintEvent: the QSS corner
        # this clip has to sit inside is rescaled on every zoom change, so a
        # baked 18 clipped the orb short of the curve and left the panel's own
        # background showing in the corners.
        from frontEnd.theme_utils import zoom_px
        _r = zoom_px(self.RADIUS)
        clip.addRoundedRect(QtCore.QRectF(rect), _r, _r)
        painter.setClipPath(clip)
        painter.fillRect(rect, orb)
        painter.end()
        super().paintEvent(event)


# --------------------------------------------------------------------- section
class SectionHeader(QtWidgets.QLabel):
    """Small uppercase section header used between welcome cards."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setProperty('cssClass', 'caps')
        self.setContentsMargins(4, 8, 0, 4)


# --------------------------------------------------------------------- page
class Welcome(QtWidgets.QWidget):
    """The Welcome screen that fills the dock area on first launch."""

    def __init__(self):
        super().__init__()

        # Outer container that scrolls so smaller docks still work
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area in case the dock is short
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setObjectName('welcomeScroll')
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll, 1)

        # Inner widget with generous padding so drop shadows don't clip
        inner = QtWidgets.QWidget()
        scroll.setWidget(inner)
        inner_layout = QtWidgets.QVBoxLayout(inner)
        inner_layout.setContentsMargins(28, 22, 28, 24)
        inner_layout.setSpacing(8)

        # ---- Hero ----
        hero = HeroBanner()
        self._apply_tile_shadow(hero, blur=38, y=10, alpha=68,
                                radius=HeroBanner.RADIUS)
        inner_layout.addWidget(hero)
        inner_layout.addSpacing(6)

        # ---- Quick-start actions ----
        inner_layout.addWidget(SectionHeader('Quick start'))
        quick = QtWidgets.QGridLayout()
        quick.setSpacing(12)
        quick.setContentsMargins(4, 0, 4, 0)

        # attr names must match the QAction attributes on our MainWindow
        # (Application.py): new/open project are ``newproj`` / ``openproj``.
        quick_actions = [
            ('New project', 'newProject.png', 'Create a new eSim project', 'newproj'),
            ('Open project', 'openProject.png', 'Open an existing project', 'openproj'),
        ]
        for n, (name, icon, desc, attr) in enumerate(quick_actions):
            card = ToolCard(
                name,
                os.path.join(_BASE_DIR, 'images', icon),
                desc,
                attr,
                self.trigger_action,
            )
            self._apply_tile_shadow(card, blur=26, y=6, alpha=48,
                                    radius=ToolCard.RADIUS)
            quick.addWidget(card, 0, n)
            quick.setColumnStretch(n, 1)
        inner_layout.addLayout(quick)

        # ---- Tools grid ----
        inner_layout.addWidget(SectionHeader('Tools'))
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(12)
        grid.setContentsMargins(4, 0, 4, 0)

        # Tiles follow the rail's pipeline order: Design -> Simulate -> Model
        # -> Convert. NGHDL lives as the VHDL path inside Makerchip; its tile
        # uses the dedicated ``nghdl`` action that jumps straight to that stage.
        tools = [
            ('Open Schematic', 'kicad.png', 'Design your circuit in KiCad', 'kicad'),
            ('Convert to Ngspice', 'ki-ng.png', 'Generate Ngspice netlist', 'conversion'),
            ('Simulate', 'ngspice.png', 'Run circuit simulation', 'ngspice'),
            ('Model Editor', 'model.png', 'Create or edit SPICE models', 'model'),
            ('Subcircuit', 'subckt.png', 'Build reusable subcircuits', 'subcircuit'),
            ('Makerchip', 'makerchip.png', 'Verilog via Makerchip', 'makerchip'),
            ('NGHDL', 'nghdl.png', 'Add VHDL digital models', 'nghdl'),
            ('Modelica', 'omedit.png', 'Convert to Modelica format', 'omedit'),
            ('OM Optimisation', 'omoptim.png', 'Open OpenModelica optimiser', 'omoptim'),
            ('Schematic Converter', 'icon.png', 'Import PSpice / LTspice files', 'conToeSim'),
        ]

        cols = 3
        for i, (name, icon_file, desc, attr) in enumerate(tools):
            row = i // cols
            col = i % cols
            card = ToolCard(
                name,
                os.path.join(_BASE_DIR, 'images', icon_file),
                desc,
                attr,
                self.trigger_action,
            )
            self._apply_tile_shadow(card, blur=26, y=6, alpha=48,
                                    radius=ToolCard.RADIUS)
            grid.addWidget(card, row, col)
            grid.setColumnStretch(col, 1)

        inner_layout.addLayout(grid)

        inner_layout.addStretch(1)

    @staticmethod
    def _apply_tile_shadow(widget, blur=28, y=6, alpha=64, radius=16):
        """Apply a soft drop shadow so the tile floats above the base layer.

        The shadow goes on an empty backdrop behind the tile rather than on the
        tile itself. Every card here carries a name and a one-line description,
        and a QGraphicsEffect renders its source into an offscreen ARGB pixmap
        — a buffer Qt cannot run subpixel antialiasing against, so all of that
        text quietly dropped to grayscale AA and read as soft on a 1x panel.

        ``radius`` must match the corner the widget itself paints -- 16 for the
        cards' QSS border-radius, 18 for the hero -- or the backdrop's own
        corners show past the curve.
        """
        try:
            from frontEnd.elevation import elevate_backdrop
            # Tiles are shadowed before they are added to their grid, so this
            # usually defers until the card has a parent to hang a backdrop
            # beside. Either way it is the only shadow the tile gets.
            elevate_backdrop(widget, radius=radius, tint=QtGui.QColor(0, 0, 0),
                             spec=(blur, 0, y, alpha, alpha))
            return
        except Exception:
            pass
        eff = QtWidgets.QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(blur)
        eff.setOffset(0, y)
        eff.setColor(QtGui.QColor(0, 0, 0, alpha))
        widget.setGraphicsEffect(eff)

    # ------------------------------------------------------------------ dispatch
    def trigger_action(self, attr_name):
        """Resolve `attr_name` against the top-level MainWindow and trigger it."""
        app = self.window()
        if not app:
            return
        target = getattr(app, attr_name, None)
        if target is None:
            return
        if hasattr(target, 'trigger'):
            target.trigger()
        elif callable(target):
            target()
