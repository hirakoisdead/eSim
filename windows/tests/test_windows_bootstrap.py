"""Tests for windows/windows_bootstrap.py.

The bootstrap is deliberately OS-independent stdlib code so these tests run
on Linux CI even though only Windows ships the script. HOME is redirected to
tmp_path throughout -- the real ~/.esim and ~/.config are never touched.
"""

import configparser
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

import windows_bootstrap as wb  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(h), 1))
    # On Windows _kicad_config_root() resolves via APPDATA; without this the
    # KiCad-table tests read -- and WRITE -- the developer's real
    # %APPDATA%\kicad. Redirect it so every test is hermetic on both OSes.
    appdata = h / "AppData"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    return h


@pytest.fixture
def root(tmp_path):
    """A minimal fake eSim install root."""
    r = tmp_path / "eSim"
    sym = r / "library" / "kicadLibrary" / "eSim-symbols"
    sym.mkdir(parents=True)
    for lib in ("eSim_Devices", "eSim_Ngveri", "eSim_NgVeriCosim",
                "eSim_Nghdl"):
        (sym / (lib + ".kicad_sym")).write_text(
            '(kicad_symbol_lib (version 20211014) '
            '(generator kicad_symbol_editor)\n)\n')
    # Real helper module, so registration logic is the shipped one.
    maker = r / "src" / "maker"
    maker.mkdir(parents=True)
    shutil.copy2(os.path.join(REPO, "src", "maker", "kicad_symlib.py"), maker)
    return r


def test_config_written_and_home_rewritten(home, root):
    path = wb.write_esim_config(str(root))
    cfg = configparser.ConfigParser()
    cfg.read(path)
    assert cfg.get("eSim", "eSim_HOME") == str(root)
    # A moved install self-heals on next launch.
    moved = str(root) + "-moved"
    cfg2 = configparser.ConfigParser()
    cfg2.read(wb.write_esim_config(moved))
    assert cfg2.get("eSim", "eSim_HOME") == moved


def test_seed_never_clobbers(home, root):
    dst = wb.seed_generated_symbols(str(root))
    seeded = os.path.join(dst, "eSim_Ngveri.kicad_sym")
    assert os.path.isfile(seeded)
    # Static libs are NOT copied to the per-user dir.
    assert not os.path.exists(os.path.join(dst, "eSim_Devices.kicad_sym"))
    with open(seeded, "w") as fh:
        fh.write("USER MODELS")
    wb.seed_generated_symbols(str(root))
    assert open(seeded).read() == "USER MODELS"


def test_nghdl_config_needs_some_toolchain(home, root):
    """No tools/nghdl and no tools/msys64 -> nothing to describe."""
    assert wb.write_nghdl_config(str(root)) is None


def test_nghdl_config_msys_only(home, root):
    """Compact-ish install: MSYS2 present, no built nghdl tree -> only the
    COMPILER section is written (no keys pointing at missing dirs)."""
    (root / "tools" / "msys64").mkdir(parents=True)
    path = wb.write_nghdl_config(str(root))
    cfg = configparser.ConfigParser()
    cfg.read(path)
    assert cfg.get("COMPILER", "MSYS_HOME") == str(root / "tools" / "msys64")
    assert not cfg.has_section("NGHDL")


def test_nghdl_config_full_install(home, root):
    """Full install: every key the nghdl python + CosimConfig read, with
    absolute paths mirroring the Ubuntu installer's config."""
    nghdl = root / "tools" / "nghdl"
    nghdl.mkdir(parents=True)
    (root / "tools" / "msys64").mkdir(parents=True)
    ivbin = root / "library" / "bin" / "iverilog" / "bin"
    ivbin.mkdir(parents=True)
    (ivbin / "iverilog.exe").write_text("")
    (ivbin / "vvp.exe").write_text("")
    (ivbin / "libvvp-2.dll").write_text("")   # mingw: DLLs land in bin/

    path = wb.write_nghdl_config(str(root))
    cfg = configparser.ConfigParser()
    cfg.read(path)
    assert cfg.get("NGHDL", "NGHDL_HOME") == str(nghdl)
    assert cfg.get("NGHDL", "DIGITAL_MODEL") == str(
        nghdl / "src" / "xspice" / "icm")
    assert cfg.get("NGHDL", "RELEASE") == str(nghdl / "release")
    assert cfg.get("SRC", "SRC_HOME") == str(root / "nghdl")
    assert cfg.get("SRC", "LICENSE") == str(root / "nghdl" / "LICENSE")
    assert cfg.get("COMPILER", "MSYS_HOME") == str(root / "tools" / "msys64")
    assert cfg.get("COSIM", "IVERILOG") == str(ivbin / "iverilog.exe")
    assert cfg.get("COSIM", "IVERILOG_LIB") == str(ivbin)


