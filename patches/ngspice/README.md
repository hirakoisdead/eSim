# Patches applied to the ngspice (nghdl-simulator) source tree

Every `*.patch` in this directory is applied with `patch -p1` from the root of
the tree extracted from `nghdl/nghdl-simulator-source.tar.xz`, by both
installers:

* Windows — `windows/build-windows.ps1`, in the MSYS2 chain right after the
  tarball is unpacked.
* Ubuntu — `nghdl/install-nghdl.sh`, function `apply_esim_patches`.

They live here rather than being baked into the tarball so that each change to
the simulator stays a readable diff that a reviewer can check, instead of an
opaque difference inside a binary blob.

The [NGHDL repository](https://github.com/VaradhaCodes/nghdl) carries the same
directory next to the tarball it patches, so that a standalone NGHDL install
(`install-nghdl.sh --install`, without eSim) is patched too. `nghdl/install-
nghdl.sh` looks for `patches/ngspice` beside itself first and falls back to
this directory, which is what an eSim checkout hits. Change a patch in one
place and mirror it to the other.

Do not put patches for any other tree here. `patches/` itself holds patches
against the eSim/ngspice-ghdl Python sources, which are a different tree with
different paths; mixing them would make every patch fail to apply.

## Contents

* `0002-d_cosim-evaluate-co-simulation-at-operating-point.patch` — makes a
  `d_cosim` block report its real outputs at the operating point instead of
  all-zero, so it agrees with an equivalent NgVeri (Verilator) model of the
  same Verilog from t=0. Touches `src/xspice/icm/digital/d_cosim/cfunc.mod`
  and the ivlng bridge (`src/xspice/verilog/vpi.c`, `icarus_shim.h`). See the
  patch header for the measurements, and `docs/NGVERI_ACCURACY.md`.
