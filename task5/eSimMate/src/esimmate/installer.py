"""
Installation Manager Module.
Orchestrates package manager selection, dry-run previews, safety confirmation prompts,
safe subprocess execution (without shell=True or os.system), stdout/stderr capturing,
logging, and error classification.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from packaging.version import parse as parse_ver

from esimmate.detector import SystemDetector, SystemInfo
from esimmate.logger import LoggingManager
from esimmate.package_manager import (
    AbstractPackageManager,
    AptAdapter,
    ChocolateyAdapter,
    ManualDownloadAdapter,
    ManualScriptAdapter,
    WingetAdapter,
)
from esimmate.tool import AbstractTool
from esimmate.version_manager import VersionManager, VersionStatus


class InstallStatus(str, Enum):
    """Status codes representing the result of an installation attempt."""
    SUCCESS = "SUCCESS"
    DRY_RUN_PREVIEW = "DRY_RUN_PREVIEW"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"
    UNSUPPORTED_OS = "UNSUPPORTED_OS"
    PACKAGE_MANAGER_UNAVAILABLE = "PACKAGE_MANAGER_UNAVAILABLE"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    INSTALLATION_FAILED = "INSTALLATION_FAILED"


class InstallMethod(str, Enum):
    """Structured installation method category."""
    PACKAGE_MANAGER = "PACKAGE_MANAGER"
    MANUAL_DOWNLOAD = "MANUAL_DOWNLOAD"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class InstallationResult:
    """Structured result of an installation workflow attempt."""
    tool_id: str
    tool_name: str
    package_name: Optional[str]
    package_manager_name: str
    status: InstallStatus
    message: str
    command_executed: Optional[List[str]] = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    dry_run: bool = False
    install_method: InstallMethod = InstallMethod.PACKAGE_MANAGER
    suggested_action: Optional[str] = None


class InstallationManager:
    """Manages external tool installation workflows, confirmations, dry-runs, and execution safety."""

    def __init__(
        self,
        system_detector: Optional[SystemDetector] = None,
        logging_manager: Optional[LoggingManager] = None,
        adapters: Optional[List[AbstractPackageManager]] = None,
    ) -> None:
        self.detector = system_detector or SystemDetector()
        self.logger_mgr = logging_manager or LoggingManager()
        self.logger = self.logger_mgr.get_logger()
        self.version_manager = VersionManager()

        default_adapters = [
            AptAdapter(),
            WingetAdapter(),
            ChocolateyAdapter(),
            ManualScriptAdapter(),
            ManualDownloadAdapter(),
        ]
        self.adapters: Dict[str, AbstractPackageManager] = {
            adapter.name: adapter for adapter in (adapters or default_adapters)
        }

    def register_adapter(self, adapter: AbstractPackageManager) -> None:
        """Register a new package manager adapter."""
        self.adapters[adapter.name] = adapter

    def resolve_package_manager(
        self,
        sys_info: SystemInfo,
        tool: AbstractTool,
    ) -> tuple[Optional[AbstractPackageManager], Optional[str], InstallMethod]:
        """
        Find an available package manager adapter and corresponding package identifier for the tool.
        Verifies package availability dynamically (e.g. winget search). If package is unavailable,
        resolves configured manual/script fallbacks.
        """
        pkg_managers = tool.metadata.package_managers

        # 1. Try system package managers present in sys_info.available_package_managers
        for pm_name in sys_info.available_package_managers:
            pkg_id = pkg_managers.get(pm_name)
            if pkg_id:
                adapter = self.adapters.get(pm_name)
                if adapter and adapter.is_available():
                    if adapter.is_package_available(pkg_id):
                        return adapter, pkg_id, InstallMethod.PACKAGE_MANAGER
                    else:
                        self.logger.info(
                            f"Package '{pkg_id}' for tool '{tool.name}' is unavailable on package manager '{pm_name}'."
                        )

        # 2. Try manual download fallback if configured for tool
        manual_url = pkg_managers.get("manual_download") or tool.metadata.optional_config.get("official_download_url")
        if manual_url:
            adapter = self.adapters.get("manual_download")
            if adapter and adapter.is_available():
                return adapter, manual_url, InstallMethod.MANUAL_DOWNLOAD

        # 3. Try generic script fallback if configured
        script_id = pkg_managers.get("script")
        if script_id:
            adapter = self.adapters.get("script")
            if adapter and adapter.is_available():
                return adapter, script_id, InstallMethod.MANUAL_DOWNLOAD

        return None, None, InstallMethod.UNSUPPORTED

    def _get_target_install_dir(self, tool: AbstractTool) -> Path:
        """Resolve configurable per-user installation directory for manual tool downloads."""
        custom_dir = tool.metadata.optional_config.get("install_dir")
        if custom_dir:
            return Path(custom_dir)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base_dir = Path(local_app_data) / "eSimMate" / "tools"
        else:
            base_dir = Path.home() / ".esimmate" / "tools"
        return base_dir / tool.id

    def _find_7z_extractor(self) -> Optional[List[str]]:
        """
        Locate a supported 7-Zip extraction binary (7z, 7za, or tar) on host system.
        """
        for binary in ("7z", "7za"):
            exe_path = shutil.which(binary)
            if exe_path:
                return [exe_path]

        if sys.platform == "win32":
            candidate_paths = [
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "7-Zip" / "7z.exe",
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "7-Zip" / "7z.exe",
            ]
            for candidate in candidate_paths:
                if candidate.exists():
                    return [str(candidate)]

        tar_path = shutil.which("tar")
        if tar_path:
            return [tar_path]

        return None

    def install_tool(
        self,
        tool: AbstractTool,
        dry_run: bool = False,
        auto_confirm: bool = False,
        confirm_callback: Optional[Callable[[List[str], bool], bool]] = None,
        timeout_seconds: int = 300,
    ) -> InstallationResult:
        """Execute or preview the installation workflow for an external tool."""
        sys_info = self.detector.get_system_info()
        self.logger.info(f"Initiating installation check for tool '{tool.id}' on {sys_info.os_name}")

        # 1. Verify OS Support
        if not tool.is_platform_supported(sys_info.os_name):
            msg = f"Tool '{tool.name}' does not support host OS '{sys_info.os_name}'."
            self.logger.warning(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=None,
                package_manager_name="none",
                status=InstallStatus.UNSUPPORTED_OS,
                message=msg,
                dry_run=dry_run,
                install_method=InstallMethod.UNSUPPORTED,
            )

        # 2. Resolve Package Manager & Package Identifier
        adapter, package_name, install_method = self.resolve_package_manager(sys_info, tool)
        if adapter is None or package_name is None:
            pm_used = sys_info.available_package_managers[0] if sys_info.available_package_managers else "none"
            pkg_id = tool.metadata.package_managers.get(pm_used, "N/A")
            official_url = tool.metadata.optional_config.get(
                "official_download_url",
                "https://sourceforge.net/projects/ngspice/files/"
            )

            if not sys_info.available_package_managers:
                msg = f"No supported package manager available on host system ({sys_info.os_name})."
                status = InstallStatus.PACKAGE_MANAGER_UNAVAILABLE
                suggested_action = "Install a supported package manager or configure tool path manually."
            elif pkg_id == "N/A":
                msg = f"No package identifier defined for tool '{tool.name}' under available package managers ({sys_info.available_package_managers})."
                status = InstallStatus.PACKAGE_NOT_FOUND
                suggested_action = "Configure package manager identifier in tools.yaml."
            else:
                msg = (
                    f"Tool: {tool.name} ({tool.id})\n"
                    f"Package Manager: {pm_used}\n"
                    f"Package ID: {pkg_id}\n"
                    f"Reason: Package '{pkg_id}' was not found in {pm_used} package source repositories.\n"
                    f"Suggested Action: Package is unavailable via {pm_used}. Download official release package directly from SourceForge ({official_url}) and extract to candidate directory."
                )
                status = InstallStatus.PACKAGE_NOT_FOUND
                suggested_action = f"Download official release package directly from SourceForge ({official_url})."

            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=None,
                package_manager_name=pm_used,
                status=status,
                message=msg,
                dry_run=dry_run,
                install_method=InstallMethod.UNSUPPORTED,
                suggested_action=suggested_action,
            )

        # 3. Construct Installation Command Argument List
        cmd = adapter.build_install_command(package_name)
        requires_elevation = adapter.requires_elevation()

        # 4. Handle Dry-Run Mode
        if dry_run:
            if install_method == InstallMethod.MANUAL_DOWNLOAD:
                pkg_id = tool.metadata.package_managers.get("winget") or tool.metadata.package_managers.get("apt") or "N/A"
                official_url = tool.metadata.optional_config.get("official_download_url", package_name)
                source_name = tool.metadata.optional_config.get("official_source_name", "Official Ngspice Release")
                official_ver = tool.metadata.optional_config.get("official_version", "46")
                archive_fn = tool.metadata.optional_config.get("archive_filename", Path(official_url).name)
                target_dir = self._get_target_install_dir(tool)
                pm_display = sys_info.available_package_managers[0] if sys_info.available_package_managers else "winget"

                msg = (
                    f"[DRY-RUN PREVIEW] Package '{pkg_id}' is unavailable on package manager.\n\n"
                    f"Dry-Run Execution Plan:\n"
                    f"  Tool:                   {tool.name} ({tool.id})\n"
                    f"  Package Manager:        {pm_display.capitalize()}\n"
                    f"  {pm_display.capitalize()} Availability:    NOT AVAILABLE\n"
                    f"  Fallback Strategy:      MANUAL_DOWNLOAD\n"
                    f"  Source:                 {source_name}\n"
                    f"  Version:                {official_ver}\n"
                    f"  Archive Filename:       {archive_fn}\n"
                    f"  Download URL:           {official_url}\n"
                    f"  Installation Directory: {target_dir}\n\n"
                    f"No changes will be made to your system."
                )
            else:
                cmd_str = " ".join(cmd)
                msg = f"[DRY-RUN PREVIEW] Would execute installation via {adapter.name}: {cmd_str}"

            self.logger.info(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=package_name,
                package_manager_name=adapter.name,
                status=InstallStatus.DRY_RUN_PREVIEW,
                message=msg,
                command_executed=cmd,
                dry_run=True,
                install_method=install_method,
            )

        # 5. Elevation & User Confirmation Check
        if not auto_confirm:
            if confirm_callback is not None:
                confirmed = confirm_callback(cmd, requires_elevation)
                msg = f"Installation of '{tool.name}' was cancelled by user."
            else:
                confirmed = False
                msg = f"Installation of '{tool.name}' was cancelled safely: Confirmation callback required when auto_confirm=False."

            if not confirmed:
                self.logger.info(msg)
                return InstallationResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    package_name=package_name,
                    package_manager_name=adapter.name,
                    status=InstallStatus.CANCELLED_BY_USER,
                    message=msg,
                    command_executed=cmd,
                    dry_run=False,
                    install_method=install_method,
                )

        # 6. Execute MANUAL_DOWNLOAD workflow if fallback strategy selected
        if install_method == InstallMethod.MANUAL_DOWNLOAD:
            return self._execute_manual_download_installation(tool, package_name, timeout_seconds=timeout_seconds)

        # 7. Execute Command Safely via subprocess.run (shell=False)
        cmd_str = " ".join(cmd)
        self.logger.info(f"Executing installation command: {cmd_str} (Elevated: {requires_elevation})")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            returncode = result.returncode

            self.logger.debug(f"Process returncode: {returncode}\nStdout: {stdout}\nStderr: {stderr}")

            if returncode == 0:
                msg = f"Successfully installed '{tool.name}' via {adapter.name} ({install_method.value})."
                self.logger.info(msg)
                return InstallationResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    package_name=package_name,
                    package_manager_name=adapter.name,
                    status=InstallStatus.SUCCESS,
                    message=msg,
                    command_executed=cmd,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=0,
                    dry_run=False,
                    install_method=install_method,
                )

            # Classify error outputs with structured details
            combined_err = (stdout + "\n" + stderr).lower()
            if "permission denied" in combined_err or returncode in (126, 13, 2316632067, -1978335221) or "administrator" in combined_err or "elevation required" in combined_err:
                status = InstallStatus.PERMISSION_DENIED
                msg = (
                    f"Tool: {tool.name} ({tool.id})\n"
                    f"Package Manager: {adapter.name}\n"
                    f"Package ID: {package_name}\n"
                    f"Reason: Permission or Administrator privilege required to execute installer.\n"
                    f"Suggested Action: Re-run terminal command as Administrator / root user."
                )
            elif "command not found" in combined_err or "is not recognized" in combined_err or returncode == 127:
                status = InstallStatus.COMMAND_NOT_FOUND
                msg = (
                    f"Tool: {tool.name} ({tool.id})\n"
                    f"Package Manager: {adapter.name}\n"
                    f"Package ID: {package_name}\n"
                    f"Reason: Package manager binary or installation command was not found.\n"
                    f"Suggested Action: Verify package manager installation on system PATH."
                )
            elif returncode in (2316632084,) or "no package found" in combined_err or "cannot find" in combined_err:
                status = InstallStatus.PACKAGE_NOT_FOUND
                official_url = tool.metadata.optional_config.get("official_download_url", "https://sourceforge.net/projects/ngspice/files/")
                msg = (
                    f"Tool: {tool.name} ({tool.id})\n"
                    f"Package Manager: {adapter.name}\n"
                    f"Package ID: {package_name}\n"
                    f"Reason: Package '{package_name}' is not available in package manager repositories (exit code {returncode}).\n"
                    f"Suggested Action: Download official Windows release package directly from SourceForge ({official_url}) and extract executable to candidate directory."
                )
            elif any(net_err in combined_err for net_err in ["could not resolve", "network error", "connection timed out", "download failed", "http 404", "unable to fetch"]):
                status = InstallStatus.NETWORK_FAILURE
                msg = f"Network failure downloading package for '{tool.name}'."
            else:
                status = InstallStatus.INSTALLATION_FAILED
                msg = (
                    f"Tool: {tool.name} ({tool.id})\n"
                    f"Package Manager: {adapter.name}\n"
                    f"Package ID: {package_name}\n"
                    f"Reason: Installation command failed with exit code {returncode}.\n"
                    f"Suggested Action: Check stderr logs or run command manually."
                )

            self.logger.error(f"{msg} (Return code: {returncode})\nStderr: {stderr}")
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=package_name,
                package_manager_name=adapter.name,
                status=status,
                message=msg,
                command_executed=cmd,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                dry_run=False,
                install_method=install_method,
            )

        except FileNotFoundError:
            msg = f"Binary '{cmd[0]}' was not found on host system."
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=package_name,
                package_manager_name=adapter.name,
                status=InstallStatus.COMMAND_NOT_FOUND,
                message=msg,
                command_executed=cmd,
                returncode=127,
                dry_run=False,
                install_method=install_method,
            )
        except PermissionError:
            msg = f"Permission denied executing '{cmd[0]}'."
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=package_name,
                package_manager_name=adapter.name,
                status=InstallStatus.PERMISSION_DENIED,
                message=msg,
                command_executed=cmd,
                returncode=126,
                dry_run=False,
                install_method=install_method,
            )
        except subprocess.TimeoutExpired:
            msg = f"Installation command timed out after {timeout_seconds} seconds."
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=package_name,
                package_manager_name=adapter.name,
                status=InstallStatus.NETWORK_FAILURE,
                message=msg,
                command_executed=cmd,
                returncode=-1,
                dry_run=False,
                install_method=install_method,
            )

    def _execute_manual_download_installation(
        self,
        tool: AbstractTool,
        download_url: str,
        timeout_seconds: int = 300,
    ) -> InstallationResult:
        """
        Execute full MANUAL_DOWNLOAD workflow:
        1. Download official archive
        2. Verify HTTP success & downloaded file exists
        3. Verify SHA-256 checksum if configured
        4. Extract archive safely using supported 7z/zip extractor
        5. Locate ngspice.exe / tool executable
        6. Register executable path in managed candidate search paths
        7. Execute version query command
        8. Verify installed version satisfies compatibility bounds
        9. Return SUCCESS only if all verification steps pass
        """
        install_dir = self._get_target_install_dir(tool)
        archive_name = tool.metadata.optional_config.get("archive_filename", Path(download_url).name)
        if not archive_name or archive_name == "download":
            archive_name = f"{tool.id}_archive.7z"

        archive_path = install_dir / archive_name

        try:
            install_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            msg = f"Failed to create installation directory '{install_dir}': {e}"
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.INSTALLATION_FAILED,
                message=msg,
                returncode=1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
            )

        # 1. Download official archive
        self.logger.info(f"Downloading official archive for '{tool.name}' from {download_url} to {archive_path}")
        try:
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "eSimMate-ToolManager/0.1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                if response.status not in (200, 301, 302):
                    msg = (
                        f"Installation Failed\n\n"
                        f"Tool: {tool.name}\n"
                        f"Strategy: MANUAL_DOWNLOAD\n"
                        f"Archive: {archive_name}\n\n"
                        f"Reason:\n"
                        f"HTTP status failure ({response.status}) downloading from official URL '{download_url}'.\n\n"
                        f"Suggested action:\n"
                        f"Verify internet connection or official URL."
                    )
                    self.logger.error(msg)
                    return InstallationResult(
                        tool_id=tool.id,
                        tool_name=tool.name,
                        package_name=download_url,
                        package_manager_name="manual_download",
                        status=InstallStatus.NETWORK_FAILURE,
                        message=msg,
                        returncode=response.status,
                        install_method=InstallMethod.MANUAL_DOWNLOAD,
                        suggested_action="Verify internet connection or official download URL.",
                    )
                with open(archive_path, "wb") as out_file:
                    shutil.copyfileobj(response, out_file)
        except urllib.error.URLError as e:
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Network failure downloading official release archive: {e.reason if hasattr(e, 'reason') else e}\n\n"
                f"Suggested action:\n"
                f"Check internet connection or proxy settings."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.NETWORK_FAILURE,
                message=msg,
                returncode=-1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Check internet connection or proxy settings.",
            )
        except Exception as e:
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Download failed for '{tool.name}': {e}\n\n"
                f"Suggested action:\n"
                f"Check network connectivity or retry installation."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.NETWORK_FAILURE,
                message=msg,
                returncode=-1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Check network connectivity or retry installation.",
            )

        # 2. Verify downloaded file exists and non-empty
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Downloaded archive file '{archive_path}' does not exist or is 0 bytes.\n\n"
                f"Suggested action:\n"
                f"Retry installation or download archive manually."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.NETWORK_FAILURE,
                message=msg,
                returncode=-1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Retry installation or download archive manually.",
            )

        # 3. Checksum Verification (if configured)
        expected_checksum = tool.metadata.optional_config.get("sha256_checksum")
        if expected_checksum:
            self.logger.info("Verifying SHA-256 checksum for downloaded archive...")
            sha256 = hashlib.sha256()
            with open(archive_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            computed = sha256.hexdigest().lower()
            if computed != expected_checksum.lower():
                msg = f"SHA-256 checksum mismatch for '{archive_name}' (expected {expected_checksum}, got {computed})."
                self.logger.error(msg)
                return InstallationResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    package_name=download_url,
                    package_manager_name="manual_download",
                    status=InstallStatus.INSTALLATION_FAILED,
                    message=msg,
                    returncode=1,
                    install_method=InstallMethod.MANUAL_DOWNLOAD,
                )
        else:
            self.logger.info("Note: Official SourceForge direct download URL does not publish a static SHA-256 header; skipping optional checksum verification.")

        # 4. Extract archive safely using supported extractor
        self.logger.info(f"Extracting archive '{archive_path}' to '{install_dir}'...")
        ext = archive_path.suffix.lower()

        try:
            extracted_ok = False
            if ext == ".zip":
                import zipfile
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(install_dir)
                extracted_ok = True
            else:
                extractor = self._find_7z_extractor()
                if extractor is None:
                    msg = (
                        f"Installation Failed\n\n"
                        f"Tool: {tool.name}\n"
                        f"Strategy: MANUAL_DOWNLOAD\n"
                        f"Archive: {archive_name}\n\n"
                        f"Reason:\n"
                        f"The 7-Zip extraction dependency (7z/7za/tar) is unavailable on host system.\n\n"
                        f"Suggested action:\n"
                        f"Install 7-Zip or configure an existing 7z executable on system PATH."
                    )
                    self.logger.error(msg)
                    return InstallationResult(
                        tool_id=tool.id,
                        tool_name=tool.name,
                        package_name=download_url,
                        package_manager_name="manual_download",
                        status=InstallStatus.INSTALLATION_FAILED,
                        message=msg,
                        returncode=1,
                        install_method=InstallMethod.MANUAL_DOWNLOAD,
                        suggested_action="Install 7-Zip or configure an existing 7z executable.",
                    )

                bin_name = Path(extractor[0]).name.lower()
                if "7z" in bin_name or "7za" in bin_name:
                    cmd = extractor + ["x", str(archive_path), f"-o{install_dir}", "-y"]
                else:
                    cmd = extractor + ["-xf", str(archive_path), "-C", str(install_dir)]

                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    shell=False,
                )
                if res.returncode == 0:
                    extracted_ok = True

            if not extracted_ok:
                msg = (
                    f"Installation Failed\n\n"
                    f"Tool: {tool.name}\n"
                    f"Strategy: MANUAL_DOWNLOAD\n"
                    f"Archive: {archive_name}\n\n"
                    f"Reason:\n"
                    f"Archive extraction failed for '{archive_name}'. Archive may be corrupt or invalid.\n\n"
                    f"Suggested action:\n"
                    f"Verify archive file integrity or extract manually."
                )
                self.logger.error(msg)
                return InstallationResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    package_name=download_url,
                    package_manager_name="manual_download",
                    status=InstallStatus.INSTALLATION_FAILED,
                    message=msg,
                    returncode=1,
                    install_method=InstallMethod.MANUAL_DOWNLOAD,
                    suggested_action="Verify archive file integrity or extract manually.",
                )
        except Exception as e:
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Archive extraction error: {e}\n\n"
                f"Suggested action:\n"
                f"Verify archive file integrity or extract manually."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.INSTALLATION_FAILED,
                message=msg,
                returncode=1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Verify archive file integrity or extract manually.",
            )

        # 5. Locate executable
        sys_info = self.detector.get_system_info()
        exe_candidates = (
            tool.get_executable_candidates(sys_info.os_name)
            if hasattr(tool, "get_executable_candidates")
            else ([tool.get_executable(sys_info.os_name)] if hasattr(tool, "get_executable") and tool.get_executable(sys_info.os_name) else ["ngspice_con.exe", "ngspice.exe"])
        )
        exe_path: Optional[Path] = None

        for cand in exe_candidates:
            for root, dirs, files in os.walk(install_dir):
                if cand in files:
                    exe_path = Path(root) / cand
                    break
            if exe_path is not None:
                break

        exe_name_display = exe_candidates[0] if exe_candidates else "executable"

        if exe_path is None or not exe_path.exists():
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Executable '{exe_name_display}' not found in extracted archive directory '{install_dir}'.\n\n"
                f"Suggested action:\n"
                f"Verify archive contents or extract manually."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.INSTALLATION_FAILED,
                message=msg,
                returncode=1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Verify archive contents or extract manually.",
            )

        # 6. Register executable path in candidate search paths
        search_paths = tool.metadata.default_search_paths.setdefault(sys_info.os_name.lower(), [])
        if str(exe_path) not in search_paths:
            search_paths.insert(0, str(exe_path))

        # 7. Run version query command on executable via VersionManager (supports interactive_banner mode)
        try:
            ver_res = self.version_manager.check_tool(tool, executable_path=exe_path)
            if ver_res.status in (VersionStatus.COMPATIBLE, VersionStatus.NEWER_VERSION):
                extracted_ver_str = ver_res.installed_version or "unknown"
                msg = (
                    f"Successfully installed '{tool.name}' version {extracted_ver_str} via official archive fallback.\n"
                    f"Executable registered at: '{exe_path}'"
                )
                self.logger.info(msg)
                return InstallationResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    package_name=download_url,
                    package_manager_name="manual_download",
                    status=InstallStatus.SUCCESS,
                    message=msg,
                    command_executed=ver_res.command_executed,
                    stdout=ver_res.raw_output or "",
                    stderr="",
                    returncode=0,
                    dry_run=False,
                    install_method=InstallMethod.MANUAL_DOWNLOAD,
                )

            # Failure during version checking or compatibility check
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Version verification failed for executable '{exe_path}': {ver_res.message}\n\n"
                f"Suggested action:\n"
                f"Verify tool execution permissions or version check configuration."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.INSTALLATION_FAILED,
                message=msg,
                stdout=ver_res.raw_output,
                stderr="",
                returncode=1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Verify tool execution permissions or version check configuration.",
            )

        except Exception as e:
            msg = (
                f"Installation Failed\n\n"
                f"Tool: {tool.name}\n"
                f"Strategy: MANUAL_DOWNLOAD\n"
                f"Archive: {archive_name}\n\n"
                f"Reason:\n"
                f"Verification execution failed for '{exe_path}': {e}\n\n"
                f"Suggested action:\n"
                f"Check file permissions and execution policies."
            )
            self.logger.error(msg)
            return InstallationResult(
                tool_id=tool.id,
                tool_name=tool.name,
                package_name=download_url,
                package_manager_name="manual_download",
                status=InstallStatus.INSTALLATION_FAILED,
                message=msg,
                returncode=1,
                install_method=InstallMethod.MANUAL_DOWNLOAD,
                suggested_action="Check file permissions and execution policies.",
            )


