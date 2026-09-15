"""Visual theme for the eSim code editor.

One light, high-contrast scheme ("eSim Light") plus a single
``apply()`` that styles *any* QScintilla lexer by classifying each of
its styles from the human-readable ``description()`` string -- so the
SPICE, Verilog and VHDL lexers all get consistent, deliberate colours
instead of the near-black defaults.
"""

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

try:
    from PyQt6.Qsci import QsciScintilla
except ImportError:               # QScintilla not installed / failed to load
    # Optional dependency -- see lexers.py. Only apply() touches the class,
    # and apply() is only ever handed a real QsciScintilla editor, which
    # cannot exist without the module. editor_font() and the palettes stay
    # usable for the plain-text fallback editor.
    QsciScintilla = None


# ── palettes ─────────────────────────────────────────────────────────
# Two schemes: "eSim Light" (the original) and a matching dark scheme so the
# QScintilla editor tracks the Aurora theme instead of staying a white box on
# a dark UI. The bare module names below (PAPER, TEXT, …) are rebound by
# _activate_palette() at apply() time; every helper reads them as globals.
LIGHT = {
    "PAPER": "#FFFFFF", "TEXT": "#24292E", "COMMENT": "#6A9955",
    "KEYWORD": "#0033B3", "NUMBER": "#098658", "STRING": "#A31515",
    "VALUE": "#9A3FB6", "PARAMETER": "#0070C1", "FUNCTION": "#795E26",
    "PREPROC": "#AF00DB", "OPERATOR": "#6E7781", "INSTANCE": "#C2410C",
    "EXPRESSION": "#9A3FB6", "NODE": "#0E7490",
    # chrome
    "MARGIN_FG": "#9DA5B4", "MARGIN_BG": "#F3F4F6", "MARGIN_SEP": "#DFE1E6",
    "CARET_LINE": "#F5F8FF", "SELECTION": "#CFE3FB", "BRACE_FG": "#0033B3",
    "BRACE_BG": "#C8E6C9", "GUIDE": "#E6E8EB", "CARET": "#24292E",
    "SEARCH_HL": "#FBD56A", "CURRENT_HL": "#FF9632",
}
DARK = {
    "PAPER": "#0E1728", "TEXT": "#E6EDF7", "COMMENT": "#6A9955",
    "KEYWORD": "#569CD6", "NUMBER": "#B5CEA8", "STRING": "#CE9178",
    "VALUE": "#C586C0", "PARAMETER": "#9CDCFE", "FUNCTION": "#DCDCAA",
    "PREPROC": "#C586C0", "OPERATOR": "#C9D3E0", "INSTANCE": "#F1956B",
    "EXPRESSION": "#C586C0", "NODE": "#4EC9B0",
    # chrome
    "MARGIN_FG": "#5F728D", "MARGIN_BG": "#0A1020", "MARGIN_SEP": "#1D2B45",
    "CARET_LINE": "#121E33", "SELECTION": "#264F78", "BRACE_FG": "#569CD6",
    "BRACE_BG": "#1D2B45", "GUIDE": "#1D2B45", "CARET": "#E6EDF7",
    "SEARCH_HL": "#FBD56A", "CURRENT_HL": "#FF9632",
}
# Start on the light scheme; _activate_palette() switches to dark when the app
# palette is dark. globals().update keeps the historical bare-name API intact.
globals().update(LIGHT)


def is_dark_theme():
    """True when the running app is on a dark Aurora palette.

    Detect from the QApplication's window colour -- the same signal
    theme_utils/icon_paths use -- defaulting to light when there is no app
    yet (e.g. unit tests)."""
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def _activate_palette():
    """Rebind the colour globals to match the active Aurora theme."""
    dark = is_dark_theme()
    globals().update(DARK if dark else LIGHT)
    return dark

#: indicator numbers used for find highlighting (clear of lexer use)
SEARCH_INDICATOR = 8
CURRENT_INDICATOR = 9

#: stable Scintilla message id (lexer property setter)
_SCI_SETPROPERTY = getattr(QsciScintilla, "SCI_SETPROPERTY", 4004)

_FONT_PREFS = [
    "Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Fira Code",
    "Consolas", "Menlo", "DejaVu Sans Mono", "Liberation Mono",
    "Noto Sans Mono", "Monospace",
]


