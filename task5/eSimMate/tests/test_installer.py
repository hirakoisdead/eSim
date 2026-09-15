"""
Comprehensive unit tests for the Installation Manager module.
All subprocess executions are strictly mocked to ensure NO actual software is installed during testing.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from esimmate.detector import SystemDetector, SystemInfo
from esimmate.installer import InstallationManager, InstallationResult, InstallStatus
from esimmate.package_manager import AbstractPackageManager, AptAdapter, WingetAdapter
from esimmate.tool import ConfigurableTool, ToolMetadata, VersionBounds


def create_mock_tool(
    tool_id: str = "kicad",
    name: str = "KiCad EDA",
    supported_platforms: list = None,
    pkg_map: dict = None,
) -> ConfigurableTool:
    """Helper fixture to create a mock tool instance."""
    if tool_id == "ngspice":
        exec_map = {"linux": "ngspice", "windows": "ngspice_con.exe"}
        cand_map = {"linux": ["ngspice"], "windows": ["ngspice_con.exe", "ngspice.exe"]}
    else:
        exec_map = {"linux": tool_id, "windows": f"{tool_id}.exe"}
        cand_map = {"linux": [tool_id], "windows": [f"{tool_id}.exe"]}

    meta = ToolMetadata(
        id=tool_id,
        name=name,
        category="schematic_pcb",
        mandatory=True,
        purpose="Testing tool",
        executables=exec_map,
        executable_candidates=cand_map,
        compatibility=VersionBounds("6.0.0", "7.0.0", "8.0.0"),
        supported_platforms=supported_platforms or ["Linux", "Windows"],
        package_managers=pkg_map or {"apt": "kicad", "winget": "KiCad.KiCad"},
    )
    return ConfigurableTool(meta)


def create_mock_detector(os_name="Linux", available_pms=None) -> SystemDetector:
    """Helper to mock SystemDetector."""
    detector = MagicMock(spec=SystemDetector)
    sys_info = SystemInfo(
        os_name=os_name,
        os_version="Test OS 1.0",
        os_release="1.0",
        architecture="x86_64",
        architecture_normalized="x86_64",
        is_64bit=True,
        python_version="3.11.9",
        available_package_managers=available_pms if available_pms is not None else ["apt"],
    )
    detector.get_system_info.return_value = sys_info
    return detector


def test_dry_run_mode(tmp_path):
    """Test 1: --dry-run returns DRY_RUN_PREVIEW without executing command."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, dry_run=True)

    assert isinstance(res, InstallationResult)
    assert res.status == InstallStatus.DRY_RUN_PREVIEW
    assert res.dry_run is True
    assert res.command_executed == ["sudo", "apt-get", "install", "-y", "kicad"]
    assert "[DRY-RUN PREVIEW]" in res.message


def test_confirmation_declined():
    """Test 2: User declining confirmation returns CANCELLED_BY_USER."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    callback = MagicMock(return_value=False)

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, dry_run=False, auto_confirm=False, confirm_callback=callback)

    assert res.status == InstallStatus.CANCELLED_BY_USER
    assert callback.called
    assert "cancelled by user" in res.message


def test_no_confirmation_callback_cancels():
    """Test: If auto_confirm=False and no confirm_callback is provided, installation is cancelled safely."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, auto_confirm=False, confirm_callback=None)

    assert res.status == InstallStatus.CANCELLED_BY_USER
    assert "Confirmation callback required" in res.message


