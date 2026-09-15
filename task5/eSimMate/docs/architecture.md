# eSimMate System Architecture Specification

**Project:** eSimMate — Automated Tool & Dependency Manager for eSim  
**Context:** FOSSEE eSim Semester Long Internship (Autumn 2026) — Screening Task 5  
**Document Version:** 1.0.0  
**Status:** Architecture Baseline Document  

---

## 1. Executive Summary & Design Goals

**eSimMate** is designed as a modular, extensible, platform-agnostic, and safe tool and dependency manager for eSim. It decouples core business logic (system detection, version comparison, package manager execution) from the presentation layer (CLI or future PyQt6 GUI).

### Core Architectural Principles:
1. **SOLID Design Principles:** High cohesion, low coupling, single-responsibility modules, and interface segregation.
2. **Open-Closed Principle (Extensibility):** Core managers operate on abstract specifications. New tools can be added via simple YAML files without modifying core Python code. New package managers can be added via the Adapter design pattern.
3. **Safety & Zero-Surprise Privilege Handling:** Installation execution is explicit, dry-run testable, and audited. Privileged commands are never executed implicitly or via dangerous shell string execution.
4. **Platform Isolation:** OS-specific logic (Windows registry/PATH vs. Linux `/usr/bin`) is abstracted behind platform adapters.

---

## 2. High-Level Subsystem Architecture

eSimMate comprises ten core subsystems:

```mermaid
graph TD
    CLI["1. CLI Layer (Typer / Rich)"]
    LOG["10. Logging Manager"]
    CFG["9. Configuration Manager"]
    REG["2. Tool Registry"]
    TOOL["3. Tool Abstraction"]
    SYS["5. System Detector"]
    VER["4. Version Manager"]
    COMP["8. Compatibility Checker"]
    INST["7. Installation Manager"]
    PKG["6. Package Manager Abstraction (Adapters)"]

    CLI --> CFG
    CLI --> LOG
    CLI --> REG
    REG --> TOOL
    TOOL --> SYS
    TOOL --> VER
    TOOL --> COMP
    CLI --> INST
    INST --> PKG
    INST --> LOG
    PKG --> SYS

    subgraph Package Manager Adapters
        PKG --> APT["AptAdapter (Ubuntu)"]
        PKG --> WINGET["WingetAdapter (Windows)"]
        PKG --> CHOCO["ChocolateyAdapter (Windows)"]
        PKG --> SCRIPT["ManualScriptAdapter"]
        PKG --> MANUAL["ManualDownloadAdapter (Official Archive Fallback)"]
    end
```

---

## 3. Subsystem Breakdown & Component Specification

### 3.1 Subsystem 1: CLI Layer (`esimmate.cli`)
* **Responsibility:** User interaction, command parsing, terminal visual layout, confirmation prompts, and rendering tabular diagnostic reports.
* **Technology:** Built with `Typer` and `Rich`.
* **Key Commands:**
  * `esimmate check`: Triggers environment detection and compatibility status scan across all registered tools.
  * `esimmate list`: Displays configured tools, executable targets, and supported version bounds.
  * `esimmate install <tool>`: Initiates installation for specified tool (or `--all`). Supports `--dry-run` and `--yes`.
  * `esimmate config`: Views or updates user preferences and custom binary search paths.
  * `esimmate log`: Inspects persistent operation audit logs.

### 3.2 Subsystem 2: Tool Registry (`esimmate.core.registry`)
* **Responsibility:** Dynamically discovers, loads, and manages `Tool` objects from YAML definitions (`configs/tools.yaml` and optional custom user tool drop-ins at `~/.esimmate/tools.d/*.yaml`).
* **Extensibility:** To support a new external tool, users simply add a YAML file into `tools.d/`. The `ToolRegistry` parses the file and instantiates a standard `Tool` instance automatically—**zero core Python code modification required.**

### 3.3 Subsystem 3: Tool Abstraction (`esimmate.core.tool`)
* **Responsibility:** Encapsulates the domain model of an external EDA tool.
* **Attributes:** Tool ID, display name, category, mandatory flag, platform binary names, version check command arguments, extraction regex, package manager mapping, and default search paths.
* **Methods:** `detect_binary_path()`, `fetch_installed_version()`, `evaluate_compatibility()`.

### 3.4 Subsystem 4: Version Manager (`esimmate.core.version`)
* **Responsibility:** Handles version string extraction from subprocess `stdout`/`stderr` using tool-specific regular expressions and parses them into comparable `packaging.version.Version` objects.
* **Resilience:** Handles version format discrepancies (e.g., `ngspice-38`, `KiCad v7.0.10`, `GHDL 3.0.0`).

