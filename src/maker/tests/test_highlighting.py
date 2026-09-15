"""Syntax-highlighting tests for the shared code-editor theme + lexers.

These pin the Verilog fixes and guard the shared blast radius:

* port declarations (`input wire clk`) colour the direction/net keywords as
  keywords and the signal name as a plain identifier -- not one black blob;
* modern SystemVerilog keywords (`logic`, `always_ff`, `typedef`, …) are
  recognised;
* system tasks (`$display`) read apart from control keywords;
* the dead branch of a `` `ifdef `` is muted rather than full strength;
* SPICE and VHDL classification is unchanged (the theme is shared).

``_classify``/``_mute`` are pure; the lexer/styling tests need a QApplication
(the ``qapp`` fixture) because they instantiate Qt objects.
"""
from PyQt6.QtGui import QColor

from codeEditor import lexers, theme

# Scintilla "style at position" query (stable ABI id).
_SCI_GETSTYLEAT = 2010

# QsciLexerVerilog style numbers exercised below.
_PRIMARY_KEYWORD = 5
_SYSTEM_TASK = 8
_IDENTIFIER = 11


# ── pure _classify / _mute (no Qt) ────────────────────────────────────
def test_system_task_reads_as_function_not_control_keyword():
    assert theme._classify("System task")[0] == theme.FUNCTION
    # control keywords keep the bold keyword colour
    assert theme._classify("Primary keywords and identifiers") == (
        theme.KEYWORD, True, False)


def test_inactive_style_is_muted_and_unbolded():
    base, base_bold, _ = theme._classify("Primary keywords and identifiers")
    colour, bold, _ = theme._classify(
        "Inactive primary keywords and identifiers")
    assert base_bold is True and bold is False      # dead code never shouts
    assert colour == theme._mute(base) != base      # faded, not full strength


def test_inactive_comment_keeps_italic():
    assert theme._classify("Inactive comment")[2] is True


def test_mute_blends_each_channel_toward_paper():
    muted = QColor(theme._mute(theme.KEYWORD, amount=0.5))
    kw, paper = QColor(theme.KEYWORD), QColor(theme.PAPER)
    for got, src, dst in (
        (muted.red(), kw.red(), paper.red()),
        (muted.green(), kw.green(), paper.green()),
        (muted.blue(), kw.blue(), paper.blue()),
    ):
        assert min(src, dst) <= got <= max(src, dst)


def test_spice_and_vhdl_classification_unchanged():
    # Guards the shared theme: the Verilog-only edits (inactive/system-task)
    # must not perturb how SPICE or VHDL styles are coloured.
    assert theme._classify("Directive") == (theme.KEYWORD, True, False)
    assert theme._classify("Command") == (theme.KEYWORD, True, False)
    assert theme._classify("Instance device") == (theme.INSTANCE, True, False)
    assert theme._classify("Node net") == (theme.NODE, False, False)
    assert theme._classify("Expression") == (theme.EXPRESSION, False, False)
    assert theme._classify("Keyword") == (theme.KEYWORD, True, False)
    assert theme._classify("Standard function") == (theme.FUNCTION, False, False)
    assert theme._classify("Comment") == (theme.COMMENT, False, True)


def test_classify_structured_format_styles():
    # New XML/JSON/Python/Markdown/Intel-hex style descriptions get
    # deliberate colours instead of falling through to plain text...
    assert theme._classify("Tag") == (theme.KEYWORD, True, False)
    assert theme._classify("Attribute") == (theme.PARAMETER, False, False)
    assert theme._classify("Property") == (theme.PARAMETER, False, False)
    assert theme._classify("Entity") == (theme.VALUE, False, False)
    assert theme._classify("CDATA") == (theme.STRING, False, False)
    assert theme._classify("Class name") == (theme.FUNCTION, True, False)
    assert theme._classify("Decorator") == (theme.PREPROC, False, False)
    assert theme._classify("Escape sequence") == (theme.STRING, False, False)
    assert theme._classify("Level 1 header") == (theme.KEYWORD, True, False)
    assert theme._classify("Checksum") == (theme.FUNCTION, False, False)
    assert theme._classify("Data address") == (theme.PARAMETER, False, False)
    assert theme._classify("Even data") == (theme.NUMBER, False, False)
    # ...without breaking the generic descriptions they sit above.
    assert theme._classify("HTML number") == (theme.NUMBER, False, False)
    assert theme._classify("Python keyword") == (theme.KEYWORD, True, False)
    assert theme._classify("JSON keyword") == (theme.KEYWORD, True, False)
    assert theme._classify("Operator") == (theme.OPERATOR, False, False)


# ── extension routing (pure, no Qt) ───────────────────────────────────
def test_cir_out_double_extension_is_spice():
    assert lexers.language_for("proj.cir.out") == "SPICE"
    assert lexers.comment_token("proj.cir.out") == "*"
    assert lexers.is_generated("proj.cir.out")          # stays read-only


