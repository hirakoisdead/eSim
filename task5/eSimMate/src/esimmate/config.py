"""
Configuration Manager Module.
Loads user settings and tool definitions from YAML files.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import yaml


class ConfigManager:
    """Manages application and tool configuration loading and access."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        tools_path: Optional[Path] = None,
    ) -> None:
        root_dir = Path(__file__).resolve().parent.parent.parent
        default_config = root_dir / "configs" / "config.yaml"
        default_tools = root_dir / "configs" / "tools.yaml"

        if config_path:
            self.config_path = Path(config_path)
        elif default_config.exists():
            self.config_path = default_config
        elif Path("configs/config.yaml").exists():
            self.config_path = Path("configs/config.yaml").resolve()
        else:
            self.config_path = default_config

        if tools_path:
            self.tools_path = Path(tools_path)
        elif default_tools.exists():
            self.tools_path = default_tools
        elif Path("configs/tools.yaml").exists():
            self.tools_path = Path("configs/tools.yaml").resolve()
        else:
            self.tools_path = default_tools

        self._user_config: Dict[str, Any] = {}
        self._tools_config: Dict[str, Any] = {}

    def load_user_config(self) -> Dict[str, Any]:
        """Load user configuration from YAML file."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._user_config = yaml.safe_load(f) or {}
        return self._user_config

    def load_tools_config(self) -> Dict[str, Any]:
        """Load tools definition database from YAML file."""
        if self.tools_path.exists():
            with open(self.tools_path, "r", encoding="utf-8") as f:
                self._tools_config = yaml.safe_load(f) or {}
        return self._tools_config

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Fetch a specific user configuration setting by dot-notation key."""
        keys = key.split(".")
        current = self._user_config
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current
