"""Tests for windows/uninstall_cleanup.py.

Like windows_bootstrap.py, the cleanup is deliberately OS-independent stdlib
code so these run on Linux CI even though only the Windows uninstaller (and
Ubuntu's install-eSim.sh --uninstall) calls it. HOME and APPDATA are
redirected to tmp_path throughout -- the developer's real ~/.esim and KiCad
table are never touched.

The thing under test is a DELETING script, so every case pins down what must
survive as tightly as what must go.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import uninstall_cleanup as uc  # noqa: E402


TABLE_HEAD = '(sym_lib_table\n  (version 7)\n'
TABLE_TAIL = ')\n'


def row(name, uri):
    return ('  (lib (name "%s")(type "KiCad")(uri "%s")'
            '(options "")(descr ""))\n' % (name, uri))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(h), 1))
    appdata = h / "AppData"
    (appdata / "kicad" / "9.0").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    return h


@pytest.fixture
def install(tmp_path):
    """The install tree being uninstalled (its files are already gone as far
    as this script cares -- only the path matters)."""
    return tmp_path / "FOSSEE" / "eSim"


@pytest.fixture
def table(home):
    return home / "AppData" / "kicad" / "9.0" / "sym-lib-table"


def write_table(path, rows):
    path.write_text(TABLE_HEAD + "".join(rows) + TABLE_TAIL)


def read_names(path):
    return [line.split('"')[1] for line in path.read_text().splitlines()
            if "(lib (name" in line]


# --------------------------------------------------------------------------
# sym-lib-table rows
# --------------------------------------------------------------------------

def test_install_tree_rows_go_user_rows_stay(home, install, table, tmp_path):
    mine = tmp_path / "my_libs" / "eSim_MyOwn.kicad_sym"
    write_table(table, [
        row("eSim_Devices",
            str(install / "library" / "kicadLibrary" / "eSim-symbols"
                / "eSim_Devices.kicad_sym")),
        row("eSim_Analog",
            str(install / "library" / "kicadLibrary" / "eSim-symbols"
                / "eSim_Analog.kicad_sym")),
        row("Bundled_Device",
            str(install / "tools" / "kicad" / "share" / "kicad" /
                "symbols" / "Device.kicad_sym")),
        row("Device", "${KICAD9_SYMBOL_DIR}/Device.kicad_sym"),
        row("eSim_MyOwn", str(mine)),
    ])

    assert uc.clean_sym_lib_table(str(table), str(install)) == 3

    # KiCad's own library survives, and so does an eSim_* library the user
    # keeps somewhere of their own -- eSim never put it there.
    assert read_names(table) == ["Device", "eSim_MyOwn"]
    assert table.read_text().startswith(TABLE_HEAD)
    assert table.read_text().endswith(TABLE_TAIL)


def test_generated_rows_follow_the_user_data_answer(home, install, table):
    gen = home / ".esim" / "kicad_symbols" / "eSim_Ngveri.kicad_sym"
    rows = [
        row("eSim_Devices", str(install / "library" / "kicadLibrary"
                                / "eSim-symbols" / "eSim_Devices.kicad_sym")),
        row("eSim_Ngveri", str(gen)),
    ]

    write_table(table, rows)
    # Keeping ~/.esim keeps the models the user built usable from a plain
    # KiCad, so their row must stay pointing at a file that still exists.
    assert uc.clean_sym_lib_table(str(table), str(install)) == 1
    assert read_names(table) == ["eSim_Ngveri"]

    write_table(table, rows)
    assert uc.clean_sym_lib_table(str(table), str(install),
                                  purge_user_data=True) == 2
    assert read_names(table) == []


def test_static_legacy_rows_follow_the_user_data_answer(home, install, table):
    static = home / ".esim" / "kicad_static" / "legacy"
    write_table(table, [
        row("eSim_PSpice", str(static / "eSim_PSpice.lib")),
        row("CONNECT", str(static / "CONNECT.lib")),
    ])
    assert uc.clean_sym_lib_table(str(table), str(install)) == 0
    assert read_names(table) == ["eSim_PSpice", "CONNECT"]

    assert uc.clean_sym_lib_table(str(table), str(install),
                                  purge_user_data=True) == 2
    assert read_names(table) == []


def test_legacy_kicad_symbol_dir_rows_go(home, install, table):
    write_table(table, [
        row("eSim_Nghdl", "${KICAD6_SYMBOL_DIR}/eSim_Nghdl.kicad_sym"),
        row("Device", "${KICAD6_SYMBOL_DIR}/Device.kicad_sym"),
    ])
    assert uc.clean_sym_lib_table(str(table), str(install)) == 1
    assert read_names(table) == ["Device"]


def test_idempotent_and_dry_run(home, install, table):
    write_table(table, [
        row("eSim_Devices", str(install / "lib" / "eSim_Devices.kicad_sym")),
    ])
    before = table.read_text()

    assert uc.clean_sym_lib_table(str(table), str(install),
                                  dry_run=True) == 1
    assert table.read_text() == before          # dry run writes nothing

    assert uc.clean_sym_lib_table(str(table), str(install)) == 1
    after = table.read_text()
    assert uc.clean_sym_lib_table(str(table), str(install)) == 0
    assert table.read_text() == after           # second pass is a no-op


def test_forward_slash_and_case_variants_still_match(home, install, table):
    uri = str(install / "library" / "eSim_Devices.kicad_sym").replace(
        "\\", "/")
    if os.name == "nt":
        uri = uri.upper()
    write_table(table, [row("eSim_Devices", uri)])
    assert uc.clean_sym_lib_table(str(table), str(install)) == 1
    assert read_names(table) == []


def test_unwritable_table_is_reported_not_raised(home, install, tmp_path):
    missing = tmp_path / "nope" / "sym-lib-table"
    assert uc.clean_sym_lib_table(str(missing), str(install)) == -1


def test_every_version_dir_is_visited(home, install):
    base = home / "AppData" / "kicad"
    (base / "8.0").mkdir()
    for ver in ("8.0", "9.0"):
        write_table(base / ver / "sym-lib-table",
                    [row("eSim_Devices",
                         str(install / "lib" / "eSim_Devices.kicad_sym"))])
    report = uc.clean_kicad_tables(str(install))
    assert sorted(n for _, n in report) == [1, 1]


# --------------------------------------------------------------------------
# ~/.esim and ~/.nghdl
# --------------------------------------------------------------------------

def test_user_dirs_only_go_when_asked(home):
    (home / ".esim" / "kicad_symbols").mkdir(parents=True)
    (home / ".esim" / "config.ini").write_text("[eSim]\n")
    (home / ".nghdl").mkdir()
    (home / "eSim-Workspace" / "MyProject").mkdir(parents=True)

    assert uc.purge_user_dirs(dry_run=True) == [
        str(home / ".esim"), str(home / ".nghdl")]
    assert (home / ".esim").is_dir()            # dry run deleted nothing

    uc.purge_user_dirs()
    assert not (home / ".esim").exists()
    assert not (home / ".nghdl").exists()
    # The user's projects are never in scope, whatever they answered.
    assert (home / "eSim-Workspace" / "MyProject").is_dir()


def test_purge_is_a_no_op_when_nothing_is_there(home):
    assert uc.purge_user_dirs() == []


# --------------------------------------------------------------------------
# the KiCad config skeleton eSim itself creates
# --------------------------------------------------------------------------

def test_seeded_empty_config_dir_is_pruned(home, install, table):
    write_table(table, [row("eSim_Devices",
                            str(install / "lib" / "eSim_Devices.kicad_sym"))])
    uc.clean_kicad_tables(str(install))
    dropped = uc.prune_empty_kicad_config()
    assert str(table.parent) in dropped
    assert not table.parent.exists()
    # ...and the kicad root with it, since eSim created that too.
    assert not (home / "AppData" / "kicad").exists()


def test_real_kicad_config_is_left_alone(home, install, table):
    write_table(table, [
        row("eSim_Devices", str(install / "lib" / "eSim_Devices.kicad_sym")),
        row("Device", "${KICAD9_SYMBOL_DIR}/Device.kicad_sym"),
    ])
    (table.parent / "kicad_common.json").write_text("{}\n")
    uc.clean_kicad_tables(str(install))
    assert uc.prune_empty_kicad_config() == []
    assert table.is_file()
    assert (table.parent / "kicad_common.json").is_file()


def test_empty_table_with_other_settings_beside_it_stays(home):
    vdir = home / "AppData" / "kicad" / "9.0"
    (vdir / "sym-lib-table").write_text(TABLE_HEAD + TABLE_TAIL)
    (vdir / "fp-lib-table").write_text("(fp_lib_table\n)\n")
    assert uc.prune_empty_kicad_config() == []
    assert (vdir / "sym-lib-table").is_file()


# --------------------------------------------------------------------------
# the entry point the uninstaller actually calls
# --------------------------------------------------------------------------

def test_main_cleans_everything_and_never_fails(home, install, table):
    write_table(table, [
        row("eSim_Devices", str(install / "lib" / "eSim_Devices.kicad_sym")),
        row("eSim_Ngveri",
            str(home / ".esim" / "kicad_symbols" / "eSim_Ngveri.kicad_sym")),
    ])
    (home / ".esim").mkdir()
    (home / ".nghdl").mkdir()

    assert uc.main(["--esim-root", str(install)]) == 0
    assert read_names(table) == ["eSim_Ngveri"]
    assert (home / ".esim").is_dir()            # not asked for, not touched

    assert uc.main(["--esim-root", str(install), "--purge-user-data"]) == 0
    assert not (home / ".esim").exists()
    assert not (home / ".nghdl").exists()
    assert not table.exists()                   # skeleton pruned with it


def test_main_survives_a_missing_kicad_config(home, install, monkeypatch):
    monkeypatch.setenv("APPDATA", str(home / "does-not-exist"))
    assert uc.main(["--esim-root", str(install), "--purge-user-data"]) == 0
