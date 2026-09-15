"""
System Detector Module.
Provides operating system, OS version, CPU architecture, Python version,
and package manager detection for Windows and Linux platforms.
"""

import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SystemInfo:
    """Host system platform and environment information."""
    os_name: str                          # "Windows", "Linux", "Darwin", etc.
    os_version: str                       # Detailed version (e.g. "Ubuntu 22.04 LTS", "Windows 11 (10.0.22631)")
    os_release: str                       # Release identifier (e.g. "22.04", "11")
    architecture: str                     # Raw architecture (e.g. "AMD64", "x86_64", "aarch64")
    architecture_normalized: str          # Standardized architecture ("x86_64", "arm64", "x86")
    is_64bit: bool                        # True if 64-bit environment
    python_version: str                   # Python runtime version (e.g. "3.11.9")
    available_package_managers: List[str] = field(default_factory=list) # Available PM names


class SystemDetector:
    """Detects host system environment details, OS metadata, package managers, and binary paths."""

    KNOWN_PACKAGE_MANAGERS: Dict[str, List[Tuple[str, str]]] = {
        "Linux": [
            ("apt-get", "apt"),
            ("apt", "apt"),
            ("dpkg", "dpkg"),
            ("snap", "snap"),
            ("flatpak", "flatpak"),
        ],
        "Windows": [
            ("winget", "winget"),
            ("choco", "choco"),
            ("scoop", "scoop"),
        ],
    }

    def __init__(self) -> None:
        self._sys_info: Optional[SystemInfo] = None

    def get_system_info(self, force_refresh: bool = False) -> SystemInfo:
        """Detect and return host system platform information."""
        if self._sys_info is None or force_refresh:
            os_name = self.detect_os_name()
            os_version, os_release = self.detect_os_version(os_name)
            arch, arch_norm, is_64bit = self.detect_architecture()
            py_version = self.detect_python_version()
            pkg_managers = self.detect_package_managers(os_name)

            self._sys_info = SystemInfo(
                os_name=os_name,
                os_version=os_version,
                os_release=os_release,
                architecture=arch,
                architecture_normalized=arch_norm,
                is_64bit=is_64bit,
                python_version=py_version,
                available_package_managers=pkg_managers,
            )
        return self._sys_info

    def detect_os_name(self) -> str:
        """Detect the operating system kernel name."""
        return platform.system()

    def detect_os_version(self, os_name: Optional[str] = None) -> Tuple[str, str]:
        """Detect OS version string and release identifier."""
        if os_name is None:
            os_name = self.detect_os_name()

        if os_name == "Linux":
            try:
                if hasattr(platform, "freedesktop_os_release"):
                    os_rel_data = platform.freedesktop_os_release()
                    pretty_name = os_rel_data.get("PRETTY_NAME", "")
                    version_id = os_rel_data.get("VERSION_ID", "")
                    if pretty_name:
                        return pretty_name, version_id or platform.release()
            except (AttributeError, OSError, KeyError, FileNotFoundError):
                pass
            return f"Linux {platform.release()}", platform.release()

        elif os_name == "Windows":
            release = platform.release()
            version = platform.version()
            if hasattr(sys, "getwindowsversion"):
                try:
                    win_ver = sys.getwindowsversion()
                    build = getattr(win_ver, "build", "")
                    return f"Windows {release} (build {build})", release
                except Exception:
                    pass
            return f"Windows {release} ({version})", release

        return f"{os_name} {platform.release()}", platform.release()

    def detect_architecture(self) -> Tuple[str, str, bool]:
        """Detect CPU architecture, normalized architecture name, and 64-bit status."""
        raw_arch = platform.machine()
        arch_lower = raw_arch.lower()

        if raw_arch.upper() in ("AMD64", "X86_64", "X86-64") or arch_lower == "x86_64":
            normalized = "x86_64"
        elif raw_arch.upper() in ("AARCH64", "ARM64") or arch_lower in ("arm64", "aarch64"):
            normalized = "arm64"
        elif raw_arch.upper() in ("I386", "I686", "X86"):
            normalized = "x86"
        else:
            normalized = arch_lower

        if normalized in ("x86", "i386", "i686", "arm", "armv7l"):
            is_64bit = False
        else:
            is_64bit = (
                sys.maxsize > 2**32
                or normalized in ("x86_64", "arm64", "aarch64")
            )

        return raw_arch, normalized, is_64bit

    def detect_python_version(self) -> str:
        """Return the running Python interpreter version."""
        return platform.python_version()

    def detect_package_managers(self, os_name: Optional[str] = None) -> List[str]:
        """Detect available system package managers for the target OS."""
        if os_name is None:
            os_name = self.detect_os_name()

        target_managers = self.KNOWN_PACKAGE_MANAGERS.get(os_name, [])
        detected: List[str] = []

        for binary_cmd, pm_id in target_managers:
            if shutil.which(binary_cmd) is not None:
                if pm_id not in detected:
                    detected.append(pm_id)

        return detected

    def find_binary_on_path(self, binary_name: str) -> Optional[Path]:
        """Scan system PATH environment variable for a binary executable."""
        path_str = shutil.which(binary_name)
        if path_str:
            return Path(path_str)
        return None

    def check_candidate_paths(self, candidate_paths: List[str]) -> Optional[Path]:
        """Check a list of candidate filesystem paths for an existing executable."""
        for raw_path in candidate_paths:
            expanded = os.path.expandvars(os.path.expanduser(raw_path))
            path_obj = Path(expanded)
            if path_obj.is_file() and os.access(path_obj, os.X_OK):
                return path_obj
        return None

    def find_tool_executable(self, tool: Any, os_name: Optional[str] = None) -> Optional[Path]:
        """Discover the binary executable path for a given tool on host system or default candidate paths."""
        if os_name is None:
            os_name = self.get_system_info().os_name

        executable_candidates = (
            tool.get_executable_candidates(os_name)
            if hasattr(tool, "get_executable_candidates")
            else ([tool.get_executable(os_name)] if hasattr(tool, "get_executable") and tool.get_executable(os_name) else [])
        )

        for exe_name in executable_candidates:
            if exe_name:
                path = self.find_binary_on_path(exe_name)
                if path:
                    return path

        if hasattr(tool, "metadata"):
            candidate_paths = tool.metadata.default_search_paths.get(os_name.lower(), [])
            path = self.check_candidate_paths(candidate_paths)
            if path:
                return path

        return None

