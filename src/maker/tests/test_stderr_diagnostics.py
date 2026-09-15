"""The NgVeri terminal must not call a successful build red.

gcc, mingw32-make and verilator write everything to stderr -- progress,
"is up to date", the `rm` of an intermediate file, and every -W warning with
its six-line source excerpt. The terminal used to paint that whole stream
#ff0000, so a build that produced a working model ended in a wall of red and
users read routine toolchain noise (verilator's own STDOUT_FILENO
redefinition warning on MinGW) as a crash.

These tests pin the classifier: red only for things that actually break a
build, amber for warnings, plain text for chatter -- and a diagnostic's
continuation lines coloured to match the line that opened it.
"""
import importlib
import os
import sys

import pytest
from PyQt6 import QtWidgets

from maker import CosimConfig, ModelGeneration, NgVeri


ERROR_RED = "#ff0000"
WARN_AMBER = "#E07B00"


@pytest.fixture
def model(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)
    terminal = QtWidgets.QTextEdit()
    m = ModelGeneration.ModelGeneration(str(tmp_path / "and_gate.v"), terminal)
    m.modelpath = str(tmp_path / "and_gate") + "/"
    os.makedirs(m.modelpath, exist_ok=True)
    return m


def emitted(model):
    """Every (html) line the terminal was given, in order."""
    out = []
    model.line.connect(out.append)
    return out


# The exact block a real Windows model build prints, from the report that
# started this: two warnings, their excerpts, the include chain, the notes,
# then make's own perfectly ordinary progress.
VERILATED_WARNING_BLOCK = """\
C:/msys64/mingw64/share/verilator/include/verilated.cpp:78:10: warning: 'STDOUT_FILENO' redefined
   78 | # define STDOUT_FILENO _fileno(stdout)
      |          ^~~~~~~~~~~~~
In file included from C:/msys64/mingw64/include/locale.h:12,
                 from C:/msys64/mingw64/include/c++/16.1.0/clocale:47,
                 from C:/msys64/mingw64/share/verilator/include/verilated.cpp:51:
C:/msys64/mingw64/include/stdio.h:75:9: note: this is the location of the previous definition
   75 | #define STDOUT_FILENO 1
      |         ^~~~~~~~~~~~~
mingw32-make: '../verilated_threads.o' is up to date.
rm Vand_gate__ALL.verilator_deplist.tmp"""


# --------------------------------------------------------------------------- #
# Severity classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line", [
    "foo.c:1:2: error: 'x' undeclared",
    "collect2.exe: error: ld returned 1 exit status",
    "verilated.cpp:9:1: fatal error: verilated.h: No such file or directory",
    "%Error: and_gate.v:3:5: syntax error, unexpected endmodule",
    "mingw32-make[1]: *** [Makefile:230: Vand_gate__ALL.o] Error 1",
    "mingw32-make: *** No rule to make target 'sim_main.cpp'.  Stop.",
    "Vand_gate__ALL.o:(.text+0x40): undefined reference to `sc_time_stamp()'",
    "C:/msys64/bin/ld.exe: cannot find -lngspice",
])
def test_real_failures_are_red(model, line):
    assert model._classify_stderr(line) == "error"


@pytest.mark.parametrize("line", [
    "verilated.cpp:78:10: warning: 'STDOUT_FILENO' redefined",
    "and_gate.v:2: warning: implicit definition of wire 'q'",
    "%Warning-WIDTH: and_gate.v:4:9: Operator ASSIGN expects 8 bits",
])
def test_warnings_are_amber_not_red(model, line):
    assert model._classify_stderr(line) == "warning"


@pytest.mark.parametrize("line", [
    "mingw32-make: '../verilated_threads.o' is up to date.",
    "rm Vand_gate__ALL.verilator_deplist.tmp",
    "mingw32-make[1]: Entering directory '/c/FOSSEE/eSim/tools/nghdl'",
    "/usr/bin/mkdir -p Ngveri Ngveri/and_gate",
    "- Verilator: Walltime 0.066 s (elab=0.001, cvt=0.009, bld=0.000)",
    "g++ -Os -I. -MMD -DVERILATOR=1 -c -o Vand_gate__ALL.o Vand_gate__ALL.cpp",
])
def test_ordinary_tool_chatter_is_plain_text(model, line):
    assert model._classify_stderr(line) is None


