# d_cosim (Icarus Verilog) substrate — install notes

These are the toolchain dependencies the **d_cosim / Icarus Verilog**
co-simulation feature needs at runtime, how to install them by hand, and how
eSim discovers them (no hardcoded paths). This file is the source recipe for the
installer wiring in Phase 3 — keep it in sync with what the installer does.

eSim itself never shells out to a hardcoded path: `src/maker/CosimConfig.py`
resolves every tool via, in order, an **env override** → `~/.nghdl/config.ini`
→ PATH / standard location. The installer only has to put the tools somewhere
and record them in `config.ini`.

---

## 1. ngspice (d_cosim + ivlng) — already handled by nghdl-simulator

The d_cosim code model and the `ivlng` adapter are **already built and shipped**
by eSim's existing `nghdl-simulator` install (the custom ngspice from
`nghdl/nghdl-simulator-source.tar.xz`, configured `--enable-xspice`). Verify:

```bash
ls "$HOME/nghdl-simulator/install_dir/lib/ngspice/"   # expect: digital.cm, ivlng.so, ivlng.vpi
"$HOME/nghdl-simulator/install_dir/bin/ngspice" --version   # >= 45 here
```

`ivlng.so` dlopens **libvvp at runtime** (it is NOT linked at build time), so the
ngspice build does not depend on iverilog. **No ngspice action is required** for
d_cosim beyond the normal nghdl install. (If a future tarball predates ivlng,
rebuild it from ngspice >= 44 source with `--enable-xspice`.)

---

## 2. iverilog with libvvp — the one piece to add

Distro/apt iverilog does **not** ship `libvvp`, which `ivlng` needs. Build Icarus
Verilog from source with `--enable-libvvp`.

Build deps (Ubuntu): `autoconf gperf bison flex g++ make git` (only `gperf` was
missing on the dev box).

```bash
sudo apt-get install -y gperf            # + autoconf bison flex g++ make git if absent
git clone https://github.com/steveicarus/iverilog.git ~/iverilog-build
cd ~/iverilog-build
git rev-parse HEAD                        # dev box pinned: de415b2f03c1b41ab5b46faa9632716d98c1cd86
sh autoconf.sh
./configure --prefix="$HOME/iverilog" --enable-libvvp   # prints "Building with libvvp support enabled"
make -j3                                  # -j3 not -j$(nproc): -j7 OOM-killed make on a 6.3 GB box
make install
```

Produces `~/iverilog/bin/{iverilog,vvp}` and `~/iverilog/lib/libvvp.so`.

> Installer (Phase 3): choose a system / eSim-owned prefix instead of `$HOME`,
> and build iverilog **before** ngspice is built if you ever rebuild ngspice
> against it. On Windows ship a prebuilt iverilog that includes libvvp instead of
> source-building (avoids MSYS2).

---

## 3. Record the paths in config.ini

eSim reads a new `[COSIM]` section from `~/.nghdl/config.ini` (POSIX) /
`library/config/.nghdl/config.ini` (Windows). Append (do NOT rewrite the file
with configparser — `[NGHDL]` uses `%(NGHDL_HOME)s` interpolation):

```bash
cat >> ~/.nghdl/config.ini <<EOF

[COSIM]
IVERILOG = $HOME/iverilog/bin/iverilog
IVERILOG_LIB = $HOME/iverilog/lib
EOF
```

These are optional — if absent, CosimConfig falls back to `iverilog` on PATH and
`<prefix>/lib` derived from it. They exist so a non-PATH install still resolves.

Dev override without touching config: `export ESIM_IVERILOG=... ESIM_IVERILOG_LIB=...`
(and `ESIM_NGSPICE=...` for the ngspice binary).

---

## 4. Install the symbol library (dev only)

The empty seed lib `library/kicadLibrary/eSim-symbols/eSim_NgVeriCosim.kicad_sym`
must be present where KiCad looks (the installer copies all eSim-symbols there):

```bash
sudo cp library/kicadLibrary/eSim-symbols/eSim_NgVeriCosim.kicad_sym \
        /usr/share/kicad/symbols/
```

`library/kicadLibrary/template/sym-lib-table` already registers it; the project
template copy picks it up for new projects.

---

## 5. Validate

```bash
# substrate smoke test (no eSim), inverter:
mkdir -p /tmp/t && cd /tmp/t
printf '`timescale 1ns/1ps\nmodule inv(input a,output reg y);always @(*) y=~a;endmodule\n' > inv.v
~/iverilog/bin/iverilog -g2012 -o inv inv.v
cat > t.cir <<'EOF'
* inv d_cosim
.model adc_b adc_bridge(in_low=0.4 in_high=0.6)
.model dac_b dac_bridge(out_low=0 out_high=1 t_rise=1n t_fall=1n)
vin ain 0 pulse(0 1 0 1u 1u 5u 12u)
aadc [ain] [a] adc_b
ainv [a] [y] dut
.model dut d_cosim simulation="ivlng" sim_args=["inv"]
adac [y] [yout] dac_b
.control
tran 0.5u 40u
wrdata out.txt v(ain) v(yout)
.endc
.end
EOF
LD_LIBRARY_PATH=$HOME/iverilog/lib ~/nghdl-simulator/install_dir/bin/ngspice -b t.cir
# yout should be ~ain (inverted)

# eSim capability check:
cd ~/eSim/src && python3 -c "from maker import CosimConfig as C; print('has_dcosim', C.has_dcosim())"
```
