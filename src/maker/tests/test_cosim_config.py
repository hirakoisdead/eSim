"""Unit tests for the CosimConfig toolchain resolver.

CosimConfig is the single source of truth for locating the Icarus toolchain
(shared by the d_cosim build and the Verilog Simulator IDE), so its resolution
order and the manual-path persistence both need to be pinned down. These tests
are Qt-free and run anywhere.
"""
import importlib
import os

import pytest

from maker import CosimConfig


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point config.ini resolution at an isolated HOME and clear any env
    overrides, then hand back a freshly-reloaded CosimConfig module.

    The bundled-toolchain probe is stubbed out too. It reads
    ``<repo>/library/bin/iverilog``, which is a build-staging artifact: it is
    untracked, so CI never has it and a developer who has just staged a
    Windows build always does. Leaving it live made "nothing configured, so
    resolution is None" pass or fail depending on whose machine ran it.
    Turning it off here is what makes these tests about the resolution ORDER
    rather than about the checkout."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for var in ("ESIM_IVERILOG", "ESIM_VVP", "ESIM_NGSPICE",
                "ESIM_NGSPICE_GUI", "ESIM_IVERILOG_LIB"):
        monkeypatch.delenv(var, raising=False)
    reload_isolated(CosimConfig, monkeypatch)
    return CosimConfig


def reload_isolated(module, monkeypatch):
    """Re-read config.ini, then re-stub the bundled probe.

    importlib.reload rebinds every module attribute, so it throws away the
    fixture's stub; a test that reloads to check persistence would silently
    get the developer's staged toolchain back."""
    importlib.reload(module)
    monkeypatch.setattr(module, "_bundled_tool", lambda _name: None)
    return module


