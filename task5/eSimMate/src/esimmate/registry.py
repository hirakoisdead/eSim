"""
Tool Registry Module.
Manages discovery, dynamic loading from YAML configurations, and lookup of all external tool definitions.
No tools are hardcoded in source code; all tools are registered via configuration.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from esimmate.tool import (
    AbstractTool,
    ConfigurableTool,
    ToolMetadata,
    VersionBounds,
    VersionCheckConfig,
)


class ToolRegistry:
    """Dynamic registry holding external tool definitions loaded from configuration."""

    def __init__(self) -> None:
        self._tools: Dict[str, AbstractTool] = {}

    def register_tool(self, tool: AbstractTool) -> None:
        """Register a tool instance in the registry."""
        self._tools[tool.id] = tool

    def get_tool(self, tool_id: str) -> Optional[AbstractTool]:
        """Fetch a registered tool by its ID."""
        return self._tools.get(tool_id)

    def list_tools(self) -> List[AbstractTool]:
        """Return a list of all registered tools."""
        return list(self._tools.values())

    def list_mandatory_tools(self) -> List[AbstractTool]:
        """Return a list of tools marked as mandatory."""
        return [tool for tool in self._tools.values() if tool.is_mandatory]

    def list_tools_by_category(self, category: str) -> List[AbstractTool]:
        """Return tools belonging to a specific category."""
        return [tool for tool in self._tools.values() if tool.metadata.category == category]

    def clear(self) -> None:
        """Remove all registered tools from the registry."""
        self._tools.clear()

    @staticmethod
    def parse_tool_definition(tool_id: str, info: Dict[str, Any]) -> ConfigurableTool:
        """Parse a tool definition dictionary from configuration into a ConfigurableTool instance."""
        comp_info = info.get("compatibility", {})
        compat_bounds = VersionBounds(
            min_version=str(comp_info.get("min_version", "0.0.0")),
            recommended_version=str(comp_info.get("recommended_version", "0.0.0")),
            max_version=str(comp_info.get("max_version", "999.0.0")),
        )

        ver_info = info.get("version_check", {})
        version_config = VersionCheckConfig(
            command=ver_info.get("command", ["--version"]),
            regex=ver_info.get("regex", r"(\d+\.\d+\.\d+)"),
            timeout_seconds=int(ver_info.get("timeout_seconds", 5)),
            mode=str(ver_info.get("mode", "standard")),
        )

        metadata = ToolMetadata(
            id=tool_id,
            name=info.get("name", tool_id),
            category=info.get("category", "eda"),
            mandatory=bool(info.get("mandatory", False)),
            purpose=info.get("purpose", ""),
            executables=info.get("executables", {}),
            compatibility=compat_bounds,
            version_check=version_config,
            supported_platforms=info.get("supported_platforms", ["Linux", "Windows"]),
            package_managers=info.get("package_managers", {}),
            default_search_paths=info.get("default_search_paths", {}),
            environment_variables=info.get("environment_variables", []),
            optional_config=info.get("optional_config", {}),
            executable_candidates=info.get("executable_candidates", {}),
        )
        return ConfigurableTool(metadata)

    def load_from_config(self, tools_dict: Dict[str, Any]) -> int:
        """Populate registry from a tools dictionary containing a 'tools' key."""
        tools_data = tools_dict.get("tools", {})
        count = 0
        for tool_id, info in tools_data.items():
            if isinstance(info, dict):
                tool_instance = self.parse_tool_definition(tool_id, info)
                self.register_tool(tool_instance)
                count += 1
        return count

    def load_from_file(self, file_path: Union[str, Path]) -> int:
        """Load tool definitions from a YAML configuration file."""
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Tools configuration file not found: '{file_path}'")

        with open(path_obj, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return self.load_from_config(data)

    def load_from_directory(self, dir_path: Union[str, Path]) -> int:
        """Scan a directory for *.yaml files and dynamically register all tool definitions."""
        path_obj = Path(dir_path)
        if not path_obj.exists() or not path_obj.is_dir():
            return 0

        total_loaded = 0
        for yaml_file in sorted(path_obj.glob("*.yaml")):
            try:
                total_loaded += self.load_from_file(yaml_file)
            except Exception:
                pass
        return total_loaded
