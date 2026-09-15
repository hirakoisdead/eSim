"""Zoom drives two curves: layout linear, text compressed below 100%.

A single linear multiplier over every ``px`` in the stylesheet is what made
60% zoom unusable -- the layout survived the trip down (a 32px button became a
19px button) and the text did not (a 14px label became an 8px label). These pin
the split, the floors that stop small roles falling off the legibility cliff,
and -- just as important -- that nothing at or above 100% moved, so no zoom
level anyone already tuned by eye has changed underneath them.
"""
import os
import sys

import pytest

_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)

from frontEnd import theme_utils as tu          # noqa: E402


# The design sizes actually used in style_dark.qss / style_light.qss.
_ROLES = (10, 11, 12, 13, 14, 16, 22, 26, 28)


class TestTheTextCurve:
    @pytest.mark.parametrize("zoom,base,expected", [
        # The case that started this: the body role at the zoom a mentor
        # reported as "looks great... the font size is a bit small". Linear
        # would give 8px.
        (60, 14, 11),
        (60, 13, 11),
        (60, 12, 11),
        (60, 10, 10),
        (60, 26, 20),
        (70, 14, 12),
        (80, 14, 12),
        # 90% is the hand-tuned value on two different real machines. The body
        # roles must land exactly where they already did.
        (90, 14, 13),
        (90, 13, 12),
        (90, 12, 11),
        (100, 14, 14),
        (130, 14, 18),
        (150, 14, 21),
    ])
    def test_pinned(self, zoom, base, expected):
        assert tu.scale_font_px(base, zoom) == expected

    def test_is_identity_at_100(self):
        for base in _ROLES:
            assert tu.scale_font_px(base, 100) == base

    def test_is_linear_at_and_above_100(self):
        """Someone who zooms to 200% is asking for big text, not a curve."""
        for zoom in (100, 110, 150, 200, 300):
            for base in _ROLES:
                assert tu.scale_font_px(base, zoom) == round(
                    base * zoom / 100.0)

    def test_never_shrinks_a_role_past_its_floor(self):
        for zoom in range(50, 101, 5):
            assert tu.scale_font_px(14, zoom) >= tu._FONT_FLOOR_PX
            assert tu.scale_font_px(10, zoom) >= tu._FONT_FLOOR_SMALL_PX

    def test_a_floor_never_grows_a_role(self):
        """A role that ships at 9px is deliberately tiny; the floor is a
        minimum for shrinking, not a size to inflate small text up to."""
        for zoom in range(50, 101, 5):
            assert tu.scale_font_px(9, zoom) <= 9
            assert tu.scale_font_px(10, zoom) <= 10

    def test_never_goes_backwards(self):
        for base in _ROLES:
            sizes = [tu.scale_font_px(base, z) for z in range(50, 301, 5)]
            assert sizes == sorted(sizes), base

    def test_text_shrinks_more_slowly_than_layout(self):
        """The whole point of the split, stated as an invariant."""
        for zoom in range(50, 100, 5):
            assert tu.font_scale(zoom) > tu.zoom_scale(zoom)
        for zoom in range(100, 301, 25):
            assert tu.font_scale(zoom) == pytest.approx(tu.zoom_scale(zoom))


class TestTheLayoutCurve:
    def test_stays_linear_everywhere(self):
        for zoom in (50, 60, 90, 100, 150, 300):
            assert tu.zoom_px(200, zoom) == round(200 * zoom / 100.0)

    def test_never_collapses_a_metric_to_nothing(self):
        assert tu.zoom_px(1, 50) >= 1
        assert tu.zoom_px(0, 50) == 0


