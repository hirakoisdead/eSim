# NgVeri / digital co-simulation — accuracy record and open work

Status of the correctness work on eSim's digital co-simulation backends: what
has been fixed, what is proven, and what is deliberately left open.

This document is meant to be readable by someone who was not present for the
investigation. Everything under "Fixed" is closed; everything under "Open" is a
usable handoff brief.

**Scope rule.** eSim's core converter and the NgVeri (Verilator) backend behave
as they did in eSim 2.5. Where 2.5 is wrong, it is measured and written down,
not changed — see [`UPSTREAM_DECISIONS.md`](UPSTREAM_DECISIONS.md), which lists
every fix that exists, works, and is deliberately switched off, and why.
d_cosim is new, so it is fixed freely — but its target is *NgVeri as 2.5
behaved*, bug for bug, so that swapping backends never changes a number. Some
entries below therefore describe a defect that is fixed **inside d_cosim only**
while the same defect is left standing in NgVeri on purpose.

---

## Background: how a NgVeri model reaches ngspice

`src/maker/ModelGeneration.py` turns a Verilog module into an XSPICE code
model:

| Generated file | Role |
|---|---|
| `sim_main_<stem>.cpp` / `.h` | C++ driver around the Verilator object; `foo_<stem>(init, id)` constructs on `init==0` and runs one `eval()` otherwise |
| `cfunc.mod` | the XSPICE code model: reads `INPUT_STATE`, calls `foo_`, writes `OUTPUT_STATE` |
| `ifspec.ifs` | port table (`Vector_Bounds: [w w]` per port) and parameters |

`nghdl/src/model_generation.py` is the equivalent for VHDL/GHDL and carries a
near-identical copy of the `cfunc.mod` writer. **The two must be kept in
step** — a defect found in one has, so far, always been present in the other.

The contract that matters: an XSPICE code model keeps *all* of its state in
blocks obtained from `cm_event_alloc()` / `cm_event_get_ptr()`, because ngspice
rotates and rolls those blocks back when a timestep is rejected.

---

## Fixed

### N1 — every output port after the first froze after one transition (CRITICAL)

`cm_event_get_ptr(tag, timepoint)` takes two **orthogonal** arguments
(`tools/nghdl/src/xspice/cm/cmevt.c`): `tag` selects the port's storage block,
`timepoint` says how many timesteps **back** to look — 0 current, 1 previous.
Every stock ngspice code model uses `(tag,0)` / `(tag,1)` for *every* tag; see
`d_dff`, which has four.

Both generators carried a second counter initialised outside the port loop and
bumped twice per port, so the timepoint climbed with the tag:

```
port 0 -> (0,0)/(0,1)      correct
port 1 -> (1,1)/(1,2)      wrong
port 2 -> (2,2)/(2,3)      wrong
```

Every port after the first therefore wrote its new value into a *previous*
timestep's block — one ngspice has already copied forward, so the current block
never saw it — and compared against a block two steps back which aliases the
one just written. `_op_x[i] != _op_x_old[i]` is then permanently false,
`OUTPUT_CHANGED` stays `FALSE`, and the pin holds its first transition forever.

Silent: no error, ngspice reports "Simulation Completed Successfully", and a
stuck-high pin looks exactly like a legitimate `done` / `valid` / `error`
output. The wrong value is in the netlist, so downstream blocks consume it too.
In practice the surviving port 0 is the datapath and the casualties are the
status pins.

**This was not a 2.6 regression.** The identical loop shipped in eSim 2.5. What
changed is the bundled simulator:

| | eSim 2.5 | eSim 2.6 |
|---|---|---|
| ngspice | 35 (Aug 2021) | 45.2 (Sept 2025) |
| `cm/cmevt.c` | — | **byte-identical** |
| `EVTaccept` state handling | keeps the full per-instance state history | collapses to one block per accepted timestep, recycling the rest onto a free list |

Under ngspice 35 the out-of-range timepoint happened to land on a
self-consistent older block and the bug stayed latent. ngspice 45's state
recycling removed that padding and made it live. **2.5 was not correct here —
it was lucky.** `(tag,0)/(tag,1)` is the target, not "whatever 2.5 did".

Fixed in `src/maker/ModelGeneration.py` (`cfuncmod`) and
`nghdl/src/model_generation.py` (`createCfuncModFile`).

