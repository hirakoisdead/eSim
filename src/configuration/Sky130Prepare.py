"""Validate and repair the vendored SKY130 primitive model tree.

The bundled ``sky130_fd_pr.tar.xz`` is an upstream 2022 snapshot.  One line
in that snapshot is Spectre-like text rather than a SPICE directive, so
ngspice treats it as a current source and aborts while loading *any* corner.
Keep the archive byte-for-byte reproducible and apply this narrow, inspectable
repair after extraction on every supported operating system.
"""

from __future__ import annotations

import argparse
from pathlib import Path


BROKEN_INCLUDE = b'include "sky130_fd_pr__esd_nfet_05v0_nvt.pm3"'
FIXED_INCLUDE = (
    b'.include "../esd_nfet_05v0_nvt/'
    b'sky130_fd_pr__esd_nfet_05v0_nvt.pm3.spice"'
)
MODEL_RELATIVE = Path(
    "cells/nfet_05v0_nvt/sky130_fd_pr__nfet_05v0_nvt.pm3.spice"
)
INCLUDED_RELATIVE = Path(
    "cells/esd_nfet_05v0_nvt/"
    "sky130_fd_pr__esd_nfet_05v0_nvt.pm3.spice"
)
LIBRARY_RELATIVE = Path("models/sky130.lib.spice")


class Sky130PreparationError(RuntimeError):
    """The extracted PDK is absent, incomplete, or unexpectedly different."""


def prepare_sky130(pdk_root: Path) -> str:
    """Repair the known bad include and validate the runtime entry points.

    Returns ``"repaired"`` when the vendored defect was changed and
    ``"ready"`` when an already-corrected tree was supplied.  Any other file
    state is rejected instead of guessing at a third-party model deck.
    """

    root = Path(pdk_root)
    model = root / MODEL_RELATIVE
    included = root / INCLUDED_RELATIVE
    library = root / LIBRARY_RELATIVE

    missing = [path for path in (model, included, library) if not path.is_file()]
    if missing:
        raise Sky130PreparationError(
            "incomplete SKY130 PDK; missing: "
            + ", ".join(str(path) for path in missing)
        )

    data = model.read_bytes()
    broken_count = data.count(BROKEN_INCLUDE)
    fixed_count = data.count(FIXED_INCLUDE)

    if broken_count == 1 and fixed_count == 0:
        model.write_bytes(data.replace(BROKEN_INCLUDE, FIXED_INCLUDE, 1))
        state = "repaired"
    elif broken_count == 0 and fixed_count == 1:
        state = "ready"
    else:
        raise Sky130PreparationError(
            "unexpected nfet_05v0_nvt include state "
            f"(broken={broken_count}, corrected={fixed_count}); refusing "
            "to rewrite an unknown PDK revision"
        )

    verified = model.read_bytes()
    if BROKEN_INCLUDE in verified or verified.count(FIXED_INCLUDE) != 1:
        raise Sky130PreparationError("SKY130 include repair did not verify")
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="prepare an extracted eSim SKY130 PDK for ngspice"
    )
    parser.add_argument("pdk_root", type=Path)
    args = parser.parse_args(argv)
    try:
        state = prepare_sky130(args.pdk_root)
    except (OSError, Sky130PreparationError) as exc:
        parser.exit(1, f"SKY130 preparation failed: {exc}\n")
    print(f"SKY130 PDK {state}: {args.pdk_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
