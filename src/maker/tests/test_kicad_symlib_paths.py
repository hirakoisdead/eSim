"""Tests for the generated-symbol-library location + lazy migration + KiCad
sym-lib-table registration helpers in ``kicad_symlib``.

The three libraries eSim rewrites at runtime (eSim_Ngveri / eSim_NgVeriCosim /
eSim_Nghdl) moved out of the root-owned /usr/share/kicad/symbols into the
user's own ~/.esim/kicad_symbols. These tests pin:
  (a) generated_symlib_path returns ~/.esim/kicad_symbols/<lib> and creates it,
  (b) lazy migration copies a legacy file ONCE and never clobbers a new one,
  (c) ensure_lib_registered appends / rewrites-stale / leaves-correct.

HOME (and os.path.expanduser) is redirected to tmp_path throughout, so the real
~/.esim is never touched. %APPDATA% is redirected too, because the KiCad config
dir lives there on Windows and is NOT covered by expanduser. Before this,
ensure_lib_registered wrote bogus entries into the developer's real
%APPDATA%\\kicad\\sym-lib-table on every Windows run.
"""
import os

import maker.kicad_symlib as ksym


def _redirect_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # _kicad_config_dir() reads %APPDATA% on Windows; redirect it into the same
    # sandbox so ensure_lib_registered can never reach the real KiCad profile.
    # Done per test (monkeypatch restores it) and deliberately NOT in a shared
    # conftest: a global APPDATA redirect also moves the per-user site-packages
    # that subprocess-based tests import PyQt6 from.
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(home), 1))
    return home


def _block_default_probe(monkeypatch):
    """Neutralise the built-in /usr/share/kicad/symbols migration probe so the
    test does not depend on whatever a real eSim install left on THIS box."""
    real_isfile = os.path.isfile
    monkeypatch.setattr(
        os.path, "isfile",
        lambda p: False if "/usr/share" in p else real_isfile(p))


# ── (a) path + dir creation ────────────────────────────────────────────────

def test_generated_symlib_path_location_and_dir(tmp_path, monkeypatch):
    home = _redirect_home(tmp_path, monkeypatch)
    _block_default_probe(monkeypatch)
    p = ksym.generated_symlib_path("eSim_Ngveri")
    assert p == os.path.join(str(home), ".esim", "kicad_symbols",
                             "eSim_Ngveri.kicad_sym")
    # dir created on demand, even though the file itself is not yet written.
    assert os.path.isdir(os.path.join(str(home), ".esim", "kicad_symbols"))
    assert not os.path.exists(p)


# ── (b) lazy migration ─────────────────────────────────────────────────────

def test_migration_copies_legacy_once(tmp_path, monkeypatch):
    _redirect_home(tmp_path, monkeypatch)
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy = legacy_dir / "eSim_Ngveri.kicad_sym"
    legacy.write_text("LEGACY MODELS\n")

    p = ksym.generated_symlib_path("eSim_Ngveri", legacy_dirs=[str(legacy_dir)])
    # migrated in, preserving the user's accumulated models.
    assert open(p).read() == "LEGACY MODELS\n"
    # legacy file left behind on purpose (never moved).
    assert legacy.exists()


def test_migration_never_overwrites_existing_new_file(tmp_path, monkeypatch):
    home = _redirect_home(tmp_path, monkeypatch)
    gendir = os.path.join(str(home), ".esim", "kicad_symbols")
    os.makedirs(gendir)
    new = os.path.join(gendir, "eSim_Ngveri.kicad_sym")
    with open(new, "w") as f:
        f.write("NEW MODELS\n")

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "eSim_Ngveri.kicad_sym").write_text("STALE LEGACY\n")

    p = ksym.generated_symlib_path("eSim_Ngveri", legacy_dirs=[str(legacy_dir)])
    # new file wins: migration is a one-time thing, never a clobber.
    assert open(p).read() == "NEW MODELS\n"


def test_migration_absent_legacy_is_noop(tmp_path, monkeypatch):
    _redirect_home(tmp_path, monkeypatch)
    _block_default_probe(monkeypatch)
    p = ksym.generated_symlib_path("eSim_Nghdl", legacy_dirs=[str(tmp_path)])
    assert not os.path.exists(p)     # nothing to migrate -> file not created


# ── (c) ensure_lib_registered ──────────────────────────────────────────────

_HEADER = ("(sym_lib_table\n"
           "  (version 7)\n")


def _kicad_verdir(tmp_path, monkeypatch):
    """Create the KiCad ``<ver>`` config dir under the redirected HOME.

    The version dir is derived from ``ksym._kicad_config_dir()`` — NOT a
    hardcoded ``~/.config/kicad`` — so it lands exactly where
    ``ensure_lib_registered`` will look on both platforms (``%APPDATA%\\kicad``
    on Windows, ``~/.config/kicad`` on POSIX). Hardcoding the POSIX path was the
    The test once wrote here while the code read the real %APPDATA%, so the
    append/rewrite assertions failed on Windows and the real profile got junked.
    """
    _redirect_home(tmp_path, monkeypatch)
    verdir = os.path.join(ksym._kicad_config_dir(), "9.0")
    os.makedirs(verdir)
    return verdir