def test_fix_spinit_rewrites_codemodel_paths(home, root):
    """Build-machine absolute codemodel paths get repointed at THIS install,
    idempotently."""
    inst = root / "tools" / "nghdl" / "install_dir"
    scripts = inst / "share" / "ngspice" / "scripts"
    scripts.mkdir(parents=True)
    cmdir = inst / "lib" / "ngspice"
    cmdir.mkdir(parents=True)
    (scripts / "spinit").write_text(
        "* Standard ngspice init file\n"
        "codemodel C:/buildbot/stage/eSim/tools/nghdl/install_dir/lib/"
        "ngspice/analog.cm\n"
        "codemodel C:/buildbot/stage/eSim/tools/nghdl/install_dir/lib/"
        "ngspice/ghdl.cm\n"
        "set num_threads=2\n")
    changed = wb.fix_spinit(str(root))
    assert changed == 2
    text = (scripts / "spinit").read_text()
    want = str(cmdir).replace("\\", "/") + "/analog.cm"
    assert "codemodel " + want in text
    assert "buildbot" not in text
    assert "set num_threads=2" in text          # untouched lines survive
    # Second run: nothing left to rewrite.
    assert wb.fix_spinit(str(root)) == 0


def test_fix_spinit_absent_tree_is_noop(home, root):
    assert wb.fix_spinit(str(root)) == 0


def test_fix_spinit_rewrite_is_atomic(home, root, monkeypatch):
    """spinit is how ngspice locates EVERY .cm code model, so a rewrite that
    dies part-way leaves a truncated file and then every simulation fails with
    "codemodel not found" -- nowhere near this code. The rewrite goes through
    kicad_symlib._atomic_write (temp file + os.replace), so a failure must
    leave the previous spinit byte-for-byte intact and drop no scratch file."""
    inst = root / "tools" / "nghdl" / "install_dir"
    scripts = inst / "share" / "ngspice" / "scripts"
    scripts.mkdir(parents=True)
    (inst / "lib" / "ngspice").mkdir(parents=True)
    original = ("* Standard ngspice init file\n"
                "codemodel C:/buildbot/stage/lib/ngspice/analog.cm\n")
    (scripts / "spinit").write_text(original)

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        wb.fix_spinit(str(root))

    assert (scripts / "spinit").read_text() == original
    assert [n for n in os.listdir(str(scripts))
            if n.startswith(".eSim_atomic_")] == []


def test_register_appends_and_repoints(home, root, kicad_config_root):
    # A KiCad user table with one stale eSim entry.
    kdir = kicad_config_root / "9.0"
    kdir.mkdir(parents=True)
    table = kdir / "sym-lib-table"
    table.write_text(
        '(sym_lib_table\n'
        '  (lib (name "eSim_Ngveri")(type "KiCad")'
        '(uri "${KICAD6_SYMBOL_DIR}/eSim_Ngveri.kicad_sym")'
        '(options "")(descr ""))\n'
        ')\n')
    wb.seed_generated_symbols(str(root))
    assert wb.register_kicad_libraries(str(root)) is True
    content = table.read_text()
    # Stale generated-lib uri repointed to ~/.esim/kicad_symbols.
    assert "${KICAD6_SYMBOL_DIR}/eSim_Ngveri" not in content
    assert os.path.join(".esim", "kicad_symbols",
                        "eSim_Ngveri.kicad_sym") in content
    # Static lib appended, referenced in place from the install dir.
    assert "eSim_Devices" in content
    assert str(root) in content
    legacy = root / "library" / "kicadLibrary" / "eSim-symbols" / "legacy"
    legacy.mkdir()
    (legacy / "eSim_PSpice.lib").write_text("EESchema-LIBRARY Version 2.4\n")
    assert wb.register_kicad_libraries(str(root)) is True
    content = table.read_text()
    assert '(name "eSim_PSpice")' in content
    assert str(legacy / "eSim_PSpice.lib") in content
    # Idempotent: second run changes nothing.
    wb.register_kicad_libraries(str(root))
    assert table.read_text() == content


