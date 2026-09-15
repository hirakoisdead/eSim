"""Regression guards for embedding the NGHDL GUI as a Makerchip tab.

The NGHDL window (``nghdl/src/ngspice_ghdl.py``) doubles as a standalone app
*and* as a tab inside eSim's Makerchip dock. When embedded it must never:

  * call ``sys.exit()`` -- that would terminate all of eSim; and
  * leave eSim's working directory changed.

It must also construct as a plain ``QWidget`` so it can live in a tab, and a
broken / missing NGHDL install must degrade to a placeholder rather than break
the Makerchip dock.

If one of these tests fails, fix the embedding in ``ngspice_ghdl.py`` /
``makerchip.py`` rather than relaxing the guard.
"""
import ast
import os

import pytest

_HERE = os.path.dirname(__file__)
_NGHDL_SRC = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "nghdl", "src"))
_NGHDL_GUI = os.path.join(_NGHDL_SRC, "ngspice_ghdl.py")
_MAKERCHIP = os.path.join(_HERE, "..", "makerchip.py")
_FLOWNAV = os.path.join(_HERE, "..", "FlowNavigator.py")
_APPLICATION = os.path.join(_HERE, "..", "..", "frontEnd", "Application.py")


def _read(path):
    with open(path) as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# AST guard: no unguarded sys.exit() in the NGHDL GUI
# ---------------------------------------------------------------------------

def _sys_exit_calls(tree):
    """Yield (Call node, ancestors) for every ``sys.exit(...)`` in the tree."""
    def walk(node, ancestors):
        for child in ast.iter_child_nodes(node):
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "exit"
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "sys"):
                yield child, ancestors
            yield from walk(child, ancestors + [node])
    yield from walk(tree, [])


def _guarded_by_embedded(ancestors):
    """True if some ancestor ``if`` statement tests ``self.embedded``."""
    for node in ancestors:
        if isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Attribute) and sub.attr == "embedded":
                    return True
    return False


def _in_main(ancestors):
    """True if the call lives inside the standalone ``main()`` entry point."""
    return any(isinstance(n, ast.FunctionDef) and n.name == "main"
               for n in ancestors)


def test_no_unguarded_sys_exit_in_nghdl_gui():
    tree = ast.parse(_read(_NGHDL_GUI))
    offenders = [call.lineno for call, ancestors in _sys_exit_calls(tree)
                 if not (_in_main(ancestors) or _guarded_by_embedded(ancestors))]
    assert not offenders, (
        "Unguarded sys.exit() at line(s) %s in ngspice_ghdl.py -- in embedded "
        "mode this terminates all of eSim. Guard with `if not self.embedded`."
        % offenders)


# ---------------------------------------------------------------------------
# Source-level wiring guards (cheap, no heavy imports)
# ---------------------------------------------------------------------------

def test_flownav_wires_nghdl_stage():
    # NGHDL is now the VHDL stage of the Flow Navigator (it replaced the flat
    # Makerchip/NgVeri/NGHDL tab strip), built in embedded mode.
    src = _read(_FLOWNAV)
    assert "NGHDL" in src, "FlowNavigator must expose an NGHDL (VHDL) stage"
    assert "Mainwindow(embedded=True)" in src, \
        "the NGHDL stage must construct the GUI in embedded mode"
    assert "_placeholder" in src, \
        "a guarded placeholder fallback must exist"


def test_flownav_stage_build_is_guarded():
    """The lazy stage build must be wrapped in try/except so a broken NGHDL
    install (or any stage) cannot take down the Makerchip dock."""
    tree = ast.parse(_read(_FLOWNAV))
    build = next((n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_ensure_stage"),
                 None)
    assert build is not None, "FlowNavigator must define _ensure_stage"
    assert any(isinstance(n, ast.Try) for n in ast.walk(build)), \
        "_ensure_stage must guard stage construction with try/except"


def test_nghdl_launcher_opens_vhdl_path():
    """The NGHDL toolbar/menu action is kept, but no longer launches a flying
    NGHDL window: it opens Model Creation straight on the VHDL / NGHDL path
    (``makerchip(select_vhdl=True)``). Guard that contract so the shortcut can
    never silently regress to the default Verilog stage."""
    app_src = _read(_APPLICATION)
    assert "def open_nghdl" in app_src, \
        "open_nghdl launcher must exist as the VHDL shortcut"
    tree = ast.parse(app_src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "open_nghdl"),
              None)
    assert fn is not None, "open_nghdl must be defined"
    # It must reach makerchip(...) with select_vhdl=True.
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "makerchip"]
    assert any(any(kw.arg == "select_vhdl"
                   and isinstance(kw.value, ast.Constant) and kw.value.value is True
                   for kw in c.keywords)
               for c in calls), \
        "open_nghdl must call makerchip(select_vhdl=True) so NGHDL lands on VHDL"


# ---------------------------------------------------------------------------
# Functional guard (needs a configured NGHDL install + headless Qt)
# ---------------------------------------------------------------------------

# Captured at import time: when this module is imported outside any test
# (subset runs like `pytest src/maker`), HOME is still the real home, so this
# points at the real installed config. In full-suite runs pytest imports the
# module while another test's isolated_user_home is active; the config then
# appears absent and the test below skips -- exactly as before.
_REAL_NGHDL_CFG = os.path.join(os.path.expanduser("~"),
                               ".nghdl", "config.ini")


def _have_config():
    return (os.path.isfile(_REAL_NGHDL_CFG)
            and os.path.getsize(_REAL_NGHDL_CFG) > 0)


@pytest.mark.skipif(not _have_config(),
                    reason="NGHDL not installed (~/.nghdl/config.ini absent)")
def test_embedded_mainwindow_is_safe_widget(qapp):
    import shutil
    import sys
    if _NGHDL_SRC not in sys.path:
        sys.path.append(_NGHDL_SRC)
    from PyQt6 import QtWidgets
    import Appconfig
    from ngspice_ghdl import Mainwindow

    # The repo-wide isolated_user_home fixture points HOME at an empty temp
    # dir, hiding the ~/.nghdl the skipif above verified. Mirror the real
    # config into the isolated home so Mainwindow can construct against the
    # actual install without the test ever writing to the real home.
    cfgdir = os.path.join(os.path.expanduser("~"), ".nghdl")
    os.makedirs(cfgdir, exist_ok=True)
    shutil.copy(_REAL_NGHDL_CFG, os.path.join(cfgdir, "config.ini"))

    cwd_before = os.getcwd()
    win = Mainwindow(embedded=True)
    try:
        assert isinstance(win, QtWidgets.QWidget)
        # Embedded mode behaves like `nghdl -e` (creates the KiCad symbol).
        assert Appconfig.Appconfig.esimFlag == 1
        # The Exit button must not be placed in the embedded layout.
        assert win.exitbtn.parent() is None
        # Constructing the tab must not move eSim's working directory.
        assert os.getcwd() == cwd_before
    finally:
        win.deleteLater()
