"""Unit tests for the ToolchainCheck doctor.

The doctor is the single dependency gate for every simulation flow (CLI
--doctor, Help-menu dialog, and the pre-flow require() calls), so its probing
logic is pinned down here on Linux with fake install trees, a fake HOME and a
monkeypatched PATH -- including the Windows-only branches (MSYS2/mintty and
the mingw64 tool resolution), which run anywhere because the module reads
os.name lazily through _win().
"""
import importlib
import os
import stat

import pytest

from maker import CosimConfig, ToolchainCheck


def _make_tool(dirpath, name, output="tool version 1.0"):
    """Create a fake executable that answers any invocation with `output`."""
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, name)
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\necho '%s'\n" % output)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Isolated HOME, empty PATH, no ESIM_* overrides; reloaded modules."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "emptybin"))
    for var in ("ESIM_IVERILOG", "ESIM_VVP", "ESIM_NGSPICE",
                "ESIM_IVERILOG_LIB"):
        monkeypatch.delenv(var, raising=False)
    importlib.reload(CosimConfig)
    importlib.reload(ToolchainCheck)
    return tmp_path


def _write_nghdl_config(home, body):
    cfg_dir = os.path.join(str(home), ".nghdl")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "config.ini"), "w") as fh:
        fh.write(body)


def _full_linux_tree(home):
    """Build a complete fake Ubuntu install: nghdl-simulator prefix with
    ngspice + code models (ivlng, ghdl.cm), iverilog prefix with libvvp,
    build tools on PATH, non-mcode ghdl."""
    nghdl_home = os.path.join(str(home), "nghdl-simulator")
    bindir = os.path.join(nghdl_home, "install_dir", "bin")
    _make_tool(bindir, "ngspice", "ngspice-45.2")
    cmdir = os.path.join(nghdl_home, "install_dir", "lib", "ngspice")
    os.makedirs(cmdir)
    for cm in ("analog.cm", "digital.cm", "ghdl.cm", "Ngveri.cm",
               "ivlng.so"):
        open(os.path.join(cmdir, cm), "w").close()
    release_icm = os.path.join(nghdl_home, "release", "src", "xspice", "icm")
    os.makedirs(release_icm)

    iv_prefix = os.path.join(str(home), "nghdl-simulator", "iverilog")
    _make_tool(os.path.join(iv_prefix, "bin"), "iverilog",
               "Icarus Verilog version 12.0")
    _make_tool(os.path.join(iv_prefix, "bin"), "vvp", "vvp 12.0")
    libdir = os.path.join(iv_prefix, "lib")
    os.makedirs(libdir)
    open(os.path.join(libdir, "libvvp.so"), "w").close()

    toolbin = os.path.join(str(home), "usrbin")
    _make_tool(toolbin, "verilator", "Verilator 5.020")
    _make_tool(toolbin, "make", "GNU Make 4.3")
    _make_tool(toolbin, "gcc", "gcc 14.2.0")
    _make_tool(toolbin, "ghdl", "GHDL 4.0.0 llvm code generator")

    _write_nghdl_config(home, (
        "[NGHDL]\n"
        "NGHDL_HOME = %(h)s\n"
        "DIGITAL_MODEL = %(h)s/src/xspice/icm\n"
        "RELEASE = %(h)s/release\n"
        "[SRC]\n"
        "SRC_HOME = /src\n"
        "[COSIM]\n"
        "IVERILOG = %(iv)s/bin/iverilog\n"
        "VVP = %(iv)s/bin/vvp\n"
        "IVERILOG_LIB = %(iv)s/lib\n"
    ) % {"h": nghdl_home.replace("%", "%%"),
         "iv": iv_prefix.replace("%", "%%")})
    return nghdl_home, toolbin


class TestHealthyTree:
    def test_all_green(self, fake_env, monkeypatch):
        _, toolbin = _full_linux_tree(fake_env)
        monkeypatch.setenv("PATH", toolbin)
        assert ToolchainCheck.failures() == []
        assert ToolchainCheck.ok_for(ToolchainCheck.DCOSIM)
        assert ToolchainCheck.ok_for(ToolchainCheck.NGHDL)
        assert ToolchainCheck.failure_message(ToolchainCheck.NGVERI) == ""

    def test_report_mentions_all_ok(self, fake_env, monkeypatch):
        _, toolbin = _full_linux_tree(fake_env)
        monkeypatch.setenv("PATH", toolbin)
        text = ToolchainCheck.report()
        assert "All checks passed." in text
        assert "MISSING" not in text


class TestEmptySystem:
    def test_everything_missing(self, fake_env):
        bad = {c.key for c in ToolchainCheck.failures()}
        # ngspice resolver falls back to the bare name; the file check fails.
        assert "codemodel_dir" in bad
        assert "ivlng" in bad
        assert "iverilog" in bad
        assert "verilator" in bad
        assert "ghdl" in bad
        assert "nghdl_config" in bad

    def test_flow_filter_scopes_checks(self, fake_env):
        keys = {c.key for c in ToolchainCheck.run_checks(
            ToolchainCheck.VERIFIER)}
        assert "iverilog" in keys and "vvp" in keys
        assert "ghdl" not in keys          # verifier does not need GHDL
        assert "verilator" not in keys     # nor Verilator

    def test_failure_message_has_paths_and_hints(self, fake_env):
        msg = ToolchainCheck.failure_message(ToolchainCheck.DCOSIM)
        assert "probed:" in msg
        assert "fix" in msg
        assert "d_cosim" in msg

    def test_report_lists_affected_flows(self, fake_env):
        text = ToolchainCheck.report()
        assert "problem(s) found" in text
        assert "MISSING" in text


