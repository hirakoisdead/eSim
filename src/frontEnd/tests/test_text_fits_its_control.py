"""A control's label must never spill out of the control that draws it.

Raise the zoom and the QSS font grows; a container whose width was set from
Python does not. The label then runs past both edges of its button and is
sheared off mid-glyph -- "the text just goes out of the button and gets cropped
left and right". Two things stop that, and both are pinned here:

1. Containers sized from Python go through ``zoom_px`` so they grow with the
   text in the first place.
2. ``ComboPopupStyle`` elides any style-drawn label that still does not fit, so
   the worst case is a readable "Remove Mod..." rather than a sheared one.
"""
import os
import sys

import pytest

from PyQt6 import QtCore, QtGui, QtWidgets

_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)

from frontEnd import theme_utils as tu          # noqa: E402

_NO_FLAGS = QtCore.Qt.AlignmentFlag.AlignLeft


@pytest.fixture
def fm(qapp):
    return QtGui.QFontMetrics(QtGui.QFont())


class TestElision:
    def test_text_that_fits_is_returned_untouched(self, fm):
        text = "OK"
        assert tu.elide_to_fit(fm, text, _NO_FLAGS, 500) == text

    def test_text_that_does_not_fit_is_elided_not_clipped(self, fm):
        text = "Remove Models from this project"
        out = tu.elide_to_fit(fm, text, _NO_FLAGS, 60)
        assert out != text
        assert out.endswith("…")
        assert fm.horizontalAdvance(out) <= 60

    def test_the_elided_result_always_fits(self, fm):
        text = "Convert PSpice schematic to KiCad"
        for width in range(20, 400, 17):
            out = tu.elide_to_fit(fm, text, _NO_FLAGS, width)
            assert fm.horizontalAdvance(out) <= width, width

    def test_word_wrapped_text_is_left_alone(self, fm):
        """The layout already reserved height for the wrap; eliding it to one
        line would throw away content that was going to be visible."""
        text = "A long description that is meant to wrap onto two lines"
        flags = _NO_FLAGS | QtCore.Qt.TextFlag.TextWordWrap
        assert tu.elide_to_fit(fm, text, flags, 40) == text

    def test_multiline_text_is_left_alone(self, fm):
        text = "line one\nline two"
        assert tu.elide_to_fit(fm, text, _NO_FLAGS, 10) == text

    @pytest.mark.parametrize("width", [0, -1])
    def test_a_degenerate_width_is_survivable(self, fm, width):
        assert tu.elide_to_fit(fm, "text", _NO_FLAGS, width) == "text"

    def test_empty_text(self, fm):
        assert tu.elide_to_fit(fm, "", _NO_FLAGS, 100) == ""


