from pathlib import Path

import pytest

from configuration.Sky130Prepare import (
    BROKEN_INCLUDE,
    FIXED_INCLUDE,
    INCLUDED_RELATIVE,
    LIBRARY_RELATIVE,
    MODEL_RELATIVE,
    Sky130PreparationError,
    prepare_sky130,
)


def _minimal_pdk(root: Path, include: bytes = BROKEN_INCLUDE) -> Path:
    pdk = root / "sky130_fd_pr"
    for relative in (MODEL_RELATIVE, INCLUDED_RELATIVE, LIBRARY_RELATIVE):
        path = pdk / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"* fixture\n")
    (pdk / MODEL_RELATIVE).write_bytes(b"* header\r\n" + include + b"\r\n")
    return pdk


def test_repairs_vendored_include_and_preserves_line_endings(tmp_path):
    pdk = _minimal_pdk(tmp_path)

    assert prepare_sky130(pdk) == "repaired"

    data = (pdk / MODEL_RELATIVE).read_bytes()
    assert BROKEN_INCLUDE not in data
    assert FIXED_INCLUDE + b"\r\n" in data


def test_already_repaired_tree_is_idempotent(tmp_path):
    pdk = _minimal_pdk(tmp_path, FIXED_INCLUDE)

    assert prepare_sky130(pdk) == "ready"
    assert prepare_sky130(pdk) == "ready"


def test_rejects_unknown_model_revision(tmp_path):
    pdk = _minimal_pdk(tmp_path, b"include something-else")

    with pytest.raises(Sky130PreparationError, match="unexpected"):
        prepare_sky130(pdk)


def test_rejects_incomplete_pdk(tmp_path):
    pdk = _minimal_pdk(tmp_path)
    (pdk / INCLUDED_RELATIVE).unlink()

    with pytest.raises(Sky130PreparationError, match="incomplete"):
        prepare_sky130(pdk)
