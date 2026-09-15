"""Shared pytest fixtures for the maker test suite.

Puts eSim's ``src`` tree on sys.path and forces a headless Qt platform so the
tests run in CI without a display. A session-scoped QApplication fixture is
provided for tests that construct Qt widgets (RemoveItemsDialog).
"""
import os
import sys

import pytest

# Headless Qt for CI and for any test that touches a QWidget-backed object.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Make the eSim 'src' tree importable (maker, configuration, …) regardless of
# the directory pytest is invoked from.
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication; reused if one already exists."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