class TestGhdlBackendTrap:
    def test_mcode_backend_rejected(self, fake_env, monkeypatch):
        toolbin = os.path.join(str(fake_env), "usrbin")
        _make_tool(toolbin, "ghdl", "GHDL 4.0.0 mcode code generator")
        monkeypatch.setenv("PATH", toolbin)
        check = [c for c in ToolchainCheck.run_checks() if c.key == "ghdl"][0]
        assert not check.ok
        assert "mcode" in check.detail
        assert "ghdl-llvm" in check.hint or "llvm" in check.hint

    def test_llvm_backend_accepted(self, fake_env, monkeypatch):
        toolbin = os.path.join(str(fake_env), "usrbin")
        _make_tool(toolbin, "ghdl", "GHDL 4.0.0 llvm code generator")
        monkeypatch.setenv("PATH", toolbin)
        check = [c for c in ToolchainCheck.run_checks() if c.key == "ghdl"][0]
        assert check.ok
        assert "llvm" in check.detail


class TestLibvvpGate:
    def test_iverilog_without_libvvp_fails_dcosim_only(self, fake_env,
                                                       monkeypatch):
        """An apt-style iverilog (no libvvp) keeps the Verifier green but
        must flag d_cosim -- the exact Ubuntu fallback scenario."""
        toolbin = os.path.join(str(fake_env), "usrbin")
        _make_tool(toolbin, "iverilog", "Icarus Verilog version 12.0")
        _make_tool(toolbin, "vvp", "vvp 12.0")
        monkeypatch.setenv("PATH", toolbin)
        verifier_bad = {c.key for c in ToolchainCheck.failures(
            ToolchainCheck.VERIFIER)}
        assert "iverilog" not in verifier_bad
        assert "vvp" not in verifier_bad
        dcosim_bad = {c.key for c in ToolchainCheck.failures(
            ToolchainCheck.DCOSIM)}
        assert "libvvp" in dcosim_bad


class TestWindowsBranches:
    """Exercise the nt-only logic by faking _win() -- the module reads it at
    call time exactly so these branches are testable on Linux."""

    @pytest.fixture
    def fake_windows(self, fake_env, monkeypatch):
        monkeypatch.setattr(ToolchainCheck, "_win", lambda: True)
        return fake_env

    def test_msys_checks_present_and_failing(self, fake_windows):
        keys = {c.key: c for c in ToolchainCheck.run_checks()}
        assert "msys_bash" in keys
        assert "msys_mintty" in keys
        assert not keys["msys_bash"].ok
        assert "MSYS_HOME" in keys["msys_bash"].path

    def test_msys_tree_found(self, fake_windows, monkeypatch):
        msys = os.path.join(str(fake_windows), "msys64")
        for exe in ("bash.exe", "mintty.exe"):
            _make_tool(os.path.join(msys, "usr", "bin"), exe)
        _write_nghdl_config(fake_windows,
                            "[COMPILER]\nMSYS_HOME = %s\n"
                            % msys.replace("%", "%%"))
        keys = {c.key: c for c in ToolchainCheck.run_checks()}
        assert keys["msys_bash"].ok
        assert keys["msys_mintty"].ok

    def test_mingw_tools_resolved_from_msys_home(self, fake_windows,
                                                 monkeypatch):
        """make/gcc/verilator/ghdl must resolve from <MSYS_HOME>/mingw64/bin
        first -- that is the toolchain the nt build branches invoke."""
        msys = os.path.join(str(fake_windows), "msys64")
        mingw_bin = os.path.join(msys, "mingw64", "bin")
        for exe in ("mingw32-make.exe", "gcc.exe", "verilator.exe"):
            _make_tool(mingw_bin, exe, "5.0")
        _make_tool(mingw_bin, "ghdl.exe", "GHDL 4.1.0 llvm code generator")
        _write_nghdl_config(fake_windows,
                            "[COMPILER]\nMSYS_HOME = %s\n"
                            % msys.replace("%", "%%"))
        keys = {c.key: c for c in ToolchainCheck.run_checks()}
        assert keys["make"].ok
        assert keys["make"].path == os.path.join(mingw_bin,
                                                 "mingw32-make.exe")
        assert keys["gcc"].ok
        assert keys["verilator"].ok
        assert keys["ghdl"].ok

    def test_missing_msys_points_at_component(self, fake_windows):
        msg = ToolchainCheck.failure_message(ToolchainCheck.NGVERI)
        assert "HDL" in msg or "MSYS" in msg


class TestRequireGate:
    def test_require_true_when_ok(self, fake_env, monkeypatch):
        _, toolbin = _full_linux_tree(fake_env)
        monkeypatch.setenv("PATH", toolbin)
        assert ToolchainCheck.require(ToolchainCheck.NGVERI) is True

    def test_require_routes_message_to_sink(self, fake_env):
        seen = {}

        def sink(title, text):
            seen["title"] = title
            seen["text"] = text

        assert ToolchainCheck.require(ToolchainCheck.DCOSIM,
                                      dialogs=sink) is False
        assert "toolchain" in seen["title"].lower()
        assert "probed:" in seen["text"]
