"""
Tests for Tool abstraction module.
"""

from pathlib import Path
from esimmate.tool import PlaceholderTool, ToolMetadata, VersionBounds


def test_placeholder_tool_metadata():
    tool = PlaceholderTool(tool_id="test_kicad", name="Test KiCad", mandatory=True)
    assert tool.id == "test_kicad"
    assert tool.name == "Test KiCad"
    assert tool.is_mandatory is True


def test_placeholder_tool_mock_detection():
    mock_path = Path("/usr/bin/kicad")
    tool = PlaceholderTool(
        tool_id="kicad",
        name="KiCad",
        mock_path=mock_path,
        mock_version="7.0.10",
    )
    assert tool.detect_path() == mock_path
    assert tool.get_installed_version() == "7.0.10"
