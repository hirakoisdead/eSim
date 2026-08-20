"""
Comprehensive unit tests for the Tool Registry module.
Verifies YAML tool definition loading, metadata parsing, dynamic addition of new tools
without core code modification, and registry lookup methods.
"""

from pathlib import Path
import pytest
from esimmate.registry import ToolRegistry
from esimmate.tool import ConfigurableTool, PlaceholderTool


def test_registry_load_from_tools_yaml():
    """Verify loading default tools.yaml registers all core eSim tools with complete metadata."""
    registry = ToolRegistry()
    tools_path = Path("configs/tools.yaml")
    count = registry.load_from_file(tools_path)

    assert count >= 7
    kicad = registry.get_tool("kicad")
    assert kicad is not None
    assert kicad.name == "KiCad EDA"
    assert kicad.is_mandatory is True
    assert kicad.get_executable("Linux") == "kicad"
    assert kicad.get_executable("Windows") == "kicad.exe"
    assert kicad.metadata.compatibility.min_version == "6.0.0"
    assert "Linux" in kicad.supported_platforms
    assert "Windows" in kicad.supported_platforms
    assert kicad.get_package_name("apt") == "kicad"
    assert kicad.get_package_name("winget") == "KiCad.KiCad"
    assert kicad.metadata.version_check.command == ["kicad", "--version"]
    assert "KiCad" in kicad.metadata.version_check.regex


def test_registry_add_new_tool_via_config_without_code_modification():
    """Verify a new tool can be added via dictionary/configuration without modifying core registry code."""
    registry = ToolRegistry()
    custom_tool_config = {
        "tools": {
            "custom_sim": {
                "name": "Custom Circuit Simulator",
                "category": "simulation",
                "mandatory": False,
                "purpose": "A custom user-added simulation engine",
                "supported_platforms": ["Linux", "Windows"],
                "executables": {
                    "linux": "customsim",
                    "windows": "customsim.exe"
                },
                "version_check": {
                    "command": ["customsim", "--version"],
                    "regex": r"CustomSim\s+v(\d+\.\d+)",
                    "timeout_seconds": 3
                },
                "compatibility": {
                    "min_version": "1.0.0",
                    "recommended_version": "1.5.0",
                    "max_version": "2.0.0"
                },
                "package_managers": {
                    "apt": "custom-sim-pkg",
                    "winget": "CustomSim.CustomSim"
                },
                "optional_config": {
                    "custom_flag": True,
                    "max_threads": 4
                }
            }
        }
    }

    count = registry.load_from_config(custom_tool_config)
    assert count == 1

    custom_tool = registry.get_tool("custom_sim")
    assert custom_tool is not None
    assert isinstance(custom_tool, ConfigurableTool)
    assert custom_tool.name == "Custom Circuit Simulator"
    assert custom_tool.get_executable("Linux") == "customsim"
    assert custom_tool.get_executable("Windows") == "customsim.exe"
    assert custom_tool.metadata.compatibility.min_version == "1.0.0"
    assert custom_tool.get_package_name("apt") == "custom-sim-pkg"
    assert custom_tool.metadata.version_check.command == ["customsim", "--version"]
    assert custom_tool.metadata.optional_config.get("custom_flag") is True


def test_registry_load_from_directory(tmp_path):
    """Verify ToolRegistry scans a directory of YAML files and registers drop-in tool definitions."""
    tool_file_1 = tmp_path / "tool_a.yaml"
    tool_file_1.write_text("""
tools:
  tool_a:
    name: "Tool A"
    category: "eda"
    mandatory: true
    executables:
      linux: "toola"
""")

    tool_file_2 = tmp_path / "tool_b.yaml"
    tool_file_2.write_text("""
tools:
  tool_b:
    name: "Tool B"
    category: "eda"
    mandatory: false
    executables:
      linux: "toolb"
""")

    registry = ToolRegistry()
    loaded = registry.load_from_directory(tmp_path)
    assert loaded == 2
    assert registry.get_tool("tool_a") is not None
    assert registry.get_tool("tool_b") is not None


def test_registry_filtering_and_clear():
    """Verify mandatory filtering, category filtering, and clearing the registry."""
    registry = ToolRegistry()
    registry.load_from_file("configs/tools.yaml")

    all_tools = registry.list_tools()
    mandatory_tools = registry.list_mandatory_tools()
    sim_tools = registry.list_tools_by_category("simulation")

    assert len(all_tools) >= 7
    assert len(mandatory_tools) >= 3  # kicad, ngspice, python
    assert any(t.id == "ngspice" for t in sim_tools)

    registry.clear()
    assert len(registry.list_tools()) == 0
