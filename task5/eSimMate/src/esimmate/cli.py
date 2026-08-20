"""
CLI Layer Module.
Provides Typer command-line application interface for eSimMate.
Commands: list, check, install, doctor, log/logs, config.
"""

import json
import os
from pathlib import Path
from typing import List, Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from esimmate import __version__
from esimmate.config import ConfigManager
from esimmate.detector import SystemDetector
from esimmate.installer import InstallationManager, InstallStatus
from esimmate.registry import ToolRegistry
from esimmate.version_manager import VersionManager, VersionStatus

app = typer.Typer(
    name="esimmate",
    help="eSimMate — Automated Tool & Dependency Manager for eSim",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"eSimMate version: [bold green]{__version__}[/bold green]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show eSimMate version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """eSimMate: Automated Tool & Dependency Manager for eSim."""
    pass


@app.command("list")
def list_command(
    output_json: bool = typer.Option(False, "--json", help="Output registered tools in JSON format."),
) -> None:
    """List registered tools, installed status, and installed version."""
    detector = SystemDetector()
    version_mgr = VersionManager()
    config_mgr = ConfigManager()

    sys_info = detector.get_system_info()
    tools_dict = config_mgr.load_tools_config()
    registry = ToolRegistry()
    registry.load_from_config(tools_dict)

    if output_json:
        json_data = []
        for tool in registry.list_tools():
            executable_name = tool.get_executable(sys_info.os_name)
            path = detector.find_binary_on_path(executable_name) if executable_name else None
            if not path:
                candidate_paths = tool.metadata.default_search_paths.get(sys_info.os_name.lower(), [])
                path = detector.check_candidate_paths(candidate_paths)

            result = version_mgr.check_tool(tool, executable_path=path)
            json_data.append({
                "id": tool.id,
                "name": tool.name,
                "mandatory": tool.is_mandatory,
                "installed_version": result.installed_version,
                "min_version": tool.metadata.compatibility.min_version,
                "recommended_version": tool.metadata.compatibility.recommended_version,
                "max_version": tool.metadata.compatibility.max_version,
                "status": result.status.value,
            })
        print(json.dumps(json_data, indent=2))
        return

    table = Table(title="Registered eSim External Tools", show_header=True, header_style="bold magenta")
    table.add_column("Tool ID", style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Mandatory", style="yellow")
    table.add_column("Installed Version", style="bold")
    table.add_column("Target Version Range", style="dim")
    table.add_column("Status", style="bold")

    for tool in registry.list_tools():
        executable_name = tool.get_executable(sys_info.os_name)
        path = detector.find_binary_on_path(executable_name) if executable_name else None
        if not path:
            candidate_paths = tool.metadata.default_search_paths.get(sys_info.os_name.lower(), [])
            path = detector.check_candidate_paths(candidate_paths)

        result = version_mgr.check_tool(tool, executable_path=path)

        ver_display = result.installed_version or "N/A"
        bounds = tool.metadata.compatibility
        range_display = f"[{bounds.min_version} .. {bounds.max_version}]"

        status_colors = {
            VersionStatus.COMPATIBLE: "bold green",
            VersionStatus.NOT_INSTALLED: "bold red",
            VersionStatus.OUTDATED: "bold yellow",
            VersionStatus.NEWER_VERSION: "bold blue",
            VersionStatus.VERSION_UNKNOWN: "bold magenta",
            VersionStatus.ERROR: "bold red",
        }
        color = status_colors.get(result.status, "white")
        mandatory_str = "Yes" if tool.is_mandatory else "No"

        table.add_row(
            tool.id,
            tool.name,
            mandatory_str,
            ver_display,
            range_display,
            f"[{color}]{result.status.value}[/{color}]",
        )

    console.print(table)


@app.command("check")
def check_command(
    output_json: bool = typer.Option(False, "--json", help="Output compatibility status in JSON format."),
) -> None:
    """Check all registered tools and display installed version, required version, and compatibility status."""
    detector = SystemDetector()
    version_mgr = VersionManager()
    config_mgr = ConfigManager()

    sys_info = detector.get_system_info()
    tools_dict = config_mgr.load_tools_config()
    registry = ToolRegistry()
    registry.load_from_config(tools_dict)

    results = version_mgr.check_all_tools(registry, detector)

    if output_json:
        json_data = {
            "system_info": {
                "os_name": sys_info.os_name,
                "os_version": sys_info.os_version,
                "architecture": sys_info.architecture_normalized,
                "python_version": sys_info.python_version,
                "package_managers": sys_info.available_package_managers,
            },
            "tools": []
        }
        for result in results:
            tool = registry.get_tool(result.tool_id)
            if not tool:
                continue
            json_data["tools"].append({
                "id": tool.id,
                "name": tool.name,
                "category": tool.metadata.category,
                "mandatory": tool.is_mandatory,
                "executable_path": str(result.executable_path) if result.executable_path else None,
                "installed_version": result.installed_version,
                "min_version": tool.metadata.compatibility.min_version,
                "recommended_version": tool.metadata.compatibility.recommended_version,
                "max_version": tool.metadata.compatibility.max_version,
                "status": result.status.value,
            })
        print(json.dumps(json_data, indent=2))
        return

    console.print("[bold blue]Running eSimMate tool detection & compatibility check...[/bold blue]\n")
    console.print(
        f"[bold green]Host Environment:[/bold green] {sys_info.os_name} ({sys_info.os_version}) | "
        f"Arch: {sys_info.architecture_normalized} ({'64-bit' if sys_info.is_64bit else '32-bit'}) | "
        f"Python: {sys_info.python_version}"
    )
    pms = ", ".join(sys_info.available_package_managers) if sys_info.available_package_managers else "None"
    console.print(f"[bold green]Package Managers Detected:[/bold green] {pms}\n")

    table = Table(title="eSim Tool Compatibility Check Matrix", show_header=True, header_style="bold magenta")
    table.add_column("Tool ID", style="bold cyan")
    table.add_column("Tool Name", style="bold")
    table.add_column("Category", style="magenta")
    table.add_column("Installed Version", style="bold")
    table.add_column("Required Version Range", style="dim")
    table.add_column("Compatibility Status", style="bold")

    for result in results:
        tool = registry.get_tool(result.tool_id)
        ver_display = result.installed_version or "N/A"
        bounds = tool.metadata.compatibility if tool else None
        range_display = f"Min: {bounds.min_version} | Rec: {bounds.recommended_version} | Max: {bounds.max_version}" if bounds else ""

        status_colors = {
            VersionStatus.COMPATIBLE: "bold green",
            VersionStatus.NOT_INSTALLED: "bold red",
            VersionStatus.OUTDATED: "bold yellow",
            VersionStatus.NEWER_VERSION: "bold blue",
            VersionStatus.VERSION_UNKNOWN: "bold magenta",
            VersionStatus.ERROR: "bold red",
        }
        style = status_colors.get(result.status, "white")

        table.add_row(
            result.tool_id,
            result.tool_name,
            tool.metadata.category if tool else "",
            ver_display,
            range_display,
            f"[{style}]{result.status.value}[/{style}]",
        )

    console.print(table)



@app.command("update")
def update_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview update actions without executing."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Automatic yes to confirmation prompts."),
) -> None:
    """Update package manager database indexes and refresh tool definitions (Partial Implementation)."""
    console.print("[bold yellow]Note: Package manager update is PARTIALLY IMPLEMENTED (delegates outdated tool updates to package manager adapters).[/bold yellow]\n")
    install_command(tool_name=None, all_tools=True, dry_run=dry_run, yes=yes)


def cli_confirm_callback(cmd_list: List[str], requires_elevation: bool) -> bool:
    cmd_str = " ".join(cmd_list)
    console.print(f"[bold yellow]Installation Command:[/bold yellow] [cyan]{cmd_str}[/cyan]")
    if requires_elevation:
        console.print("[bold red]WARNING: This operation requires elevated (sudo/root) privileges![/bold red]")
    return typer.confirm("Do you want to proceed with installation?", default=False)


@app.command("install")
def install_command(
    tool_name: Optional[str] = typer.Argument(None, help="ID of the tool to install (or omit if using --all)."),
    all_tools: bool = typer.Option(False, "--all", "-a", help="Install all missing or outdated tools."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview installation commands without executing."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Automatic yes to prompts; assume yes to confirmation."),
) -> None:
    """Install a selected tool or all missing/outdated tools."""
    config_mgr = ConfigManager()
    tools_dict = config_mgr.load_tools_config()

    registry = ToolRegistry()
    registry.load_from_config(tools_dict)
    detector = SystemDetector()
    version_mgr = VersionManager()
    installer = InstallationManager()

    if not tool_name and not all_tools:
        console.print("[bold red]Error:[/bold red] Please specify a tool ID (e.g. `esimmate install kicad`) or use --all.")
        raise typer.Exit(code=1)

    sys_info = detector.get_system_info()

    if all_tools:
        eligible_tools: List[tuple] = []
        skipped_tools: List[tuple] = []

        results = version_mgr.check_all_tools(registry, detector)
        for tool, res in zip(registry.list_tools(), results):
            if res.status in (VersionStatus.NOT_INSTALLED, VersionStatus.OUTDATED):
                eligible_tools.append((tool, res))
            else:
                skipped_tools.append((tool, res))

        console.print("[bold cyan]Tools requiring action:[/bold cyan]")
        if eligible_tools:
            for tool, res in eligible_tools:
                color = "red" if res.status == VersionStatus.NOT_INSTALLED else "yellow"
                console.print(f" • [bold]{tool.name}[/bold] ({tool.id}): [{color}]{res.status.value}[/{color}]")
        else:
            console.print(" • [italic dim]None[/italic dim]")

        console.print("\n[bold dim]Skipped tools:[/bold dim]")
        if skipped_tools:
            for tool, res in skipped_tools:
                color = "green" if res.status == VersionStatus.COMPATIBLE else "yellow"
                ver_str = f" ({res.installed_version})" if res.installed_version else ""
                console.print(f" • {tool.name} ({tool.id}): [{color}]{res.status.value}{ver_str}[/{color}]")
        else:
            console.print(" • [italic dim]None[/italic dim]")

        if not eligible_tools:
            console.print("\n[bold green]No tools require installation or update.[/bold green]")
            return

        target_tools_with_res = eligible_tools
    else:
        tool = registry.get_tool(tool_name)
        if not tool:
            console.print(f"[bold red]Error:[/bold red] Tool '{tool_name}' is not registered in tools configuration database.")
            raise typer.Exit(code=1)

        res = version_mgr.check_tool(tool, detector=detector)
        if res.status == VersionStatus.COMPATIBLE and not yes and not dry_run:
            console.print(f"[bold green]Tool '{tool.name}' is already COMPATIBLE (version {res.installed_version}).[/bold green] Use --yes to reinstall.")
            return

        target_tools_with_res = [(tool, res)]

    for tool, v_res in target_tools_with_res:
        console.print(f"\n[bold blue]Processing installation for tool:[/bold blue] [cyan]{tool.name}[/cyan] ({tool.id}) [Status: {v_res.status.value}]")
        res = installer.install_tool(
            tool=tool,
            dry_run=dry_run,
            auto_confirm=yes,
            confirm_callback=cli_confirm_callback,
        )

        status_colors = {
            InstallStatus.SUCCESS: "bold green",
            InstallStatus.DRY_RUN_PREVIEW: "bold yellow",
            InstallStatus.CANCELLED_BY_USER: "bold yellow",
            InstallStatus.UNSUPPORTED_OS: "bold red",
            InstallStatus.PACKAGE_MANAGER_UNAVAILABLE: "bold red",
            InstallStatus.PACKAGE_NOT_FOUND: "bold red",
            InstallStatus.PERMISSION_DENIED: "bold red",
            InstallStatus.COMMAND_NOT_FOUND: "bold red",
            InstallStatus.NETWORK_FAILURE: "bold red",
            InstallStatus.INSTALLATION_FAILED: "bold red",
        }
        color = status_colors.get(res.status, "white")
        console.print(f"[{color}]Result ({res.status.value}): {res.message}[/{color}]")


@app.command("doctor")
def doctor_command(
    output_json: bool = typer.Option(False, "--json", help="Output doctor diagnostics in JSON format."),
) -> None:
    """Perform a complete system diagnosis: OS, architecture, Python, package managers, tools, and versions."""
    detector = SystemDetector()
    version_mgr = VersionManager()
    config_mgr = ConfigManager()
    sys_info = detector.get_system_info()

    tools_dict = config_mgr.load_tools_config()
    registry = ToolRegistry()
    registry.load_from_config(tools_dict)

    results = version_mgr.check_all_tools(registry, detector)

    if output_json:
        json_data = {
            "system_info": {
                "os_name": sys_info.os_name,
                "os_version": sys_info.os_version,
                "architecture": sys_info.architecture_normalized,
                "python_version": sys_info.python_version,
                "package_managers": sys_info.available_package_managers,
            },
            "tools": [],
            "environment_variables": {
                var: os.environ.get(var) for var in ["KICAD_SYMBOL_DIR", "OPENMODELICAHOME", "SKY130_PDK_DIR"]
            }
        }
        for result in results:
            tool = registry.get_tool(result.tool_id)
            if not tool:
                continue
            json_data["tools"].append({
                "id": tool.id,
                "name": tool.name,
                "mandatory": tool.is_mandatory,
                "executable_path": str(result.executable_path) if result.executable_path else None,
                "installed_version": result.installed_version,
                "status": result.status.value,
            })
        print(json.dumps(json_data, indent=2))
        return

    console.print("[bold blue]Running eSimMate System Doctor Diagnostic...[/bold blue]\n")

    # 1. System Platform Overview
    console.print("[bold cyan]1. Host System Environment[/bold cyan]")
    console.print(f"   • Operating System : [bold]{sys_info.os_name}[/bold] ({sys_info.os_version})")
    console.print(f"   • Architecture     : [bold]{sys_info.architecture_normalized}[/bold] ({'64-bit' if sys_info.is_64bit else '32-bit'})")
    console.print(f"   • Python Runtime   : [bold]{sys_info.python_version}[/bold]")
    console.print()

    # 2. Package Managers Check
    console.print("[bold cyan]2. Package Manager Availability[/bold cyan]")
    if sys_info.available_package_managers:
        for pm in sys_info.available_package_managers:
            console.print(f"   • [green][OK][/green] Package Manager [bold]{pm}[/bold] is available on $PATH")
    else:
        console.print("   • [red][MISSING][/red] No supported package manager found on system PATH")
    console.print()

    # 3. External Tools Health Diagnostic
    console.print("[bold cyan]3. External Tools & Dependencies Diagnostic[/bold cyan]")
    mandatory_missing = 0
    optional_missing = 0
    outdated_count = 0
    compatible_count = 0

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Tool", style="bold cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Detected Binary Path", style="dim")
    table.add_column("Installed Version", style="bold")
    table.add_column("Status", style="bold")

    for result in results:
        tool = registry.get_tool(result.tool_id)
        is_mandatory = tool.is_mandatory if tool else False

        if result.status == VersionStatus.COMPATIBLE:
            compatible_count += 1
            status_style = "bold green"
            status_symbol = "COMPATIBLE"
        elif result.status == VersionStatus.NOT_INSTALLED:
            if is_mandatory:
                mandatory_missing += 1
            else:
                optional_missing += 1
            status_style = "bold red" if is_mandatory else "bold yellow"
            status_symbol = "NOT_INSTALLED"
        elif result.status == VersionStatus.OUTDATED:
            outdated_count += 1
            status_style = "bold yellow"
            status_symbol = "OUTDATED"
        else:
            status_style = "bold red"
            status_symbol = result.status.value

        path_str = str(result.executable_path) if result.executable_path else "Not Found"
        ver_str = result.installed_version or "N/A"
        type_str = "Mandatory" if is_mandatory else "Optional"

        table.add_row(
            result.tool_name,
            type_str,
            path_str,
            ver_str,
            f"[{status_style}]{status_symbol}[/{status_style}]",
        )

    console.print(table)
    console.print()

    # 4. Environment Variables Check
    console.print("[bold cyan]4. Environment Variables Verification[/bold cyan]")
    env_vars_to_check = ["KICAD_SYMBOL_DIR", "OPENMODELICAHOME", "SKY130_PDK_DIR"]
    for env_var in env_vars_to_check:
        val = os.environ.get(env_var)
        if val:
            console.print(f"   • [green][OK][/green] [bold]{env_var}[/bold] = {val}")
        else:
            console.print(f"   • [yellow][NOT SET][/yellow] [bold]{env_var}[/bold] is not set (optional depending on workflow)")
    console.print()

    # 5. Diagnostic Summary & Recommendations
    console.print("[bold cyan]5. Diagnostic Summary & Actionable Recommendations[/bold cyan]")
    if mandatory_missing == 0 and outdated_count == 0:
        console.print("   [bold green]No mandatory tool issues detected.[/bold green]\n")
    else:
        if mandatory_missing > 0:
            console.print(f"   [bold red]X {mandatory_missing} mandatory tool(s) missing.[/bold red] Run `esimmate install --all` to install missing tools.")
        if outdated_count > 0:
            console.print(f"   [bold yellow]! {outdated_count} tool(s) outdated.[/bold yellow] Run `esimmate install <tool_id>` to upgrade.")
        console.print()



def display_logs(lines: int = 20) -> None:
    """Helper method to load and format recent eSimMate log file entries."""
    candidates = [
        Path("logs/esimmate.log"),
        Path.home() / ".esimmate" / "logs" / "esimmate.log",
    ]
    target_file = None
    for path in candidates:
        if path.exists() and path.is_file():
            target_file = path
            break

    if target_file is None:
        console.print("[yellow]No recent eSimMate audit log file found.[/yellow]")
        return

    console.print(f"[bold blue]Displaying last {lines} lines from {target_file}:[/bold blue]\n")
    try:
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            recent = all_lines[-lines:] if lines > 0 else all_lines
            for line in recent:
                console.print(f"[dim]{line.rstrip()}[/dim]")
    except Exception as exc:
        console.print(f"[bold red]Error reading log file:[/bold red] {exc}")


@app.command("log")
def log_command(
    lines: int = typer.Option(20, "--lines", "-n", help="Number of recent log lines to display."),
) -> None:
    """Display recent eSimMate operation audit logs."""
    display_logs(lines)


@app.command("logs")
def logs_alias_command(
    lines: int = typer.Option(20, "--lines", "-n", help="Number of recent log lines to display."),
) -> None:
    """Display recent eSimMate operation audit logs (alias for `esimmate log`)."""
    display_logs(lines)


@app.command("config")
def config_command() -> None:
    """View or manage eSimMate configuration settings."""
    config_mgr = ConfigManager()
    user_cfg = config_mgr.load_user_config()
    console.print("[bold blue]Current eSimMate Configuration:[/bold blue]")
    console.print(user_cfg)


if __name__ == "__main__":
    app()
