"""Tests for kicad_symlib -- the parse-based, atomic writer shared by the eSim
KiCad symbol libraries (eSim_Ngveri / eSim_NgVeriCosim / eSim_Nghdl).

These pin the behaviours the old raw byte/line surgery got wrong:
  * exact-name removal (no ``and2`` wiping ``and2_gate``),
  * paren counting that ignores quoted strings,
  * atomic writes that survive a crash mid-write, and
  * stability under thousands of overwrite cycles (no residue / glue).

All pure-file-op tests: they need neither GHDL, ngspice, Qt, nor an installed
NGHDL tarball, so they run even when the NGHDL toolchain is broken/absent.

A final drift-guard test asserts the byte-for-byte vendored copy in the
separately-packaged NGHDL tree never diverges from this canonical one.
"""
import filecmp
import os

import pytest

import maker.kicad_symlib as ksym
from maker.kicad_symlib import _balanced_end, _read_parts, _write_lib


def _block(name, body='(pin_names (offset 0)) (property "Ref" "U")'):
    """A minimal but _PART_RE-matching part block (opens '... (pin_names')."""
    return f'(symbol "{name}" {body})'


def _temp_leftovers(directory):
    """Atomic-write scratch files that survived -- must always be empty."""
    return [n for n in os.listdir(directory) if n.startswith(".eSim_atomic_")]


def _names(path):
    return sorted(_read_parts(path))


def _is_balanced_file(path):
    with open(path) as f:
        content = f.read()
    # Every top-level part the parser sees must itself be balanced, and the
    # whole wrapper '(kicad_symbol_lib ... )' must balance too.
    return _balanced_end(content, content.index("(")) == len(content.rstrip())


# ── _balanced_end: quote-aware paren matching (old bug #2) ──────────────────

def test_balanced_end_simple():
    s = "(a (b) (c))"
    assert _balanced_end(s, 0) == len(s)


def test_balanced_end_ignores_parens_inside_strings():
    # A ')' inside a quoted string must NOT close the s-expression early.
    s = '(symbol "weird )((" (pin_names))'
    assert _balanced_end(s, 0) == len(s)


def test_balanced_end_honours_escaped_quote():
    s = '(a "he said \\" ) " (b))'
    assert _balanced_end(s, 0) == len(s)


def test_balanced_end_unbalanced_returns_minus_one():
    assert _balanced_end("(a (b)", 0) == -1


# ── round-trip / serialization ──────────────────────────────────────────────