> **Already-built models are not fixed by this.** The bad indices are compiled
> into each model's `cfunc.mod`. **Every model with two or more output ports
> must be rebuilt.**

Regression witness: `universal_counter_8bit`, whose `wraps[0]` is a one-clock
pulse. It must rise at 9.000 ms **and fall at 10.000 ms**. Stuck high = not
fixed.

### N2 — 32-bit output ports silently froze (HIGH)

The generated converter took a signed `int`:

```c
for (int i = 0; i < n && num>=0; i++) { array[n-i-1] = num % 2; num /= 2; }
```

Verilator ports are unsigned (`CData`/`SData`/`IData`/`QData`). A 32-bit output
with its top bit set arrived negative, the `num>=0` guard failed on iteration
0, the body never ran, and the temp array kept the **previous timestep's
bits** — the port froze across its entire upper range, again silently.
`arr2int`'s `k = 2*k + array[i]` over 32 bits was also signed overflow (UB).

Both now work on `uint64_t` and extract/insert bits, which is exact for every
width up to 64. `ESIM_TRACE`'s `%d` on a possibly-64-bit port was corrected to
`%llu` with an explicit cast.

### N3 — port shapes this backend cannot represent — PARKED, not refused

`ModelGeneration.validate_ports()` rejects two shapes by name:

- **`inout` ports** — `getPortInfo()` files them under inputs because that is
  all the legacy flow can drive; the ifspec then declares `Direction: in` and
  the driven half never reaches ngspice. Worse, the port indices shift by the
  width of the inout, so *every* port is wrong: measured on a probe module, an
  output declared `assign q = 1'b1;` toggled with the clock.
- **ports wider than 64 bits** — Verilator represents those as `VlWide`, which
  no integer conversion can carry.

Both produce a model that builds, runs, and is quietly wrong.

**It is implemented, tested, and NOT called.** eSim 2.5 built these models, and
refusing a build that used to succeed is a maintainer's decision — as is
raising a warning where 2.5 was silent. See
[`UPSTREAM_DECISIONS.md`](UPSTREAM_DECISIONS.md) items 2 and 3; wiring it back
in is one line in `NgVeri.addverilog()`, and
`test_validate_ports_is_not_wired_into_the_build` fails if someone does it by
accident.

d_cosim refuses `inout` outright (`D6`). That is a new backend on a path no 2.5
schematic can reach, so the rule there is ours to set.

### Regression tests

- `src/maker/tests/test_ngveri_event_ptrs.py` — asserts no generated
  `cm_event_get_ptr` ever asks for a timepoint past 1, that tags match
  `cm_event_alloc` order, that the INIT branch still pairs `(tag,0)` with
  itself, and **compiles and runs** the emitted converters against the bit
  patterns that used to freeze.
- `src/maker/tests/test_nghdl_generation.py` — the same index check on a real
  end-to-end VHDL `cfunc.mod`.

---

## Fixed — the analog→digital boundary and the d_cosim (Icarus) backend

`D1` and `D5` are two symptoms of one cause and share one fix; read `D1` first.

### D1 — the design was clocked twice per analog edge (CRITICAL)

The reported symptom was "d_cosim advances the design 2x": on
`universal_counter_8bit`, `cnt_val` reads `250, 252, 254, 0, 2, 4` instead of
`250, 251, 252, …`, and the wrap fires at 6.000 ms instead of 9.000 ms.

**It is not a doubled clock, and it is not in d_cosim.** The cause is the
analog→digital boundary:

`adc_bridge` is a **three**-state converter. Below `in_low` it emits 0, above
`in_high` it emits 1, and **between them it emits x**. eSim's default band is
`in_low=1.0 / in_high=2.0`, so a clock ramping 0→5 V crosses it in two steps.
`eprint` on the digital node shows the whole story — four events per period,
not two:

```
            in_low=1.0 in_high=2.0        in_low = in_high = 1.5
  0.000321 ms   0 -> U                      0 -> 1
  0.000448 ms   U -> 1                        —
  0.501701 ms   1 -> U                        —
  0.501828 ms   U -> 0                        —
  0.502001 ms     —                         1 -> 0
```

Icarus is a real four-state simulator, and IEEE 1364 defines `posedge` as a
transition to a *higher* value — `0→U` and `U→1` are **both** posedges. So the
design is clocked twice per analog edge.

Discriminating evidence, measured on a probe design with one counter per edge
sensitivity (`src/maker/tests` has the netlist-level regression; the probe
itself is in the investigation notes):