class TestTheStylesheetPass:
    def test_font_sizes_take_the_text_curve(self):
        out = tu.scale_qss_px("QLabel { font-size: 14px; }", 60)
        assert "font-size: 11px" in out          # not 8px

    def test_everything_else_takes_the_layout_curve(self):
        out = tu.scale_qss_px("QPushButton { min-height: 32px; }", 60)
        assert "min-height: 19px" in out

    def test_both_in_one_rule(self):
        out = tu.scale_qss_px(
            "QPushButton { padding: 8px 16px; font-size: 14px;"
            " min-width: 72px; }", 60)
        assert "font-size: 11px" in out
        assert "padding: 5px 10px" in out
        assert "min-width: 43px" in out

    def test_a_height_cap_never_falls_below_its_own_text(self):
        """max-height is a hard cap -- Qt clips glyphs rather than growing the
        control. Taken straight down the layout curve it would crush the text
        the font curve just protected."""
        out = tu.scale_qss_px(
            "QPushButton#addModuleBtn { font-size: 13px; max-height: 28px; }",
            60)
        cap = int(out.split("max-height:")[1].split("px")[0])
        size = int(out.split("font-size:")[1].split("px")[0])
        assert cap == 21                 # not 17, which linear would give
        assert cap > size

    def test_a_height_cap_is_unchanged_at_and_above_100(self):
        for zoom in (100, 150, 200):
            out = tu.scale_qss_px("* { max-height: 28px; }", zoom)
            assert out == "* { max-height: %dpx; }" % round(28 * zoom / 100)

    def test_every_shipped_height_cap_clears_its_own_type(self, qapp):
        """End to end at the worst zoom: no rule in either sheet ends up with
        a cap it cannot draw its own font inside."""
        import re
        for name in ("style_dark.qss", "style_light.qss"):
            built = tu.build_qss(name, "dark" in name, "default", "system",
                                 "system", 60)
            for block in re.findall(r"\{[^}]*\}", built):
                caps = re.findall(r"max-height:\s*(\d+)px", block)
                sizes = re.findall(r"font-size:\s*(\d+)px", block)
                if caps and sizes:
                    assert int(caps[0]) > int(sizes[0]), block

    def test_hairlines_stay_crisp(self):
        """1-2px borders are hairlines, not metrics; scaling them blurs the
        whole UI's edge work."""
        out = tu.scale_qss_px("QFrame { border: 1px solid red; }", 150)
        assert "border: 1px solid red" in out

    def test_100_percent_is_untouched(self):
        src = "QLabel { font-size: 14px; padding: 8px; }"
        assert tu.scale_qss_px(src, 100) == src

    def test_a_font_size_is_never_read_as_a_layout_metric(self):
        """Regression guard on the alternation order in _PX_RE: if the bare-px
        branch ever wins at a font-size, text silently goes back to linear."""
        out = tu.scale_qss_px("* { font-size:14px }", 60)
        assert out == "* { font-size:11px }"


class TestTheFontStack:
    def test_windows_leads_with_a_directwrite_hinted_face(self):
        """Ubuntu's hinting is authored for FreeType; DirectWrite ignores it,
        which is why the bundled face read as soft at 1x on Windows."""
        stack = tu._FONT_STACK_WIN
        assert stack.index("Segoe UI") < stack.index("Ubuntu")

    def test_other_platforms_lead_with_the_bundled_face(self):
        stack = tu._FONT_STACK_OTHER
        assert stack.index("Ubuntu") < stack.index("Segoe UI")

    def test_the_bundled_face_is_never_dropped_entirely(self):
        """A Windows box with no Segoe must still get eSim's own font rather
        than falling through to a system default."""
        for stack in (tu._FONT_STACK_WIN, tu._FONT_STACK_OTHER):
            assert "Ubuntu" in stack

    def test_the_shipped_qss_declares_the_stack_the_builder_replaces(self):
        """If the .qss stack is ever edited without updating the constant, the
        per-platform swap silently stops happening."""
        for name in ("style_dark.qss", "style_light.qss"):
            path = os.path.join(_FRONTEND, name)
            with open(path, "r", encoding="utf-8") as f:
                assert tu._FONT_STACK_QSS in f.read(), name

    def test_families_list_drops_the_generic_fallback(self):
        families = tu.ui_font_families()
        assert "sans-serif" not in families
        assert families[0] in tu.ui_font_stack()


class TestBuildQss:
    def test_resolves_the_platform_stack(self, qapp):
        out = tu.build_qss("style_dark.qss", True, "default", "system",
                           "system", 100)
        assert tu.ui_font_stack() in out
        if sys.platform == "win32":
            assert tu._FONT_STACK_QSS not in out

    def test_body_text_survives_the_60_percent_trip(self, qapp):
        """End to end: no font-size anywhere in the sheet lands under the
        small-role floor once the zoom is applied."""
        import re
        out = tu.build_qss("style_dark.qss", True, "default", "system",
                           "system", 60)
        sizes = [int(m) for m in re.findall(r"font-size:\s*(\d+)px", out)]
        assert sizes, "no font sizes found -- did the sheet move?"
        assert min(sizes) >= tu._FONT_FLOOR_SMALL_PX
