"""
Comprehensive unit tests for the System Detector module.
Uses mocks to verify Windows, Linux, CPU architecture, Python version, and package manager detection.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from esimmate.detector import SystemDetector, SystemInfo


def test_get_system_info_real_system():
    """Verify system detection works on real execution platform."""
    detector = SystemDetector()
    info = detector.get_system_info()

    assert isinstance(info, SystemInfo)
    assert info.os_name in ("Windows", "Linux", "Darwin")
    assert len(info.os_version) > 0
    assert len(info.architecture) > 0
    assert info.architecture_normalized in ("x86_64", "arm64", "x86", info.architecture.lower())
    assert isinstance(info.is_64bit, bool)
    assert len(info.python_version) > 0
    assert isinstance(info.available_package_managers, list)


@patch("platform.system", return_value="Windows")
def test_detect_os_name_windows(mock_sys):
    detector = SystemDetector()
    assert detector.detect_os_name() == "Windows"


@patch("platform.system", return_value="Linux")
def test_detect_os_name_linux(mock_sys):
    detector = SystemDetector()
    assert detector.detect_os_name() == "Linux"


@patch("platform.freedesktop_os_release", return_value={"PRETTY_NAME": "Ubuntu 22.04.3 LTS", "VERSION_ID": "22.04"})
def test_detect_os_version_linux_freedesktop(mock_free_os):
    detector = SystemDetector()
    version, release = detector.detect_os_version(os_name="Linux")
    assert version == "Ubuntu 22.04.3 LTS"
    assert release == "22.04"


@patch("platform.freedesktop_os_release", side_effect=OSError("Not freedesktop"))
@patch("platform.release", return_value="5.15.0-generic")
def test_detect_os_version_linux_fallback(mock_rel, mock_free_os):
    detector = SystemDetector()
    version, release = detector.detect_os_version(os_name="Linux")
    assert version == "Linux 5.15.0-generic"
    assert release == "5.15.0-generic"


@patch("platform.release", return_value="11")
@patch("platform.version", return_value="10.0.22631")
def test_detect_os_version_windows(mock_ver, mock_rel):
    detector = SystemDetector()
    mock_win_ver = MagicMock()
    mock_win_ver.build = 22631

    with patch.object(sys, "getwindowsversion", return_value=mock_win_ver, create=True):
        version, release = detector.detect_os_version(os_name="Windows")
        assert "Windows 11" in version
        assert "22631" in version
        assert release == "11"


@patch("platform.machine", return_value="AMD64")
@patch("platform.architecture", return_value=("64bit", "WindowsPE"))
def test_detect_architecture_x86_64(mock_arch, mock_mach):
    detector = SystemDetector()
    raw_arch, norm_arch, is_64bit = detector.detect_architecture()
    assert raw_arch == "AMD64"
    assert norm_arch == "x86_64"
    assert is_64bit is True


@patch("platform.machine", return_value="aarch64")
@patch("platform.architecture", return_value=("64bit", "ELF"))
def test_detect_architecture_arm64(mock_arch, mock_mach):
    detector = SystemDetector()
    raw_arch, norm_arch, is_64bit = detector.detect_architecture()
    assert raw_arch == "aarch64"
    assert norm_arch == "arm64"
    assert is_64bit is True


@patch("platform.machine", return_value="i686")
@patch("platform.architecture", return_value=("32bit", "ELF"))
def test_detect_architecture_x86_32bit(mock_arch, mock_mach):
    detector = SystemDetector()
    raw_arch, norm_arch, is_64bit = detector.detect_architecture()
    assert raw_arch == "i686"
    assert norm_arch == "x86"
    assert is_64bit is False


@patch("platform.python_version", return_value="3.11.9")
def test_detect_python_version(mock_py_ver):
    detector = SystemDetector()
    assert detector.detect_python_version() == "3.11.9"


def test_detect_package_managers_linux():
    def mock_which(cmd):
        if cmd in ("apt-get", "snap"):
            return f"/usr/bin/{cmd}"
        return None

    detector = SystemDetector()
    with patch("shutil.which", side_effect=mock_which):
        managers = detector.detect_package_managers(os_name="Linux")
        assert "apt" in managers
        assert "snap" in managers
        assert "choco" not in managers


def test_detect_package_managers_windows():
    def mock_which(cmd):
        if cmd in ("winget", "choco"):
            return f"C:\\Windows\\System32\\{cmd}.exe"
        return None

    detector = SystemDetector()
    with patch("shutil.which", side_effect=mock_which):
        managers = detector.detect_package_managers(os_name="Windows")
        assert "winget" in managers
        assert "choco" in managers
        assert "apt" not in managers


@patch("shutil.which", return_value="/usr/bin/kicad")
def test_find_binary_on_path(mock_which):
    detector = SystemDetector()
    path = detector.find_binary_on_path("kicad")
    assert path == Path("/usr/bin/kicad")


def test_check_candidate_paths_found(tmp_path):
    dummy_exe = tmp_path / "dummy_executable"
    dummy_exe.write_text("echo test")
    dummy_exe.chmod(0o755)

    detector = SystemDetector()
    result = detector.check_candidate_paths([str(dummy_exe)])
    assert result == dummy_exe


def test_check_candidate_paths_not_found(tmp_path):
    non_existent = str(tmp_path / "non_existent_exe")
    detector = SystemDetector()
    result = detector.check_candidate_paths([non_existent])
    assert result is None
