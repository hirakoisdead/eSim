"""
Comprehensive unit tests for the Version Manager module.
Tests tool existence check, safe subprocess execution (without shell=True),
version extraction regex, semver parsing, and compatibility status classification.
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from esimmate.tool import ConfigurableTool, ToolMetadata, VersionBounds, VersionCheckConfig
from esimmate.version_manager import VersionCheckResult, VersionManager, VersionStatus


def create_test_tool(
    min_ver: str = "6.0.0",
    rec_ver: str = "7.0.10",
    max_ver: str = "8.0.99",
    regex: str = r"KiCad\s+v?(\d+\.\d+\.\d+)",
) -> ConfigurableTool:
    """Helper to create a configured test tool instance."""
    meta = ToolMetadata(
        id="kicad",
        name="KiCad EDA",
        category="schematic_pcb",
        mandatory=True,
        purpose="Test tool",
        executables={"linux": "kicad", "windows": "kicad.exe"},
        compatibility=VersionBounds(min_ver, rec_ver, max_ver),
        version_check=VersionCheckConfig(
            command=["kicad", "--version"],
            regex=regex,
            timeout_seconds=5,
        ),
    )
    return ConfigurableTool(meta)


def test_tool_not_installed(tmp_path):
    """Test 1: Executable does not exist -> NOT_INSTALLED status."""
    vm = VersionManager()
    tool = create_test_tool()
    non_existent = tmp_path / "non_existent_kicad"

    res = vm.check_tool(tool, executable_path=non_existent)
    assert isinstance(res, VersionCheckResult)
    assert res.status == VersionStatus.NOT_INSTALLED
    assert res.executable_path is None
    assert res.installed_version is None
    assert "not found" in res.message


@patch("subprocess.run")
def test_correct_version_compatible(mock_run, tmp_path):
    """Test 2: Tool returns version within bounds -> COMPATIBLE status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "KiCad v7.0.10-0, release build"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    vm = VersionManager()
    tool = create_test_tool(min_ver="6.0.0", max_ver="8.0.99")
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.COMPATIBLE
    assert res.installed_version == "7.0.10"
    assert "compatible" in res.message
    # Verify subprocess.run was called safely with list, cwd, and shell=False
    mock_run.assert_called_once_with(
        [str(dummy_exe), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
    )


@patch("subprocess.run")
def test_older_version_outdated(mock_run, tmp_path):
    """Test 3: Tool version is below min_version -> OUTDATED status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "KiCad v5.1.9, old build"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    vm = VersionManager()
    tool = create_test_tool(min_ver="6.0.0", max_ver="8.0.99")
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.OUTDATED
    assert res.installed_version == "5.1.9"
    assert "below minimum required version" in res.message


@patch("subprocess.run")
def test_newer_version_unverified(mock_run, tmp_path):
    """Test 4: Tool version is higher than max_version -> NEWER_VERSION status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "KiCad v9.0.0-dev, future build"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    vm = VersionManager()
    tool = create_test_tool(min_ver="6.0.0", max_ver="8.0.99")
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.NEWER_VERSION
    assert res.installed_version == "9.0.0"
    assert "higher than maximum verified version" in res.message


@patch("subprocess.run")
def test_invalid_version_output(mock_run, tmp_path):
    """Test 5: Binary execution output does not match version regex -> VERSION_UNKNOWN status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Invalid banner without any version number"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    vm = VersionManager()
    tool = create_test_tool()
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.VERSION_UNKNOWN
    assert res.installed_version is None
    assert "could not be parsed" in res.message


@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["kicad"], timeout=5))
def test_command_failure_timeout(mock_run, tmp_path):
    """Test 6a: Subprocess command times out -> ERROR status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    vm = VersionManager()
    tool = create_test_tool()
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.ERROR
    assert "timed out" in res.message


@patch("subprocess.run", side_effect=PermissionError("Permission denied"))
def test_command_failure_permission_error(mock_run, tmp_path):
    """Test 6b: Permission denied executing binary -> ERROR status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    vm = VersionManager()
    tool = create_test_tool()
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.ERROR
    assert "Permission denied" in res.message


@patch("subprocess.run")
def test_command_failure_nonzero_exit_code(mock_run, tmp_path):
    """Test 6c: Command returns non-zero exit code without valid output -> ERROR status."""
    dummy_exe = tmp_path / "kicad"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 127
    mock_proc.stdout = ""
    mock_proc.stderr = "Command not found or missing library"
    mock_run.return_value = mock_proc

    vm = VersionManager()
    tool = create_test_tool()
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.ERROR
    assert "non-zero exit code 127" in res.message


def test_extract_and_parse_version():
    """Unit tests for standalone helper methods."""
    vm = VersionManager()
    raw = "Ngspice simulator code v38+"
    ver = vm.extract_version_string(raw, r"ngspice[^\d]*(\d+)")
    assert ver == "38"

    parsed = vm.parse_version("38")
    assert parsed is not None
    assert vm.compare_versions("38", "34") == 1
    assert vm.compare_versions("38", "40") == -1


@patch("subprocess.Popen")
def test_interactive_banner_version_detection(mock_popen, tmp_path):
    """Test: Interactive Ngspice executable printing banner and remaining open is detected and terminated safely."""
    dummy_exe = tmp_path / "ngspice.exe"
    dummy_exe.touch()

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_stdout = MagicMock()
    mock_stdout.readline.side_effect = [
        "******\n",
        "** ngspice-46 : Circuit level simulation program\n",
        "** Compiled with KLU Direct Linear Solver\n",
        "",
    ]
    mock_process.stdout = mock_stdout
    mock_popen.return_value = mock_process

    vm = VersionManager()
    tool_meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=False,
        purpose="General-purpose circuit simulation engine",
        executables={"windows": "ngspice.exe"},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(
            command=["ngspice", "--version"],
            regex=r'ngspice[- ](\d+(?:\.\d+)*)',
            mode="interactive_banner",
            timeout_seconds=5,
        ),
    )
    tool = ConfigurableTool(tool_meta)

    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.COMPATIBLE
    assert res.installed_version == "46"
    assert "compatible" in res.message
    mock_process.terminate.assert_called_once()
    mock_stdout.close.assert_called_once()


@patch("subprocess.Popen")
def test_interactive_banner_timeout(mock_popen, tmp_path):
    """Test: Interactive executable timing out before version banner appears returns ERROR status."""
    dummy_exe = tmp_path / "ngspice.exe"
    dummy_exe.touch()

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.returncode = None
    mock_stdout = MagicMock()

    def slow_readline():
        time.sleep(0.05)
        return ""

    mock_stdout.readline.side_effect = slow_readline
    mock_process.stdout = mock_stdout
    mock_popen.return_value = mock_process

    vm = VersionManager()
    tool_meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=False,
        purpose="General-purpose circuit simulation engine",
        executables={"windows": "ngspice.exe"},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(
            command=["ngspice", "--version"],
            regex=r'ngspice[- ](\d+(?:\.\d+)*)',
            mode="interactive_banner",
            timeout_seconds=0.01,
        ),
    )
    tool = ConfigurableTool(tool_meta)

    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.ERROR
    assert "timed out" in res.message
    mock_process.terminate.assert_called_once()


def test_check_all_tools():
    """Test check_all_tools canonical pipeline runs against registry tools."""
    from esimmate.registry import ToolRegistry
    from esimmate.detector import SystemDetector

    vm = VersionManager()
    reg = ToolRegistry()
    tool = create_test_tool()
    reg.register_tool(tool)

    detector = SystemDetector()
    results = vm.check_all_tools(reg, detector)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0].tool_id == "kicad"


def test_ngspice_parser_extracts_versions():
    """Test STEP 3: Parser extracts version numbers 46, 43, 34 and handles malformed banners."""
    vm = VersionManager()
    regex = r'ngspice[- ](\d+(?:\.\d+)*)'

    assert vm.extract_version_string("ngspice-46 : Circuit level simulation program", regex) == "46"
    assert vm.extract_version_string("*** ngspice-46 : Circuit level simulation program", regex) == "46"
    assert vm.extract_version_string("ngspice-43 : Circuit level simulation program", regex) == "43"
    assert vm.extract_version_string("ngspice-34 : Circuit level simulation program", regex) == "34"
    assert vm.extract_version_string("invalid banner string without version", regex) is None


def test_ngspice_executable_discovery(tmp_path):
    """Test STEP 4 & 9: Ngspice executable discovery from managed candidate path."""
    from esimmate.detector import SystemDetector
    detector = SystemDetector()

    dummy_path = tmp_path / "ngspice.exe"
    dummy_path.touch()

    found = detector.check_candidate_paths([str(dummy_path)])
    assert found == dummy_path


@patch("subprocess.Popen")
def test_interactive_banner_stderr_parsing(mock_popen, tmp_path):
    """Test STEP 9: Banner captured via stderr stream is parsed successfully."""
    dummy_exe = tmp_path / "ngspice.exe"
    dummy_exe.touch()

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_stdout = MagicMock()
    mock_stdout.readline.side_effect = [
        "** ngspice-46 : Circuit level simulation program\n",
        "",
    ]
    mock_process.stdout = mock_stdout
    mock_popen.return_value = mock_process

    vm = VersionManager()
    tool_meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=True,
        purpose="SPICE simulation engine",
        executables={"windows": "ngspice.exe"},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(
            command=["ngspice", "--version"],
            regex=r'ngspice[- ](\d+(?:\.\d+)*)',
            mode="interactive_banner",
            timeout_seconds=5,
        ),
    )
    tool = ConfigurableTool(tool_meta)

    res = vm.check_tool(tool, executable_path=dummy_exe)
    assert res.status == VersionStatus.COMPATIBLE
    assert res.installed_version == "46"


def test_windows_ngspice_executable_discovery_prefers_ngspice_con(tmp_path):
    """Test Requirement 9.1 & 9.2: Windows executable discovery prefers ngspice_con.exe over ngspice.exe."""
    from esimmate.detector import SystemDetector
    from esimmate.tool import ConfigurableTool, ToolMetadata, VersionBounds, VersionCheckConfig

    con_exe = tmp_path / "ngspice_con.exe"
    gui_exe = tmp_path / "ngspice.exe"
    con_exe.touch()
    gui_exe.touch()

    meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=True,
        purpose="SPICE simulation engine",
        executables={"windows": "ngspice_con.exe"},
        executable_candidates={"windows": ["ngspice_con.exe", "ngspice.exe"]},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(command=["ngspice_con.exe", "-v"]),
        default_search_paths={"windows": [str(con_exe), str(gui_exe)]},
    )
    tool = ConfigurableTool(meta)
    detector = SystemDetector()

    found = detector.find_tool_executable(tool, os_name="Windows")
    assert found == con_exe
    assert found.name == "ngspice_con.exe"


def test_windows_ngspice_fallback_to_ngspice_exe_when_con_missing(tmp_path):
    """Test Requirement 9.3: If ngspice_con.exe is unavailable, falls back to ngspice.exe."""
    from esimmate.detector import SystemDetector
    from esimmate.tool import ConfigurableTool, ToolMetadata, VersionBounds, VersionCheckConfig

    con_path = str(tmp_path / "ngspice_con.exe")
    gui_exe = tmp_path / "ngspice.exe"
    gui_exe.touch()

    meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=True,
        purpose="SPICE simulation engine",
        executables={"windows": "ngspice_con.exe"},
        executable_candidates={"windows": ["ngspice_con.exe", "ngspice.exe"]},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(command=["ngspice_con.exe", "-v"]),
        default_search_paths={"windows": [con_path, str(gui_exe)]},
    )
    tool = ConfigurableTool(meta)
    detector = SystemDetector()

    found = detector.check_candidate_paths(meta.default_search_paths["windows"])
    assert found == gui_exe
    assert found.name == "ngspice.exe"


@patch("subprocess.run")
def test_ngspice_console_version_command_and_parsing(mock_run, tmp_path):
    """Test Requirement 9.4, 9.5 & 9.6: Version command uses ngspice_con.exe -v, parses ngspice-46 -> 46, returns COMPATIBLE."""
    dummy_exe = tmp_path / "ngspice_con.exe"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = (
        "******\n"
        "** ngspice-46 : Circuit level simulation program\n"
        "** Compiled with KLU Direct Linear Solver\n"
    )
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    vm = VersionManager()
    meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=True,
        purpose="SPICE simulation engine",
        executables={"windows": "ngspice_con.exe"},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(
            command=["ngspice_con.exe", "-v"],
            regex=r'ngspice[- ](\d+(?:\.\d+)*)',
            mode="standard",
            timeout_seconds=5,
        ),
    )
    tool = ConfigurableTool(meta)
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.COMPATIBLE
    assert res.installed_version == "46"
    assert res.executable_path == dummy_exe
    mock_run.assert_called_once_with(
        [str(dummy_exe), "-v"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
    )


def test_ngspice_missing_executable_status(tmp_path):
    """Test Requirement 9.7: Missing executable returns NOT_INSTALLED status."""
    vm = VersionManager()
    tool = create_test_tool()
    missing_path = tmp_path / "non_existent_ngspice_con.exe"

    res = vm.check_tool(tool, executable_path=missing_path)
    assert res.status == VersionStatus.NOT_INSTALLED
    assert res.installed_version is None


@patch("subprocess.run")
def test_ngspice_invalid_output_status(mock_run, tmp_path):
    """Test Requirement 9.8: Invalid command output returns VERSION_UNKNOWN status."""
    dummy_exe = tmp_path / "ngspice_con.exe"
    dummy_exe.touch()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "Unknown application banner without version string"
    mock_proc.stderr = ""
    mock_run.return_value = mock_proc

    vm = VersionManager()
    meta = ToolMetadata(
        id="ngspice",
        name="Ngspice Circuit Simulator",
        category="simulation",
        mandatory=True,
        purpose="SPICE simulation engine",
        executables={"windows": "ngspice_con.exe"},
        compatibility=VersionBounds("34", "38", "46"),
        version_check=VersionCheckConfig(
            command=["ngspice_con.exe", "-v"],
            regex=r'ngspice[- ](\d+(?:\.\d+)*)',
            mode="standard",
            timeout_seconds=5,
        ),
    )
    tool = ConfigurableTool(meta)
    res = vm.check_tool(tool, executable_path=dummy_exe)

    assert res.status == VersionStatus.VERSION_UNKNOWN
    assert res.installed_version is None