| counter | observed | a doubled clock would give |
|---|---|---|
| `always @(posedge clk)` | **+2** per period | +2 |
| `always @(negedge clk)` | **+2** per period | +2 |
| `always @(clk)` | **+4** per period | +2 |

The `+4` settles it. It also explains why `wraps[0]` stayed a full 1.000 ms
wide (measured 6.000441 → 7.000303 = 0.999862 ms): the wrap lands on the
*second* sub-edge and is cleared by the *first* sub-edge of the next period.

NgVeri and NGHDL escape the *double* edge only by accident — see `D5`, which
is the same `U` window doing something else.

**Fix — `cosim_wrapper_source()` in `src/maker/ModelGeneration.py`.** The design
is simulated behind a generated wrapper that reads an `x` input as logic **1**,
per bit, using `===` so the comparison itself cannot return x:

```verilog
assign esim_d_in_lv[gi] = (esim_d_in[gi] === 1'b0) ? 1'b0 : 1'b1;
```

That is precisely what NgVeri's generated C already does. The clock arrives as
`0 → 1 → 1` — one posedge, taken as the voltage crosses `in_low`, which is the
same edge at the same instant NgVeri takes. **The netlist is not touched**: it
still says `in_low=1.0 in_high=2.0`, exactly as eSim 2.5 wrote it.

This deliberately inherits NgVeri's *mistake* as well as its behaviour — an
input at 1.2 V still reads as a confident 1 (see `D5`). Matching the old
backend bug-for-bug is the requirement: a d_cosim that were "more correct" than
NgVeri would make a backend swap change the answer, which is exactly what a
drop-in alternative must never do.

There is also a netlist-level fix — `collapse_adc_band_for_hdl()` in
`src/kicadtoNgspice/KicadtoNgspice.py`, which rewrites `in_low`/`in_high` to
their midpoint. It works, it is tested end to end, and it is **parked, not
wired in**, because it changes a value eSim has emitted since 2.5. See
`UPSTREAM_DECISIONS.md` item 1.

Verified end to end against the reference run (`.tran 10u 15m`):

| run | `cnt_val` at each clock | `wraps0` |
|---|---|---|
| NgVeri (== eSim 2.5, byte-identical) | 0, 1, 250, 251 … 255, 0, 1, 2, 3, 4, 5 | rises 9.000 ms |
| d_cosim, before | 0, 2, 250, 252, 254, 0, 2, 4, 6 … | 6.000 → 7.000 ms |
| d_cosim, wrapped (netlist unchanged) | 0, 1, 250, 251 … 255, 0, 1, 2, 3, 4, 5 | 9.001 → 10.001 ms |
| d_cosim, band collapsed (parked) | 0, 1, 250, 251 … 255, 0, 1, 2, 3, 4, 5 | 9.001 → 10.001 ms |

The last two rows are independent cures for the same defect; either alone is
sufficient. Only the wrapper ships.

### D2 — a second d_cosim block segfaulted ngspice (HIGH)

ivlng loads Icarus's `libvvp`, whose engine state is **process global and
single-shot**. A netlist with two d_cosim blocks prints

```
This VVP simulation has already run and can not be reused
```

and then ngspice dies with SIGSEGV, leaving no output file and no diagnostic
the user can act on. Loading a renamed second copy of libvvp does not help:
`ivlng.vpi` imports the first copy by name, so the second engine's VPI
callbacks run against the first engine.

**Fix** — the limit is one *engine* per process, not one *block* per schematic,
so the converter puts every block into a single engine instead of refusing.

`merge_dcosim_blocks()` (`src/kicadtoNgspice/KicadtoNgspice.py`) and
`src/maker/cosim_merge.py` generate one wrapper module instantiating every
d_cosim block on the schematic, compile it to one vvp at conversion time, and
emit **one** d_cosim a-device whose `d_in`/`d_out` vectors are the blocks'
vectors concatenated. The blocks keep talking to each other, and to the analog
half, through their SPICE nodes — the wrapper never sees the connections.

Blocks are keyed by **a-device name**, not by `.model` card: two placements of
the same Verilog block share one card, and keying on it gives both copies the
same nodes.

Verified end to end: three blocks of two different models in one schematic,
each counting independently, two of them the same model released from reset
3 ms apart (`test_three_blocks_of_two_models_run_in_one_simulation`).

### The wrapper has one port per direction, and that is load-bearing

