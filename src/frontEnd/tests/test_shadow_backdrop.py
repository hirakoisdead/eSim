"""Drop shadows must not sit on widgets that display text.

Qt renders a QGraphicsEffect's source into an offscreen ARGB pixmap, and it
cannot run subpixel antialiasing (ClearType) against a translucent buffer -- so
every glyph inside an elevated widget silently drops to grayscale AA. That is
the "fonts look subtly low-res" report: it reproduced on a 1080p panel at 100%
scaling and not on a 175% one, because at 1.75x there are enough device pixels
to hide it.

``elevate_backdrop`` moves the effect onto an empty sibling behind the widget.
These pin that the effect really does end up off the widget, that the backdrop
stays glued to it, and that the deferred path works for the very common
"shadow the card, then add it to the layout" ordering.
"""
import os
import sys

import pytest

from PyQt6 import QtCore, QtGui, QtWidgets

_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)

from frontEnd import elevation                  # noqa: E402


@pytest.fixture
def host(qapp):
    """A parent with one child laid out inside it."""
    parent = QtWidgets.QWidget()
    parent.resize(400, 300)
    layout = QtWidgets.QVBoxLayout(parent)
    child = QtWidgets.QLabel("Module Hierarchy")
    layout.addWidget(child)
    parent.show()
    QtWidgets.QApplication.processEvents()
    yield parent, child
    parent.deleteLater()
    QtWidgets.QApplication.processEvents()


class TestTheEffectLeavesTheWidget:
    def test_the_widget_itself_carries_no_effect(self, host):
        _parent, child = host
        elevation.elevate_backdrop(child, "e2")
        assert child.graphicsEffect() is None

    def test_the_shadow_exists_on_a_sibling(self, host):
        parent, child = host
        eff = elevation.elevate_backdrop(child, "e2")
        assert isinstance(eff, QtWidgets.QGraphicsDropShadowEffect)
        backdrop = child._esim_shadow_backdrop
        assert backdrop.parentWidget() is parent
        assert backdrop is not child
        assert backdrop.graphicsEffect() is eff

    def test_it_replaces_an_effect_that_was_already_on_the_widget(self, host):
        """Upgrading a surface that used elevate() must not leave the old
        effect behind -- two shadows, and the text still loses ClearType."""
        _parent, child = host
        elevation.elevate(child, "e2")
        assert child.graphicsEffect() is not None
        elevation.elevate_backdrop(child, "e2")
        assert child.graphicsEffect() is None

    def test_the_backdrop_never_eats_clicks(self, host):
        _parent, child = host
        elevation.elevate_backdrop(child, "e2")
        assert child._esim_shadow_backdrop.testAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def test_calling_it_twice_does_not_stack_backdrops(self, host):
        parent, child = host
        elevation.elevate_backdrop(child, "e2")
        first = child._esim_shadow_backdrop
        elevation.elevate_backdrop(child, "e3")
        assert child._esim_shadow_backdrop is first
        assert len([w for w in parent.children()
                    if isinstance(w, elevation._ShadowBackdrop)]) == 1


class TestItStaysGluedToItsSource:
    def test_geometry_follows_a_resize(self, host):
        _parent, child = host
        elevation.elevate_backdrop(child, "e2")
        child.setFixedSize(123, 45)
        QtWidgets.QApplication.processEvents()
        assert child._esim_shadow_backdrop.geometry() == child.geometry()

    def test_visibility_follows_a_hide(self, host):
        _parent, child = host
        elevation.elevate_backdrop(child, "e2")
        child.hide()
        QtWidgets.QApplication.processEvents()
        assert not child._esim_shadow_backdrop.isVisible()

    def test_it_sits_behind_its_source_not_at_the_bottom(self, host):
        """stackUnder, not lower(): at the bottom of the parent the shadow
        spill would be painted over by whatever else lives there."""
        parent, child = host
        other = QtWidgets.QWidget(parent)
        other.lower()
        elevation.elevate_backdrop(child, "e2")
        order = parent.children()
        backdrop = child._esim_shadow_backdrop
        assert order.index(backdrop) < order.index(child)
        assert order.index(backdrop) > order.index(other)


class TestTheDeferredPath:
    def test_a_parentless_widget_waits_instead_of_falling_back(self, qapp):
        """``card = Card(); shadow(card); layout.addWidget(card)`` is the
        common ordering. Putting the effect on the card because the parent has
        not arrived yet would defeat the whole point."""
        card = QtWidgets.QLabel("New project")
        assert elevation.elevate_backdrop(card, "e2") is None
        assert card.graphicsEffect() is None

        parent = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(parent).addWidget(card)
        QtWidgets.QApplication.processEvents()

        assert card.graphicsEffect() is None
        assert isinstance(card._esim_shadow_backdrop.graphicsEffect(),
                          QtWidgets.QGraphicsDropShadowEffect)
        parent.deleteLater()


class TestFindingTheEffectAgain:
    def test_backdrop_effect_finds_a_moved_shadow(self, host):
        """Hover animations look the shadow up by widget; they must not go
        quiet just because it now lives on a sibling."""
        _parent, child = host
        eff = elevation.elevate_backdrop(child, "e2")
        assert elevation.backdrop_effect(child) is eff

    def test_backdrop_effect_still_finds_an_on_widget_shadow(self, host):
        _parent, child = host
        eff = elevation.elevate(child, "e2")
        assert elevation.backdrop_effect(child) is eff

    def test_backdrop_effect_returns_none_when_there_is_no_shadow(self, host):
        _parent, child = host
        assert elevation.backdrop_effect(child) is None


