# Technical Requirements Analysis: eSimMate (Tool Manager)

**Project:** eSimMate — Automated Tool & Dependency Manager for eSim  
**Screening Task:** FOSSEE eSim Semester Long Internship — Autumn 2026 (Screening Task 5: Tool Manager)  
**Primary Focus:** Requirement 1 (Tool Installation Management) & Requirement 5 (User Interface)  
**Document Version:** 1.0.0  
**Status:** Draft / Requirements Baseline  

---

## Executive Summary & Task Overview

eSim is an open-source Electronic Design Automation (EDA) tool developed by FOSSEE, IIT Bombay, for circuit design, simulation, and PCB layout. eSim operates as an integrated environment relying on multiple underlying open-source engines and packages—including KiCad, Ngspice, GHDL, OpenModelica, and Verilator. 

Because these external software components evolve independently across multiple operating systems (Linux, Windows), users frequently encounter dependency conflicts, missing executables, version mismatches, and complex manual installation steps ("dependency hell").

**eSimMate** is designed as a Python 3.10–3.12.x modular, reliable, and user-friendly CLI utility (with provision for a future PyQt6 GUI) that automates:
1. System environment and platform detection
2. Discovery and existence checking of integrated EDA tools
3. Extraction and semantic comparison of installed tool versions against eSim compatibility matrices
4. Package-manager abstracted installation and update workflows
5. Safe command execution with dry-run previews and privilege handling
6. Comprehensive audit logging and structured user configuration management

---

## Target Requirements Baseline

As defined in the screening task guidelines, the primary target implementation baseline for eSimMate focuses on:
* **Requirement 1 — Tool Installation Management:** Detecting tool presence, resolving package managers, downloading/executing installation routines safely, supporting dry-runs, and handling permissions.
* **Requirement 5 — User Interface:** A clear, expressive, and human-friendly CLI powered by **Typer** and terminal visualizers, displaying actionable tool statuses and guided installation prompts.

---

## 1. Functional Requirements

