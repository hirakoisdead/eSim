"""Theme-safety tests for the d_cosim GUI log (CosimLogger).

CosimLog renders the whole d_cosim build story -- phases, progress, tool output
-- into the NgVeri terminal, a QTextEdit whose palette follows eSim's light /
dark theme. Any line that hardcodes a color ignores that palette, which is why
ModelGeneration.termtext/termtitle dropped their '#000000': it renders
black-on-black and the text simply vanishes on the dark theme. CosimLog paints
into the SAME widget and had kept the light-theme values, so on dark the
d_cosim log was mostly invisible.

These tests pin the split: body-ish lines emit no color (inherit the palette),
lines whose color carries MEANING keep one, and those use the theme-tested
values shared with the rest of the maker UI. No Qt widget needed -- the logger
takes a plain callable sink.
"""
import re

from maker.CosimLogger import CosimLog


def _log():
    """A CosimLog whose GUI sink just collects the emitted HTML."""
    out = []
    return CosimLog(sink=out.append), out


# ── lines that must inherit the palette ─────────────────────────────────────

def test_info_inherits_palette():
    log, out = _log()
    log.info("staging netlist")
    assert len(out) == 1
    assert "color:" not in out[0]


def test_stdout_output_inherits_palette():
    log, out = _log()
    log.output("Compiling counter.v", stream="stdout")
    assert len(out) == 1
    assert "color:" not in out[0]


def test_phase_header_inherits_palette_but_stays_prominent():
    # A phase header is already set apart by size + weight; the old #0000FF is
    # a poor read on dark and adds nothing the emphasis does not.
    log, out = _log()
    log.phase("BUILD MODEL")
    assert "color:" not in out[0]
    assert "font-weight:800" in out[0]
    assert "font-size:14pt" in out[0]
    assert "BUILD MODEL" in out[0]


def test_no_line_emits_pure_black():
    """The exact regression: '#000000' is invisible on the dark theme."""
    log, out = _log()
    log.phase("P")
    log.info("i")
    log.detail("d")
    log.ok("o")
    log.warn("w")
    log.error("e")
    log.fix("f")
    log.output("so", stream="stdout")
    log.output("se", stream="stderr")
    joined = "".join(out).lower()
    assert "#000000" not in joined
    assert "#0000ff" not in joined


# ── lines whose color carries meaning ───────────────────────────────────────

def test_semantic_colors_are_kept():
    log, out = _log()
    log.ok("done")
    log.warn("careful")
    log.error("failed")
    assert "color:#00AA00;" in out[0]
    assert "color:#E07B00;" in out[1]
    assert "color:#FF0000;" in out[2]


def test_stderr_uses_the_same_red_as_the_ngveri_terminal():
    # ModelGeneration._emit_stderr paints a real failure #ff0000; the darker
    # #B00000 CosimLog used read as near-black on the dark theme.
    log, out = _log()
    log.output("undefined reference to `main'", stream="stderr")
    assert "color:#FF0000;" in out[0]


# ── the emitted HTML stays well-formed ──────────────────────────────────────

def test_style_attribute_is_valid_without_a_color():
    # Dropping the color must not leave a dangling 'color:;' or a stray ';;'.
    log, out = _log()
    log.info("x")
    style = re.search(r'style="([^"]*)"', out[0]).group(1)
    assert "color:" not in style
    assert ";;" not in style
    assert style.endswith(";")


def test_message_text_is_still_escaped():
    log, out = _log()
    log.info('<script>alert("x")</script>')
    assert "<script>" not in out[0]
    assert "&lt;script&gt;" in out[0]