class TestItPaintsTheSameShapeAsItsSource:
    """A backdrop is an opaque rectangle sitting directly behind a panel.

    Two ways that shows through when it does not match the panel exactly:
    square corners poking out past a rounded one, and -- because a stylesheet
    background can be translucent -- its fill colour tinting the whole panel.
    """

    def _fill_visible(self, source_colour="#FF0000"):
        parent = QtWidgets.QWidget()
        parent.setAutoFillBackground(True)
        pal = parent.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#F3F7FC"))
        parent.setPalette(pal)
        parent.resize(300, 200)

        panel = QtWidgets.QWidget(parent)
        panel.setGeometry(40, 40, 200, 100)
        pal = panel.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window,
                     QtGui.QColor(source_colour))
        panel.setPalette(pal)
        return parent, panel

    @staticmethod
    def _render_backdrop(backdrop):
        """The backdrop's own paint output over a known, untouched ground.

        Rendered rather than screen-grabbed because the backdrop tracks its
        source's visibility -- hiding the panel to look behind it hides the
        backdrop too.
        """
        # The drop shadow is a QGraphicsEffect, and rendering through one
        # redirects the widget into the effect's own offscreen pixmap -- the
        # target image comes back untouched. Drop it: the shape is what is
        # under test, and the blur has its own coverage above.
        backdrop.setGraphicsEffect(None)
        img = QtGui.QImage(backdrop.size(),
                           QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtGui.QColor("#00FF00"))          # anything it does not paint
        backdrop.render(img)
        return img

    def test_a_rounded_source_gets_a_rounded_backdrop(self, qapp):
        parent, panel = self._fill_visible()
        elevation.elevate_backdrop(panel, "e2", radius=14)
        QtWidgets.QApplication.processEvents()
        img = self._render_backdrop(panel._esim_shadow_backdrop)
        assert img.pixelColor(100, 50).name() == "#ff0000", "body not filled"
        # Anything but the fill colour: the corner pixel is left to whatever
        # was under the widget, which is the point.
        assert img.pixelColor(0, 0).name() != "#ff0000", (
            "square backdrop corner is sticking out past the rounded panel")
        parent.deleteLater()

    def test_radius_zero_still_paints_square(self, qapp):
        parent, panel = self._fill_visible()
        elevation.elevate_backdrop(panel, "e2", radius=0)
        QtWidgets.QApplication.processEvents()
        img = self._render_backdrop(panel._esim_shadow_backdrop)
        assert img.pixelColor(0, 0).name() == "#ff0000"
        parent.deleteLater()

    def test_the_radius_tracks_the_zoom_the_sheet_uses(self, qapp,
                                                       monkeypatch):
        """QSS border-radius rides the zoom curve, so the backdrop must too."""
        from frontEnd import theme_utils
        parent, panel = self._fill_visible()
        elevation.elevate_backdrop(panel, "e2", radius=14)
        backdrop = panel._esim_shadow_backdrop
        for zoom in (60, 100, 150):
            monkeypatch.setattr(theme_utils, "_CURRENT_ZOOM", zoom)
            assert backdrop._scaled_radius() == theme_utils.zoom_px(14)
        parent.deleteLater()

    def test_a_gradient_source_does_not_tint_the_panel_black(self, qapp):
        """``QBrush.color()`` on a gradient brush is black.

        The welcome hero's stylesheet background is a gradient AND only 96%
        opaque, so copying that "colour" put a black rectangle behind it and
        4% of it came through across the whole panel as a grey veil.
        """
        parent = QtWidgets.QWidget()
        parent.setAutoFillBackground(True)
        pal = parent.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#F3F7FC"))
        parent.setPalette(pal)
        parent.resize(300, 200)

        panel = QtWidgets.QWidget(parent)
        panel.setGeometry(40, 40, 200, 100)
        gradient = QtGui.QLinearGradient(0, 0, 1, 1)
        gradient.setColorAt(0.0, QtGui.QColor("#FFFFFF"))
        gradient.setColorAt(1.0, QtGui.QColor("#F8FBFF"))
        pal = panel.palette()
        pal.setBrush(QtGui.QPalette.ColorRole.Window, QtGui.QBrush(gradient))
        panel.setPalette(pal)

        elevation.elevate_backdrop(panel, "e2", radius=18)
        backdrop = panel._esim_shadow_backdrop
        assert backdrop._fill_colour().name() != "#000000"
        assert backdrop._fill_colour().name() == "#f3f7fc"
        parent.deleteLater()


class TestSurfacesThatMustNotRegress:
    """The specific always-visible surfaces the sharpness fix was for."""

    def test_the_project_tree_keeps_its_text_sharp(self, qapp, monkeypatch):
        parent = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(parent)
        tree = QtWidgets.QTreeWidget()
        layout.addWidget(tree)
        elevation.elevate_backdrop(tree, "e2", radius=14)
        assert tree.graphicsEffect() is None
        # 14 == the sheets' QTreeWidget border-radius; a square backdrop shows
        # four white tabs at the corners of the project panel.
        assert tree._esim_shadow_backdrop._radius == 14
        parent.deleteLater()

    def test_a_toolbar_keeps_its_text_sharp(self, qapp):
        from frontEnd import motion
        window = QtWidgets.QMainWindow()
        bar = QtWidgets.QToolBar("topToolbar", window)
        bar.setObjectName("topToolbar")
        window.addToolBar(bar)
        bar.addWidget(QtWidgets.QLabel(" 90% "))
        motion.apply_toolbar_depth(window)
        assert bar.graphicsEffect() is None
        assert isinstance(bar._esim_shadow_backdrop.graphicsEffect(),
                          QtWidgets.QGraphicsDropShadowEffect)
        window.deleteLater()