def test_analysis_file_is_spice():
    assert lexers.language_for(r"C:\proj\analysis") == "SPICE"
    assert lexers.language_for("analysis") == "SPICE"
    assert not lexers.is_generated("analysis")          # hand-tunable


def test_plain_out_is_not_spice():
    # Only X.<spice>.out promotes; a bare .out stays plain text.
    assert lexers.language_for("random.out") == "Text"


def test_new_language_routing():
    assert lexers.language_for("a.proj") == "XML"
    assert lexers.language_for("a.xml") == "XML"
    assert lexers.language_for("a.kicad_pro") == "JSON"
    assert lexers.language_for("a.json") == "JSON"
    assert lexers.language_for("a.py") == "Python"
    assert lexers.language_for("a.mo") == "Modelica"
    assert lexers.language_for("a.md") == "Markdown"
    assert lexers.language_for("a.hex") == "Hex"
    # Deliberately plain — no sane stock lexer.
    assert lexers.language_for("a.kicad_sch") == "Text"
    assert lexers.language_for("a.log") == "Text"


def test_new_language_comment_tokens():
    assert lexers.comment_token("a.py") == "#"
    assert lexers.comment_token("a.mo") == "//"
    assert lexers.comment_token("a.xml") is None
    assert lexers.comment_token("a.json") is None


def test_modelica_keywords_present(qapp):
    kw = set(lexers.ModelicaLexer().keywords(1).split())
    assert {"model", "equation", "parameter", "connector", "Real",
            "annotation", "der", "when"} <= kw


# ── lexer keyword set (needs QApplication) ────────────────────────────
def test_systemverilog_keywords_present_and_join_bug_repaired(qapp):
    words = set(lexers.VerilogLexer().keywords(1).split())
    assert {"logic", "bit", "byte", "int", "typedef", "enum", "struct",
            "always_ff", "always_comb", "always_latch"} <= words
    # stock QScintilla ships "endprimitiveendspecify" with no space.
    assert "endprimitiveendspecify" not in words
    assert {"endprimitive", "endspecify"} <= words


def test_make_lexer_uses_verilog_lexer_for_v_and_sv(qapp):
    font = theme.editor_font()
    assert isinstance(lexers.make_lexer("m.v", font), lexers.VerilogLexer)
    assert isinstance(lexers.make_lexer("m.sv", font), lexers.VerilogLexer)


# ── end-to-end styling (needs QApplication) ───────────────────────────
def _style_lookup(text, path="m.v"):
    from PyQt6.Qsci import QsciScintilla

    font = theme.editor_font()
    lexer = lexers.make_lexer(path, font)
    editor = QsciScintilla()
    editor.setLexer(lexer)
    theme.apply(editor, lexer, font)
    editor.setText(text)
    editor.recolor()

    def style_of(token):
        return editor.SendScintilla(_SCI_GETSTYLEAT, text.find(token))

    return style_of


def test_port_keywords_keep_keyword_style_names_stay_plain(qapp):
    style = _style_lookup(
        "module m (input wire clk, output reg dout, inout wire bidir);\n"
        "endmodule\n")
    for kw in ("input", "output", "inout", "wire", "reg"):
        assert style(kw) == _PRIMARY_KEYWORD, kw
    for name in ("clk", "dout", "bidir"):
        assert style(name) == _IDENTIFIER, name


def test_systemverilog_keyword_is_highlighted(qapp):
    style = _style_lookup(
        "module m;\n  logic ready;\n"
        "  always_ff @(posedge clk) ready <= 1'b1;\nendmodule\n")
    assert style("logic") == _PRIMARY_KEYWORD
    assert style("always_ff") == _PRIMARY_KEYWORD


def test_system_task_uses_distinct_style(qapp):
    style = _style_lookup('initial $display("hi");\n')
    # lexer tags it as a system task...
    assert style("$display") == _SYSTEM_TASK
    # ...and the theme colours that apart from control keywords.
    assert theme._classify("System task")[0] != theme.KEYWORD


# ── SPICE styling (needs QApplication) ────────────────────────────────
_SCI_GETLINESTATE = 2093


def _spice_editor(text, path="t.cir"):
    """Return (editor, style_at) for a SPICE deck styled end-to-end."""
    from PyQt6.Qsci import QsciScintilla

    font = theme.editor_font()
    lexer = lexers.make_lexer(path, font)
    editor = QsciScintilla()
    editor.setLexer(lexer)
    # A custom lexer set without a parent is not owned by the widget and
    # editor.lexer() returns None; keep our own reference so tests can drive
    # styleText directly.
    editor._lexer_ref = lexer
    theme.apply(editor, lexer, font)
    # The title-deck rule reads editor.file_path; a bare QsciScintilla has
    # none, so set it before styling (mirrors CodeEditor).
    editor.file_path = path
    editor.setText(text)
    editor.recolor()
    return editor, (lambda pos: editor.SendScintilla(_SCI_GETSTYLEAT, pos))


