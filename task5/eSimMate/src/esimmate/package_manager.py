"""
Package Manager Abstraction Module.
Defines the abstract base interface and concrete adapters for Linux and Windows package managers.
Supports apt, winget, choco, and custom script installers.
"""

import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class InstallResult:
    """Result of a package manager installation operation."""
    success: bool
    package_name: str
    return_code: int
    message: str
    command_executed: List[str]
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False


class AbstractPackageManager(ABC):
    """Abstract base class for OS package manager adapters."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the package manager binary is available on system PATH."""
        pass

    @abstractmethod
    def build_install_command(self, package_id: str) -> List[str]:
        """Construct the package installation command as a list of strings."""
        pass

    @abstractmethod
    def requires_elevation(self) -> bool:
        """Determine if this package manager requires root or administrator privileges."""
        pass

    def is_package_available(self, package_id: str) -> bool:
        """Check if a specific package identifier is available in package manager repositories."""
        return True


class AptAdapter(AbstractPackageManager):
    """Package manager adapter for Debian/Ubuntu apt-get."""

    def __init__(self) -> None:
        super().__init__("apt")

    def is_available(self) -> bool:
        return shutil.which("apt-get") is not None or shutil.which("apt") is not None

    def build_install_command(self, package_id: str) -> List[str]:
        return ["sudo", "apt-get", "install", "-y", package_id]

    def requires_elevation(self) -> bool:
        return True


class WingetAdapter(AbstractPackageManager):
    """Package manager adapter for Windows Package Manager (winget)."""

    def __init__(self) -> None:
        super().__init__("winget")

    def is_available(self) -> bool:
        return shutil.which("winget") is not None

    def build_install_command(self, package_id: str) -> List[str]:
        return [
            "winget",
            "install",
            "--id",
            package_id,
            "-e",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]

    def requires_elevation(self) -> bool:
        return False

    def is_package_available(self, package_id: str) -> bool:
        """Check if package_id exists in winget package sources via winget search."""
        if not package_id:
            return False
        try:
            import subprocess

            cmd = ["winget", "search", "--id", package_id, "-e"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            if result.returncode == 0 and package_id.lower() in (result.stdout or "").lower():
                return True
            return False
        except Exception:
            return False


class ChocolateyAdapter(AbstractPackageManager):
    """Package manager adapter for Windows Chocolatey (choco)."""

    def __init__(self) -> None:
        super().__init__("choco")

    def is_available(self) -> bool:
        return shutil.which("choco") is not None

    def build_install_command(self, package_id: str) -> List[str]:
        return ["choco", "install", package_id, "-y"]

    def requires_elevation(self) -> bool:
        return True


class ManualScriptAdapter(AbstractPackageManager):
    """Installer adapter for executing standalone installer scripts."""

    def __init__(self) -> None:
        super().__init__("script")

    def is_available(self) -> bool:
        return True

    def build_install_command(self, package_id: str) -> List[str]:
        if sys.platform == "win32":
            return ["powershell", "-ExecutionPolicy", "Bypass", "-File", package_id]
        return ["bash", package_id]

    def requires_elevation(self) -> bool:
        return False


class ManualDownloadAdapter(AbstractPackageManager):
    """Installer adapter for downloading and extracting official tool binary archives."""

    def __init__(self) -> None:
        super().__init__("manual_download")

    def is_available(self) -> bool:
        return True

    def build_install_command(self, package_id: str) -> List[str]:
        return ["download-archive", package_id]

    def requires_elevation(self) -> bool:
        return False


class PlaceholderPackageManager(AbstractPackageManager):
    """Placeholder implementation of AbstractPackageManager for testing."""

    def __init__(
        self,
        name: str = "placeholder_pm",
        available: bool = True,
        elevation: bool = False,
    ) -> None:
        super().__init__(name)
        self._available = available
        self._elevation = elevation

    def is_available(self) -> bool:
        return self._available

    def build_install_command(self, package_id: str) -> List[str]:
        return ["echo", f"Installing {package_id} via {self.name}"]

    def requires_elevation(self) -> bool:
        return self._elevation
