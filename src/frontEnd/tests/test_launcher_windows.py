"""In-process Windows environment setup (replaces esim.bat's second
interpreter for windows_bootstrap).

Pins that setup_environment prepends the tool dirs in the order esim.bat did
(bundled ngspice < nghdl ngspice; system KiCad < bundled KiCad, so the bundled
copies win at the front of PATH), sets SPICE_LIB_DIR, and honours the
ESIM_ENV_READY sentinel so it never double-prepends when esim.bat already ran.
"""
import os

import pytest

from frontEnd import launcher_windows

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launcher only")


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("")


def _fake_root(tmp_path):
    root = str(tmp_path)
    _touch(os.path.join(root, "tools", "ngspice", "bin", "ngspice.exe"))
    _touch(os.path.join(root, "tools", "nghdl", "install_dir", "bin",
                        "ngspice.exe"))
    _touch(os.path.join(root, "tools", "kicad", "bin", "eeschema.exe"))
    return root


def test_setup_environment_orders_path_and_sets_spice_lib(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    monkeypatch.setenv("PATH", "C:\\existing")
    monkeypatch.delenv("ESIM_ENV_READY", raising=False)
    monkeypatch.delenv("SPICE_LIB_DIR", raising=False)
    # No system KiCad in this fake ProgramFiles.
    monkeypatch.setenv("ProgramFiles", os.path.join(root, "no_program_files"))

    launcher_windows.setup_environment(root)

    parts = os.environ["PATH"].split(os.pathsep)
    bundled_kicad = os.path.join(root, "tools", "kicad", "bin")
    nghdl_bin = os.path.join(root, "tools", "nghdl", "install_dir", "bin")
    ngspice_bin = os.path.join(root, "tools", "ngspice", "bin")
    # Bundled KiCad wins (front), then nghdl ngspice, then bundled ngspice.
    assert parts[0] == bundled_kicad
    assert parts.index(nghdl_bin) < parts.index(ngspice_bin)
    assert os.environ["SPICE_LIB_DIR"].endswith(
        os.path.join("install_dir", "share", "ngspice"))
    assert os.environ["ESIM_ENV_READY"] == "1"


def test_setup_environment_skips_when_sentinel_set(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    monkeypatch.setenv("PATH", "C:\\existing")
    monkeypatch.setenv("ESIM_ENV_READY", "1")
    launcher_windows.setup_environment(root)
    # Untouched: esim.bat already configured the environment.
    assert os.environ["PATH"] == "C:\\existing"
