"""Port-direction parsing regression tests.

``connection_info.txt`` lines are exactly ``name direction bits``. Four copies
of the reader historically detected the direction by substring-searching the
WHOLE line, so a port whose *name* contained a direction keyword was counted
in both the input and the output list — a silently corrupt model (wrong ifspec,
wrong KiCad pin count, wrong generated C). The nghdl copies were worse: bare
``IN``/``OUT`` misclassified ``sout``/``win``/``dout``. A leading blank line
also left the match variables unbound and crashed.

These tests feed an adversarial fixture to every copy we can import and assert
exact classification with no double-counting. The fourth copy
(``nghdl/src/createKicadLibrary.py``) drags in Appconfig/PyQt and cannot be
imported in isolation, so it gets a static source-parity guard instead.
"""
import importlib.util
import os
import types

from maker import ModelGeneration, createkicad

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Ports whose NAMES contain direction keywords, in file order, plus the
# direction each MUST be classified as. output_valid/input_load stress the
# maker copies (input/output substrings); dout/sout/win stress the nghdl copies
# (in/out substrings); data_reg exercises inout-folds-to-input.
_INPUT_PORTS = [("clk", "1"), ("output_valid", "1"),
                ("dout", "1"), ("data_reg", "4")]
_OUTPUT_PORTS = [("input_load", "2"), ("sout", "3"),
                 ("win", "1"), ("q", "8")]

# (name, direction, bits) rows in the on-disk order the reader sees them.
_ROWS = [("clk", "1"), ("output_valid", "1"), ("input_load", "2"),
         ("dout", "1"), ("sout", "3"), ("win", "1"),
         ("data_reg", "4"), ("q", "8")]
_DIR = {"clk": "input", "output_valid": "input", "input_load": "output",
        "dout": "input", "sout": "output", "win": "output",
        "data_reg": "inout", "q": "output"}


def _write_conn(path, maker_tokens, leading_blank=True):
    """Write a connection_info.txt using maker (input/output/inout) or nghdl
    (in/out/inout) direction tokens. Optionally prepend blank lines."""
    tok = {"input": "input", "output": "output", "inout": "inout"} if \
        maker_tokens else {"input": "in", "output": "out", "inout": "inout"}
    lines = ["\n", "   \n"] if leading_blank else []
    for name, bits in _ROWS:
        lines.append("%s %s %s\n" % (name, tok[_DIR[name]], bits))
    with open(path, "w") as fh:
        fh.writelines(lines)


def test_model_generation_getportinfo(tmp_path):
    conn = tmp_path / "connection_info.txt"
    _write_conn(str(conn), maker_tokens=True)

    mg = ModelGeneration.ModelGeneration.__new__(
        ModelGeneration.ModelGeneration)
    mg.modelpath = str(tmp_path) + os.sep
    mg.getPortInfo()

    # No double-counting: every port lands in exactly one list.
    assert len(mg.input_list) + len(mg.output_list) == len(_ROWS)
    assert mg.input_port == ["clk:1", "output_valid:1", "dout:1", "data_reg:4"]
    assert mg.output_port == ["input_load:2", "sout:3", "win:1", "q:8"]


def test_createkicad_portinfo(tmp_path):
    conn = tmp_path / "connection_info.txt"
    _write_conn(str(conn), maker_tokens=True)

    model = types.SimpleNamespace(modelname="dut")
    port = createkicad.PortInfo(model, str(tmp_path) + os.sep)
    port.getPortInfo()

    # bit_list is inputs-then-outputs; input_len marks the split.
    assert port.input_len == len(_INPUT_PORTS)
    assert port.bit_list == ["1", "1", "1", "4", "2", "3", "1", "8"]
    assert port.port_name == ["clk", "output_valid", "dout", "data_reg",
                              "input_load", "sout", "win", "q"]


def test_model_generation_blank_first_line_no_crash(tmp_path):
    """A leading blank line must not raise (it used to leave the match
    variables unbound)."""
    conn = tmp_path / "connection_info.txt"
    _write_conn(str(conn), maker_tokens=True, leading_blank=True)

    mg = ModelGeneration.ModelGeneration.__new__(
        ModelGeneration.ModelGeneration)
    mg.modelpath = str(tmp_path) + os.sep
    mg.getPortInfo()  # previously raised NameError
    assert len(mg.input_list) == len(_INPUT_PORTS)


def _load_nghdl_model_generation():
    """Import nghdl/src/model_generation.py by path (stdlib-only module) with
    no sys.path pollution / vendored-module shadowing."""
    src = os.path.join(_REPO_ROOT, "nghdl", "src", "model_generation.py")
    spec = importlib.util.spec_from_file_location("nghdl_model_generation", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_nghdl_readportinfo(tmp_path):
    mod = _load_nghdl_model_generation()
    conn = tmp_path / "connection_info.txt"
    _write_conn(str(conn), maker_tokens=False)

    mg = mod.ModelGeneration.__new__(mod.ModelGeneration)
    # The generator reads and writes under outdir instead of the process CWD,
    # so the __new__-bypassed instance must be given one.
    mg.outdir = str(tmp_path)
    mg.readPortInfo()

    assert mg.input_port == ["clk:1", "output_valid:1", "dout:1", "data_reg:4"]
    assert mg.output_port == ["input_load:2", "sout:3", "win:1", "q:8"]


def _getportinfo_source(rel_path):
    """Return the source of the getPortInfo method in a file we cannot import
    (heavy deps) — from 'def getPortInfo' to the next top-level 'def '."""
    with open(os.path.join(_REPO_ROOT, rel_path)) as fh:
        text = fh.read()
    start = text.index("def getPortInfo(")  # not getPortInformation
    tail = text[start:]
    nxt = tail.find("\n    def ", 1)
    return tail if nxt == -1 else tail[:nxt]


def test_nghdl_createkicadlibrary_parity():
    """The fourth copy has heavy imports, so a source guard confirms the same
    structural fix: parse the direction FIELD, no substring findall."""
    src = _getportinfo_source(os.path.join("nghdl", "src",
                                           "createKicadLibrary.py"))
    assert "parts[1].lower()" in src
    assert "findall" not in src