### 3.5 Subsystem 5: System Detector (`esimmate.core.system`)
* **Responsibility:** Queries host environment metadata:
  * Operating System (`Windows`, `Linux`)
  * OS Distribution & Version (`Ubuntu 22.04`, `Ubuntu 24.04`, `Windows 11`)
  * CPU Architecture (`x86_64`, `AMD64`, `arm64`)
  * System `$PATH` environment variable scanner
  * Standard installation directory inspector

### 3.6 Subsystem 6: Package Manager Abstraction & Adapters (`esimmate.managers.package_manager`)
* **Responsibility:** Abstract Base Class (`AbstractPackageManager`) isolating package installation commands behind a unified API (`install_package()`, `is_available()`, `build_command()`).
* **Design Pattern:** **Adapter Pattern**. Future package managers (e.g., `FlatpakAdapter`, `BrewAdapter`) can be added by implementing the base interface.
* **Adapters Included:**
  * `AptAdapter`: Handles `sudo apt-get install -y <pkg>` on Ubuntu/Debian.
  * `WingetAdapter`: Handles `winget install --id <id> --accept-source-agreements` on Windows.
  * `ChocolateyAdapter`: Handles `choco install <pkg> -y` on Windows.
  * `ManualInstallerAdapter`: Executes standalone installer scripts or binary installers safely.

### 3.7 Subsystem 7: Installation Manager (`esimmate.managers.installer`)
* **Responsibility:** Coordinates end-to-end tool installation workflows.
* **Features:**
  * Validates system detection and resolves appropriate package manager adapter.
  * Generates dry-run execution plans (`PlanResult`).
  * Prompts for privilege elevation confirmation (`sudo` or Windows Admin).
  * Executes commands using safe `subprocess.run(cmd_list)` calls with log redirection.
  * Performs post-installation verification to ensure the tool is functional and on `$PATH`.

### 3.8 Subsystem 8: Compatibility Checker (`esimmate.core.compatibility`)
* **Responsibility:** Compares an installed tool version against the compatibility bounds (`min_version`, `recommended_version`, `max_version`) in `tools.yaml`.
* **Statuses:**
  * `MISSING`: Binary not found.
  * `OUTDATED`: Installed version < `min_version`.
  * `COMPATIBLE`: `min_version` <= Installed version <= `max_version`.
  * `UNTESTED_NEWER`: Installed version > `max_version`.
  * `DETECTION_ERROR`: Execution timeout or regex mismatch.

### 3.9 Subsystem 9: Configuration Manager (`esimmate.config`)
* **Responsibility:** Manages application settings (`config.yaml`) and tool definition database (`tools.yaml`).
* **Precedence Resolution:** CLI flags > Environment Variables (`ESIMMATE_*`) > User Config (`~/.config/esimmate/config.yaml`) > Defaults.

### 3.10 Subsystem 10: Logging Manager (`esimmate.utils.logging`)
* **Responsibility:** Centralized logging routing:
  * **Console Handler:** Filtered Rich terminal output for real-time user feedback.
  * **File Handler:** Rotating structured persistent logs at `~/.esimmate/logs/esimmate.log`.

---

## 4. Class Design & Adapter Architecture

```mermaid
classDiagram
    class Tool {
        +string id
        +string name
        +bool mandatory
        +Dict executables
        +VersionCheckConfig version_config
        +CompatibilityBounds compatibility
        +detect_path(SystemDetector) Path
        +get_installed_version(SystemDetector) Version
    }

    class ToolRegistry {
        -Dict~string, Tool~ tools
        +load_from_yaml(Path)
        +get_tool(string) Tool
        +list_all_tools() List~Tool~
    }

    class AbstractPackageManager {
        <<abstract>>
        +name: string
        +is_available()* bool
        +build_install_command(string package_id)* List~string~
        +requires_elevation()* bool
        +install(string package_id, bool dry_run)* InstallResult
    }

    class AptAdapter {
        +is_available() bool
        +build_install_command(string package_id) List~string~
        +requires_elevation() bool
        +install(string package_id, bool dry_run) InstallResult
    }

    class WingetAdapter {
        +is_available() bool
        +build_install_command(string package_id) List~string~
        +requires_elevation() bool
        +install(string package_id, bool dry_run) InstallResult
    }

    class ChocolateyAdapter {
        +is_available() bool
        +build_install_command(string package_id) List~string~
        +requires_elevation() bool
        +install(string package_id, bool dry_run) InstallResult
    }

    class ManualInstallerAdapter {
        +is_available() bool
        +build_install_command(string package_id) List~string~
        +requires_elevation() bool
        +install(string package_id, bool dry_run) InstallResult
    }

    AbstractPackageManager <|-- AptAdapter
    AbstractPackageManager <|-- WingetAdapter
    AbstractPackageManager <|-- ChocolateyAdapter
    AbstractPackageManager <|-- ManualInstallerAdapter
    ToolRegistry "1" *-- "many" Tool
```

---

