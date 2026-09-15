"""
Version Manager Module.
Executes version query commands safely without shell=True, parses version strings via regex,
evaluates version compatibility matrices, and returns structured diagnostic results.
"""

import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional
from packaging.version import InvalidVersion, Version

from esimmate.tool import AbstractTool, VersionBounds, VersionCheckConfig


class VersionStatus(str, Enum):
    """Structured version check and compatibility status states."""
    NOT_INSTALLED = "NOT_INSTALLED"
    COMPATIBLE = "COMPATIBLE"
    OUTDATED = "OUTDATED"
    NEWER_VERSION = "NEWER_VERSION"
    VERSION_UNKNOWN = "VERSION_UNKNOWN"
    ERROR = "ERROR"


@dataclass
class VersionCheckResult:
    """Structured result containing binary existence, version parsing, and compatibility status."""
    tool_id: str
    tool_name: str
    executable_path: Optional[Path]
    installed_version: Optional[str]
    status: VersionStatus
    message: str
    raw_output: Optional[str] = None
    command_executed: Optional[List[str]] = None


class VersionManager:
    """Manages execution of version check commands, parsing output, and checking compatibility."""

    def extract_version_string(self, raw_output: str, regex_pattern: str) -> Optional[str]:
        """Apply a regular expression pattern to raw stdout/stderr to extract a version string."""
        if not raw_output or not regex_pattern:
            return None
        match = re.search(regex_pattern, raw_output, re.IGNORECASE | re.MULTILINE)
        if match:
            # Prefer group 1 if captured, otherwise full match
            return match.group(1) if match.groups() else match.group(0)
        return None

    def parse_version(self, version_str: str) -> Optional[Version]:
        """Parse a raw version string into a packaging.version.Version object."""
        if not version_str:
            return None
        try:
            return Version(version_str)
        except InvalidVersion:
            return None

    def compare_versions(self, v1: str, v2: str) -> int:
        """Compare two version strings. Returns -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2."""
        parsed_v1 = self.parse_version(v1)
        parsed_v2 = self.parse_version(v2)

        if parsed_v1 is None or parsed_v2 is None:
            raise ValueError(f"Cannot compare invalid version strings: '{v1}' and '{v2}'")

        if parsed_v1 < parsed_v2:
            return -1
        elif parsed_v1 > parsed_v2:
            return 1
        return 0

    def execute_version_command(
        self,
        executable_path: Path,
        version_config: VersionCheckConfig,
    ) -> tuple[Optional[str], int, Optional[str]]:
        """
        Safely execute version query command.
        Supports standard mode (commands that exit naturally) and interactive_banner mode
        (for interactive tools like Ngspice that print version/banner on startup and remain running).
        """
        if not executable_path.exists():
            return None, -1, f"Executable binary '{executable_path}' was not found."

        cmd_args = list(version_config.command)
        if cmd_args:
            cmd_args[0] = str(executable_path)
        else:
            cmd_args = [str(executable_path), "--version"]

        cwd = executable_path.parent if executable_path.parent.exists() else None

        if getattr(version_config, "mode", "standard") == "interactive_banner":
            return self._execute_interactive_version_command(cmd_args, cwd, version_config)

        try:
            result = subprocess.run(
                cmd_args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=version_config.timeout_seconds,
                shell=False,
            )
            raw_output = (result.stdout or "") + "\n" + (result.stderr or "")
            return raw_output, result.returncode, None
        except subprocess.TimeoutExpired:
            return None, -1, f"Command timed out after {version_config.timeout_seconds} seconds"
        except (OSError, PermissionError, subprocess.SubprocessError) as exc:
            return None, -1, f"Process execution failed: {str(exc)}"

    def _execute_interactive_version_command(
        self,
        cmd_args: List[str],
        cwd: Optional[Path],
        version_config: VersionCheckConfig,
    ) -> tuple[Optional[str], int, Optional[str]]:
        """
        Execute interactive console executable (e.g. Ngspice) using subprocess.Popen.
        Captures startup stdout/stderr in real-time line-by-line, monitors for version regex match,
        and safely terminates the process immediately upon finding the version banner.
        Does NOT leave orphan processes running.
        """
        try:
            process = subprocess.Popen(
                cmd_args,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False,
            )
        except (OSError, PermissionError, subprocess.SubprocessError) as exc:
            return None, -1, f"Process execution failed: {str(exc)}"

        accumulated_lines: List[str] = []
        start_time = time.time()
        found_version = False

        try:
            while time.time() - start_time < version_config.timeout_seconds:
                if process.stdout:
                    line = process.stdout.readline()
                    if not line:
                        break
                    accumulated_lines.append(line)
                    current_output = "".join(accumulated_lines)

                    if version_config.regex and re.search(version_config.regex, current_output, re.IGNORECASE | re.MULTILINE):
                        found_version = True
                        break
                else:
                    break
        except Exception:
            pass

        # Terminate the subprocess safely (never kill arbitrary processes)
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        except Exception:
            pass

        # Close standard streams safely
        if process.stdout:
            try:
                process.stdout.close()
            except Exception:
                pass

        raw_output = "".join(accumulated_lines)

        if found_version:
            return raw_output, 0, None

        if time.time() - start_time >= version_config.timeout_seconds:
            return raw_output if raw_output else None, -1, f"Command timed out after {version_config.timeout_seconds} seconds"

        rc = process.returncode if isinstance(process.returncode, int) else 0
        return raw_output, rc, None

    def check_tool(
        self,
        tool: AbstractTool,
        executable_path: Optional[Path] = None,
        detector: Optional[Any] = None,
    ) -> VersionCheckResult:
        """Complete version detection workflow: detect binary, run command, parse version, compare bounds."""
        path_to_check = executable_path or tool.detect_path()
        if path_to_check is None and detector is not None:
            path_to_check = detector.find_tool_executable(tool)

        if path_to_check is None or not Path(path_to_check).exists():
            return VersionCheckResult(
                tool_id=tool.id,
                tool_name=tool.name,
                executable_path=None,
                installed_version=None,
                status=VersionStatus.NOT_INSTALLED,
                message=f"Executable for {tool.name} was not found on host system.",
            )

        ver_config = getattr(tool.metadata, "version_check", VersionCheckConfig())

        raw_output, returncode, err_msg = self.execute_version_command(path_to_check, ver_config)
        cmd_executed = [str(path_to_check)] + list(ver_config.command[1:] if ver_config.command else ["--version"])

        if err_msg is not None:
            return VersionCheckResult(
                tool_id=tool.id,
                tool_name=tool.name,
                executable_path=path_to_check,
                installed_version=None,
                status=VersionStatus.ERROR,
                message=f"Command execution error: {err_msg}",
                raw_output=None,
                command_executed=cmd_executed,
            )

        extracted_version = self.extract_version_string(raw_output or "", ver_config.regex)
        parsed_version = self.parse_version(extracted_version) if extracted_version else None

        if extracted_version is None or parsed_version is None:
            if returncode != 0:
                return VersionCheckResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    executable_path=path_to_check,
                    installed_version=None,
                    status=VersionStatus.ERROR,
                    message=f"Version check command failed with non-zero exit code {returncode}.",
                    raw_output=raw_output,
                    command_executed=cmd_executed,
                )

            return VersionCheckResult(
                tool_id=tool.id,
                tool_name=tool.name,
                executable_path=path_to_check,
                installed_version=extracted_version,
                status=VersionStatus.VERSION_UNKNOWN,
                message="Executable responded but version pattern could not be parsed.",
                raw_output=raw_output,
                command_executed=cmd_executed,
            )

        # Evaluate against compatibility version bounds
        bounds = tool.metadata.compatibility
        try:
            if self.compare_versions(extracted_version, bounds.min_version) < 0:
                status = VersionStatus.OUTDATED
                msg = f"Installed version '{extracted_version}' is below minimum required version '{bounds.min_version}'."
            elif self.compare_versions(extracted_version, bounds.max_version) > 0:
                status = VersionStatus.NEWER_VERSION
                msg = f"Installed version '{extracted_version}' is higher than maximum verified version '{bounds.max_version}'."
            else:
                status = VersionStatus.COMPATIBLE
                msg = f"Installed version '{extracted_version}' is compatible."

            return VersionCheckResult(
                tool_id=tool.id,
                tool_name=tool.name,
                executable_path=path_to_check,
                installed_version=extracted_version,
                status=status,
                message=msg,
                raw_output=raw_output,
                command_executed=cmd_executed,
            )
        except ValueError:
            return VersionCheckResult(
                tool_id=tool.id,
                tool_name=tool.name,
                executable_path=path_to_check,
                installed_version=extracted_version,
                status=VersionStatus.VERSION_UNKNOWN,
                message=f"Extracted version string '{extracted_version}' is not valid semantic versioning.",
                raw_output=raw_output,
                command_executed=cmd_executed,
            )

    def check_all_tools(
        self,
        registry: Any,
        detector: Optional[Any] = None,
    ) -> List[VersionCheckResult]:
        """
        Canonical tool health check pipeline:
        Iterates all tools in registry, resolves binary path via SystemDetector,
        executes version verification, parses version, and evaluates compatibility status.
        """
        if detector is None:
            from esimmate.detector import SystemDetector
            detector = SystemDetector()

        sys_info = detector.get_system_info()
        results: List[VersionCheckResult] = []

        for tool in registry.list_tools():
            path = detector.find_tool_executable(tool, sys_info.os_name)
            res = self.check_tool(tool, executable_path=path, detector=detector)
            results.append(res)

        return results

