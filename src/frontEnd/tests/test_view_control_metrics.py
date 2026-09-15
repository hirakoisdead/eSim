"""The zoom pill and theme toggle must track the toolbar's zoom.

build_qss() scales the px metrics *inside* the stylesheet, but sizes set from
Python are invisible to it. The zoom pill used to be pinned at
setMinimumWidth(132) and the theme toggle at a QSS min-width/min-height of
32px, so zooming out shrank the "60%" text while the box around it stayed put,
and the toggle never matched the file / workspace icon buttons at any zoom.
"""
import os
import sys

import pytest

from PyQt6 import QtCore, QtGui, QtWidgets

# Application.py does a bare ``import pathmagic``, so its own directory has to
# be importable -- the launcher gets this for free by chdir'ing into frontEnd.
_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)


class _StubToolbar:
    """Stands in for a QToolBar: records the icon size, has no home button."""

    def __init__(self):
        self.icon_size = QtCore.QSize(28, 28)

    def setIconSize(self, size):
        self.icon_size = size

    def widgetForAction(self, action):
        return None


class _Stub:
    """Minimum surface _apply_view_control_metrics() touches, so the test
    doesn't have to build the whole Application window."""

    def __init__(self):
        self.topToolbar = _StubToolbar()
        self.lefttoolbar = _StubToolbar()
        self.zoom_container = QtWidgets.QWidget()
        self.zoom_layout = QtWidgets.QHBoxLayout(self.zoom_container)
        self.zoom_label = QtWidgets.QLabel()
        self.theme_toggle_btn = QtWidgets.QToolButton()
        # Same aspect ratio as the real fosseeLogo.png (632x233).
        self.logo = QtWidgets.QLabel()
        self._logo_src = QtGui.QPixmap(632, 233)
        self._logo_src.fill(QtGui.QColor("red"))


def _logo_height(stub):
    """Displayed (device-independent) height of the rendered logo."""
    pix = stub.logo.pixmap()
    return round(pix.height() / pix.devicePixelRatio())


def _metrics(stub, zoom):
    from frontEnd.Application import Application
    Application._apply_view_control_metrics(stub, zoom)


@pytest.fixture
def stub(qapp):
    return _Stub()


@pytest.mark.parametrize("zoom", [50, 60, 100, 200, 300])
def test_pill_and_toggle_scale_with_zoom(stub, zoom):
    _metrics(stub, zoom)
    scale = zoom / 100.0

    assert stub.zoom_container.minimumWidth() == round(132 * scale)
    assert stub.zoom_label.minimumWidth() == round(50 * scale)
    assert stub.topToolbar.icon_size.width() == round(28 * scale)
    assert stub.lefttoolbar.icon_size.width() == round(40 * scale)


def test_toggle_is_square_and_pill_height_matches_it(stub):
    _metrics(stub, 100)
    box = stub.theme_toggle_btn.height()
    assert stub.theme_toggle_btn.width() == box
    # The two view controls read as a matched pair with the icon buttons.
    assert stub.zoom_container.height() == box
    # The toggle carries a real icon, sized like a toolbar icon.
    assert stub.theme_toggle_btn.iconSize().width() == 28


def test_zooming_out_then_in_restores_the_original_box(stub):
    _metrics(stub, 100)
    before = (stub.zoom_container.minimumWidth(),
              stub.theme_toggle_btn.width())
    _metrics(stub, 60)
    assert stub.zoom_container.minimumWidth() < before[0]
    assert stub.theme_toggle_btn.width() < before[1]
    _metrics(stub, 100)
    assert (stub.zoom_container.minimumWidth(),
            stub.theme_toggle_btn.width()) == before


@pytest.mark.parametrize("zoom", [50, 60, 100, 200, 300])
def test_brand_logo_is_one_icon_button_tall(stub, zoom):
    """The logo was the toolbar's height floor: frozen at a scaled(150, 150)
    box, it held the bar at ~63px when 50%-zoom buttons only needed ~34px, and
    was dwarfed by 130px buttons at 300%. It now tracks the same box as the
    zoom pill and the theme toggle, so the whole bar shrinks and grows as one.
    """
    _metrics(stub, zoom)
    assert _logo_height(stub) == stub.theme_toggle_btn.height()
    assert stub.logo.pixmap().height() > 0


def test_brand_logo_keeps_its_aspect_ratio(stub):
    _metrics(stub, 100)
    pix = stub.logo.pixmap()
    assert pix.width() / pix.height() == pytest.approx(632 / 233, rel=0.02)


def test_brand_logo_shrinks_and_grows_with_zoom(stub):
    _metrics(stub, 50)
    small = _logo_height(stub)
    _metrics(stub, 100)
    mid = _logo_height(stub)
    _metrics(stub, 300)
    big = _logo_height(stub)
    assert small < mid < big
    # The old hard-coded 150x150-box scale rendered 55px tall at every level.
    assert 55 not in (small, big)


def test_metrics_survive_a_missing_logo(stub):
    """A null/absent pixmap must not take the rest of the toolbar down."""
    stub._logo_src = QtGui.QPixmap()
    _metrics(stub, 100)
    assert stub.theme_toggle_btn.height() > 0
    del stub._logo_src
    _metrics(stub, 100)
    assert stub.theme_toggle_btn.height() > 0


def test_theme_toggle_icon_renders_non_empty(qapp):
    from frontEnd.icon_paths import theme_toggle_icon
    icon = theme_toggle_icon()
    assert not icon.isNull()
    # Rasterised well above the 24px viewBox so 300% zoom stays crisp.
    pixmap = icon.pixmap(QtCore.QSize(256, 256))
    assert pixmap.width() >= 256
    assert not pixmap.toImage().allGray()  # actually painted something