## 5. End-to-End Data Flow Diagrams

### 5.1 Workflow 1: Detect Tool
User runs `esimmate check` to discover binary locations across host OS.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI Layer (`check`)
    participant Reg as ToolRegistry
    participant Tool as Tool Instance
    participant Sys as SystemDetector

    User->>CLI: esimmate check
    CLI->>Reg: get_all_tools()
    Reg-->>CLI: List[Tool]
    loop For each registered tool
        CLI->>Tool: detect_path(Sys)
        Tool->>Sys: scan_path_and_standard_dirs(executable_name)
        Sys-->>Tool: Path or None
        Tool-->>CLI: PathResult(found=True/False, path=...)
    end
    CLI->>User: Render Tool Path Summary Matrix
```

---

### 5.2 Workflow 2: Check Version
User queries or checks tool versions and evaluates against compatibility bounds.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI Layer
    participant Tool as Tool Instance
    participant Ver as VersionManager
    participant Comp as CompatibilityChecker

    User->>CLI: esimmate check
    CLI->>Tool: get_installed_version()
    Tool->>Ver: execute_version_cmd(command, timeout)
    Ver-->>Tool: raw_output (stdout/stderr)
    Tool->>Ver: parse_version(raw_output, regex)
    Ver-->>Tool: Version object ("7.0.10")
    Tool->>Comp: check_compatibility(installed_version, bounds)
    Comp-->>Tool: Status ("COMPATIBLE")
    Tool-->>CLI: DiagnosticResult(version="7.0.10", status="COMPATIBLE")
    CLI->>User: Display Status Badge [INSTALLED - COMPATIBLE]
```

---

### 5.3 Workflow 3: Install Tool
User requests installation of missing tool (`esimmate install ngspice`).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI Layer
    participant Inst as InstallationManager
    participant Sys as SystemDetector
    participant Adapter as AbstractPackageManager (e.g. AptAdapter)
    participant Log as LoggingManager

    User->>CLI: esimmate install ngspice [--dry-run]
    CLI->>Inst: prepare_installation("ngspice", dry_run)
    Inst->>Sys: get_os_and_package_managers()
    Sys-->>Inst: OS="Ubuntu 22.04", PM="apt"
    Inst->>Adapter: build_install_command("ngspice")
    Adapter-->>Inst: Command ["sudo", "apt-get", "install", "-y", "ngspice"]
    
    alt Dry-Run Mode
        Inst-->>CLI: PlanResult(commands, elevation_required=True)
        CLI->>User: Show Dry-Run Preview (No execution)
    else Normal Execution Mode
        Inst-->>CLI: RequestConfirmation(prompt="Run elevated install command?")
        User->>CLI: Confirm (Yes)
        CLI->>Inst: execute_installation()
        Inst->>Adapter: install("ngspice")
        Adapter->>Log: Log command execution
        Adapter-->>Inst: InstallResult(success=True, returncode=0)
        Inst-->>CLI: Success Response
        CLI->>User: Display Installation Succeeded!
    end
```

---

### 5.4 Workflow 4: Verify Installation
Post-installation automated health verification step executed by InstallationManager.

```mermaid
sequenceDiagram
    autonumber
    participant Inst as InstallationManager
    participant Sys as SystemDetector
    participant Tool as Tool Instance
    participant Ver as VersionManager

    Inst->>Sys: refresh_environment_path()
    Inst->>Tool: detect_path(Sys)
    alt Path Found
        Inst->>Tool: fetch_installed_version()
        Tool->>Ver: parse_version()
        Ver-->>Inst: Installed Version ("38")
        Inst-->>Inst: Compare with expected version
        Inst-->>Inst: Verification PASSED
    else Path Not Found
        Inst-->>Inst: Verification FAILED (Path missing)
    end
```

---

### 5.5 Workflow 5: View Logs
User inspects execution history via `esimmate log view`.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI Layer (`log view`)
    participant Log as LoggingManager

    User->>CLI: esimmate log view --lines 50
    CLI->>Log: fetch_recent_logs(lines=50)
    Log->>Log: Read ~/.esimmate/logs/esimmate.log
    Log-->>CLI: Formatted Log Entries
    CLI->>User: Render Rich Log View Table
```

---

## 6. Summary of Architectural Guarantees

1. **Zero Code Change for New Tools:** Adding a new tool is as simple as creating `~/.esimmate/tools.d/my_tool.yaml`.
2. **Adapter Flexibility:** Adding support for macOS `brew`, Linux `snap` or `flatpak` requires only introducing a new class inheriting from `AbstractPackageManager`.
3. **Safety First:** Commands are strictly parameterized lists executed through `subprocess.run()`. `shell=True` is forbidden.
4. **Independent Modules:** Every subsystem can be independently unit tested using mocks.

---
*End of Architecture Specification Document.*
