"""
Tests for Package Manager Abstraction module and adapters.
"""

from unittest.mock import MagicMock, patch
from esimmate.package_manager import (
    AptAdapter,
    ChocolateyAdapter,
    ManualScriptAdapter,
    PlaceholderPackageManager,
    WingetAdapter,
)


def test_apt_adapter():
    adapter = AptAdapter()
    assert adapter.name == "apt"
    assert adapter.requires_elevation() is True
    cmd = adapter.build_install_command("kicad")
    assert cmd == ["sudo", "apt-get", "install", "-y", "kicad"]


def test_winget_adapter():
    adapter = WingetAdapter()
    assert adapter.name == "winget"
    assert adapter.requires_elevation() is False
    cmd = adapter.build_install_command("KiCad.KiCad")
    assert cmd[0] == "winget"
    assert "--id" in cmd
    assert "KiCad.KiCad" in cmd


def test_choco_adapter():
    adapter = ChocolateyAdapter()
    assert adapter.name == "choco"
    assert adapter.requires_elevation() is True
    cmd = adapter.build_install_command("ngspice")
    assert cmd == ["choco", "install", "ngspice", "-y"]


def test_manual_script_adapter():
    adapter = ManualScriptAdapter()
    assert adapter.name == "script"
    assert adapter.is_available() is True
    cmd = adapter.build_install_command("install-eSim.sh")
    assert len(cmd) >= 2


def test_placeholder_package_manager_properties():
    pm = PlaceholderPackageManager(name="apt", available=True, elevation=True)
    assert pm.name == "apt"
    assert pm.is_available() is True
    assert pm.requires_elevation() is True


@patch("subprocess.run")
def test_winget_is_package_available_true(mock_run):
    adapter = WingetAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Name Id Version Source\nKiCad KiCad.KiCad 8.0.0 winget"
    mock_run.return_value = mock_proc

    assert adapter.is_package_available("KiCad.KiCad") is True
    mock_run.assert_called_once_with(
        ["winget", "search", "--id", "KiCad.KiCad", "-e"],
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )


@patch("subprocess.run")
def test_winget_is_package_available_false(mock_run):
    adapter = WingetAdapter()
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = "No package found matching input criteria."
    mock_run.return_value = mock_proc

    assert adapter.is_package_available("Ngspice.Ngspice") is False