@patch("subprocess.run")
def test_successful_installation(mock_run):
    """Test 3: Successful installation returns SUCCESS status with captured stdout/stderr."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Reading package lists...\nBuilding dependency tree...\nDone!"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.SUCCESS
    assert res.returncode == 0
    assert "Successfully installed" in res.message
    assert "Reading package lists" in res.stdout
    mock_run.assert_called_once_with(
        ["sudo", "apt-get", "install", "-y", "kicad"],
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )


def test_unsupported_os():
    """Test 4: Tool requested on unsupported platform returns UNSUPPORTED_OS."""
    detector = create_mock_detector(os_name="Darwin", available_pms=["brew"])
    tool = create_mock_tool(supported_platforms=["Linux", "Windows"])
    mgr = InstallationManager(system_detector=detector)

    res = mgr.install_tool(tool)
    assert res.status == InstallStatus.UNSUPPORTED_OS
    assert "does not support host OS" in res.message


def test_package_manager_unavailable():
    """Test 5: No package manager available on host system returns PACKAGE_MANAGER_UNAVAILABLE."""
    detector = create_mock_detector(os_name="Linux", available_pms=[])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    res = mgr.install_tool(tool)
    assert res.status == InstallStatus.PACKAGE_MANAGER_UNAVAILABLE
    assert "No supported package manager available" in res.message


def test_package_not_found_in_registry():
    """Test 6: Missing package ID for available manager returns PACKAGE_NOT_FOUND."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool(pkg_map={"winget": "KiCad.KiCad"}) # No apt mapping
    mgr = InstallationManager(system_detector=detector)

    res = mgr.install_tool(tool)
    assert res.status == InstallStatus.PACKAGE_NOT_FOUND
    assert "No package identifier defined" in res.message


@patch("subprocess.run", side_effect=PermissionError("Permission denied"))
def test_permission_error_exception(mock_run):
    """Test 7: Permission error during execution returns PERMISSION_DENIED status."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.PERMISSION_DENIED
    assert "Permission denied" in res.message


@patch("subprocess.run", side_effect=FileNotFoundError("Command not found"))
def test_command_not_found_exception(mock_run):
    """Test 8: Command binary missing returns COMMAND_NOT_FOUND status."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.COMMAND_NOT_FOUND
    assert "was not found on host system" in res.message


