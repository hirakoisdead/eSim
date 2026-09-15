"""
Tests for Compatibility Checker module.
"""

from esimmate.compatibility import CompatibilityChecker, CompatibilityStatus
from esimmate.tool import VersionBounds


def test_compatibility_checker():
    checker = CompatibilityChecker()
    bounds = VersionBounds(min_version="6.0.0", recommended_version="7.0.0", max_version="8.0.0")

    assert checker.evaluate(None, bounds) == CompatibilityStatus.NOT_INSTALLED
    assert checker.evaluate("5.9.0", bounds) == CompatibilityStatus.OUTDATED
    assert checker.evaluate("7.0.10", bounds) == CompatibilityStatus.COMPATIBLE
    assert checker.evaluate("9.0.0", bounds) == CompatibilityStatus.NEWER_VERSION
    assert checker.evaluate("invalid_version", bounds) == CompatibilityStatus.VERSION_UNKNOWN