def editor_font(size=11):
    """Best available monospace font."""
    available = set(QFontDatabase.families())
    family = next((f for f in _FONT_PREFS if f in available), "Monospace")
    font = QFont(family, size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


def _mute(hex_colour, amount=0.55):
    """Blend *hex_colour* toward the paper so inactive code recedes.

    The Verilog lexer emits dedicated "Inactive …" styles for the dead
    branch of a `` `ifdef ``; rendering them in full strength makes
    compiled-out code shout as loudly as live code.  Fading each toward
    the background keeps it readable but clearly secondary.
    """
    fg, bg = QColor(hex_colour), QColor(PAPER)

    def mix(a, b):
        return round(a + (b - a) * amount)

    return QColor(mix(fg.red(), bg.red()),
                  mix(fg.green(), bg.green()),
                  mix(fg.blue(), bg.blue())).name()


def _classify(desc):
    """Map a lexer style description to (colour, bold, italic)."""
    d = desc.lower()
    if d.startswith("inactive"):
        # Dead `` `ifdef `` branch: classify the underlying token, then
        # fade it and drop any bold so it reads as compiled-out.
        colour, _bold, italic = _classify(d[len("inactive"):].strip())
        return _mute(colour), False, italic
    if "comment" in d:
        return COMMENT, False, True
    if "instance" in d or "device" in d:
        return INSTANCE, True, False
    if "node" in d or "net" in d:
        return NODE, False, False
    if "system task" in d:
        # Built-in tasks ($display, $finish, …) read as support
        # functions, not control keywords -- colour them apart.
        return FUNCTION, False, False
    # ── structured-format styles (XML / JSON / Python / Markdown / Intel-hex).
    # These come before the generic checks below so a description like
    # "HTML number" still resolves to NUMBER, while the format-specific
    # names get deliberate colours.  Kept above "keyword"/"operator" etc.
    if "class name" in d:                       # Python class name
        return FUNCTION, True, False
    if "decorator" in d:                        # Python decorator
        return PREPROC, False, False
    if "tag" in d:                              # XML/HTML tags
        return KEYWORD, True, False
    if "attribute" in d:                        # XML attrs (+ VHDL attributes)
        return PARAMETER, False, False
    if "property" in d:                         # JSON object keys
        return PARAMETER, False, False
    if "entity" in d:                           # XML/SGML entity refs
        return VALUE, False, False
    if "cdata" in d:                            # XML CDATA section
        return STRING, False, False
    if "escape sequence" in d:                  # Python/JSON/CPP escapes
        return STRING, False, False
    if "header" in d:                           # Markdown headers
        return KEYWORD, True, False
    if "emphasis" in d:                         # Markdown *bold* / _italic_
        return VALUE, "strong" in d, True
    if "code between" in d or "code block" in d:   # Markdown code spans
        return STRING, False, False
    if "list item" in d:                        # Markdown bullets / numbers
        return KEYWORD, False, False
    if "block quote" in d:                       # Markdown blockquote
        return COMMENT, False, True
    if d == "link":                             # Markdown link
        return PARAMETER, False, False
    if "record start" in d or "record type" in d:   # Intel-hex framing
        return KEYWORD, True, False
    if "byte count" in d:                       # Intel-hex byte count
        return NUMBER, False, False
    if "address" in d:                          # Intel-hex address fields
        return PARAMETER, False, False
    if "checksum" in d:                         # Intel-hex checksum
        return FUNCTION, False, False
    if "even data" in d:                        # Intel-hex payload bytes
        return NUMBER, False, False
    if "odd data" in d:
        return VALUE, False, False
    if any(k in d for k in ("keyword", "command", "directive")):
        return KEYWORD, True, False
    if "preprocessor" in d or "macro" in d:
        return PREPROC, False, False
    if "expression" in d:
        return EXPRESSION, False, False
    if "number" in d:
        return NUMBER, False, False
    if "string" in d or "character" in d:
        return STRING, False, False
    if "value" in d:
        return VALUE, False, False
    if "parameter" in d:
        return PARAMETER, False, False
    if "function" in d or "task" in d:
        return FUNCTION, False, False
    if "operator" in d or "delimiter" in d:
        return OPERATOR, False, False
    return TEXT, False, False


def apply(editor, lexer, font=None):
    """Theme *editor* (a QsciScintilla) and its *lexer* (may be None).

    Re-reads the active Aurora palette first, so calling apply() again after a
    theme switch (e.g. from an editor's changeEvent) repaints it dark/light."""
    _activate_palette()
    font = font or editor_font()
    paper = QColor(PAPER)

    if lexer is not None:
        lexer.setDefaultPaper(paper)
        lexer.setDefaultColor(QColor(TEXT))
        lexer.setDefaultFont(font)
        for style in range(128):
            desc = lexer.description(style)
            if not desc:
                continue
            colour, bold, italic = _classify(desc)
            lexer.setColor(QColor(colour), style)
            lexer.setPaper(paper, style)
            styled = QFont(font)
            styled.setBold(bold)
            styled.setItalic(italic)
            lexer.setFont(styled, style)
        _tune_lexer(editor, lexer)

    _apply_chrome(editor, font)


def _tune_lexer(editor, lexer):
    """Normalise lexer tokenisation that would otherwise defeat theming."""
    if lexer.language() == "Verilog":
        # By default the Verilog lexer lumps a whole port declaration
        # (`input wire clk`) into one "port" style spanning the direction
        # keyword, the net type and the signal name -- so they can't be
        # coloured independently and currently fall through to plain
        # text.  Disabling port styling lets `input`/`output`/`wire`/`reg`
        # colour as the keywords they are and the names as identifiers.
        editor.SendScintilla(
            _SCI_SETPROPERTY, b"lexer.verilog.portstyling", b"0")
        editor.recolor()


def _apply_chrome(editor, font):
    editor.setMarginsFont(font)
    editor.setMarginsForegroundColor(QColor(MARGIN_FG))
    editor.setMarginsBackgroundColor(QColor(MARGIN_BG))
    # Margin 1 is the spacer between line numbers and the fold column.
    # Paint it slightly darker so it reads as a subtle separator stripe.
    # SCI_SETMARGINBACKN (2190): wParam=margin index, lParam=BBGGRR colour.
    sep = QColor(MARGIN_SEP)
    sep_packed = (sep.blue() << 16) | (sep.green() << 8) | sep.red()
    editor.SendScintilla(2190, 1, sep_packed)
    editor.setCaretLineBackgroundColor(QColor(CARET_LINE))
    editor.setCaretForegroundColor(QColor(CARET))
    editor.setCaretWidth(2)
    editor.setSelectionBackgroundColor(QColor(SELECTION))
    editor.resetSelectionForegroundColor()
    editor.setMatchedBraceForegroundColor(QColor(BRACE_FG))
    editor.setMatchedBraceBackgroundColor(QColor(BRACE_BG))
    editor.setIndentationGuidesForegroundColor(QColor(GUIDE))
    editor.setIndentationGuidesBackgroundColor(QColor(PAPER))
    editor.setFoldMarginColors(QColor(MARGIN_BG), QColor(MARGIN_BG))
    editor.setPaper(QColor(PAPER))
    editor.setColor(QColor(TEXT))
    # a touch of line spacing for readability
    editor.setExtraAscent(2)
    editor.setExtraDescent(2)
    # Search highlights are translucent boxes (StraightBox = fill +
    # outline) with a low fill alpha, so the matched glyphs stay
    # readable underneath -- a solid fill made single letters like "a"
    # vanish into the highlight.  The current match gets a stronger
    # fill and a solid outline so it still stands out from the rest.
    editor.indicatorDefine(
        QsciScintilla.IndicatorStyle.StraightBoxIndicator, SEARCH_INDICATOR)
    editor.setIndicatorForegroundColor(QColor(SEARCH_HL), SEARCH_INDICATOR)
    editor.SendScintilla(
        QsciScintilla.SCI_INDICSETALPHA, SEARCH_INDICATOR, 90)
    editor.SendScintilla(
        QsciScintilla.SCI_INDICSETOUTLINEALPHA, SEARCH_INDICATOR, 150)
    editor.indicatorDefine(
        QsciScintilla.IndicatorStyle.StraightBoxIndicator, CURRENT_INDICATOR)
    editor.setIndicatorForegroundColor(QColor(CURRENT_HL), CURRENT_INDICATOR)
    editor.SendScintilla(
        QsciScintilla.SCI_INDICSETALPHA, CURRENT_INDICATOR, 120)
    editor.SendScintilla(
        QsciScintilla.SCI_INDICSETOUTLINEALPHA, CURRENT_INDICATOR, 255)
