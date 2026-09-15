"""Regression guard: forbid parentless / PyQt5-style message popups in eSim.

This walks the whole ``src`` tree and fails if any module (other than the
``configuration.Dialogs`` helper itself) does one of the following:

1. constructs a bare ``QMessageBox()`` with no parent, or *any*
   ``QErrorMessage(...)`` at all -- these become top-level windows that stack
   *behind* the main window on X11/Wayland/Windows (the "app looks frozen"
   bug). QErrorMessage is a top-level window even when given a parent and has
   no place outside the ``Dialogs`` helper, so every construction is flagged
   regardless of args (a bare-args-only rule let ``QErrorMessage(self)`` slip
   back in across the legacy shell/subcircuit/modelEditor tools);
2. calls a raw ``QtWidgets.QMessageBox.<information|warning|critical|question|
   about>(...)`` static method -- popups must go through ``configuration``
   ``.Dialogs`` so a parent is always resolved;
3. uses an unscoped ``QMessageBox.<Yes|No|Ok|...>`` enum -- these were removed
   in PyQt6 and raise ``AttributeError`` at runtime; use the scoped
   ``QMessageBox.StandardButton.<...>`` / ``QMessageBox.Icon.<...>`` forms;
4. calls the PyQt5 ``.exec_()`` method -- removed in PyQt6, it raises
   ``AttributeError`` on the reachable path that triggers it; use ``.exec()``.

If this test fails, fix the offending call site to use ``configuration``
``.Dialogs`` (see that module's docstring) rather than relaxing the test.
"""
import ast
import os

_SRC_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))

# The one module allowed to construct QMessageBox / QErrorMessage directly.
_ALLOWED = os.path.join(_SRC_ROOT, "configuration", "Dialogs.py")

_STATIC_METHODS = {"information", "warning", "critical", "question", "about"}

# Button / icon constants that were unscoped in PyQt5 and removed in PyQt6.
_UNSCOPED_ENUMS = {
    "Ok", "Open", "Save", "Cancel", "Close", "Discard", "Apply", "Reset",
    "RestoreDefaults", "Help", "SaveAll", "Yes", "YesToAll", "No", "NoToAll",
    "Abort", "Retry", "Ignore", "NoButton",
    "NoIcon", "Information", "Warning", "Critical", "Question",
}


def _is(node, name):
    """True if ``node`` names ``name`` either bare or as ``X.name``."""
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    return False


def _iter_source_files():
    for dirpath, _dirs, files in os.walk(_SRC_ROOT):
        if os.sep + "tests" in dirpath:
            continue
        for fn in files:
            if fn.endswith(".py"):
                path = os.path.join(dirpath, fn)
                if path != _ALLOWED:
                    yield path


def _violations_in(path):
    with open(path, encoding="utf-8") as fh:
        try:
            tree = ast.parse(fh.read(), path)
        except SyntaxError:
            return []
    out = []
    rel = os.path.relpath(path, _SRC_ROOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if _is(fn, "QErrorMessage"):
                out.append(f"{rel}:{node.lineno}: {ast.unparse(fn)}(...) "
                           f"is a stray top-level window -> use "
                           f"configuration.Dialogs (critical/make_error_message)")
            elif (_is(fn, "QMessageBox")
                    and not node.args and not node.keywords):
                out.append(f"{rel}:{node.lineno}: bare {ast.unparse(fn)}() "
                           f"with no parent -> use configuration.Dialogs")
            if (isinstance(fn, ast.Attribute) and fn.attr in _STATIC_METHODS
                    and _is(fn.value, "QMessageBox")):
                out.append(f"{rel}:{node.lineno}: raw QMessageBox.{fn.attr}() "
                           f"-> use configuration.Dialogs.{fn.attr}()")
            if isinstance(fn, ast.Attribute) and fn.attr == "exec_":
                out.append(f"{rel}:{node.lineno}: PyQt5 .exec_() "
                           f"(removed in PyQt6) -> use .exec()")
        if (isinstance(node, ast.Attribute) and node.attr in _UNSCOPED_ENUMS
                and _is(node.value, "QMessageBox")):
            out.append(f"{rel}:{node.lineno}: unscoped QMessageBox.{node.attr} "
                       f"(removed in PyQt6) -> use the scoped enum")
    return out


def test_no_parentless_or_pyqt5_message_boxes():
    violations = []
    for path in _iter_source_files():
        violations.extend(_violations_in(path))
    assert not violations, (
        "Parentless / PyQt5-style message popups found "
        "(route them through configuration.Dialogs):\n  "
        + "\n  ".join(sorted(violations)))
