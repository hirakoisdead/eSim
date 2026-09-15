# Things we found, measured, and deliberately did not change

**For the eSim maintainers.** Every item below is a place where eSim's existing
behaviour is measurably wrong, where we have a fix that works, and where we have
**left the fix switched off** because applying it would change results eSim has
produced since 2.5 — on schematics users already consider working.

The rule we followed while adding the d_cosim (Icarus) backend:

> The core converter and the NgVeri (Verilator) backend behave exactly as they
> did in eSim 2.5. Where 2.5 is wrong, we measure it, write it down, and leave
> it alone. d_cosim is new, so it is ours to get right — but "right" for
> d_cosim means *matching NgVeri as 2.5 behaved*, bug for bug, so that swapping
> backends never changes a number.

So this branch adds a backend and fixes that backend. It does not quietly
improve the simulator underneath it. Those calls are yours.

Each item says what is wrong, how we know, what the fix is, where the switched-
off code lives, and what turning it on would change. Full measurements are in
`NGVERI_ACCURACY.md`.

---

## 1. `adc_bridge`'s unknown band reaches the digital side as an `x`

**What is wrong.** XSPICE's `adc_bridge` is a *three*-state converter: below
`in_low` it emits 0, above `in_high` it emits 1, and **between them it emits
x**. eSim's default band is `in_low=1.0 / in_high=2.0`, so a clock ramping
0→5 V crosses the digital node in two steps, not one:

```
  0.000321 ms   0 -> x        (crossed in_low going up)
  0.000448 ms   x -> 1        (crossed in_high)
  0.501701 ms   1 -> x
  0.501828 ms   x -> 0
```

Four events per period. What each backend does with that `x` differs, and
neither answer is right:

* **NgVeri (Verilator) and NGHDL (GHDL)** read it as a confident logic **1**.
  Their generated C is literally `if (INPUT_STATE(port) == ZERO) 0; else 1;` —
  anything that is not a definite 0 is a 1. So an input genuinely sitting at
  1.2 V, which is *inside* the band and *below* its midpoint, arrives as a 1.
  Measured on the already-built `universal_counter_8bit`: holding `lden` at
  1.2 V loads 250 forever instead of counting.
* **Icarus** sees the `x` for what it is, and IEEE 1364 makes `0→x` and `x→1`
  *both* posedges — so the design is clocked twice per analog edge.

**How we know.** A probe design with one counter per edge sensitivity:

| counter | observed | a doubled clock would give |
|---|---|---|
| `always @(posedge clk)` | **+2** per period | +2 |
| `always @(negedge clk)` | **+2** per period | +2 |
| `always @(clk)` | **+4** per period | +2 |

The `+4` rules out every clock-doubling explanation.

**The fix we did not apply.** `collapse_adc_band_for_hdl()` in
`src/kicadtoNgspice/KicadtoNgspice.py` rewrites `in_low`/`in_high` to their
midpoint for any `adc_bridge` feeding an HDL block, at netlist-generation time.
It is fully implemented and tested — including an end-to-end test that runs
ngspice and shows the counter going right
(`test_dcosim_simulation.py::test_collapsed_band_advances_once_per_clock`). It
is simply **never called**. The call site in `createNetlistFile` is a comment
pointing here.

**Why we stopped.** `in_low`/`in_high` describe a *static* datasheet guarantee
("≤1 V is low, ≥2 V is high, in between is unspecified"). A real logic input
has one switching threshold, and applying a 1 V-wide indeterminate band to a
ramping clock is the modelling error. We believe the midpoint is the right
default. But it is a value eSim has emitted unchanged since 2.5, and changing
it moves the numbers for any design with a slowly-moving or genuinely analog
input in the 1.0–2.0 V range. That is a maintainer's call.

**What turning it on would change.** Nothing for a pure digital design — we
measured the counter sequence as byte-identical before and after, with only
sub-microsecond movement in edge timestamps. For an analog input inside the
band, results change, and they change towards correct.

**What we did instead.** d_cosim reads `x` as 1 in its own generated wrapper,
exactly as NgVeri's C does (`ModelGeneration.cosim_wrapper_source`). That kills
the double-clocking, makes d_cosim agree with NgVeri edge-for-edge, and touches
no netlist. It also means **d_cosim inherits this defect on purpose**: it too
reads 1.2 V as a 1. Deliberately, so the two backends never disagree.

