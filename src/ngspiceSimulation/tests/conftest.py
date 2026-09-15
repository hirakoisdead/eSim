"""Shared pytest fixtures for the ngspiceSimulation test suite.

Puts eSim's ``src`` tree on sys.path and forces a headless Qt platform so the
tests run in CI without a display. A session-scoped QApplication fixture is
provided for the few tests that construct Qt-backed objects (DataExtraction
pulls in Appconfig, which builds QWidgets).
"""
import os
import sys

import pytest

# Headless Qt for CI and for any test that touches a QWidget-backed object.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Make the eSim 'src' tree importable (configuration, ngspiceSimulation, …)
# regardless of the directory pytest is invoked from.
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication; reused if one already exists."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _isolate_matplotlib_rcparams():
    """Restore the process-global ``matplotlib.rcParams`` after every test.

    ``plotWindow._setup_matplotlib_style`` mutates ``plt.rcParams`` (font sizes
    keyed off the DPI, plus theme colors) on every construction. rcParams is a
    single process-wide dict, so without this each plotWindow build bleeds its
    font/theme state into later tests and modules. Snapshot before, restore
    after — a no-op for the
    tests that don't build a plotWindow.
    """
    import matplotlib
    snapshot = dict(matplotlib.rcParams)
    yield
    matplotlib.rcParams.update(snapshot)
