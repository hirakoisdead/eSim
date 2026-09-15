"""
Comprehensive unit tests for the Typer CLI layer module.
Tests list, check, install, update, doctor, log, logs, and config subcommands.
"""

import json
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from esimmate.cli import app

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "eSimMate version:" in result.stdout


def test_cli_list():
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Registered eSim External Tools" in result.stdout
    assert "kicad" in result.stdout
    assert "ngspice" in result.stdout


def test_cli_list_json():
    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert any(t["id"] == "kicad" for t in data)


def test_cli_check():
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "Running eSimMate tool detection" in result.stdout
    assert "eSim Tool Compatibility Check Matrix" in result.stdout


def test_cli_check_json():
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "system_info" in data
    assert "tools" in data
    assert len(data["tools"]) >= 7


def test_cli_update_dry_run():
    result = runner.invoke(app, ["update", "--dry-run"])
    assert result.exit_code == 0
    assert "PARTIALLY IMPLEMENTED" in result.stdout


def test_cli_install_dry_run():
    result = runner.invoke(app, ["install", "ngspice", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY_RUN_PREVIEW" in result.stdout
    assert "ngspice" in result.stdout.lower() or "Ngspice" in result.stdout


def test_cli_install_all_dry_run():
    result = runner.invoke(app, ["install", "--all", "--dry-run"])
    assert result.exit_code == 0
    assert "Tools requiring action:" in result.stdout
    assert "Skipped tools:" in result.stdout


@patch("subprocess.run")
def test_cli_install_yes(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Installed successfully"
    mock_run.return_value.stderr = ""

    result = runner.invoke(app, ["install", "ngspice", "--yes"])
    assert result.exit_code == 0
    assert "Processing installation for tool" in result.stdout
    assert "ngspice" in result.stdout.lower() or "Ngspice" in result.stdout


def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Running eSimMate System Doctor Diagnostic" in result.stdout
    assert "Host System Environment" in result.stdout
    assert "Package Manager Availability" in result.stdout
    assert "External Tools & Dependencies Diagnostic" in result.stdout


def test_cli_doctor_json():
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "system_info" in data
    assert "tools" in data
    assert "environment_variables" in data
    assert len(data["tools"]) >= 7


def test_check_and_doctor_consistency():
    check_res = runner.invoke(app, ["check", "--json"])
    doctor_res = runner.invoke(app, ["doctor", "--json"])

    assert check_res.exit_code == 0
    assert doctor_res.exit_code == 0

    check_data = json.loads(check_res.stdout)
    doctor_data = json.loads(doctor_res.stdout)

    check_ng = next(t for t in check_data["tools"] if t["id"] == "ngspice")
    doctor_ng = next(t for t in doctor_data["tools"] if t["id"] == "ngspice")

    assert check_ng["status"] == doctor_ng["status"]
    assert check_ng["installed_version"] == doctor_ng["installed_version"]
    assert check_ng["executable_path"] == doctor_ng["executable_path"]


def test_doctor_summary_does_not_count_version_unknown_as_missing():
    from esimmate.version_manager import VersionCheckResult, VersionStatus
    with patch("esimmate.version_manager.VersionManager.check_all_tools") as mock_check_all:
        mock_check_all.return_value = [
            VersionCheckResult(
                tool_id="ngspice",
                tool_name="Ngspice Circuit Simulator",
                executable_path=Path("dummy/ngspice.exe"),
                installed_version="unknown_ver",
                status=VersionStatus.VERSION_UNKNOWN,
                message="Executable responded but version pattern could not be parsed.",
            ),
            VersionCheckResult(
                tool_id="kicad",
                tool_name="KiCad EDA",
                executable_path=None,
                installed_version=None,
                status=VersionStatus.NOT_INSTALLED,
                message="Executable not found.",
            ),
        ]
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        # Should count exactly 1 mandatory tool missing (KiCad), not 2
        assert "1 mandatory tool(s) missing." in result.stdout


def test_cli_log_command(tmp_path):
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0


def test_cli_logs_alias_command(tmp_path):
    result = runner.invoke(app, ["logs", "-n", "10"])
    assert result.exit_code == 0


def test_cli_config_command():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Current eSimMate Configuration" in result.stdout

