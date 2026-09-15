# Cutting an eSim release — maintainer cookbook

Audience: a FOSSEE maintainer with **zero prior context**.
Design and rationale live in [PACKAGING.md](PACKAGING.md); this file is the
"run these commands, tick these boxes" guide.

There are two artifacts per release:

1. `eSim-<VERSION>-ubuntu.zip` — built on any Linux box with `./make-release.sh`
2. `eSim-<VERSION>-installer.exe` — built on a Windows box with
   `windows\build-windows.ps1`

There is also a zero-download-page install path for Ubuntu:
`Ubuntu/bootstrap.sh`, served raw from GitHub as a `curl | bash` one-liner
(see README/INSTALL). It fetches the branch tarball to `~/eSim` and execs
`Ubuntu/install-eSim.sh` there — it contains NO install logic of its own, so
it needs no per-release work beyond keeping its default `ESIM_BRANCH`/
`ESIM_REPO` pointed at the source users should get. The merged-source defaults
are `FOSSEE/eSim` and `master`; tagged release instructions set `ESIM_BRANCH`
to the release tag so that an installation remains pinned to that release.

---

## 0. Pre-flight

```bash
cd eSim
cat VERSION                      # bump this file first if cutting a new version
git status                       # know what you're freezing: make-release.sh
                                 # snapshots the WORKING TREE, dirty or not,
                                 # and stamps the dirty state into RELEASE
python3 -m pytest src windows/tests -q     # must be green
bash -n Ubuntu/install-eSim.sh             # installer syntax
./Ubuntu/install-eSim.sh --dry-run         # sane plan for YOUR Ubuntu version
```

## 1. Ubuntu artifact

```bash
./make-release.sh
# -> dist/eSim-<VERSION>-ubuntu.zip  +  .sha256
```

Smoke-test the artifact itself (any machine):

```bash
cd /tmp && unzip -q <repo>/dist/eSim-<VERSION>-ubuntu.zip
cd eSim-<VERSION> && cat RELEASE && ./install-eSim.sh --dry-run
```

Full install test — **needs clean VMs** (never test installs on your dev
box): one Ubuntu 24.04 VM and one 26.04 VM, then the checklist in §4.

## 2. Windows artifact

On a Windows 10/11 x64 machine (or a `windows-latest` CI runner) with 7-Zip:

```powershell
git clone <repo> ; cd eSim
powershell -ExecutionPolicy Bypass -File windows\build-windows.ps1
# -> windows\dist\eSim-<VERSION>-installer.exe (+ KiCad installer + .sha256)
```

If the build stops with "no pinned sha256", a dependency was version-bumped:
re-run with `-AcceptNewHashes`, then **verify the recorded hash against the
upstream project's published checksum**, and commit the updated
`windows/deps-manifest.json`.

Full install test — clean Windows 10 or 11 VM, checklist in §4.

## 3. Publish (push-map)

| What | Where | Notes |
|---|---|---|
| Source code, installers, packaging scripts, this doc | `FOSSEE/eSim` branch `master` | `Ubuntu/install-eSim.sh`, `make-release.sh`, `windows/*`, `PACKAGING.md`, `MAINTAINERS-PACKAGING.md` all live on master — there is **no separate "installers" branch** anymore; per-version script branches are exactly the drift that killed the old scheme. |
| `eSim-<VERSION>-ubuntu.zip` + `.sha256` | GitHub Release assets on `FOSSEE/eSim`, tag `v<VERSION>` | Never commit built zips to the repo. |
| `eSim-<VERSION>-installer.exe` + KiCad installer + `.sha256` | Same GitHub Release | Built from the tagged commit; the exe embeds `windows/build/eSim/python-wheels.lock` — attach that lock file to the release notes too, together with `windows/build/eSim/tools/msys64/PACKAGES.lock` (the resolved MSYS2 gcc/verilator/ghdl set; `pacman` is rolling, so this is the only record of which toolchain a given release shipped). |
| nghdl changes (`nghdl/` dir) | `FOSSEE/nghdl` repo, kept in sync | `nghdl/` in this repo is the packaging copy that `make-release.sh` zips; upstream fixes belong in both. The vendored duplicates (`src/maker/kicad_symlib.py` ↔ `nghdl/src/kicad_symlib.py`, `model_teardown.py`) must stay byte-identical — a drift-guard test enforces it. |
| esim.fossee.in downloads page | FOSSEE web team | Point at the GitHub Release assets; include both sha256 sums. |

Tag after both artifacts pass their VM checklists:

```bash
git tag -a v<VERSION> -m "eSim <VERSION>"
git push origin master v<VERSION>
```

## 4. Release verification checklist

Copy this table into the release PR/issue and fill the Result column.
"VM" = must run on a clean VM of that OS.