@patch("subprocess.run")
def test_network_failure(mock_run):
    """Test 9: Subprocess failure containing network error keywords returns NETWORK_FAILURE."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    mock_proc = MagicMock()
    mock_proc.returncode = 100
    mock_proc.stdout = ""
    mock_proc.stderr = "Err:1 http://archive.ubuntu.com Could not resolve host name"
    mock_run.return_value = mock_proc

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.NETWORK_FAILURE
    assert "Network failure" in res.message


@patch("subprocess.run")
def test_general_installation_failure(mock_run):
    """Test 10: Non-zero exit code without network error returns INSTALLATION_FAILED."""
    detector = create_mock_detector(os_name="Linux", available_pms=["apt"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "dpkg returned an error code (1)"
    mock_run.return_value = mock_proc

    with patch("shutil.which", return_value="/usr/bin/apt-get"):
        res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.INSTALLATION_FAILED
    assert res.returncode == 1
    assert "failed with exit code 1" in res.message


@patch("subprocess.run")
def test_windows_winget_installation(mock_run):
    """Test 11: Windows Winget installation workflow."""
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool()
    mgr = InstallationManager(system_detector=detector)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Found KiCad [KiCad.KiCad]\nInstalling package..."
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=True):
        with patch("shutil.which", return_value="C:\\Windows\\System32\\winget.exe"):
            res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.SUCCESS
    assert res.package_manager_name == "winget"
    assert res.command_executed == [
        "winget",
        "install",
        "--id",
        "KiCad.KiCad",
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ]


def test_winget_package_available_selected():
    """Test: When WinGet package is available, PACKAGE_MANAGER method is selected."""
    from esimmate.installer import InstallMethod

    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(pkg_map={"winget": "KiCad.KiCad"})
    mgr = InstallationManager(system_detector=detector)

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=True):
        adapter, pkg, method = mgr.resolve_package_manager(detector.get_system_info(), tool)

    assert adapter.name == "winget"
    assert pkg == "KiCad.KiCad"
    assert method == InstallMethod.PACKAGE_MANAGER


def test_winget_package_unavailable_fallback_selected():
    """Test: When WinGet package is unavailable, MANUAL_DOWNLOAD fallback strategy is selected."""
    from esimmate.installer import InstallMethod

    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(pkg_map={
        "winget": "Ngspice.Ngspice",
        "manual_download": "https://sourceforge.net/projects/ngspice/files/ngspice-43/ngspice-43_64.zip/download"
    })
    mgr = InstallationManager(system_detector=detector)

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        adapter, pkg, method = mgr.resolve_package_manager(detector.get_system_info(), tool)

    assert adapter.name == "manual_download"
    assert pkg == "https://sourceforge.net/projects/ngspice/files/ngspice-43/ngspice-43_64.zip/download"
    assert method == InstallMethod.MANUAL_DOWNLOAD


def test_dry_run_fallback_preview():
    """Test: Dry-run preview displays fallback MANUAL_DOWNLOAD strategy when WinGet package is unavailable."""
    from esimmate.installer import InstallMethod

    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(pkg_map={
        "winget": "Ngspice.Ngspice",
        "manual_download": "https://sourceforge.net/projects/ngspice/files/ngspice-43/ngspice-43_64.zip/download"
    })
    mgr = InstallationManager(system_detector=detector)

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        res = mgr.install_tool(tool, dry_run=True)

    assert res.status == InstallStatus.DRY_RUN_PREVIEW
    assert res.install_method == InstallMethod.MANUAL_DOWNLOAD
    assert "Fallback Strategy:      MANUAL_DOWNLOAD" in res.message


def test_package_not_found_structured_error_message():
    """Test: Structured error message format when WinGet package is unavailable and no fallback exists."""
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(pkg_map={"winget": "Ngspice.Ngspice"}) # No manual_download
    mgr = InstallationManager(system_detector=detector)

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        res = mgr.install_tool(tool)

    assert res.status == InstallStatus.PACKAGE_NOT_FOUND
    assert "Tool:" in res.message
    assert "Package Manager: winget" in res.message
    assert "Package ID: Ngspice.Ngspice" in res.message
    assert "Reason:" in res.message
    assert "Suggested Action:" in res.message


@patch("urllib.request.urlopen")
def test_manual_download_http_failure(mock_urlopen, tmp_path):
    """Test: HTTP failure downloading package returns NETWORK_FAILURE."""
    import urllib.error
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(
        tool_id="ngspice",
        name="Ngspice Simulator",
        pkg_map={
            "winget": "Ngspice.Ngspice",
            "manual_download": "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download"
        }
    )
    tool.metadata.optional_config["install_dir"] = str(tmp_path)
    mgr = InstallationManager(system_detector=detector)

    mock_urlopen.side_effect = urllib.error.URLError("HTTP 404 Not Found")
    winget_adapter = mgr.adapters["winget"]

    with patch.object(winget_adapter, "is_package_available", return_value=False):
        res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.NETWORK_FAILURE
    assert "Network failure" in res.message or "HTTP status failure" in res.message or "Installation Failed" in res.message


@patch("urllib.request.urlopen")
def test_manual_download_archive_extraction_failure(mock_urlopen, tmp_path):
    """Test: Archive extraction failure returns INSTALLATION_FAILED."""
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(
        tool_id="ngspice",
        name="Ngspice Simulator",
        pkg_map={
            "winget": "Ngspice.Ngspice",
            "manual_download": "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download"
        }
    )
    tool.metadata.optional_config["install_dir"] = str(tmp_path)
    mgr = InstallationManager(system_detector=detector)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.side_effect = [b"mock archive data", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        with patch.object(mgr, "_find_7z_extractor", return_value=["7z"]):
            with patch("subprocess.run", return_value=MagicMock(returncode=1)):
                res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.INSTALLATION_FAILED
    assert "Archive extraction failed" in res.message or "Installation Failed" in res.message


@patch("urllib.request.urlopen")
def test_manual_download_executable_not_found(mock_urlopen, tmp_path):
    """Test: When archive extracts but executable is missing, returns INSTALLATION_FAILED."""
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(
        tool_id="ngspice",
        name="Ngspice Simulator",
        pkg_map={
            "winget": "Ngspice.Ngspice",
            "manual_download": "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download"
        }
    )
    tool.metadata.optional_config["install_dir"] = str(tmp_path)
    mgr = InstallationManager(system_detector=detector)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.side_effect = [b"mock binary archive", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        with patch.object(mgr, "_find_7z_extractor", return_value=["7z"]):
            with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.INSTALLATION_FAILED
    assert "Executable 'ngspice_con.exe' not found" in res.message or "Executable 'ngspice" in res.message


@patch("urllib.request.urlopen")
def test_manual_download_version_verification_failure(mock_urlopen, tmp_path):
    """Test: Executable found but fails version verification returns INSTALLATION_FAILED."""
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(
        tool_id="ngspice",
        name="Ngspice Simulator",
        pkg_map={
            "winget": "Ngspice.Ngspice",
            "manual_download": "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download"
        }
    )
    tool.metadata.optional_config["install_dir"] = str(tmp_path)
    mgr = InstallationManager(system_detector=detector)

    # Create dummy executable file in tmp_path
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    exe_file = bin_dir / "ngspice_con.exe"
    exe_file.write_text("mock executable")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.side_effect = [b"mock archive content", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        with patch.object(mgr, "_find_7z_extractor", return_value=["7z"]):
            with patch("subprocess.run", side_effect=[MagicMock(returncode=0), MagicMock(returncode=1, stdout="", stderr="Error launching")]):
                res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.INSTALLATION_FAILED
    assert "failed version verification" in res.message or "regex failed" in res.message or "Installation Failed" in res.message


@patch("urllib.request.urlopen")
def test_manual_download_7z_extractor_unavailable(mock_urlopen, tmp_path):
    """Test: When 7-Zip extractor is unavailable, returns structured error with suggested action."""
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(
        tool_id="ngspice",
        name="Ngspice Simulator",
        pkg_map={
            "winget": "Ngspice.Ngspice",
            "manual_download": "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download"
        }
    )
    tool.metadata.optional_config["install_dir"] = str(tmp_path)
    tool.metadata.optional_config["archive_filename"] = "ngspice-46_64.7z"
    mgr = InstallationManager(system_detector=detector)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.side_effect = [b"mock archive data", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    winget_adapter = mgr.adapters["winget"]
    with patch.object(winget_adapter, "is_package_available", return_value=False):
        with patch.object(mgr, "_find_7z_extractor", return_value=None):
            res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.INSTALLATION_FAILED
    assert "7-Zip extraction dependency" in res.message
    assert "ngspice-46_64.7z" in res.message
    assert "Install 7-Zip" in res.suggested_action


@patch("urllib.request.urlopen")
def test_manual_download_successful_flow(mock_urlopen, tmp_path):
    """Test: Full MANUAL_DOWNLOAD flow success for Ngspice 46 (Download -> Extract -> Executable -> Version Verify -> SUCCESS)."""
    from esimmate.installer import InstallMethod
    from esimmate.tool import VersionCheckConfig, VersionBounds
    from esimmate.version_manager import VersionCheckResult, VersionStatus
    detector = create_mock_detector(os_name="Windows", available_pms=["winget"])
    tool = create_mock_tool(
        tool_id="ngspice",
        name="Ngspice Simulator",
        pkg_map={
            "winget": "Ngspice.Ngspice",
            "manual_download": "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download"
        }
    )
    tool.metadata.version_check = VersionCheckConfig(command=["ngspice_con.exe", "-v"], regex=r'ngspice[^\d]*(\d+)')
    tool.metadata.compatibility = VersionBounds(min_version="34", recommended_version="38", max_version="46")
    tool.metadata.optional_config["install_dir"] = str(tmp_path)
    tool.metadata.optional_config["archive_filename"] = "ngspice-46_64.7z"
    mgr = InstallationManager(system_detector=detector)

    # Create dummy executable file in tmp_path
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    exe_file = bin_dir / "ngspice_con.exe"
    exe_file.write_text("mock executable")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.side_effect = [b"mock archive data", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    winget_adapter = mgr.adapters["winget"]
    mock_ver_res = VersionCheckResult(
        tool_id="ngspice",
        tool_name="Ngspice Simulator",
        executable_path=exe_file,
        installed_version="46",
        status=VersionStatus.COMPATIBLE,
        message="Installed version '46' is compatible.",
        raw_output="ngspice-46 : Circuit level simulation program",
        command_executed=[str(exe_file), "-v"],
    )

    with patch.object(winget_adapter, "is_package_available", return_value=False):
        with patch.object(mgr, "_find_7z_extractor", return_value=["7z"]):
            with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                with patch.object(mgr.version_manager, "check_tool", return_value=mock_ver_res):
                    res = mgr.install_tool(tool, auto_confirm=True)

    assert res.status == InstallStatus.SUCCESS
    assert res.install_method == InstallMethod.MANUAL_DOWNLOAD
    assert "version 46" in res.message