### 1.1 Tool Detection (`detect`)
* **FR-1.1.1:** The system shall scan the host OS system `PATH` to locate binaries for all registered eSim external tools.
* **FR-1.1.2:** The system shall check standard installation paths specific to each operating system (e.g., `/usr/bin`, `/usr/local/bin` on Linux; `C:\Program Files\`, `C:\Program Files (x86)\`, `%LOCALAPPDATA%` on Windows).
* **FR-1.1.3:** The system shall allow users to configure custom search directories per tool via configuration files.
* **FR-1.1.4:** The system shall report the exact binary path if found, or flag the tool status as `NOT_INSTALLED`.

### 1.2 Installed Version Detection (`version`)
* **FR-1.2.1:** For each detected binary, the system shall invoke the tool's version command (e.g., `kicad --version`, `ngspice --version`, `ghdl --version`).
* **FR-1.2.2:** The system shall execute version queries safely with execution timeouts (default: 5 seconds) to prevent hanging processes.
* **FR-1.2.3:** The system shall extract the raw version string from standard output (`stdout`) or standard error (`stderr`) using configurable Regular Expression (regex) rules.
* **FR-1.2.4:** The system shall parse version strings into Semantic Versioning representation (`major.minor.patch`).

### 1.3 Version Comparison & Compatibility Matrix (`compare`)
* **FR-1.3.1:** The system shall load an extensible tool compatibility database (`tools.yaml`) specifying:
  * Minimum required version (`min_version`)
  * Recommended/tested version (`recommended_version`)
  * Maximum known compatible version (`max_version`)
* **FR-1.3.2:** The system shall evaluate the installed version against the compatibility matrix and assign one of the following statuses:
  * `MISSING`: Tool binary is not found on system.
  * `OUTDATED`: Installed version is below `min_version`.
  * `COMPATIBLE`: Installed version satisfies `min_version <= installed <= max_version`.
  * `UNTESTED_NEWER`: Installed version is higher than `max_version` (potential compatibility warning).
  * `DETECTION_ERROR`: Binary exists but failed to respond to version command or regex parsing.

### 1.4 Tool Installation Management (`install`)
* **FR-1.4.1:** The system shall select the appropriate system package manager (`apt`, `winget`, `choco`) or installation script based on detected host OS.
* **FR-1.4.2:** The system shall construct installation commands for missing or outdated tools.
* **FR-1.4.3:** The system shall support a **Dry-Run Mode** (`--dry-run`), displaying exact commands, target directories, and privilege requirements without executing any changes.
* **FR-1.4.4:** The system shall require explicit user confirmation before executing commands requiring elevated permissions (`sudo` on Linux, UAC/Administrator on Windows).
* **FR-1.4.5:** The system shall capture command stdout/stderr during installation and display real-time or summarized progress to the user.

### 1.5 User Interface — CLI (`cli`)
* **FR-1.5.1:** The CLI shall be built using `Typer` and provide structured subcommands:
  * `esimmate check`: Run system diagnostic and display tool status summary table.
  * `esimmate list`: List all supported tools, descriptions, and compatibility ranges.
  * `esimmate install [TOOL]`: Install a specific tool or all missing tools (`--all`).
  * `esimmate config [ACTION]`: View or update user settings and custom tool paths.
  * `esimmate log [ACTION]`: View recent operation logs.
* **FR-1.5.2:** The CLI shall format tabular data using rich terminal components (colors, status badges `[INSTALLED]`, `[MISSING]`, `[OUTDATED]`).

### 1.6 Action Logging (`logging`)
* **FR-1.6.1:** The system shall record all detection runs, version comparisons, user confirmations, and installation commands into a persistent log file (`~/.esimmate/logs/esimmate.log`).
* **FR-1.6.2:** Each log entry shall contain: timestamp (ISO 8601), log level (`INFO`, `WARNING`, `ERROR`), module context, and detailed event message.

---

## 2. Non-Functional Requirements

### 2.1 Safety & Security
* **NFR-2.1.1 (No Privileged Execution Without Consent):** The system shall never execute privileged installation commands (`sudo`, elevated installer commands) silently.
* **NFR-2.1.2 (Process Safety):** The system shall NEVER use `os.system()` or `shell=True` unless strictly necessary and explicitly documented with argument escaping. All command execution must use `subprocess.run()` with list-formatted arguments.
* **NFR-2.1.3 (Non-Destructive Guarantee):** Tool installation operations must not delete, overwrite, or modify unrelated system files or user configurations.

### 2.2 Performance & Responsiveness
* **NFR-2.2.1:** Full system environment check and version detection across all supported tools shall complete in under 3.0 seconds on standard desktop hardware.
* **NFR-2.2.2:** Individual version detection subprocesses must enforce strict execution timeouts (maximum 5 seconds per tool).

### 2.3 Reliability & Error Isolation
* **NFR-2.3.1:** A failure in detecting or installing one tool must not crash the manager or prevent detection of remaining tools.
* **NFR-2.3.2:** System errors (e.g., missing package manager, network disconnection, permission denied) must result in clear, actionable human-readable messages rather than raw Python tracebacks.

### 2.4 Maintainability & Extensibility
* **NFR-2.4.1 (SOLID Principles):** Codebase must adhere to SOLID architectural principles, using abstract base classes for tool detectors, package managers, and command runners.
* **NFR-2.4.2 (Zero Hardcoded Paths):** Absolute user-specific paths (`C:\Users\username\` or `/home/user/`) must never be hardcoded into source files. All paths must be dynamically resolved or configurable via PyYAML.
* **NFR-2.4.3 (Modular File Structure):** Application code must be divided into dedicated modules (`core/`, `detectors/`, `managers/`, `cli/`, `config/`, `utils/`).

---

## 3. Expected User Workflows

```
                     +-----------------------------------+
                     |           User Invokes            |
                     |         `esimmate check`          |
                     +-----------------+-----------------+
                                       |
                                       v
                     +-----------------+-----------------+
                     |   System Detects OS, Arch, PATH   |
                     |   & Queries Tool Versions         |
                     +-----------------+-----------------+
                                       |
                                       v
                     +-----------------+-----------------+
                     |   Displays Tool Status Matrix     |
                     | (KiCad, Ngspice, GHDL, OMC, etc.) |
                     +-----------------+-----------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
     [ All Dependencies Met ]                [ Missing / Outdated Tools ]
                   |                                       |
                   v                                       v
        User Continues with eSim           User Invokes `esimmate install <tool>`
                                                           |
                                                           v
                                            +--------------+--------------+
                                            | Displays Dry-Run Summary    |
                                            | & Prompts for Confirmation  |
                                            +--------------+--------------+
                                                           |
                                             +-------------+-------------+
                                             |                           |
                                      [ Confirmed ]                 [ Cancelled ]
                                             |                           |
                                             v                           v
                              +--------------+--------------+    Operation Cancelled
                              | Executes Package Manager    |    Clean Exit
                              | & Logs Output               |
                              +--------------+--------------+
                                             |
                                             v
                              +--------------+--------------+
                              | Shows Success / Failure     |
                              +-----------------------------+
```

### Key Workflows:
1. **System Health Check (`esimmate check`):** Quick diagnostic listing installed tools, detected versions, expected ranges, and health status.
2. **Dry-Run Installation Preview (`esimmate install <tool> --dry-run`):** Shows exact package manager commands, required permissions, and package names without executing.
3. **Interactive Guided Installation (`esimmate install <tool>`):** Verifies tool status, asks for elevation approval if needed, streams progress, and logs the result.
4. **Configuration Management (`esimmate config set --tool kicad --path /custom/path`):** Allows registering non-standard binary paths.

---

## 4. External Tools Initially Supported

The initial release of eSimMate will support detection, version checking, and installation management for the core external tools required by eSim:

| Tool Name | Core Role in eSim | Primary Executable (Linux) | Primary Executable (Windows) | Default Version Check Command | eSim Compatibility Range (Target) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **KiCad** | Schematic Capture & PCB Design | `kicad` or `kicad-cli` | `kicad.exe` or `kicad-cli.exe` | `kicad --version` or `kicad-cli --version` | `>= 6.0.0, <= 8.0.x` *(eSim 2.5 uses KiCad 7/8)* |
| **Ngspice** | Analog & Mixed-Signal Simulation Engine | `ngspice` | `ngspice.exe` | `ngspice --version` | `>= 34` *(Recommended: 38+)* |
| **GHDL** | VHDL Digital Simulator | `ghdl` | `ghdl.exe` | `ghdl --version` | `>= 2.0.0` |
| **OpenModelica** | System-Level Modeling & Simulation | `omc` | `omc.exe` | `omc --version` | `>= 1.19.0` |
| **Verilator** | Verilog Simulator & Hardware Co-simulation | `verilator` | `verilator.exe` | `verilator --version` | `>= 4.200` |

*Note: Tool versions and paths will be dynamically parsed from `tools.yaml` to allow updating ranges without modifying code logic.*

---

## 5. OS & Platform Considerations

### 5.1 Operating Systems Supported
* **Ubuntu Linux:** Focus on LTS releases (20.04, 22.04, 24.04).
* **Windows:** Windows 10 & Windows 11 (64-bit).

### 5.2 Architecture Detection
* Detect system processor architecture using Python `platform.machine()` (`x86_64`, `AMD64`, `aarch64`).
* Enforce 64-bit architecture checks where required by EDA tool binaries (e.g., KiCad and Ngspice standard builds).

### 5.3 Path Handling & Environment
* Linux: Resolve binaries via `$PATH`, standard system paths (`/usr/bin`, `/usr/local/bin`), and Flatpak/Snap binaries if present.
* Windows: Resolve binaries via `%PATH%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, and `%LocalAppData%`.
* Use Python `pathlib.Path` universally to ensure cross-platform path manipulation without hardcoded backslashes or forward slashes.

---

## 6. Package-Manager Considerations

eSimMate uses a **Package Manager Abstraction Layer** to isolate platform-specific package installation commands behind a unified interface:

```
                      +-----------------------------+
                      |   AbstractPackageManager    |
                      +--------------+--------------+
                                     |
         +---------------------------+---------------------------+
         |                           |                           |
         v                           v                           v
+--------+--------+         +--------+--------+         +--------+--------+
|   AptManager    |         |  WingetManager  |         |  ChocoManager   |
| (Ubuntu/Debian) |         | (Windows 10/11) |         |    (Windows)    |
+-----------------+         +-----------------+         +-----------------+
```

### Package Manager Strategy:
1. **Linux (Ubuntu):**
   * Primary: `apt-get` / `apt` package manager.
   * Command formatting: `sudo apt-get install -y <package_name>`
   * Verification: Check if `apt-get` binary exists on PATH.
2. **Windows:**
   * Primary: `winget` (Windows Package Manager).
   * Secondary/Fallback: `choco` (Chocolatey) or direct download script runner.
   * Command formatting: `winget install --id <package_id> -e --accept-source-agreements --accept-package-agreements`
3. **Fallback Script Manager:**
   * For tools not available in standard system package repositories (or for pinned eSim helper scripts), support running registered shell/Powershell installer scripts safely.

---

## 7. Version-Management Strategy

### 7.1 Semantic Version Parsing
* Utilizes Python `packaging.version.parse` (or custom `semver` regex matcher) to transform version strings into comparable tuples (`Major.Minor.Patch`).

### 7.2 Version String Extraction Regex Patterns
Raw output from `--version` varies per tool. The system will use regular expression patterns defined in configuration:
* **KiCad:** `KiCad\s+v?(\d+\.\d+\.\d+)`
* **Ngspice:** `ngspice\s+(?:code\s+)?v?(\d+)` or `ngspice-(\d+)`
* **GHDL:** `GHDL\s+(\d+\.\d+\.\d+)`
* **OpenModelica:** `OpenModelica\s+v?(\d+\.\d+\.\d+)`
* **Verilator:** `Verilator\s+(\d+\.\d+)`

### 7.3 Compatibility Matrix Evaluation
A matrix in `tools.yaml` maps version strings into structured states:
```yaml
kicad:
  min_version: "6.0.0"
  recommended_version: "7.0.10"
  max_version: "8.0.99"
  packages:
    apt: "kicad"
    winget: "KiCad.KiCad"
```

---

## 8. Configuration Strategy

### 8.1 Configuration Storage & Schema
eSimMate will maintain two YAML configuration files located in the user's home configuration directory:
* **Linux:** `~/.config/esimmate/`
* **Windows:** `%APPDATA%\esimmate\`

#### Configuration Files:
1. `config.yaml`: User preferences, logging verbosity, default package manager override, and custom tool binary search paths.
2. `tools.yaml`: Tool definition database containing executable names, version check flags, regex rules, package manager mapping, and compatibility constraints.

### 8.2 Precedence Hierarchy
Configuration values are resolved using strict precedence (highest to lowest):
1. Command Line Flags (e.g., `--config-path`, `--log-level`)
2. Environment Variables (e.g., `ESIMMATE_LOG_LEVEL`)
3. User Configuration (`config.yaml`)
4. Pinned Application Defaults (`tools.yaml`)

---

## 9. Logging Requirements

### 9.1 Logging Targets & Levels
* **Console Log:** Clean, formatted output using Typer/Rich (controlled by `--verbose` or `--quiet`).
* **File Log:** Persistent, detailed append-only log written to `~/.esimmate/logs/esimmate.log`.

### 9.2 Log Format Structure
```text
2026-08-08 20:45:12,345 | INFO    | core.detector | Detected KiCad at /usr/bin/kicad (Version: 7.0.10)
2026-08-08 20:45:12,390 | WARNING | core.version  | Ngspice version 30 is below minimum required 34
2026-08-08 20:45:15,102 | INFO    | cli.install   | User requested dry-run installation for ngspice
```

### 9.3 Retention & Rotation
* Implement Python `logging.handlers.RotatingFileHandler` with max log file size of 5 MB and up to 3 backup log files.

---

## 10. Error-Handling Requirements

### 10.1 Custom Exception Hierarchy
```
eSimMateBaseError
 ├── SystemDetectionError
 ├── ToolNotFoundError
 ├── VersionParsingError
 ├── ConfigurationError
 ├── PackageManagerError
 │    ├── PackageNotFoundError
 │    └── ElevationDeniedError
 └── ProcessExecutionError
```

### 10.2 Graceful Error Recovery
* **Command Failure:** If a version query fails due to command timeout or non-zero exit code, log the error details silently to file and mark the tool status as `DETECTION_FAILED` without aborting the CLI.
* **Privilege Rejection:** If the user declines privilege elevation during an installation prompt, log `ElevationDeniedError` and return gracefully with exit code 2.

---

## 11. Testing Strategy

### 11.1 Test Framework & Structure
* Framework: `pytest` with `pytest-cov` for coverage tracking.
* Coverage Target: At least 80% coverage on core detection, version comparison, and configuration modules.

### 11.2 Mock-Based Command Testing
To satisfy the safety and isolation requirements:
* Unit tests **MUST NOT** execute real package manager installations (`apt install`, `winget install`) or modify system binaries.
* Subprocess execution must be mocked using `unittest.mock.patch("subprocess.run")` and custom mock fixtures (`MockPackageManager`, `MockToolDetector`).

### 11.3 CLI Command Testing
* Test CLI command invocations using Typer's `CliRunner`.

---

## 12. Security Considerations

1. **Subprocess Isolation:** Use `subprocess.run(["cmd", "arg1", "arg2"])` argument lists exclusively. Prevent shell injection vulnerabilities by avoiding concatenated strings and `shell=True`.
2. **Explicit Privilege Escalation:** Privileged commands (`sudo`) must be explicitly highlighted to the user before execution.
3. **File Permission & Paths:** Restrict configuration and log directory permissions (`0700` on Linux). Sanitize paths to avoid directory traversal.

---

## 13. Future Extensibility

1. **GUI Integration:** The core business logic (`SystemDetector`, `VersionManager`, `PackageManager`) will remain entirely independent of the CLI layer, enabling direct integration into a **PyQt6** desktop interface in subsequent phases.
2. **Custom Tool Definition Addons:** Users can drop custom `.yaml` tool definition files into `~/.esimmate/tools.d/` to add support for new EDA tools without modifying eSimMate source code.
3. **PDK & Library Management:** Structure allow extending tool management concepts to PDK (Process Design Kit) management (e.g., SkyWater SKY130 PDK download and verification).

---

## 14. Unresolved Technical Questions

Before proceeding to architecture design and scaffolding, the following technical questions must be verified:

1. **Exact eSim Pinned Tool Versions:** What are the exact minimum and recommended version bounds required for eSim 2.5 for each tool (KiCad, Ngspice, GHDL, OpenModelica, Verilator)?
2. **Windows Binary Paths:** For Windows standalone installations, do tools like Ngspice or GHDL register default Registry keys, or do they rely purely on manual `PATH` entries?
3. **Subprocess Privilege Escalation on Windows:** Should Windows installation fallback to launching an elevated PowerShell process (`Start-Process -Verb RunAs`) when `winget` requires Administrator privileges, or rely on the user running the terminal as Administrator?
4. **AppImage / Docker Tool Bundles:** Does eSimMate need to detect tools running inside Docker containers or AppImage packages, or only native system binaries?
5. **Non-Interactive Execution Flag:** Should eSimMate support a `--yes` / `-y` flag for non-interactive automated setups (e.g., CI/CD pipelines or headless installer scripts)?

---
*End of Technical Requirements Analysis Document.*