def test_a_bundled_toolchain_wins_over_path(tmp_path, monkeypatch):
    """The behaviour the fixture stubs out, kept under test on its own: an
    install that ships Icarus under library/bin uses it, whatever is on PATH.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    importlib.reload(CosimConfig)
    bundled = _make_tool(str(tmp_path / "bundled"), "iverilog")
    monkeypatch.setattr(CosimConfig, "_bundled_tool",
                        lambda name: bundled if name == "iverilog" else None)
    monkeypatch.setenv("PATH", str(tmp_path / "elsewhere"))
    _make_tool(str(tmp_path / "elsewhere"), "iverilog")

    assert CosimConfig.iverilog_binary() == bundled


def _make_tool(dirpath, name):
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, name)
    with open(path, "w"):
        pass
    os.chmod(path, 0o755)
    return path


def test_unconfigured_returns_path_or_none(fake_home, monkeypatch):
    # With no config and nothing on a scrubbed PATH, resolution is None.
    monkeypatch.setenv("PATH", "")
    assert fake_home.iverilog_binary() is None
    assert fake_home.vvp_binary() is None
    assert fake_home.nghdl_cfg("NGHDL", "NGHDL_HOME") == ""
    assert fake_home.nghdl_cfg("NGHDL", "NGHDL_HOME", "fallback") == \
        "fallback"


def test_unconfigured_digital_models_use_safe_user_default(fake_home):
    expected = os.path.join(
        os.path.expanduser("~"), ".nghdl", "DigitalModelLibrary")
    assert fake_home.digital_model_root() == expected
    # d_cosim builds into its own tree, a sibling of the legacy Ngveri one, so
    # neither backend's teardown can delete the other's build.
    assert fake_home.cosim_vvp_target("counter") == os.path.join(
        expected, "NgVeriCosim", "counter", "counter")
    assert fake_home.legacy_cosim_vvp_path("counter") == os.path.join(
        expected, "Ngveri", "counter", "counter")
    # Nothing built anywhere -> the reader reports the canonical location.
    assert fake_home.cosim_vvp_path("counter") == \
        fake_home.cosim_vvp_target("counter")


def test_set_manual_paths_roundtrip(fake_home, tmp_path, monkeypatch):
    bindir = tmp_path / "tool" / "bin"
    iv = _make_tool(str(bindir), "iverilog")
    vv = _make_tool(str(bindir), "vvp")
    (tmp_path / "tool" / "lib").mkdir(parents=True)

    assert fake_home.set_manual_paths(iverilog_path=iv, vvp_path=vv) is True

    # Re-read config.ini fresh: the persisted paths must win.
    reload_isolated(fake_home, monkeypatch)
    assert fake_home.iverilog_binary() == iv
    assert fake_home.vvp_binary() == vv
    # IVERILOG_LIB is derived from the iverilog prefix so has_iverilog can work.
    assert fake_home.iverilog_libdir() == str(tmp_path / "tool" / "lib")


def test_env_override_beats_config(fake_home, tmp_path, monkeypatch):
    cfg_iv = _make_tool(str(tmp_path / "cfg" / "bin"), "iverilog")
    env_iv = _make_tool(str(tmp_path / "env" / "bin"), "iverilog")
    fake_home.set_manual_paths(iverilog_path=cfg_iv)
    reload_isolated(fake_home, monkeypatch)
    monkeypatch.setenv("ESIM_IVERILOG", env_iv)
    assert fake_home.iverilog_binary() == env_iv


def test_vvp_falls_back_next_to_iverilog(fake_home, tmp_path, monkeypatch):
    # Only iverilog is configured; vvp must be discovered alongside it even
    # with nothing on PATH and no explicit VVP key.
    #
    # The sibling is looked up as "vvp" + the platform's executable suffix, so
    # the fixture file has to carry it: a bare "vvp" is not something Windows
    # would run, and asserting on one only ever passed here by falling through
    # to a bundled toolchain that happened to be staged in the checkout.
    monkeypatch.setenv("PATH", "")
    bindir = tmp_path / "tool" / "bin"
    iv = _make_tool(str(bindir), "iverilog" + fake_home._EXE)
    vv = _make_tool(str(bindir), "vvp" + fake_home._EXE)
    fake_home.set_manual_paths(iverilog_path=iv)
    reload_isolated(fake_home, monkeypatch)
    assert fake_home.vvp_binary() == vv


def test_ngspice_gui_is_windows_only(fake_home, tmp_path, monkeypatch):
    # POSIX ngspice plots through X11 from the console binary; there is no
    # wingui twin to find, even if a stray file of that name sits in bin/.
    bindir = tmp_path / "install_dir" / "bin"
    _make_tool(str(bindir), "ngspice")
    _make_tool(str(bindir), "ngspice_gui.exe")
    monkeypatch.setenv("ESIM_NGSPICE", str(bindir / "ngspice"))
    monkeypatch.setattr(fake_home, "_WIN", False)
    assert fake_home.ngspice_gui_binary() is None


def test_ngspice_gui_found_next_to_console_ngspice(fake_home, tmp_path,
                                                   monkeypatch):
    bindir = tmp_path / "install_dir" / "bin"
    ngspice = _make_tool(str(bindir), "ngspice.exe")
    gui = _make_tool(str(bindir), "ngspice_gui.exe")
    monkeypatch.setenv("ESIM_NGSPICE", ngspice)
    monkeypatch.setattr(fake_home, "_WIN", True)
    assert fake_home.ngspice_gui_binary() == gui


def test_ngspice_gui_absent_is_none_not_a_bogus_path(fake_home, tmp_path,
                                                     monkeypatch):
    # An install without the wingui twin must report None so the caller can say
    # so, rather than handing QProcess a path that will fail to start.
    bindir = tmp_path / "install_dir" / "bin"
    ngspice = _make_tool(str(bindir), "ngspice.exe")
    monkeypatch.setenv("ESIM_NGSPICE", ngspice)
    monkeypatch.setattr(fake_home, "_WIN", True)
    assert fake_home.ngspice_gui_binary() is None


def test_ngspice_gui_env_override_beats_sibling(fake_home, tmp_path,
                                                monkeypatch):
    bindir = tmp_path / "install_dir" / "bin"
    ngspice = _make_tool(str(bindir), "ngspice.exe")
    _make_tool(str(bindir), "ngspice_gui.exe")
    override = _make_tool(str(tmp_path / "elsewhere"), "ngspice_gui.exe")
    monkeypatch.setenv("ESIM_NGSPICE", ngspice)
    monkeypatch.setenv("ESIM_NGSPICE_GUI", override)
    monkeypatch.setattr(fake_home, "_WIN", True)
    assert fake_home.ngspice_gui_binary() == override