def test_register_no_kicad_config_is_noop(home, root):
    assert wb.register_kicad_libraries(str(root)) is False
    assert wb.register_kicad_stock_libraries(str(root)) is False


@pytest.fixture
def kicad_config_root(home):
    """Where _kicad_config_root() resolves under the hermetic `home` fixture:
    APPDATA drives it on Windows, HOME/.config elsewhere."""
    if os.name == "nt":
        return home / "AppData" / "kicad"
    return home / ".config" / "kicad"


def _write_bundled_kicad_template(root):
    kdir = root / "tools" / "kicad"
    template = kdir / "share" / "kicad" / "template"
    symbols = kdir / "share" / "kicad" / "symbols"
    template.mkdir(parents=True)
    symbols.mkdir(parents=True)
    (kdir / "KICAD-VERSION").write_text("9.0.3\n")
    (template / "sym-lib-table").write_text(
        '(sym_lib_table\n'
        '  (version 7)\n'
        '  (lib (name "74xx")(type "KiCad")'
        '(uri "${KICAD9_SYMBOL_DIR}/74xx.kicad_sym")'
        '(options "")(descr "74xx symbols"))\n'
        '  (lib (name "Device")(type "KiCad")'
        '(uri "${KICAD9_SYMBOL_DIR}/Device.kicad_sym")'
        '(options "")(descr "Generic symbols"))\n'
        ')\n')
    for name in ("74xx", "Device"):
        (symbols / (name + ".kicad_sym")).write_text("(kicad_symbol_lib)\n")
    return template / "sym-lib-table"


def test_stock_libraries_are_visible_but_disabled(home, root,
                                                  kicad_config_root):
    _write_bundled_kicad_template(root)
    other = kicad_config_root / "8.0"
    other.mkdir(parents=True)
    other_table = other / "sym-lib-table"
    other_table.write_text('(sym_lib_table\n  (version 7)\n)\n')

    wb.ensure_kicad_config_dir(str(root))
    assert wb.register_kicad_stock_libraries(str(root)) is True
    table = kicad_config_root / "9.0" / "sym-lib-table"
    content = table.read_text()

    assert str(root / "tools" / "kicad" / "share" / "kicad" / "symbols" /
               "74xx.kicad_sym") in content
    assert str(root / "tools" / "kicad" / "share" / "kicad" / "symbols" /
               "Device.kicad_sym") in content
    assert '${KICAD9_SYMBOL_DIR}' not in content
    assert content.count('(disabled)') == 2
    assert '(hidden)' not in content
    assert '74xx symbols' in content
    assert other_table.read_text() == '(sym_lib_table\n  (version 7)\n)\n'

    wb.seed_generated_symbols(str(root))
    wb.register_kicad_libraries(str(root))
    content = table.read_text()
    esim_row = next(line for line in content.splitlines()
                    if '(name "eSim_Devices")' in line)
    assert '(disabled)' not in esim_row
    assert '(hidden)' not in esim_row


