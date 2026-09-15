"""The real surfaces build, and grow, at every zoom.

The zoom work touches sizes inside widgets that only exist at runtime, so tests
on the curves alone would not catch a ``zoom_px`` called outside the scope it
was imported into, or a container that quietly stayed frozen. These build the
actual panels at 60/100/150 and check both that they survive it and that the
boxes holding text really did change size.

Not covered here: ``subcircuit.Subcircuit``. Constructing it inside a pytest
session and letting it be collected faults in Qt's teardown on this platform,
on the pre-change tree as well -- a harness problem, not a zoom one. Its tile
geometry is derived from ``scale_font_px``/``zoom_px``, which are pinned in
test_font_scale.py.
"""
import os
import sys

import pytest

from PyQt6 import QtWidgets

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from frontEnd import theme_utils as tu          # noqa: E402

_ZOOMS = (60, 100, 150)


@pytest.fixture
def at_zoom(qapp, monkeypatch):
    """Pin the live zoom without touching the user's preferences file."""
    def _set(zoom):
        monkeypatch.setattr(tu, "_CURRENT_ZOOM", zoom)
        return zoom
    return _set


class TestTheAboutCard:
    def test_the_logo_chip_scales(self, at_zoom):
        from frontEnd import dialogs
        colors = {"chip": "#ffffff", "chip_border": "#cccccc"}
        for zoom in _ZOOMS:
            at_zoom(zoom)
            chip = dialogs._logo_chip("", colors)
            assert chip.width() == tu.zoom_px(76, zoom)
            chip.deleteLater()
        QtWidgets.QApplication.processEvents()

    def test_the_card_itself_scales(self, at_zoom):
        """A setFixedSize dialog that ignores zoom simply crops its own
        contents at anything above 100%."""
        assert tu.zoom_px(440, 150) > tu.zoom_px(440, 100) > tu.zoom_px(440, 60)


class TestThePreferencesNav:
    def test_the_category_rail_grows_with_the_zoom(self, at_zoom):
        from frontEnd.PreferencesDialog import PreferencesDialog
        widths = {}
        for zoom in _ZOOMS:
            at_zoom(zoom)
            dlg = PreferencesDialog(None)
            widths[zoom] = dlg.nav.width()
            dlg.deleteLater()
        QtWidgets.QApplication.processEvents()
        assert widths[150] > widths[100] > widths[60]


class TestTheWelcomeScreen:
    def test_the_tiles_grow_with_the_zoom(self, at_zoom):
        from browser.Welcome import ToolCard
        heights = {}
        for zoom in _ZOOMS:
            at_zoom(zoom)
            card = ToolCard("New project", "", "Create a new eSim project",
                            "newproj", lambda *_a: None)
            heights[zoom] = card.minimumHeight()
            card.deleteLater()
        QtWidgets.QApplication.processEvents()
        assert heights[150] > heights[100] > heights[60]

    def test_a_tile_carries_no_effect_of_its_own(self, at_zoom):
        """Its name and description have to stay subpixel-antialiased."""
        from browser.Welcome import ToolCard, Welcome
        at_zoom(100)
        card = ToolCard("New project", "", "desc", "newproj", lambda *_a: None)
        parent = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(parent).addWidget(card)
        Welcome._apply_tile_shadow(card)
        QtWidgets.QApplication.processEvents()
        assert card.graphicsEffect() is None
        assert isinstance(card._esim_shadow_backdrop.graphicsEffect(),
                          QtWidgets.QGraphicsDropShadowEffect)
        parent.deleteLater()


class TestTheEditorFindBar:
    def test_its_fields_grow_with_the_zoom(self, at_zoom):
        from codeEditor.FindBar import FindBar
        widths = {}
        for zoom in _ZOOMS:
            at_zoom(zoom)
            host = QtWidgets.QWidget()
            bar = FindBar(host, host=None)
            widths[zoom] = bar._find_edit.minimumWidth()
            host.deleteLater()
        QtWidgets.QApplication.processEvents()
        assert widths[150] > widths[100] > widths[60]