def test_round_trip_two_models(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    parts = {"mux": _block("mux"), "adder": _block("adder")}
    _write_lib(sym, parts)
    assert _names(sym) == ["adder", "mux"]
    assert _is_balanced_file(sym)


def test_read_missing_file_is_empty(tmp_path):
    assert _read_parts(str(tmp_path / "nope.kicad_sym")) == {}


# ── add / overwrite / remove are idempotent ─────────────────────────────────

def test_overwrite_replaces_not_appends(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    for _ in range(3):
        p = _read_parts(sym)
        p["mux"] = _block("mux")
        _write_lib(sym, p)
    p = _read_parts(sym)
    assert list(p) == ["mux"]              # exactly one, never duplicated


def test_remove_absent_is_noop(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    _write_lib(sym, {"mux": _block("mux")})
    p = _read_parts(sym)
    p.pop("ghost", None)                   # absent -> no error
    _write_lib(sym, p)
    assert _names(sym) == ["mux"]


def test_remove_then_readd_cycle(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    for _ in range(50):
        p = _read_parts(sym)
        p["mux"] = _block("mux")
        _write_lib(sym, p)
        assert _names(sym) == ["mux"]
        p = _read_parts(sym)
        p.pop("mux", None)
        _write_lib(sym, p)
        assert _names(sym) == []           # truly gone each cycle


# ── exact-name removal (old bug #1: prefix collision) ───────────────────────

def test_remove_does_not_touch_prefix_sibling(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    _write_lib(sym, {"and2": _block("and2"), "and2_gate": _block("and2_gate")})
    p = _read_parts(sym)
    p.pop("and2", None)
    _write_lib(sym, p)
    assert _names(sym) == ["and2_gate"]    # sibling survives


def test_nested_subunits_removed_with_parent(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    nested = (
        '(symbol "u1" (pin_names (offset 0)) '
        '(symbol "u1_0_1" (rectangle (start 0 0))) '
        '(symbol "u1_1_1" (pin (at 0 0))))'
    )
    _write_lib(sym, {"u1": nested})
    assert _names(sym) == ["u1"]           # sub-units are nested, not parts
    p = _read_parts(sym)
    p.pop("u1", None)
    _write_lib(sym, p)
    assert _names(sym) == []


def test_paren_in_string_block_survives_sibling_removal(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    tricky = _block("tricky", '(pin_names (offset 0)) (property "D" "a ( b ) )")')
    _write_lib(sym, {"tricky": tricky, "victim": _block("victim")})
    p = _read_parts(sym)
    p.pop("victim", None)
    _write_lib(sym, p)
    assert _names(sym) == ["tricky"]
    assert _read_parts(sym)["tricky"] == tricky.strip()
    assert _is_balanced_file(sym)


# ── 1000x overwrite stress (the user's explicit edge case) ──────────────────

def test_overwrite_1000x_stays_single_and_balanced(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    _write_lib(sym, {"keep": _block("keep")})
    for i in range(1000):
        p = _read_parts(sym)
        p["churn"] = _block("churn", f'(pin_names (offset {i}))')
        _write_lib(sym, p)
    p = _read_parts(sym)
    assert sorted(p) == ["churn", "keep"]  # never accreted residue
    assert _is_balanced_file(sym)


# ── corrupt-file healing ────────────────────────────────────────────────────

def test_glued_corrupt_file_is_healed_on_next_write(tmp_path):
    sym = str(tmp_path / "lib.kicad_sym")
    # Simulate what the old surgery produced: two blocks glued with no
    # separation and a stray trailing fragment.
    with open(sym, "w") as f:
        f.write('(kicad_symbol_lib (version 20211014))'
                + _block("a") + _block("b") + '(symbol "trunc" (pin_names')
    p = _read_parts(sym)                   # parser keeps only balanced blocks
    assert sorted(p) == ["a", "b"]
    _write_lib(sym, p)
    assert _is_balanced_file(sym)


# ── atomic write (crash / kill-9 / full-disk safety) ────────────────────────

def test_write_failure_leaves_original_intact_and_no_temp(tmp_path, monkeypatch):
    sym = str(tmp_path / "lib.kicad_sym")
    _write_lib(sym, {"good": _block("good")})
    before = open(sym).read()

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(ksym.os, "replace", boom)
    with pytest.raises(OSError):
        _write_lib(sym, {"good": _block("good"), "new": _block("new")})

    assert open(sym).read() == before      # original untouched
    assert _temp_leftovers(tmp_path) == []  # temp cleaned up


# ── _atomic_write: the shared temp-file + os.replace core ───────────────────
# _write_lib's atomicity was extracted so the OTHER small-but-load-bearing
# files eSim rewrites in place (sym-lib-table, modpath.lst, spinit) get it too:
# each is read by a different tool that fails far from the writer when the file
# is half-written.

def test_atomic_write_creates_file(tmp_path):
    target = str(tmp_path / "spinit")
    ksym._atomic_write(target, "codemodel /a/b.cm\n")
    assert open(target).read() == "codemodel /a/b.cm\n"
    assert _temp_leftovers(tmp_path) == []


def test_atomic_write_replaces_whole_content(tmp_path):
    target = str(tmp_path / "modpath.lst")
    ksym._atomic_write(target, "aaaaaaaaaaaa\nbbbbbbbbbbbb\n")
    ksym._atomic_write(target, "c\n")       # shorter: no tail may survive
    assert open(target).read() == "c\n"
    assert _temp_leftovers(tmp_path) == []


def test_atomic_write_failure_leaves_original_and_no_temp(
        tmp_path, monkeypatch):
    target = str(tmp_path / "sym-lib-table")
    ksym._atomic_write(target, "(sym_lib_table\n)\n")

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(ksym.os, "replace", boom)
    with pytest.raises(OSError):
        ksym._atomic_write(target, "TRUNCATED")

    # The whole point: the previous file survives a failed rewrite intact.
    assert open(target).read() == "(sym_lib_table\n)\n"
    assert _temp_leftovers(tmp_path) == []


def test_atomic_write_temp_lands_in_same_dir(tmp_path, monkeypatch):
    # os.replace is only atomic within one filesystem, so the temp file must be
    # created beside the target -- never in /tmp.
    target = str(tmp_path / "sub" / "modpath.lst")
    os.makedirs(os.path.dirname(target))
    seen = {}
    real_mkstemp = ksym.tempfile.mkstemp

    def spy(*a, **kw):
        seen["dir"] = kw.get("dir")
        return real_mkstemp(*a, **kw)

    monkeypatch.setattr(ksym.tempfile, "mkstemp", spy)
    ksym._atomic_write(target, "x\n")
    assert seen["dir"] == os.path.dirname(target)


# ── drift guard: eSim canonical == NGHDL vendored copy ──────────────────────

def test_vendored_copy_is_byte_identical():
    canonical = ksym.__file__
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(canonical)))
    vendored = os.path.join(repo_root, "nghdl", "src", "kicad_symlib.py")
    assert os.path.exists(vendored), (
        "NGHDL vendored copy missing: " + vendored)
    assert filecmp.cmp(canonical, vendored, shallow=False), (
        "src/maker/kicad_symlib.py and nghdl/src/kicad_symlib.py have drifted; "
        "edit one and copy it verbatim to the other.")