def test_no_error_flag_in_a_command_line_is_mistaken_for_an_error(model):
    # The compile command itself is echoed on stderr and is stuffed with flag
    # names. A naive `"error" in line` search called every build a failure.
    assert model._classify_stderr(
        "g++ -Werror=return-type -Wno-error=unused -c foo.cpp") is None


# --------------------------------------------------------------------------- #
# Continuation lines inherit the diagnostic that opened the block
# --------------------------------------------------------------------------- #
def test_warning_excerpt_stays_amber_end_to_end(model):
    out = emitted(model)
    model._emit_stderr(VERILATED_WARNING_BLOCK)

    body = [ln for ln in out]
    assert len(body) == len(VERILATED_WARNING_BLOCK.split("\n"))
    # Not one red line anywhere in a block that broke nothing.
    assert not any(ERROR_RED in ln for ln in body)
    # The warning, its source echo, its caret, the include chain and the
    # closing note are one visual unit.
    for i in range(0, 8):
        assert WARN_AMBER in body[i], body[i]
    # ...and make's progress after it is not dressed up as a diagnostic.
    assert WARN_AMBER not in body[-1]
    assert WARN_AMBER not in body[-2]


def test_error_excerpt_stays_red(model):
    out = emitted(model)
    model._emit_stderr(
        "and_gate.v:3:5: error: 'q' undeclared\n"
        "    3 | assign q = a & b;\n"
        "      |        ^")
    assert len(out) == 3
    assert all(ERROR_RED in ln for ln in out)


def test_a_new_step_does_not_inherit_the_previous_step_severity(model):
    # A step whose last stderr line was an error must not bleed red into the
    # first line of the next tool's output, which is usually just a banner.
    model._classify_stderr("foo.c:1:1: error: broken")
    assert model._diag_severity == "error"

    out = emitted(model)
    model._run(
        [sys.executable, "-c",
         "import sys; sys.stderr.write('   78 | # define X 1\\n')"],
        "NEXT STEP")
    excerpt = [ln for ln in out if "# define X 1" in ln]
    assert excerpt and ERROR_RED not in excerpt[0]


# --------------------------------------------------------------------------- #
# Escaping: compiler output is full of angle brackets
# --------------------------------------------------------------------------- #
def test_angle_brackets_survive_the_terminal(model):
    # QTextEdit.append() parses HTML, so an unescaped <stdio.h> was swallowed
    # whole -- the user lost the one token that named the missing header.
    model._emit_stderr(
        "foo.c:1:10: fatal error: stdio.h: No such file or directory\n"
        "    1 | #include <stdio.h>")
    text = model.termedit.toPlainText()
    assert "<stdio.h>" in text


def test_termtext_escapes_too(model):
    model.termtext("Command: g++ -o a.o <input>")
    assert "<input>" in model.termedit.toPlainText()


# --------------------------------------------------------------------------- #
# Closing verdict
# --------------------------------------------------------------------------- #
def test_counts_one_diagnostic_per_block_not_per_line(model):
    model._emit_stderr(VERILATED_WARNING_BLOCK)
    assert model.diag_warnings == 1        # 10 lines, one warning
    assert model.diag_errors == 0


def test_summary_reports_the_tally(qapp):
    ng = NgVeri.NgVeri.__new__(NgVeri.NgVeri)

    class _Counts:
        diag_errors = 0
        diag_warnings = 2

    ng._build_model = _Counts()
    html = ng._diag_summary_html()
    assert "0 errors" in html and "2 warnings" in html
    # A clean build with warnings must say so in words, not leave the user to
    # infer it from the colour of the scrollback.
    assert "Warnings do not stop a build." in html


def test_summary_singular_and_no_reassurance_when_the_build_broke(qapp):
    ng = NgVeri.NgVeri.__new__(NgVeri.NgVeri)

    class _Counts:
        diag_errors = 1
        diag_warnings = 1

    ng._build_model = _Counts()
    html = ng._diag_summary_html()
    assert "1 error" in html and "1 warning" in html
    assert "errors" not in html and "warnings" not in html
    assert "do not stop" not in html