| # | Check | How | Where |
|---|---|---|---|
| U1 | Tests green | `python3 -m pytest src windows/tests -q` | dev box |
| U2 | Installer syntax + plan | `bash -n …` + `--dry-run` | dev box |
| U3 | Release zip layout | unzip → `RELEASE`, `install-eSim.sh` at root, `nghdl.zip`, `library/kicadLibrary.tar.xz` present | dev box |
| U4 | Clean install 24.04 | `./install-eSim.sh --install` completes; log at `~/eSim-install.log` | VM |
| U5 | Clean install 26.04 | same | VM |
| U6 | GUI launches | `esim` from terminal; PyQt6 GUI appears; code editor opens (Qsci) | VM |
| U7 | ngspice sim end-to-end | open an `Examples/` project → KiCad-to-Ngspice → simulate → plot | VM |
| U8 | NgVeri build | add a Verilog model (verilator path); symbol appears in eeschema | VM |
| U9 | Verilog Verifier | compile+simulate a `.v` in the verifier (iverilog) | VM |
| U10 | nghdl VHDL co-sim | build + simulate an nghdl example (ghdl-llvm backend) | VM |
| U11 | Symbol split correct | `/usr/share/kicad/symbols` root-owned, no `eSim_Ngveri/NgVeriCosim/Nghdl` files there; the 3 live in `~/.esim/kicad_symbols`; `sym-lib-table` uris absolute | VM |
| U12 | Reinstall no-clobber | build a model (U8), re-run `--install`, model still in `~/.esim/kicad_symbols` lib | VM |
| U13 | Uninstall scoped | `--uninstall`; verify no leftover `/usr/share/kicad` wipe of KiCad-owned files beyond package purge | VM |
| W1 | Build completes | `build-windows.ps1` (Full flavour) with all hashes pinned; Stage-SimToolchain's ngspice smoke run + code-model checks pass | Win build box |
| W2 | Install + launch | run installer to default `C:\FOSSEE\eSim`; desktop shortcut starts GUI | Win VM |
| W3 | KiCad hand-off | with KiCad absent, installer offers the bundled official KiCad setup | Win VM |
| W4 | Per-user bootstrap | after first launch: `%USERPROFILE%\.esim\config.ini`, `kicad_symbols\` seeded, full `%USERPROFILE%\.nghdl\config.ini` (NGHDL/SRC/COMPILER/COSIM sections), spinit codemodel lines point at the install, eSim libs in `%APPDATA%\kicad\<ver>\sym-lib-table` | Win VM |
| W5 | Doctor all-green | `C:\FOSSEE\eSim\esim.bat --doctor` exits 0, every row OK (Full flavour) | Win VM |
| W6 | ngspice + SKY130 sim | Examples project simulates + plots; `library\sky130_fd_pr` exists, `sky130_fd_pr.tar*` does not; a SKY130 1.8 V CMOS inverter simulates and inverts correctly through `tools\nghdl\install_dir\bin\ngspice.exe` | Win VM |
| W7 | Verifier (iverilog) | compile+simulate a `.v` | Win VM |
| W8 | NgVeri build (Full) | Verilog model build via bundled MSYS2 toolchain; symbol lands in `eSim_Ngveri` | Win VM |
| W9 | d_cosim end-to-end (Full) | NgVeri Dual Co-sim build, then simulate a schematic using the model (ivlng loads libvvp — check `~/.esim/dcosim.log`) | Win VM |
| W10 | NGHDL VHDL co-sim (Full) | Makerchip → VHDL tab → upload an `nghdl/Example` model → build (ghdlserver compiles, `-lws2_32` links) → simulate; mintty testbench window appears | Win VM |
| W11 | Second user | log in as a different Windows user, launch: bootstrap recreates per-user state | Win VM |
| W12 | Uninstall | uninstaller removes `C:\FOSSEE\eSim` including runtime-built models under `tools\nghdl`, leaves `%USERPROFILE%\.esim` (by design) | Win VM |
| W13 | Compact flavour honest | Compact install: plain sim works, doctor clearly reports the missing HDL pieces, NgVeri/NGHDL tabs show actionable placeholders (no tracebacks) | Win VM |

When any W-row fails: `powershell -ExecutionPolicy Bypass -File C:\FOSSEE\eSim\windows\collect-logs.ps1` bundles the doctor report + configs + spinit + logs into one Desktop zip — attach it to the issue.

### Results — 2026-07-05 packaging overhaul

Ran on the dev box (Ubuntu 25.04, no clean VMs available):

* U1 [PASS] 328 passed / 6 skipped (`src`), 6 passed (`windows/tests`), 186 (`src/maker`)
* U2 [PASS] `bash -n` clean; `--dry-run` correct on 25.04 profile
* U3 [PASS] built `dist/eSim-2.5-ubuntu.zip` (82 MB), extracted, `--dry-run` from
  the extracted root resolves nghdl.zip + kicadLibrary tarball + sky130
* U4–U13 [PENDING] **clean 24.04 + 26.04 VM runs required**
* W1–W13 [PENDING] **Windows build box + VM required** (no Windows packaging had
  ever been in-repo before; `build-windows.ps1` is untested on real Windows —
  expect a shakedown run; all manifest sha256 fields are blank until the
  first `-AcceptNewHashes` build)

### Addendum — 2026-07-05 sim-toolchain parity session

The Windows target now builds the FULL simulation toolchain from source
(custom ngspice with d_cosim/ivlng/ghdl.cm, libvvp iverilog, MSYS2
ghdl-llvm, staged nghdl python/ghdlserver) — see PACKAGING.md. New in this
session: `src/maker/ToolchainCheck.py` (doctor; CLI `esim --doctor`, Help
menu, pre-flow gates), installer preflight/self-check on Ubuntu, the
`library/config/.nghdl` legacy-path fixes, `-lws2_32` Winsock linking, and
`windows/collect-logs.ps1`. Checklist rows W5/W9/W10/W13 were added for it.
Everything is unit-tested on Linux (`pytest src windows/tests` green);
W1–W13 still need the first real Windows run.
* Known non-blocker: `pytest src/projManagement src/kicadtoNgspice` in that
  argument order has a pre-existing test-ordering flake in
  `test_model_cache.py` (passes alone and in full-suite order).
  *Since diagnosed and fixed — not ordering at all; see both 2026-07-12 run
  reports below.*

### Results — 2026-07-12 Ubuntu 24.04 VM run

Ran U4–U13 on a 24.04.4 VirtualBox VM (the 26.04 sweep runs on its own VM):

* U1 [PASS] 435 passed / 8 skipped after fixes; the `test_model_cache.py`
  "ordering flake" noted above was actually a HOME-isolation bug in the test
  (module-level `_TMP_HOME` vs the repo-wide `isolated_user_home` fixture) —
  fixed, passes in every order now
* U2 [PASS] `bash -n` + `--dry-run` correct on the 24.04 profile
* U4 [PASS] clean install; second full pass after U13's purge also green
* U6 [PASS] GUI up on the live desktop 30 s, themed, Qsci/QtSvg import
* U7 [PASS] BJT_amplifier: 1008 rows, gain ≈ 20×
* U8 [PASS] NgVeri counter model: Ngveri.cm rebuilt, symbol in eSim_Ngveri
* U9 [PASS] verifier engine compile+sim+VCD parse via source-built iverilog
* U10 [PASS] and_gate VHDL co-sim: socket handshake, 194 rows, truth table clean
  on steady-state samples — **after** the ghdl-gcc fallback fix below
* U11 [PASS] after fixing `sudo rsync -a` source-ownership leak (`--chown=root:root`)
* U12 [PASS] eSim_Ngveri.kicad_sym byte-identical across reinstall
* U13 [PASS] no leftovers, KiCad removed by package purge only

24.04-specific findings fixed this run:

1. **Qt 6.4**: noble ships Qt 6.4.2; `QStyleHints.colorScheme()` /
   `colorSchemeChanged` are Qt ≥ 6.5. Added `theme_utils.system_is_dark()`
   (gsettings → palette fallback) and guarded the signal hookup.
2. **ghdl-llvm broken as shipped on noble**: backend wants
   `libLLVM-18.so.18.1`, noble's libllvm18 ships `libLLVM.so.18.1`.
   `install-nghdl.sh` now compile-smoke-tests GHDL and falls back to
   ghdl-gcc (see the addendum in install-nghdl-scripts/GHDL-BACKEND-26.04.md).
3. `StandardKey.SaveAs` unbound on the Qt 6.4 fallback theme — pinned
   Ctrl+Shift+S in the Verilog Verifier.

### Results — 2026-07-12 Ubuntu 26.04 clean-VM run

Ran U5–U13 on a clean Ubuntu 26.04 LTS VM (fresh box; a prior eSim 2.5
install was fully removed first). Four breaks found and fixed — two of them
(the QtSvg dep and the rsync ownership leak) were hit independently by the
24.04 run above and landed with that run's commits; the other two are
committed with this run:

* U5 [PASS] `--install` completes end-to-end (KiCad 9.0.8 from universe,
  PyQt6/Qsci from apt, venv, nghdl, sky130, launcher, doctor all-green).
  **Fix 1:** the nghdl-simulator (ngspice-45.2) tarball is a repacked source
  tree, so automake maintainer mode re-runs `aclocal-1.16` (absent on
  24.04+/26.04) and dies — `install-nghdl.sh` now configures with
  `--disable-maintainer-mode`.
  **Fix 2:** the GUI hard-imports `PyQt6.QtSvg`, which Debian/Ubuntu split
  into `python3-pyqt6.qtsvg` (NOT a dependency of `python3-pyqt6`) —
  added to `QT_PKGS` + an install-time import check.
* U6 [PASS] `esim` launches, PyQt6 GUI stays up, Qsci imports (after Fix 2).
* U7 [PASS] `Examples/Halfwave_Rectifier` netlist through the nghdl ngspice:
  62 data rows, `plot_data_v/i.txt` produced.
* U8 [PASS] NgVeri Verilator build driven through the real
  `ModelGeneration` pipeline; symbol lands in `~/.esim` `eSim_Ngveri`,
  model simulates. **Fix 3:** hdlparse silently drops the FIRST port of a
  single-line ANSI header (`module m(input a, input b, ...)`) — the header
  splitter now also breaks the line after `(`.
* U9 [PASS] compile+simulate with the source-built iverilog/vvp (libvvp is
  resolved via `[COSIM] IVERILOG_LIB` / `LD_LIBRARY_PATH` by design —
  bare-shell `vvp` without that env fails, which is expected).
* U10 [PASS] nghdl `and_gate` VHDL co-sim end-to-end on ghdl-llvm 5.0.1:
  ghdlserver elaborates (`ghdl -e -Wl,ghdlserver.o`), socket sim runs,
  correct output. This was the first real run of the ngspice-45.2 rewrite.
* U11 [PASS] **Fix 4:** `sudo rsync -a` preserved the checkout's user ownership
  on `/usr/share/kicad/symbols` (files AND the dir) — fixed as
  `--chown=root:root --chmod=D755,F644` (landed via the 24.04 run's commit).
* U12 [PASS] built model (U8) survives a full `--install` re-run byte-identical;
  no generated libs leak into `/usr/share`.
* U13 [PASS] uninstall leaves zero eSim artifacts; `/usr/share/kicad` reduced to
  an empty package-purged dir, nothing KiCad-owned over-wiped. Note: the
  `modelParamXML/{Nghdl,Ngveri}/*` wipe also deletes the four git-tracked
  orphan XMLs (or_gate, advanced_pwm, dvsd_8_bit_priority_encoder,
  vsdserializer_v1 — no matching template symbols); harmless for release
  zips, dirties a dev checkout. Decide whether to untrack them.
* Test-suite hygiene: the `test_model_cache.py` flake was NOT ordering — the
  test resolved paths from import-time HOME while the repo-wide
  `isolated_user_home` fixture re-points HOME per test. Fixed it plus the
  same import-time/run-time HOME mismatch in `test_hdl_icarus.py` and
  `test_nghdl_embed.py`; `pytest src windows/tests`, `pytest src/maker`
  and each file standalone are now all green (435 passed / 8 skipped full).
  (`test_model_cache.py` itself got the identical fix from the 24.04 run's
  commit; the other two are committed with this run.)
* U4 [PASS] covered by the 24.04 run above. W1–W13 remain pending.

## 5. When a code change adds a dependency or data file

| The change adds… | You must edit |
|---|---|
| a Python package (pure-python) | `requirements.txt` + `Ubuntu/install-eSim.sh` `installDependency()` pip list + `windows/requirements-windows.txt` |
| a Python package (native/compiled) | `Ubuntu/install-eSim.sh` apt list (**never** pip on Ubuntu — ABI) + `windows/requirements-windows.txt` (wheel) |
| a system tool (simulator, compiler) | Ubuntu: `Ubuntu/install-eSim.sh` or, if simulation-toolchain, `nghdl/install-nghdl.sh` (read its comments first — it encodes hard-won fixes). Windows: `windows/deps-manifest.json` entry + staging step in `build-windows.ps1`. BOTH: a probe in `src/maker/ToolchainCheck.py` (with flow tags + fix hint, plus a test) and a PACKAGING.md dependency matrix row |
| a data file/dir the app reads | ensure `make-release.sh` doesn't exclude it; if it must be per-user-writable, follow the `~/.esim` pattern (see `kicad_symbols` precedent), never a root-owned path |
| a new KiCad symbol library | static → `library/kicadLibrary/eSim-symbols/` + template `sym-lib-table`; runtime-written → also add to `GENERATED_LIBS` in **both** `kicad_symlib.py` copies, `windows/windows_bootstrap.py`, and the installer's exclude/seed lists |
| a new Ubuntu release to support | one new case in `detect_profile()` in `Ubuntu/install-eSim.sh` — that function is the *single* source of per-version truth; do not create per-version scripts |