---

## 2. NgVeri accepts `inout` ports and is silently wrong on every port

**What is wrong.** `getPortInfo()` files an `inout` under the *inputs*, because
that is all the legacy flow can drive. The ifspec then declares it
`Direction: in`, the driven half of the pin never reaches ngspice, and the port
indices shift by the width of the inout — so **every** port is wrong, not just
the bidirectional one. Measured on a probe module whose only `inout` is driven
by the design: a sibling output declared `assign q = 1'b1;` toggled with the
clock.

**The fix we did not apply.** `ModelGeneration.validate_ports()` rejects it by
name, before any C is generated. Implemented, tested, **not called** from
`NgVeri.addverilog()`.

**Why we stopped.** eSim 2.5 built these models. Refusing a build that used to
succeed takes away something the user could do before, even though what they
got was wrong. We were also asked not to introduce warnings: 2.5 was silent,
and a new warning on an old design reads as "the software broke".

**What turning it on would change.** No numbers move. Some builds that
previously produced a silently-wrong model would stop with a named error.

*(d_cosim refuses `inout` outright. That is our own new backend, on a path no
2.5 design can be using, so we set the rule there.)*

---

## 3. NgVeri accepts ports wider than 64 bits and truncates them

**What is wrong.** Verilator represents a port up to 64 bits as
`CData`/`SData`/`IData`/`QData` — plain unsigned integers. Past 64 it becomes
`VlWide`, an array of `uint32_t`, which no integer conversion can carry. The
generated C++ either fails to compile with an unreadable template error or
silently truncates.

**The fix we did not apply.** The same `validate_ports()`, same reason.

**Related, and this one we DID fix**, because it cannot change any result that
was ever well-defined: the generated `int2arr`/`arr2int` converters took a
signed `int`. A 32-bit output with its top bit set arrived negative, the
`num>=0` loop guard failed on iteration 0, the body never ran, and the port kept
the **previous timestep's** bits — frozen across its whole upper range, in
silence. `arr2int`'s `k = 2*k + array[i]` over 32 bits was signed overflow,
i.e. undefined behaviour. Both now work on `uint64_t` and extract bits, which is
**bit-identical to the old code for every width under 32** and defined above it.
Nothing that previously had an answer gets a different one.

---

## 4. Generated NgVeri models do not declare `cm_irreversible()`

**What is wrong.** XSPICE assumes a code model's entire state lives in its
`cm_event_alloc` blocks, so `EVTbackup` can restore it when ngspice **rejects a
timestep** (non-convergence, timestep cut, LTE failure). A NgVeri model breaks
that assumption: its real state is inside the Verilator object, which ngspice
cannot roll back. `EVTload` calls the model on every event, including events in
timesteps that are later thrown away, and each call runs `eval()`.

So on a rejected timestep the digital design has **silently advanced further
than the analog solution did**. Registers clocked that should not have been;
counters over-counted.

**Status: open, and not attempted here.** It has not been caught producing a
wrong waveform in the runs we examined — the counter and signal-statistics
benchmarks both converge cleanly — so it is a latent hazard rather than a
reproduced failure. It becomes reachable as soon as a schematic has analog
content that makes ngspice retry timesteps, which is normal for real
mixed-signal work.

**Why we did not touch it.** It changes *when* the model is called, not just
what it computes, so it needs bench time across a range of schematics rather
than a unit test. The reference implementation is already in the tree:
`tools/nghdl/src/xspice/icm/digital/d_cosim/cfunc.mod` declares
`cm_irreversible(PARAM(irreversible))` and only advances the co-simulator in its
`MIF_STEP_PENDING` branch. `NGVERI_ACCURACY.md` §N4 has the four-step change and
a benchmark design that would force the rejection.

**Note:** d_cosim does **not** have this defect — its code model already
declares `cm_irreversible`. That is the one place the new backend is better than
the old one, and it is better by not having a bug, not by us changing anything.

---

## ~~5. Both backends share one model name and build directory~~ — FIXED

*This one moved out of the parked list. It was parked on the belief that the
fix would strand models users had already built; that is true of the legacy
NgVeri tree, but d_cosim has never shipped, so **only the new backend's tree
had to move** and nothing users own is affected.*

