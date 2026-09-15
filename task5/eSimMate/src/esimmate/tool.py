"""
Tool Abstraction Module.
Defines domain classes, metadata structures, and concrete configurable tool classes
for managing external EDA tools in eSimMate.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class VersionBounds:
    """Compatibility version bounds for an external tool."""
    min_version: str
    recommended_version: str
    max_version: str


@dataclass
class VersionCheckConfig:
    """Subprocess configuration for querying a tool's installed version."""
    command: List[str] = field(default_factory=lambda: ["--version"])
    regex: str = r"(\d+\.\d+\.\d+)"
    timeout_seconds: int = 5
    mode: str = "standard"  # "standard" or "interactive_banner"


@dataclass
class ToolMetadata:
    """Comprehensive metadata describing an external tool."""
    id: str
    name: str
    category: str
    mandatory: bool
    purpose: str
    executables: Dict[str, str]                          # e.g. {"linux": "kicad", "windows": "kicad.exe"}
    compatibility: VersionBounds
    version_check: VersionCheckConfig = field(default_factory=VersionCheckConfig)
    supported_platforms: List[str] = field(default_factory=lambda: ["Linux", "Windows"])
    package_managers: Dict[str, str] = field(default_factory=dict) # e.g. {"apt": "kicad", "winget": "KiCad.KiCad"}
    default_search_paths: Dict[str, List[str]] = field(default_factory=dict)
    environment_variables: List[str] = field(default_factory=list)
    optional_config: Dict[str, Any] = field(default_factory=dict)
    executable_candidates: Dict[str, List[str]] = field(default_factory=dict)


class AbstractTool(ABC):
    """Abstract base class representing an external tool."""

    def __init__(self, metadata: ToolMetadata) -> None:
        self.metadata = metadata

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def is_mandatory(self) -> bool:
        return self.metadata.mandatory

    @property
    def supported_platforms(self) -> List[str]:
        return self.metadata.supported_platforms

    def get_executable(self, os_name: str) -> Optional[str]:
        """Return primary executable filename for specified OS name."""
        candidates = self.get_executable_candidates(os_name)
        return candidates[0] if candidates else None

    def get_executable_candidates(self, os_name: str) -> List[str]:
        """Return list of executable candidate names in preference order for specified OS name."""
        os_key = os_name.lower()
        candidates = (
            self.metadata.executable_candidates.get(os_key)
            or self.metadata.executable_candidates.get(os_name)
        )
        if candidates:
            return list(candidates) if isinstance(candidates, list) else [str(candidates)]

        exec_val = (
            self.metadata.executables.get(os_key)
            or self.metadata.executables.get(os_name)
        )
        if exec_val:
            return list(exec_val) if isinstance(exec_val, list) else [str(exec_val)]

        return []

    def get_package_name(self, package_manager_id: str) -> Optional[str]:
        """Return package identifier for specified package manager."""
        return self.metadata.package_managers.get(package_manager_id)

    def is_platform_supported(self, os_name: str) -> bool:
        """Check if the given OS platform is supported by this tool."""
        if not self.metadata.supported_platforms:
            return True
        return os_name in self.metadata.supported_platforms or os_name.capitalize() in self.metadata.supported_platforms

    @abstractmethod
    def detect_path(self) -> Optional[Path]:
        """Detect the binary path of the tool on the host system."""
        pass

    @abstractmethod
    def get_installed_version(self) -> Optional[str]:
        """Query and extract the installed version of the tool."""
        pass


class ConfigurableTool(AbstractTool):
    """Concrete tool implementation constructed entirely from configuration metadata."""

    def __init__(self, metadata: ToolMetadata) -> None:
        super().__init__(metadata)
        self._detected_path: Optional[Path] = None
        self._installed_version: Optional[str] = None

    def detect_path(self) -> Optional[Path]:
        """Return cached or detected path."""
        return self._detected_path

    def set_detected_path(self, path: Optional[Path]) -> None:
        """Set detected binary path."""
        self._detected_path = path

    def get_installed_version(self) -> Optional[str]:
        """Return cached or detected installed version."""
        return self._installed_version

    def set_installed_version(self, version: Optional[str]) -> None:
        """Set detected installed version string."""
        self._installed_version = version


class PlaceholderTool(AbstractTool):
    """Placeholder implementation of AbstractTool for scaffolding and testing."""

    def __init__(
        self,
        tool_id: str = "placeholder_tool",
        name: str = "Placeholder Tool",
        mandatory: bool = False,
        mock_path: Optional[Path] = None,
        mock_version: Optional[str] = None,
    ) -> None:
        metadata = ToolMetadata(
            id=tool_id,
            name=name,
            category="testing",
            mandatory=mandatory,
            purpose="Placeholder for testing architecture scaffolding",
            executables={"linux": tool_id, "windows": f"{tool_id}.exe"},
            compatibility=VersionBounds("1.0.0", "1.0.0", "2.0.0"),
            supported_platforms=["Linux", "Windows"],
        )
        super().__init__(metadata)
        self._mock_path = mock_path
        self._mock_version = mock_version

    def detect_path(self) -> Optional[Path]:
        return self._mock_path

    def get_installed_version(self) -> Optional[str]:
        return self._mock_version