def _make_table(tmp_path, monkeypatch, body):
    """Build a sym-lib-table in that version dir with the given body."""
    verdir = _kicad_verdir(tmp_path, monkeypatch)
    table = os.path.join(verdir, "sym-lib-table")
    with open(table, "w") as f:
        f.write(_HEADER + body + ")\n")
    return table


def test_register_appends_when_absent(tmp_path, monkeypatch):
    table = _make_table(
        tmp_path, monkeypatch,
        '  (lib (name "Device")(type "KiCad")'
        '(uri "${KICAD6_SYMBOL_DIR}/Device.kicad_sym")(options "")(descr ""))\n')
    ksym.ensure_lib_registered("eSim_Ngveri", "/home/u/.esim/x.kicad_sym",
                               descr="d")
    content = open(table).read()
    assert '(name "eSim_Ngveri")' in content
    assert '(uri "/home/u/.esim/x.kicad_sym")' in content
    # existing entry untouched, table still ends with the closing paren.
    assert '(name "Device")' in content
    assert content.rstrip().endswith(")")


def test_register_rewrites_stale_uri(tmp_path, monkeypatch):
    table = _make_table(
        tmp_path, monkeypatch,
        '  (lib (name "eSim_Ngveri")(type "KiCad")'
        '(uri "${KICAD6_SYMBOL_DIR}/eSim_Ngveri.kicad_sym")'
        '(options "")(descr ""))\n')
    ksym.ensure_lib_registered("eSim_Ngveri", "/home/u/.esim/eSim_Ngveri.kicad_sym")
    content = open(table).read()
    assert "${KICAD6_SYMBOL_DIR}" not in content
    assert '(uri "/home/u/.esim/eSim_Ngveri.kicad_sym")' in content
    # exactly one entry — rewritten in place, not appended.
    assert content.count('(name "eSim_Ngveri")') == 1


def test_register_leaves_correct_entry_untouched(tmp_path, monkeypatch):
    good = "/home/u/.esim/eSim_Ngveri.kicad_sym"
    table = _make_table(
        tmp_path, monkeypatch,
        '  (lib (name "eSim_Ngveri")(type "KiCad")'
        '(uri "%s")(options "")(descr "keep"))\n' % good)
    before = open(table).read()
    ksym.ensure_lib_registered("eSim_Ngveri", good, descr="other")
    assert open(table).read() == before      # byte-for-byte unchanged


def test_register_no_config_dir_is_noop(tmp_path, monkeypatch):
    _redirect_home(tmp_path, monkeypatch)     # no ~/.config/kicad created
    # must not raise.
    ksym.ensure_lib_registered("eSim_Ngveri", "/x")


def test_register_rewrite_is_atomic_and_leaves_no_temp(tmp_path, monkeypatch):
    # A crash part-way through the sym-lib-table rewrite used to truncate the
    # user's library table, after which EVERY KiCad launch errors. The rewrite
    # now goes through _atomic_write, so a failure must leave the old table
    # byte-for-byte intact and drop no scratch file in the version dir.
    table = _make_table(
        tmp_path, monkeypatch,
        '  (lib (name "eSim_Ngveri")(type "KiCad")'
        '(uri "${KICAD6_SYMBOL_DIR}/eSim_Ngveri.kicad_sym")'
        '(options "")(descr ""))\n')
    before = open(table).read()
    verdir = os.path.dirname(table)

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(ksym.os, "replace", boom)
    # ensure_lib_registered is best-effort: it swallows OSError by contract.
    ksym.ensure_lib_registered("eSim_Ngveri", "/home/u/.esim/x.kicad_sym")

    assert open(table).read() == before
    assert [n for n in os.listdir(verdir)
            if n.startswith(".eSim_atomic_")] == []


def test_register_seeds_missing_table_without_temp(tmp_path, monkeypatch):
    # KiCad does not write a per-user sym-lib-table until libraries are managed
    # once; eSim seeds one. That seed is atomic too, so a half-written
    # "(sym_lib_table" can never be left behind.
    verdir = _kicad_verdir(tmp_path, monkeypatch)
    ksym.ensure_lib_registered("eSim_Ngveri", "/home/u/.esim/x.kicad_sym")
    content = open(os.path.join(verdir, "sym-lib-table")).read()
    assert content.startswith("(sym_lib_table")
    assert '(name "eSim_Ngveri")' in content
    assert content.rstrip().endswith(")")
    assert [n for n in os.listdir(verdir)
            if n.startswith(".eSim_atomic_")] == []


def test_register_does_not_match_similar_prefix(tmp_path, monkeypatch):
    # eSim_Ngveri must not clobber the eSim_NgVeriCosim entry (shared prefix).
    table = _make_table(
        tmp_path, monkeypatch,
        '  (lib (name "eSim_NgVeriCosim")(type "KiCad")'
        '(uri "${KICAD6_SYMBOL_DIR}/eSim_NgVeriCosim.kicad_sym")'
        '(options "")(descr "cosim"))\n')
    ksym.ensure_lib_registered("eSim_Ngveri", "/home/u/.esim/eSim_Ngveri.kicad_sym")
    content = open(table).read()
    # cosim entry preserved unchanged, ngveri appended fresh.
    assert '(name "eSim_NgVeriCosim")' in content
    assert "${KICAD6_SYMBOL_DIR}/eSim_NgVeriCosim.kicad_sym" in content
    assert '(uri "/home/u/.esim/eSim_Ngveri.kicad_sym")' in content
