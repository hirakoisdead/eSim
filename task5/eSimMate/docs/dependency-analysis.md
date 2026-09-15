# eSim 2.5 Dependency & External Tool Analysis

**Project:** eSimMate — Automated Tool & Dependency Manager for eSim  
**Context:** FOSSEE eSim Semester Long Internship (Autumn 2026) — Screening Task 5  
**Target Release:** eSim 2.5 Baseline  
**Document Version:** 1.0.0  
**Status:** Technical Baseline Document  

---

## 1. Overview & Operating System Targets

eSim is an open-source Electronic Design Automation (EDA) suite developed by FOSSEE at IIT Bombay. Rather than being a monolithic application, eSim serves as an integrated front-end orchestrating multiple standalone open-source software tools, simulation engines, hardware description language (HDL) simulators, and scientific Python packages.

### Official eSim 2.5 Supported Operating Systems:
1. **Windows:** Windows 10 (64-bit) & Windows 11 (64-bit)
2. **Ubuntu Linux:** Ubuntu 20.04 LTS, Ubuntu 22.04 LTS, and Ubuntu 24.04 LTS (x86_64)

This document provides a comprehensive dependency breakdown based on official FOSSEE eSim documentation, installer scripts (`install-eSim.sh`), and repository structures.

---

## 2. Core Tool & Dependency Breakdown

### 2.1 KiCad
* **Tool Name:** KiCad EDA
* **Purpose:** Schematic capture, component symbol library management, footprint assignment, and PCB layout design. eSim interfaces directly with KiCad schematics (`.sch` / `.kicad_sch`) to extract netlists for simulation.
* **Mandatory / Optional:** **Mandatory** (Core component for design entry).
* **Required Version:** 
  * *Target for eSim 2.5:* `>= 6.0.0, <= 8.0.x` (Recommended: KiCad 7.0.x or 8.0.x).
* **Executable Name:**
  * **Linux:** `kicad` or `kicad-cli`
  * **Windows:** `kicad.exe` or `kicad-cli.exe`
* **How Installation is Performed:**
  * *Ubuntu:* Installed via standard `apt` repository or official KiCad PPA (`ppa:kicad/kicad-7.0-releases` or `ppa:kicad/kicad-8.0-releases`). Command: `sudo apt-get install -y kicad`
  * *Windows:* Installed via official KiCad executable setup wizard or Windows Package Manager (`winget install KiCad.KiCad`). Default location: `C:\Program Files\KiCad\7.0\bin\` or `8.0\bin\`.
* **How Installed Version is Detected:**
  * Command: `kicad --version` or `kicad-cli --version`
  * Version Extraction Regex: `KiCad\s+v?(\d+\.\d+\.\d+)`
* **Package Manager Availability:**
  * Linux: `apt` (`kicad`), `flatpak` (`org.kicad.KiCad`)
  * Windows: `winget` (`KiCad.KiCad`), `choco` (`kicad`)
* **PATH Requirements:** Executable directory (`/usr/bin` on Linux, `C:\Program Files\KiCad\8.0\bin\` on Windows) must be present in system `$PATH`.
* **Configuration Requirements:** Environment variables `KICAD_SYMBOL_DIR` and `KICAD7_SYMBOL_DIR` / `KICAD8_SYMBOL_DIR` must point to eSim custom library models.

---

### 2.2 Ngspice
* **Tool Name:** Ngspice Circuit Simulator
* **Purpose:** Primary simulation engine for analog, digital, and mixed-signal circuits. Processes SPICE netlists generated from KiCad schematics and calculates transient, AC, DC, and noise analysis outputs.
* **Mandatory / Optional:** **Mandatory** (Core simulation engine).
* **Required Version:**
  * *Target for eSim 2.5:* `>= 34` (Recommended: Ngspice v38 to v42+).
* **Executable Name:**
  * **Linux:** `ngspice`
  * **Windows:** `ngspice.exe`
* **How Installation is Performed:**
  * *Ubuntu:* Installed via `apt`. Command: `sudo apt-get install -y ngspice`
  * *Windows:* Extracted into eSim installation directory (e.g., `C:\FOSSEE\eSim\Ngspice\bin\`) or installed via `winget install Ngspice.Ngspice`.
* **How Installed Version is Detected:**
  * Command: `ngspice --version` or `ngspice -v`
  * Version Extraction Regex: `ngspice(?:-|\s+code\s+v?|\s+v?)(\d+)`
* **Package Manager Availability:**
  * Linux: `apt` (`ngspice`)
  * Windows: Dynamic package availability check via `winget search`. Fallback strategy: official SourceForge release archive (`ngspice-46_64.7z` from `https://sourceforge.net/projects/ngspice/files/ng-spice-rework/46/ngspice-46_64.7z/download`). Extract using system `7z`, `7za`, or `tar` extractor.