**What was wrong.** Both backends built into one directory per model name,
`<DIGITAL_MODEL>/Ngveri/<model>/`. Removing a d_cosim model rmtree'd that
directory, taking the Verilator backend's `ifspec.ifs` and `cfunc.mod` with it,
while leaving the compiled `.o` in `<release>/src/xspice/icm/Ngveri/<model>/` —
so the NgVeri model looked deleted and kept answering in ngspice. The reverse
removal destroyed the d_cosim vvp the same way.

Guarding a shared directory cannot be made airtight: on Windows the filesystem
compares names case-insensitively while every guard compares them exactly, so
`_legacy_registered("counter")` answered False about a `Counter/` tree that
`shutil.rmtree` then deleted, and `os.path.isfile(NgVeriCosim/Counter.xml)`
answered True for `counter.xml` — handing a row the dialog had badged **NgVeri**
to the **d_cosim** dismantler.

**What we changed.** d_cosim builds into a sibling tree,
`<DIGITAL_MODEL>/NgVeriCosim/<model>/` (`CosimConfig.cosim_build_root`). The
legacy layout, its `modpath.lst` and the `Ngveri.cm` rebuild are untouched — an
eSim 2.5 NgVeri model still builds, registers and simulates from exactly where
it always did. What changed is only that the d_cosim teardown no longer has a
path into it, and no longer needs to rewrite `modpath.lst` to clean up after
itself.

Three supporting fixes, all confined to identity resolution:

- `_resolve_backend` and the switch guards list the directory instead of
  calling `os.path.isfile`, so Windows and Linux answer the same.
- `_legacy_registered` counts every trace (build dir, param XML, release dir),
  not just the `modpath.lst` line. A ghost line is pruned while the files stay,
  so the line alone let a d_cosim build start on top of a live NgVeri model.
- A legacy teardown resolves the directory by its actual on-disk name, so a
  case mismatch is not a silent no-op on Linux.

**Migration.** A vvp built before the split still simulates —
`cosim_vvp_path` falls back to the old location — and is moved into the d_cosim
tree before any NgVeri teardown can delete it, provided the model is still live
(its `NgVeriCosim/<name>.xml` exists).

**Evidence.** `src/maker/tests/test_backend_isolation.py` (29 tests): each
teardown leaves the other backend's build byte-for-byte intact, neither leaves
a half-removed model, blank and traversing names delete nothing, and the
listing ends empty with both trees and the release tree clean.

---

## What we did change, and why each one is safe

For completeness, so the parked items above can be judged against the rest:

| Change | Where | Why it cannot make anything worse |
|---|---|---|
| `cm_event_get_ptr(tag,0)/(tag,1)` | NgVeri + NGHDL generators | **Restores** 2.5's output. The same buggy loop shipped in 2.5, where ngspice 35 kept a full state history and the out-of-range timepoint landed harmlessly; ngspice 45 recycles state and made it live. Without this, every output port after the first freezes after one transition. |
| `uint64_t` converters | NgVeri generator | Bit-identical below 32 bits; above that the old code was undefined. |
| x-as-1 wrapper | d_cosim only | New backend, and it makes d_cosim match NgVeri. |
| One engine for N blocks | d_cosim only | Replaces a segfault. |
| `timescale` sharpening | d_cosim only | Replaces a run that completes with every output stuck at 0. |
| `-y/-I/-Y` for iverilog | d_cosim only | Replaces "Unknown module type" on any multi-file design. |
| `inout` refused | d_cosim only | Replaces a silently corrupted netlist. |

Everything in the "d_cosim only" rows is on a path no eSim 2.5 schematic can
reach, because d_cosim did not exist.

---

## If you want to evaluate a parked fix

Items 1–3 are one line each:

* **Item 1** — in `KicadtoNgspice.createNetlistFile`, call
  `collapse_adc_band_for_hdl(store_schematicInfo, hdl_cards)` where the comment
  says so.
* **Items 2 and 3** — in `NgVeri.addverilog`, call `model.validate_ports()`
  after `model.getPortInfo()` and stop on a non-`None` result.

Both have tests that already pass with the code switched off, so turning either
on is a decision, not a development task.
