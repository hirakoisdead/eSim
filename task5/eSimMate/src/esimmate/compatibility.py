"""
Compatibility Checker Module.
Evaluates installed tool versions against configured eSim compatibility matrices.
"""

from typing import Optional
from esimmate.tool import VersionBounds
from esimmate.version_manager import VersionManager, VersionStatus

# Re-export VersionStatus as CompatibilityStatus for compatibility
CompatibilityStatus = VersionStatus


class CompatibilityChecker:
    """Evaluates tool installation status against target version bounds."""

    def __init__(self, version_manager: Optional[VersionManager] = None) -> None:
        self.version_manager = version_manager or VersionManager()

    def evaluate(
        self,
        installed_version: Optional[str],
        bounds: VersionBounds,
    ) -> VersionStatus:
        """Evaluate an installed version string against VersionBounds."""
        if installed_version is None:
            return VersionStatus.NOT_INSTALLED

        try:
            if self.version_manager.compare_versions(installed_version, bounds.min_version) < 0:
                return VersionStatus.OUTDATED

            if self.version_manager.compare_versions(installed_version, bounds.max_version) > 0:
                return VersionStatus.NEWER_VERSION

            return VersionStatus.COMPATIBLE
        except ValueError:
            return VersionStatus.VERSION_UNKNOWN
