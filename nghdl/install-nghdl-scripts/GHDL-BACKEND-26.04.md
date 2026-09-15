# GHDL backend gotcha — Ubuntu 26.04 / nghdl (READ BEFORE PACKAGING)

**TL;DR:** On Ubuntu 26.04, install **`ghdl-llvm`**, never the `ghdl`
meta-package. The meta-package pulls **`ghdl-mcode`**, which silently breaks
nghdl simulation. The 26.04 installer already does this — this file explains
why, so packaging/CI never "simplifies" it back to `apt install ghdl`.

---

## Symptom

- KiCad netlist / `.cir` is correct (`a1/a2/a3` xspice lines + `.model` fine).
- nghdl Python flow runs fine, `nand_gate_tb` etc. compiles.
- But ngspice prints:
  ```
  Connect Error ... giving up
  Simulation Failed.
  ```
- `client.log` never shows `Client-Connected to server`.

It looks like broken eSim code / a broken netlister / a bad patch. **It is
none of those.** It is the wrong GHDL backend on the box.

## Root cause

nghdl builds the VHDL socket server (the thing ngspice's A-device connects to)
by linking a C object into the testbench executable:

```sh
ghdl -e -Wl,ghdlserver.o nand_gate_tb
#        ^^^ pass a linker option -> link ghdlserver.o (C socket server)
```

Only the **gcc** or **llvm** GHDL backends can link. The **mcode** backend is a
JIT and rejects `-Wl`:

```
/usr/bin/ghdl-mcode:error: option -Wl is not available when ghdl is not
configured with gcc or llvm
```

So with mcode:
server binary never builds → nothing listens on the socket → ngspice A-device
client can't connect → `giving up` → `Simulation Failed`.

## Why `apt install ghdl` gives you mcode

The `ghdl` meta-package's dependency line is:

```
Depends: ghdl-common (= 5.0.1+dfsg-1ubuntu1), ghdl-mcode | ghdl-gcc | ghdl-llvm
```

apt installs the **first** satisfiable alternative = **`ghdl-mcode`**.

On top of that, the `/usr/bin/ghdl` wrapper (owned by `ghdl-common`, survives
backend swaps) selects the backend in order **mcode → gcc → llvm** unless the
`$GHDL_BACKEND` env var is set. So even if llvm is *also* installed, an
installed mcode wins.

> Note: on 24.04 nghdl built GHDL 4.1.0 from source against LLVM, so it always
> got an llvm-capable backend. On 26.04 we switched to apt GHDL 5.0.1 (system
> LLVM is v21, incompatible with GHDL 4.1.0's build system), and that switch is
> where the `ghdl` vs `ghdl-llvm` trap appeared.

## The fix (already in install-nghdl-26.04.sh)

```sh
sudo apt-get install -y ghdl-llvm        # NOT 'ghdl'
sudo apt-get purge   -y ghdl-mcode 2>/dev/null || true   # wrapper picks llvm only when mcode is gone
# fail loudly if mcode slips back in:
dpkg -l ghdl-mcode | grep -q '^ii' && { echo "ERROR: ghdl-mcode present"; exit 1; }
```

`ghdl-llvm` pulls `ghdl-common` itself, so the `/usr/bin/ghdl` wrapper is
preserved and now resolves to llvm.

## How to verify a box is good

```sh
ghdl --version                 # must show the LLVM code generator, never "mcode JIT"
dpkg -l | grep ghdl            # ghdl-llvm = ii ; ghdl-mcode must NOT be ii (rc/none is fine)
```

End-to-end smoke test (NAND truth table should come out 1,1,1,0):

```sh
cd ~/nghdl-simulator
install_dir/bin/ngspice -b <testbench>.cir.out
# client.log -> "Client-Connected to server"; plot_data.raw + *_v.txt written
```

## Packaging checklist

- [ ] `.deb` / install dependency = **`ghdl-llvm`**, not `ghdl`.
- [ ] `ghdl-mcode` is **not** pulled in transitively (check the meta-package).
- [ ] Post-install assert: `dpkg -l ghdl-mcode | grep '^ii'` must be empty.
- [ ] If you ever set `$GHDL_BACKEND`, set it to `llvm` (or `gcc`), never `mcode`.

---
*Discovered 2026-06-15 on the eSim `ubuntu-26.04-support` fork while bringing up
the nghdl block. The eSim code, the new KiCad netlister, and local patches were
all correct — the box just had the wrong GHDL backend from a tarball-era
install. Captured here so it does not bite us again at package time.*

---

## Addendum — Ubuntu 24.04: ghdl-llvm installs fine but cannot compile

Found 2026-07-12 running the U10 checklist on a clean 24.04 VM.

On noble, `ghdl-llvm 4.1.0+dfsg-0ubuntu2.1` is **broken as shipped**: its
backend binary requests the soname `libLLVM-18.so.18.1`, but noble's
`libllvm18` ships the library as `libLLVM.so.18.1` (no compat symlink):

```
/usr/lib/ghdl/llvm/ghdl1-llvm: error while loading shared libraries:
libLLVM-18.so.18.1: cannot open shared object file
```

The trap: `ghdl --version` works (it only runs the driver), the installer's
mcode check passes, and the failure surfaces later as a VHDL co-sim that
hangs at `Client-Initialising GHDL...` — the server compile dies before
listening, so it looks exactly like the mcode symptom above.

`install-nghdl.sh` now runs `ghdl_smoke` (analyze+elaborate a scratch
entity) after installing GHDL and falls back to **`ghdl-gcc`** when the
compile fails; the `/usr/bin/ghdl` wrapper auto-selects gcc over llvm, and
the gcc backend links `-Wl,ghdlserver.o` fine. Do not "simplify" the smoke
test away: a --version check cannot catch this class of breakage.