ivlng discovers ports by walking `vpi_iterate(vpiPort, top)` and giving each a
running bit offset (`vpi.c` `start_cb`), then finds a bit's owner by scanning
those offsets (`icarus_shim.c`). So the wiring depends on **the order VVP
reports ports in** — which is not the order they are declared in, and which was
observed to change between compiles of the same source: an early three-block
wrapper with one Verilog port per design port came out correct on one build and
with one block's `rst` wired to a `clk` on the next, giving a counter that
reset itself at random.

The wrapper therefore declares exactly one input vector and one output vector
and slices every block's ports out of them. One port per direction means one
offset, always 0, and pure arithmetic after it — there is nothing left to vary.
Node `j` of a group is bit `width - 1 - j` (`icarus_shim.c:97`, "Bit position
for big-endian"), which is the convention the single-block netlist already
used.

### D3 — a coarse `` `timescale `` in the user's own source froze the design (HIGH)

ivlng advances VVP by `(spice_time - vvp_time) / precision` ticks, and
**truncates**. When one SPICE step is shorter than a single precision tick that
quotient is 0 and VVP never runs. A source declaring `` `timescale 1ms/1ms ``
— legal, and fine under plain `vvp` — therefore simulates to completion with
every output stuck at its initial value, and ngspice reports success. Measured:
all counters read 0 for the whole 10 ms run.

eSim already injected `` `timescale 1ns/1ps `` when the source had none; it
trusted whatever the source declared.

**Fix** — `normalise_timescale()` in `src/maker/ModelGeneration.py` rewrites
**only the precision field** to `1ps` when the declared precision is coarser
(`1ms/1ms` → `1ms/1ps`), and logs which directives it touched. The time unit is
what the design's own `#` delays are expressed in, so leaving it alone keeps
their meaning exactly; a finer precision can only reduce rounding.

### D5 — NgVeri and NGHDL read any in-band voltage as a confident 1 — PARKED

The same `U` window as `D1`, taken by a two-state backend. Both generators emit

```c
if (INPUT_STATE(port[Ii]) == ZERO) temp[Ii] = 0; else temp[Ii] = 1;
```

so `UNKNOWN` is not merely approximated — it is read as a **logic 1**. With the
stock `in_low=1.0 / in_high=2.0`, *every* input voltage from 1.0 V to 2.0 V
reads as high.

Measured on the real, already-built Verilator `universal_counter_8bit`, holding
`lden` at a constant 1.2 V (inside the band, below its midpoint):

| adc_bridge | what NgVeri read | `cnt_val` |
|---|---|---|
| `in_low=1.0 in_high=2.0` | logic **1** | `250, 250, 250, …` — loads forever |
| collapsed to 1.5 V | logic **0** | `1, 2, 3, 4, …` — counts, correct |

A 1.2 V input is unambiguously below a 1.5 V threshold, and the shipped
configuration gets it backwards.

**This is not fixed, on purpose.** Correcting it means changing the adc_bridge
band eSim has emitted since 2.5, which moves the numbers for designs users
already consider working —
[`UPSTREAM_DECISIONS.md`](UPSTREAM_DECISIONS.md) item 1. NgVeri and NGHDL still
read 1.2 V as a 1, **and so does d_cosim**, because its wrapper reproduces the
same rule (`D1`). Reproducing the defect is the requirement: a d_cosim that
were more correct than NgVeri here would make a backend swap change the answer.

**What collapsing the band would not buy: better edge timing.** Same model,
same clock, band vs collapsed — the `cnt_val` sequence is byte-identical
(`0, 1, 250, 251 … 255, 0, 1, 2, 3, 4, 5`), and the digital edge merely moves
from +0.3 µs to +0.7 µs past the millisecond. Both numbers are dominated by the
analog-timestep quantisation described below, not by the threshold; which one
lands nearer its own ideal crossing is an accident of where ngspice's timepoints
fall. The only real gain would be the in-band misread above — which is why this
is a correctness question for the maintainers rather than a tuning knob.

### D4 — multi-file designs never built (MEDIUM)

`build_cosim` ran `iverilog -g2012 -o <out> <one file>`. Files added through
"Add dependency files/folder" are copied next to the top source but were never
passed, and Icarus does not search the working directory on its own, so any
design with a submodule in another file died on `Unknown module type`.

**Fix** — the compile now carries `-y <modeldir> -I <modeldir> -Y .sv`. `-y`
only pulls a file in when a module is still unresolved, so a self-contained
design compiles exactly as before.

### D6 — `inout` ports corrupted every port, and the advice was backwards (MEDIUM)

`getPortInfo()` files `inout` under `input_list`, so the netlist declares a
bidirectional pin as a plain `d_in` and d_cosim's `d_inout` group is never
populated. eSim used to *warn* ("handling of inout is limited") and carry on,
and `validate_ports()` told NgVeri users to switch to "the d_cosim backend,
which has a real inout group" — advice that sends them at a backend which is
equally broken here.

Measured on a probe module `iotest(input clk, inout io, output q)` whose design
drives `io` and declares `assign q = 1'b1;`:

```
Warning: mismatched XSPICE/co-simulator input counts: 2/1.
Warning: mismatched XSPICE/co-simulator inout counts: 0/1.
```

Two lines in a wall of ngspice output, then it runs. `io` never left the
simulation — and `q`, a **constant 1**, toggled with the clock. The port indices
are off by the width of the inout, so *every* port is wrong, not just the
bidirectional one.

**Fix** — `build_cosim` refuses an `inout` module. Detection reads the direction
*field* of `connection_info.txt`, so a port named `inout_en` is not mistaken for
one. Neither backend supports bidirectional pins; the honest answer is to split
the pin.

This is a refusal on the **new** backend only: no eSim 2.5 schematic can be
using d_cosim, so nothing that worked before stops working. NgVeri keeps
accepting `inout` and keeps being silently wrong about it, because taking that
away is a maintainer's decision — `N3` and
[`UPSTREAM_DECISIONS.md`](UPSTREAM_DECISIONS.md) item 2.

### D7 — d_cosim reported all-zero outputs at the operating point (HIGH)

A `d_cosim` block reported every output as 0 at `t=0` and for the whole of the
first timestep. An NgVeri (Verilator) model of the *same Verilog* is already
correct there, so the two co-simulation backends disagreed on identical
sources — which is the one thing this backend was not allowed to do.

It bit any design whose correct initial output is 1: an inverter, a NAND with
both inputs low, anything held by a reset.

**Measured** on the three-gate reference circuit (AND + OR + NAND, driven
through one `adc_bridge`, read back through one `dac_bridge`), against the
eSim 2.5 NgVeri run of the same schematic:

| | t=0 NAND | logic vs 2.5 over 25 ms | worst edge skew |
|---|---|---|---|
| 2.5 NgVeri (reference) | 5 V | — | — |
| 2.6 NgVeri | 5 V | identical | 2.5 ns |
| 2.6 d_cosim, before | **0 V until 2.506 µs** | **one 2.51 µs window wrong** | n/a (extra edge) |
| 2.6 d_cosim, after | 5 V | identical | 0.000 ns |

The pre-fix run also emitted `WARNING: output scheduled with impossible delay
(-2.504e-06)`, which is the same defect seen from the other side: the
co-simulator's `vtime` was still 0 while SPICE had reached the first timestep.

**Cause** — two halves, one on each side of the d_cosim/ivlng boundary.

1. `src/xspice/verilog/vpi.c`, `next_advance_cb()`. SPICE asks for time zero at
   the operating point, which gives `ticks == 0`; the loop went straight back
   to waiting for a later time, so VVP never ran its time-zero events and never
   reported the design's initial outputs.
2. `src/xspice/icm/digital/d_cosim/cfunc.mod`, `ucm_d_cosim()`. The
   `TIME == 0.0` branch pushed inputs into the co-simulator and returned
   without running it, leaving every output at the `ZERO` written during
   `INIT`. Time zero was first stepped from `STEP_PENDING`, which does not run
   until the first accepted timestep.

**Fix** — `patches/ngspice/0002-d_cosim-evaluate-co-simulation-at-operating-point.patch`.
The bridge settles once at time zero using the zero-length `set_stop()` that
`output_cb()` already uses to gather same-instant events; the code model steps
at the operating point and publishes the result through a new `op_output()`,
which writes the port state directly rather than scheduling a delayed event,
because the operating point has no future — the value *is* the DC state.

The patch is applied to the extracted simulator tree by both installers rather
than baked into `nghdl/nghdl-simulator-source.tar.xz`, so it stays a readable
diff instead of an opaque change inside a binary blob. See
`patches/ngspice/README.md`.

**Clocked behaviour is unchanged.** On a divide-by-2 flip-flop the toggle edges
land at identical times before and after (10 edges, 0.5028 µs … 9.5028 µs), and
the patch *removes* a spurious 1.5 ns startup glitch on the inverted output.

**Also fixed alongside it**: a d_cosim netlist keeps its analysis card inside
`.control` so the one-shot Icarus engine runs exactly once, which left
ngspice's own `-r <project>.raw` with nothing to run — it wrote an empty
rawfile header and held the filename open. A co-simulation therefore never
produced the project rawfile every other backend leaves behind, and any
rawfile from an earlier run stayed there, stale. `-r` is now omitted for a
d_cosim run and the netlist writes that file itself
(`KicadtoNgspice.createNetlistFile`, `NgspiceWidget._prepare_ngspice_arguments`).

### Regression tests

- `src/kicadtoNgspice/tests/test_dcosim_netlist.py` — the parked band collapse
  (targeting, midpoint, parameter preservation, no-op cases, Ngveri/Nghdl cards
  by name) and the instance count.
- `src/kicadtoNgspice/tests/test_dcosim_netlist_write.py` — driven through the
  real `MainWindow.createNetlistFile`, asserting the `.cir.out` on disk. Covers
  the *wiring*: that the adc_bridge card comes out exactly as 2.5 wrote it, that
  several blocks become one device with concatenated node vectors, and that a
  merge which cannot be done correctly writes no netlist at all.
- `src/maker/tests/test_dcosim_build.py` — the `` `timescale `` table, what
  actually reaches iverilog (library flags, temp copy, user's file untouched),
  the `inout` refusal, and the wrapper: one port per direction, `x` read as 1
  per bit, big-endian node-to-bit mapping, disjoint slices per block.
- `src/maker/tests/test_dcosim_simulation.py` — **end to end**: compiles with
  iverilog, runs under ngspice + ivlng, decodes the output bus back into
  integers. Asserts the defect (2 per clock, compiled bare), the fix (1 per
  clock, *with the 2.5 netlist unchanged*), the parked netlist-level fix, the
  one-clock strobe, and three blocks of two models counting independently in
  one simulation. Skipped when the machine has no iverilog/ivlng. This is the
  only test in the area that can catch "builds, runs, and is wrong", so a
  change here should be taken through it rather than through unit tests alone.
  Also carries the `D7` gate — `test_outputs_are_live_at_the_operating_point`,
  `test_operating_point_value_is_not_just_a_stuck_output` and
  `test_co_simulator_time_base_starts_aligned` — which fail against an
  unpatched simulator, by design. Their design has no clock, so they are
  timing-independent; the second one exists so the first cannot pass against a
  model whose outputs are merely stuck high.

  > **Known flake, pre-existing:**
  > `test_three_blocks_of_two_models_run_in_one_simulation` fails
  > intermittently (measured 4/6 runs on an unpatched simulator and 2/6 on a
  > patched one, interleaved, so it is not related to `D7`). `MULTI_NETLIST`
  > clocks from `pulse(0 5 0 1u 1u 0.5m 1m)` — first rising edge at t=0,
  > period 1 ms — and releases reset at exactly 2.0 ms, i.e. *on* a clock
  > edge, so whether the 2 ms edge counts is a race. Releasing reset between
  > two edges would make it deterministic without weakening what it asserts.

---

## Open

### N4 — generated models do not declare `cm_irreversible()` (MEDIUM, structural)

**This is the remaining gap between "correct" and "trustworthy under all
conditions", and it is a good self-contained project.**

#### The problem

XSPICE assumes a code model's entire state lives in its `cm_event_alloc`
blocks, so that `EVTbackup` (`tools/nghdl/src/xspice/evt/evtbackup.c`) can
restore it when ngspice **rejects a timestep** — non-convergence, a timestep
cut, an LTE failure. A NgVeri model breaks that assumption: its real state is
inside the Verilator object, which ngspice cannot roll back. `EVTload` calls
the model on every event, including events in timesteps that are later thrown
away, and each call runs `eval()`.

Net effect: on any rejected timestep the digital design has **silently
advanced further than the analog solution did**. Registers clocked that should
not have; counters over-counted.

This has not been caught producing a wrong waveform in the runs examined so
far — the counter and signal-statistics benchmarks both converge cleanly — so
it is a latent hazard, not a reproduced failure. It becomes reachable as soon
as a schematic has analog content that makes ngspice retry timesteps, which is
the normal case for real mixed-signal work.

#### The mechanism ngspice provides

`cm_irreversible(place)` (`tools/nghdl/src/xspice/cm/cm.c:749`) marks an
instance as holding external state. ngspice then calls it with
`CALL_TYPE == MIF_STEP_PENDING` once per **accepted** timestep, in addition to
ordinary `MIF_EVENT_DRIVEN` calls (`evtload.c:152`, `evtcall_hybrids.c`).

The reference implementation is already in the tree:
`tools/nghdl/src/xspice/icm/digital/d_cosim/cfunc.mod` — it declares
`cm_irreversible(PARAM(irreversible))` in its INIT branch (`irreversible`
defaults to 1 in its `ifspec.ifs`), records inputs into its
`cm_event_get_ptr(0,0)` block on `EVENT` calls, and only advances the
co-simulator inside the `STEP_PENDING` branch, replaying the queued inputs.

#### What would need to change

1. `ifspec.ifs` gains an `irreversible` parameter (default 1), matching
   d_cosim's.
2. `cfunc.mod`'s INIT branch calls `cm_irreversible()`.
3. `cfunc.mod` splits: on an `EVENT` call, latch the inputs into the tag-0
   storage and set `OUTPUT_CHANGED = FALSE` on every output; on a
   `STEP_PENDING` call, push the latched inputs into Verilator, run `eval()`,
   and schedule the outputs. `foo_<stem>()` correspondingly separates "set
   inputs" from "eval and read outputs" instead of doing both per call.
4. Decide what `TIME == 0.0` should do (d_cosim treats it as an
   inputs-still-settling pass and drives nothing).

#### Why it is not done here

It changes *when* the model is called, not just what it computes, so it needs
bench time across a range of schematics rather than a unit test — exactly the
kind of change that should not ride along with a silent-correctness fix. It is
also core NgVeri behaviour inherited from 2.5, which this branch does not
change on its own judgement: [`UPSTREAM_DECISIONS.md`](UPSTREAM_DECISIONS.md)
item 4.

**d_cosim does not have this defect** — its code model already declares
`cm_irreversible`. That is the one place the new backend is better than the old
one, and it is better by not having a bug rather than by anything eSim changed.

#### How to verify it

The failure it fixes only appears when ngspice rejects timesteps, so a
benchmark must **force** that: put the digital block behind analog content with
a hard-to-converge node (a sharp-kneed diode, a tight `reltol`, a stiff RC), and
compare the digital output against the same design run with a tiny fixed
`.tran` step where no rejection occurs. They must match. A `cnt_val` that runs
slightly fast under the coarse run is the bug.

### ~~Shared model name and build directory between the two backends~~ (fixed)

The two backends used to build into one directory per model name,
`<DIGITAL_MODEL>/Ngveri/<model>/`, so removing a d_cosim model deleted the
Verilator backend's `ifspec.ifs`/`cfunc.mod` for a model of the same name --
while leaving its compiled `.o` in the release tree, so ngspice kept answering
for a model whose sources were gone.

d_cosim now builds into a **sibling** tree, `<DIGITAL_MODEL>/NgVeriCosim/`; the
legacy layout is untouched. Neither teardown can reach the other's tree, so the
isolation is structural rather than a guard that has to be right every time --
which matters because on Windows the filesystem compares names
case-insensitively while every guard in Python compares them exactly. See
`CosimConfig.cosim_build_root` and `src/maker/tests/test_backend_isolation.py`.

A vvp built before the split still simulates (`cosim_vvp_path` falls back to
the old location) and is migrated out of the legacy directory before any NgVeri
teardown deletes it.

---

## Verifying a fix in this area

The generators are pure text writers, so unit tests catch a lot (see
`src/maker/tests/`), but the failure mode of this whole subsystem is *a model
that builds and runs and is wrong*. A change here should also be taken through
a real build:

1. Generate + Verilate + `make` the model (`ModelGeneration.verilogfile` ..
   `copy_verilator`).
2. Rebuild the code-model library and install it (`runMake`,
   `runMakeInstall`) — the fix does not reach an existing `Ngveri.cm` otherwise.
3. Simulate a design whose expected waveform is known **on a non-first output
   port**. A single-output model proves nothing: port 0 was always correct.
4. Measure, do not eyeball. Duty cycle and edge times; a frozen pin and a
   legitimately static one look identical in a waveform viewer.
