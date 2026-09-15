"""
Tests for Configuration Manager module.
"""

from pathlib import Path
from esimmate.config import ConfigManager


def test_config_manager_load():
    config_mgr = ConfigManager()
    user_cfg = config_mgr.load_user_config()
    tools_cfg = config_mgr.load_tools_config()

    assert isinstance(user_cfg, dict)
    assert isinstance(tools_cfg, dict)
    assert "tools" in tools_cfg


def test_config_manager_get_setting():
    config_mgr = ConfigManager()
    config_mgr.load_user_config()
    setting = config_mgr.get_setting("logging.level", default="INFO")
    assert setting == "INFO"
