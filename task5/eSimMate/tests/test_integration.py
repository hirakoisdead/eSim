"""
End-to-End Integration Tests for eSimMate Subsystems.
Verifies interaction between Detector, Registry, VersionManager, InstallationManager, and CLI.
All subprocesses are strictly mocked so NO software is modified during testing.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from esimmate.config import ConfigManager
from esimmate.detector import SystemDetector, SystemInfo
from esimmate.installer import InstallationManager, InstallStatus
from esimmate.logger import LoggingManager
from esimmate.registry import ToolRegistry
from esimmate.version_manager import VersionManager, VersionStatus


def test_full_pipeline_detection_to_version_check():
    """Integration Test 1: SystemDetector -> ToolRegistry -> VersionManager pipeline."""
    detector = SystemDetector()
    sys_info = detector.get_system_info()
    assert sys_info.os_name in ["Linux", "Windows", "Darwin"]

    config_mgr = ConfigManager()
    tools_config = config_mgr.load_tools_config()
    registry = ToolRegistry()
    registry.load_from_config(tools_config)

    assert len(registry.list_tools()) >= 7
    python_tool = registry.get_tool("python")
    assert python_tool is not None

    version_mgr = VersionManager()
    result = version_mgr.check_tool(python_tool)

    assert result.status in [VersionStatus.COMPATIBLE, VersionStatus.NOT_INSTALLED, VersionStatus.OUTDATED]
    if result.status == VersionStatus.COMPATIBLE:
        assert result.installed_version is not None


@patch("subprocess.run")
def test_full_pipeline_installation_dry_run_to_logging(mock_run, tmp_path):
    """Integration Test 2: Full dry-run installation pipeline with custom LoggingManager."""
    log_dir = tmp_path / "logs"
    log_mgr = LoggingManager(log_dir=log_dir)

    detector = MagicMock(spec=SystemDetector)
    detector.get_system_info.return_value = SystemInfo(
        os_name="Linux",
        os_version="Ubuntu 22.04 LTS",
        os_release="22.04",
        architecture="x86_64",
        architecture_normalized="x86_64",
        is_64bit=True,
        python_version="3.11.9",
        available_package_managers=["apt"],
    )

    config_mgr = ConfigManager()
    tools_config = config_mgr.load_tools_config()
    registry = ToolRegistry()
    registry.load_from_config(tools_config)

    kicad_tool = registry.get_tool("kicad")
    assert kicad_tool is not None

    installer = InstallationManager(system_detector=detector, logging_manager=log_mgr)

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = installer.install_tool(kicad_tool, dry_run=True)

    assert res.status == InstallStatus.DRY_RUN_PREVIEW
    assert res.dry_run is True
    assert res.command_executed == ["sudo", "apt-get", "install", "-y", "kicad"]
    assert (log_dir / "esimmate.log").exists()


@patch("subprocess.run")
def test_full_pipeline_successful_execution_mocked(mock_run, tmp_path):
    """Integration Test 3: Simulated full tool installation workflow with mocked execution."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Package kicad installed successfully."
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    detector = MagicMock(spec=SystemDetector)
    detector.get_system_info.return_value = SystemInfo(
        os_name="Windows",
        os_version="Windows 11",
        os_release="11",
        architecture="x86_64",
        architecture_normalized="x86_64",
        is_64bit=True,
        python_version="3.11.9",
        available_package_managers=["winget"],
    )

    config_mgr = ConfigManager()
    tools_config = config_mgr.load_tools_config()
    registry = ToolRegistry()
    registry.load_from_config(tools_config)

    ngspice_tool = registry.get_tool("ngspice")
    assert ngspice_tool is not None

    installer = InstallationManager(system_detector=detector)

    winget_adapter = installer.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=True):
        with patch("shutil.which", return_value="C:\\Windows\\System32\\winget.exe"):
            res = installer.install_tool(ngspice_tool, auto_confirm=True)

    assert res.status == InstallStatus.SUCCESS
    assert res.returncode == 0
    assert "ngspice" in res.command_executed[-4] or "Ngspice" in res.command_executed[-4]