* **PATH Requirements:** Executable directory (`/usr/bin` or `C:\FOSSEE\eSim\Ngspice\bin`) must be in system `$PATH`.
* **Configuration Requirements:** Requires standard code model libraries (`.cm` files like `spice2poly.cm`, `table.cm`) registered in `spinit` configuration file.

---

### 2.3 GHDL
* **Tool Name:** GHDL (Open Source Analyzer & Simulator for VHDL)
* **Purpose:** VHDL hardware description language simulator used in eSim for digital and mixed-signal co-simulation (NGHDL feature). Converts VHDL code into digital models that interface with Ngspice XSPICE engine.
* **Mandatory / Optional:** **Conditional / Core for Digital/Mixed-Signal** (Mandatory if VHDL simulation or NGHDL is used; optional for purely analog circuits).
* **Required Version:**
  * *Target for eSim 2.5:* `>= 2.0.0` (Supports mcode, llvm, or gcc backends).
* **Executable Name:**
  * **Linux:** `ghdl`
  * **Windows:** `ghdl.exe`
* **How Installation is Performed:**
  * *Ubuntu:* Installed via `apt`. Command: `sudo apt-get install -y ghdl` (or compiled/downloaded from GHDL GitHub release tarballs).
  * *Windows:* Extracted from GHDL zip binary releases (mcode backend) into system directory (e.g., `C:\ghdl-mcode\bin\`) or Chocolatey.
* **How Installed Version is Detected:**
  * Command: `ghdl --version`
  * Version Extraction Regex: `GHDL\s+(\d+\.\d+\.\d+)`
* **Package Manager Availability:**
  * Linux: `apt` (`ghdl`)
  * Windows: `choco` (`ghdl`)
* **PATH Requirements:** Executable directory must be added to `$PATH`.
* **Configuration Requirements:** Requires GCC / GNAT runtime libraries on Windows if using GCC backend; mcode backend is preferred for zero-dependency execution.

---

### 2.4 OpenModelica (`omc`)
* **Tool Name:** OpenModelica Compiler (`omc`)
* **Purpose:** Object-oriented equation-based modeling environment for complex physical systems. Integrated with eSim for control systems, electromechanical modeling, and continuous-time sub-system simulations.
* **Mandatory / Optional:** **Optional** (Required only for OpenModelica system simulation features in eSim).
* **Required Version:**
  * *Target for eSim 2.5:* `>= 1.19.0` (Recommended: OpenModelica 1.19.x - 1.22.x).
* **Executable Name:**
  * **Linux:** `omc`
  * **Windows:** `omc.exe`
* **How Installation is Performed:**
  * *Ubuntu:* Installed via OpenModelica official PPA repository (`http://build.openmodelica.org/apt`). Command: `sudo apt-get install -y openmodelica`
  * *Windows:* Installed via official OpenModelica Windows Installer (`OpenModelica-v1.21.0-64bit.exe`) or `winget`.
* **How Installed Version is Detected:**
  * Command: `omc --version`
  * Version Extraction Regex: `OpenModelica\s+v?(\d+\.\d+\.\d+)`
* **Package Manager Availability:**
  * Linux: `apt` (`openmodelica` via PPA)
  * Windows: `winget` (`OpenModelica.OpenModelica`)
* **PATH Requirements:** `omc` binary directory (`/usr/bin` or `C:\Program Files\OpenModelica1.21.0-64bit\bin\`) in `$PATH`.
* **Configuration Requirements:** Environment variable `OPENMODELICAHOME` pointing to OpenModelica installation directory.

---

### 2.5 Verilator
* **Tool Name:** Verilator
* **Purpose:** High-performance Verilog/SystemVerilog simulator that compiles Verilog code into C++/SystemC models. Used in eSim for digital Verilog co-simulation and Makerchip integration.
* **Mandatory / Optional:** **Optional** (Required for Verilog digital co-simulation).
* **Required Version:**
  * *Target for eSim 2.5:* `>= 4.200`
* **Executable Name:**
  * **Linux:** `verilator`
  * **Windows:** `verilator.exe` (or invoked via MSYS2 / WSL environment)
* **How Installation is Performed:**
  * *Ubuntu:* Installed via `apt`. Command: `sudo apt-get install -y verilator`
  * *Windows:* Installed via MSYS2 (`pacman -S mingw-w64-x86_64-verilator`) or bundled binary tooling.
* **How Installed Version is Detected:**
  * Command: `verilator --version`
  * Version Extraction Regex: `Verilator\s+(\d+\.\d+)`
* **Package Manager Availability:**
  * Linux: `apt` (`verilator`)
  * Windows: `msys2` (`verilator`)
* **PATH Requirements:** Executable directory in `$PATH`.
* **Configuration Requirements:** C++ compiler (`gcc` / `g++` or `clang`) must be available to build Verilated C++ models.

---

### 2.6 FreeCAD
* **Tool Name:** FreeCAD 3D Parametric Modeler
* **Purpose:** 3D CAD visualization and mechanical design integration. Allows viewing 3D footprints of components and exporting complete 3D PCB models designed in KiCad.
* **Mandatory / Optional:** **Optional** (Recommended for 3D PCB visualization).
* **Required Version:**
  * *Target for eSim 2.5:* `>= 0.19.0`
* **Executable Name:**
  * **Linux:** `freecad`
  * **Windows:** `freecad.exe` or `FreeCAD.exe`
* **How Installation is Performed:**
  * *Ubuntu:* Installed via `apt`. Command: `sudo apt-get install -y freecad`
  * *Windows:* Installed via official setup wizard or `winget install FreeCAD.FreeCAD`.
* **How Installed Version is Detected:**
  * Command: `freecad --version` or `FreeCAD --version`
  * Version Extraction Regex: `FreeCAD\s+v?(\d+\.\d+)`
* **Package Manager Availability:**
  * Linux: `apt` (`freecad`), `flatpak` (`org.freecadweb.FreeCAD`)
  * Windows: `winget` (`FreeCAD.FreeCAD`), `choco` (`freecad`)
* **PATH Requirements:** Executable directory in `$PATH`.
* **Configuration Requirements:** None mandatory for eSim core.

---

### 2.7 SkyWater SKY130 PDK
* **Tool Name:** SkyWater 130nm Open-Source Process Design Kit (SKY130 PDK)
* **Purpose:** Open-source semiconductor manufacturing PDK for designing integrated circuits (ICs) within eSim. Includes SPICE models, cell libraries, and layout rules for 130nm technology.
* **Mandatory / Optional:** **Optional** (Required only for Sky130 PDK chip design workflows).
* **Required Version:**
  * *Target for eSim 2.5:* Latest compatible release (v0.0.1+ / open_pdks format).
* **Executable / File Marker Name:** `sky130.tech` or `libs.tech/ngspice/sky130.lib.spice`
* **How Installation is Performed:**
  * Downloaded/cloned via git into eSim library directory: `~/.esim/pdk/sky130` or `C:\FOSSEE\eSim\library\pdk\sky130`.
* **How Installed Version is Detected:**
  * File existence check for `sky130.tech` and inspection of PDK manifest file (`VERSION` or `COMMIT`).
* **Package Manager Availability:** Not standard in system package managers; managed via custom eSim script download.
* **PATH / Environment Requirements:** `SKY130_PDK_DIR` environment variable pointing to PDK directory.

---

### 2.8 Python Runtime & Scientific Libraries
* **Tool Name:** Python 3 Environment & Dependencies
* **Purpose:** Underlying runtime platform executing eSim GUI, netlist converter, model generator, and plotters.
* **Mandatory / Optional:** **Mandatory** (Baseline runtime).
* **Required Version:** Python `>= 3.10` (eSim 2.5 targets Python 3.10 / 3.11).
* **Core Required Python Packages:**
  * `PyQt5` or `PyQt6`: Graphical User Interface framework.
  * `matplotlib`: Interactive simulation curve plotting.
  * `numpy`: Array and numerical netlist parsing operations.
  * `scipy`: Advanced mathematical routines for simulation data.
  * `sympy`: Symbolic math for transfer function conversion.
  * `requests`: Cloud interface with Makerchip web service.
* **How Installed Version is Detected:**
  * Command: `python3 --version` or `python --version`
  * Package verification: `python3 -m pip list` or Python `import` checks.

---

## 3. Dependency Comparison Matrix: Windows vs. Ubuntu

| Dependency | Purpose | Status | Target Version | Linux Binary | Windows Binary | Linux Package (`apt`) | Windows Package (`winget`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **KiCad** | Schematic Capture & PCB | **Mandatory** | `>= 6.0, <= 8.0` | `kicad` | `kicad.exe` | `kicad` | `KiCad.KiCad` |
| **Ngspice** | Circuit Simulator | **Mandatory** | `>= 34` | `ngspice` | `ngspice.exe` | `ngspice` | `Ngspice.Ngspice` |
| **GHDL** | VHDL Simulator | **Conditional** | `>= 2.0.0` | `ghdl` | `ghdl.exe` | `ghdl` | `choco: ghdl` |
| **OpenModelica** | System Modeling | **Optional** | `>= 1.19.0` | `omc` | `omc.exe` | `openmodelica` | `OpenModelica.OpenModelica` |
| **Verilator** | Verilog Simulator | **Optional** | `>= 4.200` | `verilator` | `verilator.exe` | `verilator` | `msys2: verilator` |
| **FreeCAD** | 3D Model Viewer | **Optional** | `>= 0.19` | `freecad` | `FreeCAD.exe` | `freecad` | `FreeCAD.FreeCAD` |
| **Python 3** | Application Runtime | **Mandatory** | `>= 3.10` | `python3` | `python.exe` | `python3` | `Python.Python.3.11` |

---

## 4. Key Dependency Management Challenges in eSim 2.5

1. **Path Inconsistency on Windows:** Windows installers for KiCad, Ngspice, and OpenModelica often place binaries in versioned folder paths (e.g., `C:\Program Files\KiCad\8.0\bin` vs `C:\Program Files\KiCad\7.0\bin` or `C:\Program Files\OpenModelica1.21.0-64bit\bin`). eSimMate must search multiple versioned candidate directories dynamically.
2. **Permission Restrictions during Setup:** Package managers (`apt` on Linux, `winget` elevated UAC on Windows) require root/administrative rights. eSimMate must verify privileges before attempting automated installation.
3. **Regex Variety in Output:** Different builds of Ngspice return version strings formatted differently (e.g., `ngspice-38`, `ngspice code v34`, `ngspice 40`). Regex detection must accommodate these variants.

---

## 5. Integration into eSimMate (`configs/tools.yaml`)

All findings from this dependency analysis are codified into eSimMate's declarative YAML configuration (`configs/tools.yaml`). This ensures eSimMate can check, detect, and install external tools without hardcoded executable logic in Python source files.

---
*End of Dependency Analysis Document.*