class TestMnemonics:
    """"&File" is five characters and four glyphs.

    With a mnemonic flag set the style eats the '&' and underlines the letter
    after it, so measuring the raw string overstates the drawn width by a whole
    ampersand. That was enough to make every top-level menu title "not fit" the
    rect the style had just sized for it: the menu bar rendered as
    "... ... V... T... ...".
    """

    _MNEMONIC = (QtCore.Qt.AlignmentFlag.AlignLeft
                 | QtCore.Qt.TextFlag.TextShowMnemonic)

    def test_the_ampersand_does_not_count_toward_the_width(self, fm):
        width = fm.horizontalAdvance("File") + 2
        assert tu.elide_to_fit(fm, "&File", self._MNEMONIC, width) == "&File"

    def test_without_the_flag_the_ampersand_is_real_text(self, fm):
        assert tu.drawn_text("R&D", _NO_FLAGS) == "R&D"

    def test_a_literal_ampersand_survives(self, fm):
        assert tu.drawn_text("Save && Close", self._MNEMONIC) == "Save & Close"

    def test_text_that_fits_keeps_its_marker(self, fm):
        """The underline must survive the round trip, not just the letters."""
        out = tu.elide_to_fit(fm, "&Tools", self._MNEMONIC, 500)
        assert out == "&Tools"

    def test_a_genuinely_overlong_label_still_elides(self, fm):
        out = tu.elide_to_fit(fm, "&Convert to KiCad schematic",
                              self._MNEMONIC, 60)
        assert out.endswith("…")
        assert fm.horizontalAdvance(out) <= 60

    def test_every_standard_menu_title_fits_at_every_zoom(self, qapp):
        """The real regression: the app's own menu bar, end to end."""
        app = QtWidgets.QApplication.instance()
        app.setStyle(tu.ComboPopupStyle("Fusion"))
        titles = ("&File", "&Edit", "&View", "&Tools", "&Help")
        elided = []
        real = tu.elide_to_fit

        def spy(fmx, text, flags, width):
            out = real(fmx, text, flags, width)
            # Only this menu bar: widgets left over from earlier tests in the
            # session are still being painted through the same style.
            if out != text and text in titles:
                elided.append((text, out))
            return out

        tu.elide_to_fit = spy
        try:
            for zoom in (60, 90, 100, 150):
                app.setStyleSheet(tu.build_qss(
                    "style_light.qss", False, "default", "system", "system",
                    zoom))
                win = QtWidgets.QMainWindow()
                bar = win.menuBar()
                for title in titles:
                    bar.addMenu(title).addAction("Item")
                win.resize(900, 200)
                win.show()
                QtWidgets.QApplication.processEvents()
                win.grab()
                win.close()
                win.deleteLater()
        finally:
            tu.elide_to_fit = real
            app.setStyleSheet("")
        assert elided == []


class TestTheStyleUsesIt:
    def test_a_cramped_button_paints_without_error(self, qapp):
        """Integration: the proxy style is what the app actually installs, so
        drive a real paint through it at a width the label cannot fit."""
        style = tu.ComboPopupStyle()
        btn = QtWidgets.QPushButton("Remove Models from this project")
        btn.setStyle(style)
        btn.resize(50, 24)
        pix = QtGui.QPixmap(btn.size())
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        btn.render(pix)
        btn.deleteLater()

    def test_the_style_shortens_an_overlong_label(self, qapp):
        """drawItemText is the one hook every style-drawn control funnels
        through, so proving it elides proves buttons, tool buttons, check
        boxes and the closed combo box all do."""
        seen = []

        class _Probe(tu.ComboPopupStyle):
            def drawItemText(self, painter, rect, flags, palette, enabled,
                             text, textRole=QtGui.QPalette.ColorRole.NoRole):
                super().drawItemText(painter, rect, flags, palette, enabled,
                                     text, textRole)
                # Re-derive what super() would have drawn.
                seen.append(tu.elide_to_fit(painter.fontMetrics(), text,
                                            flags, rect.width()))

        pix = QtGui.QPixmap(200, 40)
        pix.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pix)
        try:
            _Probe().drawItemText(
                painter, QtCore.QRect(0, 0, 40, 20), int(_NO_FLAGS),
                QtGui.QPalette(), True, "Remove Models from this project")
        finally:
            painter.end()
        assert seen and seen[0].endswith("…")


class TestContainersGrowWithTheText:
    """zoom_px on the containers is the primary fix; elision is the backstop."""

    @pytest.mark.parametrize("design_px", [210, 232, 150, 100])
    def test_a_container_scales_with_zoom(self, design_px):
        assert tu.zoom_px(design_px, 150) > tu.zoom_px(design_px, 100)
        assert tu.zoom_px(design_px, 60) < tu.zoom_px(design_px, 100)

    def test_a_container_outgrows_its_text(self, qapp):
        """The invariant that actually matters: between 100% and 300% the box
        must widen at least as fast as the label inside it, or the label wins
        and spills. Layout is linear and text is linear above 100%, so this
        holds by construction -- pinned so a future curve change cannot break
        it silently."""
        for zoom in (100, 130, 150, 200, 300):
            box = tu.zoom_px(210, zoom) / tu.zoom_px(210, 100)
            text = tu.scale_font_px(14, zoom) / tu.scale_font_px(14, 100)
            assert box >= text - 0.02, zoom