def test_stock_registration_preserves_user_activation(home, root,
                                                      kicad_config_root):
    template = _write_bundled_kicad_template(root)
    wb.ensure_kicad_config_dir(str(root))
    wb.register_kicad_stock_libraries(str(root))
    table = kicad_config_root / "9.0" / "sym-lib-table"

    enabled = table.read_text().replace('(disabled)', '', 1)
    table.write_text(enabled)
    template_content = template.read_text()
    close = template_content.rstrip().rfind(')')
    power_row = (
        '  (lib (name "Power")(type "KiCad")'
        '(uri "${KICAD9_SYMBOL_DIR}/Power.kicad_sym")'
        '(options "")(descr "Power symbols"))\n')
    template.write_text(template_content[:close] + power_row +
                        template_content[close:])

    assert wb.register_kicad_stock_libraries(str(root)) is True
    content = table.read_text()
    row_74xx = next(line for line in content.splitlines()
                    if '(name "74xx")' in line)
    row_power = next(line for line in content.splitlines()
                     if '(name "Power")' in line)
    assert '(disabled)' not in row_74xx
    assert '(disabled)' in row_power
    assert content.count('(name "74xx")') == 1

    wb.register_kicad_stock_libraries(str(root))
    assert table.read_text() == content


def test_kicad_config_dir_from_bundled_stamp(home, root, kicad_config_root):
    # No bundled KiCad (dev tree): no-op.
    assert wb.ensure_kicad_config_dir(str(root)) is None
    # Stamped bundled KiCad: %APPDATA%/kicad/<major.minor> gets created...
    kdir = root / "tools" / "kicad"
    kdir.mkdir(parents=True)
    (kdir / "KICAD-VERSION").write_text("9.0.3\n")
    made = wb.ensure_kicad_config_dir(str(root))
    assert made == str(kicad_config_root / "9.0")
    assert os.path.isdir(made)
    # ...so first-launch registration now has a version dir to seed.
    wb.seed_generated_symbols(str(root))
    assert wb.register_kicad_libraries(str(root)) is True
    table = kicad_config_root / "9.0" / "sym-lib-table"
    assert "eSim_Devices" in table.read_text()
    # Garbage stamp: no-op, never a crash at launch.
    (kdir / "KICAD-VERSION").write_text("not-a-version")
    assert wb.ensure_kicad_config_dir(str(root)) is None


def test_main_runs_everything(home, root):
    assert wb.main(["--esim-root", str(root)]) == 0
    assert (home / ".esim" / "config.ini").is_file()
    assert (home / ".esim" / "kicad_symbols" /
            "eSim_Nghdl.kicad_sym").is_file()


def test_main_isolates_a_failing_step(home, root, monkeypatch, capsys):
    """A self-heal that cannot write must not cost the user the LATER steps.

    installer.iss no longer grants users-modify on the whole {app} tree (only
    tools\\nghdl and library\\modelParamXML), so a step touching the install
    tree can now legitimately raise PermissionError. Run straight-line, that
    aborted everything after it -- most damagingly register_kicad_libraries,
    leaving eSim's symbols missing from KiCad with nothing pointing at the
    real cause."""
    def boom(_root):
        raise PermissionError(13, "Access is denied", "spinit")

    monkeypatch.setattr(wb, "fix_spinit", boom)
    rc = wb.main(["--esim-root", str(root)])

    assert rc == 1, "a failed step must be reported in the exit code"
    out = capsys.readouterr().out
    assert "spinit code-model paths skipped" in out
    assert "PermissionError" in out
    # Steps before AND after the failure still ran.
    assert (home / ".esim" / "config.ini").is_file()
    assert (home / ".esim" / "kicad_symbols" /
            "eSim_Nghdl.kicad_sym").is_file()


def test_main_survives_every_step_failing(home, root, monkeypatch):
    """Worst case (a wholly read-only install): still no traceback out of
    main(), because launcher_windows.run_bootstrap treats a raise as 'skip
    bootstrap entirely' -- which would be a far bigger regression."""
    for name in ("write_esim_config", "seed_generated_symbols",
                 "write_nghdl_config", "fix_spinit",
                 "ensure_unversioned_libvvp", "ensure_kicad_config_dir",
                 "register_kicad_stock_libraries",
                 "register_kicad_libraries"):
        monkeypatch.setattr(wb, name, lambda _root: (_ for _ in ()).throw(
            OSError("read-only install")))
    assert wb.main(["--esim-root", str(root)]) == 1
