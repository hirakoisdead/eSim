"""Regression tests for projManagement.Validation.

Covers project-input validation:
  - validateSub returns an explicit "NOSUBCKT" when a .sub file exists but
    holds no ".subckt" line (previously fell off the end returning None, which
    string-comparing callers turned into a confusing wrong-branch message).
  - validateSubcir no longer raises IndexError on a bare ".subckt" line.
"""

import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))       # .../src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from projManagement.Validation import Validation    # noqa: E402


def _tmpdir():
    return tempfile.mkdtemp(prefix="esim_sub_")


def _write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def test_validate_sub_true_and_port():
    d = _tmpdir()
    try:
        _write(os.path.join(d, "ua741.sub"),
               ".subckt ua741 6 7 3\n.ends ua741\n")
        v = Validation()
        assert v.validateSub(d, 3) == "True"
        assert v.validateSub(d, 2) == "PORT"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_validate_sub_nosubckt():
    """.sub file with no .subckt line -> explicit NOSUBCKT, never None."""
    d = _tmpdir()
    try:
        _write(os.path.join(d, "empty.sub"),
               "* just a comment\n\n* another comment\n")
        v = Validation()
        assert v.validateSub(d, 3) == "NOSUBCKT"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_validate_sub_no_file():
    d = _tmpdir()
    try:
        assert Validation().validateSub(d, 3) == "DIREC"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_validate_subcir_bare_subckt_line_no_indexerror():
    """A first content line of exactly '.subckt' must not raise IndexError."""
    d = _tmpdir()
    try:
        path = os.path.join(d, "bad.sub")
        _write(path, ".subckt\n.ends\n")
        # Should return False cleanly (malformed first line), not crash.
        assert Validation().validateSubcir(path, "bad") is False
    finally:
        shutil.rmtree(d, ignore_errors=True)