def test_cir_out_title_line_and_instances(qapp):
    # foo.cir.out is a SPICE deck: first line is the (ignored) title, an
    # element line colours its device letter as an instance.
    editor, style = _spice_editor(
        "Rtitle line copied from cir\nR1 1 2 1k\n", path="t.cir.out")
    text = editor.text()
    assert style(0) == lexers.SpiceLexer.COMMENT           # title as comment
    assert style(text.find("R1")) == lexers.SpiceLexer.INSTANCE


def test_analysis_first_directive_not_comment(qapp):
    # The analysis file has no title line: its first .tran must style as a
    # directive, never as a comment.
    editor, style = _spice_editor(".tran 1e-9 3e-9 0\n", path="analysis")
    assert style(0) == lexers.SpiceLexer.DIRECTIVE


def test_number_with_unit_is_one_token(qapp):
    # 10uF must be a single NUMBER token, not NUMBER(10u) + NODE(F).
    editor, style = _spice_editor("* title\nC1 1 2 10uF\n")
    base = editor.text().find("10uF")
    for i in range(len("10uF")):
        assert style(base + i) == lexers.SpiceLexer.NUMBER, i


def test_control_block_command_styling_and_line_state(qapp):
    # Lines inside .control style as commands; the .control flag is
    # persisted as Scintilla line state for O(1) downstream seeding.
    editor, style = _spice_editor(
        "* t\n.control\nrun\nplot v(1)\n.endc\nR1 1 2 1k\n")
    text = editor.text()
    assert style(text.find("run")) == lexers.SpiceLexer.COMMAND
    assert style(text.find("plot")) == lexers.SpiceLexer.COMMAND
    # R1 after .endc is back to an instance line.
    assert style(text.find("R1")) == lexers.SpiceLexer.INSTANCE
    gls = lambda ln: editor.SendScintilla(_SCI_GETLINESTATE, ln)  # noqa: E731
    assert gls(1) == 1 and gls(2) == 1 and gls(3) == 1   # inside .control
    assert gls(4) == 0 and gls(5) == 0                   # .endc and below


def test_control_edit_propagates_downstream(qapp):
    # Regression for the stale-colour bug: opening a .control block above an
    # existing line must recolour everything below in one incremental pass,
    # not leave stale instance colours until each line is retouched.  Driven
    # through a partial styleText (what Scintilla issues on an edit) so the
    # downstream line-state propagation loop is exercised deterministically.
    _SCI_POSITIONFROMLINE = 2167
    editor, style = _spice_editor("* t\nXX\nrun\n.endc\n")
    assert style(editor.text().find("run")) == lexers.SpiceLexer.INSTANCE

    # Turn line 1 (XX) into a .control directive, then restyle only that
    # line's byte range.
    editor.setSelection(1, 0, 1, 2)
    editor.replaceSelectedText(".control")
    lexer = editor._lexer_ref
    start = editor.SendScintilla(_SCI_POSITIONFROMLINE, 1)
    end = editor.SendScintilla(_SCI_POSITIONFROMLINE, 2)
    lexer.styleText(start, end)

    assert style(editor.text().find("run")) == lexers.SpiceLexer.COMMAND
    gls = lambda ln: editor.SendScintilla(_SCI_GETLINESTATE, ln)  # noqa: E731
    assert gls(1) == 1 and gls(2) == 1 and gls(3) == 0


# ── new stock lexers (needs QApplication) ─────────────────────────────
def test_make_lexer_new_languages(qapp):
    from PyQt6.Qsci import (
        QsciLexerIntelHex,
        QsciLexerJSON,
        QsciLexerMarkdown,
        QsciLexerPython,
        QsciLexerXML,
    )

    font = theme.editor_font()
    assert isinstance(lexers.make_lexer("a.proj", font), QsciLexerXML)
    assert isinstance(lexers.make_lexer("a.kicad_pro", font), QsciLexerJSON)
    assert isinstance(lexers.make_lexer("a.py", font), QsciLexerPython)
    assert isinstance(lexers.make_lexer("a.mo", font), lexers.ModelicaLexer)
    assert isinstance(lexers.make_lexer("a.md", font), QsciLexerMarkdown)
    assert isinstance(lexers.make_lexer("a.hex", font), QsciLexerIntelHex)


def test_xml_tag_gets_non_default_style(qapp):
    # An XML tag name must land on a themed (non-default) style after apply.
    style = _style_lookup('<root attr="1">x</root>\n', path="a.proj")
    assert style("root") != 0            # not the default/plain style
