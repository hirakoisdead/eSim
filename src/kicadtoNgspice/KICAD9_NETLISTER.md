# KiCad-9 → ngspice Netlister — Developer Guide

> **Current status: 150/150 golden tests pass** across four test phases covering
> eSim examples, subcircuit ICs, student projects, and ngveri/Digital-Verilog IPs.

This document is the canonical reference for `KicadNetlister.py` — the component
that converts a KiCad schematic into a SPICE netlist (`.cir`) that eSim can
simulate. It explains **why** it exists, **how** it works line by line, and **how**
to test and extend it. Future developers and contributors should be able to read
this and have a complete mental model of the entire system.

---

## Table of Contents

1. [What Is the Netlister?](#1-what-is-the-netlister)
2. [Why It Exists — The KiCad ≥7 Break](#2-why-it-exists--the-kicad-7-break)
3. [The Pipeline: `.kicad_sch` → `.cir`](#3-the-pipeline-kicad_sch--cir)
4. [Code Walkthrough: `KicadNetlister.py`](#4-code-walkthrough-kicadnetlisterpy)
   - 4.1 [Entry Point: `generate_netlist()`](#41-entry-point-generate_netlist)
   - 4.2 [Main Translation: `xml_to_spice_lines()`](#42-main-translation-xml_to_spice_lines)
   - 4.3 [Net Name Sanitization: `_sanitize_net()`](#43-net-name-sanitization-_sanitize_net)
   - 4.4 [Collision-Safe Net Naming](#44-collision-safe-net-naming)
   - 4.5 [Pin Ordering](#45-pin-ordering)
   - 4.6 [Dropping Components: `Spice_Netlist_Enabled`](#46-dropping-components-spice_netlist_enabled)
   - 4.7 [Subcircuit X-Prefix: `_is_subcircuit_value()`](#47-subcircuit-x-prefix-_is_subcircuit_value)
   - 4.8 [Model Detection: `_is_model_value()`](#48-model-detection-_is_model_value)
   - 4.9 [KiCad 6 Compatibility: `Sim.Device` / `Sim.Params`](#49-kicad-6-compatibility-simdevice--simparams)
5. [The Output Format: What a `.cir` Looks Like](#5-the-output-format-what-a-cir-looks-like)
6. [The Test Harness](#6-the-test-harness)
   - 6.1 [Golden Tests](#61-golden-tests)
   - 6.2 [Unit Tests](#62-unit-tests)
   - 6.3 [Topology Equivalence: `netlist_compare.py`](#63-topology-equivalence-netlist_comparepy)
   - 6.4 [Running the Tests](#64-running-the-tests)
7. [How to Add a New Golden Fixture](#7-how-to-add-a-new-golden-fixture)
8. [Known Gaps and Edge Cases](#8-known-gaps-and-edge-cases)
9. [Validation History — What We Ran](#9-validation-history--what-we-ran)
10. [Local Artifacts](#10-local-artifacts)

---

## 1. What Is the Netlister?

The **netlister** is the bridge between a KiCad schematic and an ngspice simulation.

When a user draws a circuit in eSim's schematic editor (KiCad) and clicks
**Convert KiCad to Ngspice**, the netlister runs. It reads the `.kicad_sch` file,
extracts every component and every wire connection, and writes a `.cir` file — a
flat SPICE netlist that ngspice can simulate.

**File:** `src/kicadtoNgspice/KicadNetlister.py`
**Called from:** `src/projManagement/Kicad.py` → `generate_netlist(proj_dir, proj_name)`
**Input:** `<project>/<name>.kicad_sch` (KiCad schematic, version ≥7)
**Output:** `<project>/<name>.cir` (flat SPICE netlist)

The `.cir` is not the final simulation input — eSim's GUI adds source waveforms,
device models, and analysis commands on top. But if the netlister gets the
component connectivity wrong, every downstream step produces wrong results.
That is why it is held to a strict test.

---

## 2. Why It Exists — The KiCad ≥7 Break

### The old approach

Before KiCad 7, eSim used:

```
kicad-cli sch export netlist --format spice -o <name>.net <name>.kicad_sch
```

This produced a usable SPICE netlist directly. It worked fine through KiCad 5 and 6.

### What broke in KiCad 7

KiCad 7 rewrote its SPICE exporter around a new **Simulation Model** system.
Every component now needs a `Sim.Device` / `Sim.Type` / `Sim.Params` property
to be exported with connectivity. Without those properties, KiCad emits:

```
U2 __U2
v3 __v3
```

One placeholder node, no actual nets. The connectivity is gone and cannot be recovered.

**Every eSim symbol lacks these properties.** The entire eSim library — plots,
behavioural blocks (`adc_bridge`, `dac_bridge`, `d_xor`, `d_dff`, …),
voltage/current sources, custom subcircuits — uses the old `Spice_*` field
convention, not `Sim.*`. So `--format spice` on KiCad ≥7 produces a useless
netlist for any eSim schematic.

### The solution: `--format kicadxml`

KiCad has a second export format, `kicadxml`, which is the generic netlist used
by PCB layout tools and other third-party tools. Unlike the SPICE exporter, it
always lists:

- every component, regardless of simulation properties
- every net by name
- every pin-to-net mapping

It never strips connectivity. `KicadNetlister.py` uses this format and then
rewrites the XML into the flat SPICE form eSim expects. This is entirely
independent of KiCad's simulation model system and works on KiCad 7, 8, 9, and 10.

---

## 3. The Pipeline: `.kicad_sch` → `.cir`

Here is the full flow from schematic to simulator:

```
 ┌────────────────────────────────────────────────┐
 │  User draws circuit in KiCad (eSim schematic   │
 │  editor). Saves as <name>.kicad_sch            │
 └───────────────────────┬────────────────────────┘
                         │
                         ▼
 ┌────────────────────────────────────────────────┐
 │  kicad-cli sch export netlist                  │
 │    --format kicadxml                           │
 │    -o <name>.netlist.xml                       │
 │    <name>.kicad_sch                            │
 │                                                │
 │  Produces generic XML: all comps, all nets,    │
 │  all pin→net mappings. No SPICE knowledge.     │
 └───────────────────────┬────────────────────────┘
                         │
                         ▼
 ┌────────────────────────────────────────────────┐
 │  xml_to_spice_lines()  in KicadNetlister.py    │
 │                                                │
 │  1. Parse XML: collect refs, values, fields    │
 │  2. Build net name table (sanitize + dedupe)   │
 │  3. Build pin→net map, sorted by pin number    │
 │  4. For each component (in document order):    │
 │     a. Skip if Spice_Netlist_Enabled=N         │
 │     b. Apply Spice_Node_Sequence if present    │
 │     c. Detect subcircuit → prepend X           │
 │     d. Detect KiCad-6 Sim.Device=SPICE → X    │
 │     e. Emit: <ref> <net1> <net2> ... <value>   │
 └───────────────────────┬────────────────────────┘
                         │
                         ▼
 ┌────────────────────────────────────────────────┐
 │  Written to <name>.cir                         │
 │                                                │
 │  * Title line                                  │
 │  * One line per component                      │
 │  * .end                                        │
 └───────────────────────┬────────────────────────┘
                         │
                         ▼
 ┌────────────────────────────────────────────────┐
 │  eSim GUI (kicadtoNgspice/Processing.py)       │
 │  adds: source waveforms, device models,        │
 │  .tran/.dc/.ac analysis, .include paths        │
 └───────────────────────┬────────────────────────┘
                         │
                         ▼
 ┌────────────────────────────────────────────────┐
 │  ngspice runs the completed netlist            │
 └────────────────────────────────────────────────┘
```

The `<name>.netlist.xml` is a temporary file. It is deleted at the end of
`generate_netlist()` whether or not the conversion succeeded.

---

## 4. Code Walkthrough: `KicadNetlister.py`

### 4.1 Entry Point: `generate_netlist()`

```python
def generate_netlist(proj_dir, proj_name):
```

This is the only function called externally (from `Kicad.py`). It:

1. Checks that `<proj_name>.kicad_sch` exists in `proj_dir`.
2. Locates `kicad-cli` via `shutil.which` or the `$ESIM_KICAD_CLI` env override
   (useful for flatpak/appimage installs where the binary is not on PATH).
3. Runs `kicad-cli sch export netlist --format kicadxml` to produce the XML.
4. Calls `xml_to_spice_lines()` on that XML.
5. Writes the result to `<proj_name>.cir`.
6. Deletes the temporary XML in the `finally` block.
7. Returns `(ok: bool, message: str)` — the call site in `Kicad.py` shows the
   message to the user.

**Critical safety note:** `generate_netlist()` overwrites the `.cir`. Never call
it in-place against a golden fixture. The test harness always copies the
`.kicad_sch` to a scratch directory first.

If `kicad-cli` is absent or the export fails, the function returns `(False, message)`
and leaves any existing `.cir` untouched, so the legacy/manual workflow still
applies on installations without KiCad ≥7.

---

### 4.2 Main Translation: `xml_to_spice_lines()`

```python
def xml_to_spice_lines(xml_path, title="KiCad schematic", proj_dir=None):
```

This is the brain of the netlister. It returns a list of strings — the SPICE
lines that will be joined and written to `.cir`. Here is the step-by-step logic.

**Step 1 — Parse components.**

```xml
<components>
  <comp ref="R1">
    <value>10k</value>
    <fields>
      <field name="Spice_Node_Sequence">1,0</field>
    </fields>
  </comp>
  ...
</components>
```

For each `<comp>`: collect the `ref` (e.g. `R1`), its `value` (e.g. `10k`), and
all `<field>` entries into a dict. Field name keys are **lowercased** so that
`Spice_Node_Sequence`, `spice_node_sequence`, and `SPICE_NODE_SEQUENCE` all
resolve to the same lookup — KiCad lets users type field names in any case.

**Step 2 — Build the net name table.**

```xml
<nets>
  <net code="1" name="GND">...</net>
  <net code="2" name="Net-(R1-Pad1)">...</net>
</nets>
```

Every net gets a sanitized, ngspice-safe name (see §4.3). Two nets that would
sanitize to the same string get disambiguated with their `code` (see §4.4).
This produces a `net_name` mapping from each `<net>` element to its final
safe string.

**Step 3 — Build the pin→net map.**

```xml
<nets>
  <net code="2" name="Net-(R1-Pad1)">
    <node ref="R1" pin="1"/>
    <node ref="C1" pin="2"/>
  </net>
</nets>
```

For each net, for each `<node>`: record `(ref, pin, net_name)`. Pins are then
sorted per component by `_node_sort_key()` (numeric pin numbers ascending,
non-numeric last) to produce the default node order for the SPICE line.

**Step 4 — Emit one line per component.**

Iterate through `order_refs` (the document order from `<components>`). For each:

```
<ref_out>  <net1> <net2> ... <netN>  <value>
```

Where `ref_out` is `ref.lower()`, possibly with `x` prepended (§4.7 / §4.9),
and the nets are joined with spaces. Lines that would have no nets are still
emitted (single-pin symbols like plot markers fall here).

---

### 4.3 Net Name Sanitization: `_sanitize_net()`

```python
def _sanitize_net(name):
    safe = ''.join(c if (c.isalnum() or c == '_') else '_'
                   for c in name.strip().lower())
    return safe.strip('_')
```

**The problem:** KiCad auto-generates net names from pin names and sheet paths.
These often contain characters like `+`, `-`, `/`, `(`, `)`. For example:

- `Net-(v1-+)` — from a voltage source's positive pin
- `Net-(R3-Pad2)/Net-(C1-Pad1)` — from a hierarchical path

In ngspice, `+`, `-`, `/` are **arithmetic operators** inside `v()` and `i()`
vector references. A node named `net-(v1-+)` can be simulated, but ngspice
cannot parse `v(net-(v1-+))` in a plot command — it sees subtraction and
parentheses, not a node name.

The fix: map every character that is not `[a-z0-9_]` to `_`. User-named nets
(`gnd`, `vout`, `vin`, `c_out`) contain none of these characters and pass
through unchanged. Auto-named internal nets become safe but unpronounceable
strings like `net__v1__`. Since eSim's default control script uses `print allv`
(all voltages at once) rather than naming individual nodes, this is rarely
visible to users.

The function returns `''` for a name with no usable characters. The caller
(§4.4) falls back to a code-based name in that case.

---

### 4.4 Collision-Safe Net Naming

Sanitization can make two distinct nets look identical. For example:

- `Net-(R1+)` → sanitizes to `net__r1_`
- `Net-(R1-)` → sanitizes to `net__r1_`

These are two different nodes in the circuit. If both get the same name, they
are silently shorted together — a catastrophic netlisting error.

The code uses a `used` set and appends the net's unique `code` on collision:

```python
if safe in used:
    safe = safe + '_' + code
used.add(safe)
```

KiCad guarantees that `code` values are unique within a netlist, so the
disambiguated names are always unique. This is explicitly tested by the unit tests.

---

### 4.5 Pin Ordering

SPICE netlisting is **order-sensitive**. The second token on an NPN transistor
line is the collector; the third is the base; the fourth is the emitter. Getting
this wrong silently produces a different circuit that simulates plausibly but
incorrectly.

**Default order: `_node_sort_key()`**

```python
def _node_sort_key(pin, seen_index):
    if pin.isdigit():
        return (0, int(pin), seen_index)
    return (1, 0, seen_index)
```

Numeric pin numbers sort ascending (pin 1, pin 2, pin 3 …). Non-numeric or
blank pins come last in encounter order.

eSim symbols are designed with this in mind: **they number their pins in SPICE
node order**. Pin 1 = first SPICE terminal, pin 2 = second, and so on. So for
an NPN transistor (`Q`), pin 1 = collector, pin 2 = base, pin 3 = emitter —
exactly the SPICE `Q` element order. For an 8-pin opamp subcircuit, pin 1
through pin 8 map directly to the subcircuit's node list.

**Override: `Spice_Node_Sequence`**

When a symbol needs a different SPICE order than its physical pin numbering, it
carries a `Spice_Node_Sequence` field: a comma- or space-separated list of
0-based indices.

```
Spice_Node_Sequence = 2,1,0
```

This reorders the already-sorted node list. For a 3-pin component with default
order `[net_a, net_b, net_c]`, the sequence `2,1,0` produces
`[net_c, net_b, net_a]`.

`_apply_node_sequence()` validates that the sequence is a permutation of
`range(len(nodes))` before applying it. A malformed field is silently ignored,
preserving the default order.

---

### 4.6 Dropping Components: `Spice_Netlist_Enabled`

Some eSim symbols are drawing aids — plot markers, current probes, annotation
symbols — that should appear in the schematic but not in the netlist. They carry:

```
Spice_Netlist_Enabled = N
```

The netlister drops any component whose `Spice_Netlist_Enabled` field (looked
up case-insensitively) is in the set `{'n', 'no', 'false', '0'}`. All other
components — including those with no such field — are emitted normally.

---

### 4.7 Subcircuit X-Prefix: `_is_subcircuit_value()`

**The rule in SPICE:** a subcircuit instantiation line must start with `X`.
ngspice identifies element type purely by the first character of the line:
`R` = resistor, `Q` = BJT, `X` = subcircuit call, etc.

**The problem in eSim:** students commonly use `U1`, `U2`, etc. as reference
designators for opamp subcircuits (e.g. value `lm_741`). In the KiCad schematic
they write `U1`, but the SPICE line must be `xu1 <nets> lm_741`, not
`u1 <nets> lm_741`. Without the `X`, ngspice does not recognize it as a
subcircuit and the simulation fails. The eSim SubcircuitTab also misses it —
it detects subcircuit lines solely by checking `line[0] == 'x'`.

The original 52 bundled eSim examples used `X1`, `X2` refs consistently. Student
schematics from real projects used `U1`, `U2` for the same components, exposing
the gap.

**The fix:**

```python
def _is_subcircuit_value(value, proj_dir):
    if os.path.isfile(os.path.join(proj_dir, value + '.sub')):
        return True
    lib = _esim_subckt_lib()
    if lib and os.path.isfile(os.path.join(lib, value, value + '.sub')):
        return True
    return False
```

Before emitting a component line, if the ref does not already start with `x`
and the component's value has a matching `.sub` file — either in the project
directory or in `library/SubcircuitLibrary/<value>/<value>.sub` — an `x` is
prepended to the reference.

**What this does NOT affect:**

- Components with a `U` ref where the value is an eSim behavioural model
  (`plot_v1`, `PORT`, `adc_bridge_1`, `d_dff`, `d_xor`, …). These have no
  `.sub` file, so `_is_subcircuit_value()` returns `False` and the `u` prefix
  is kept. Behavioural blocks use the `U` element type in the eSim processing
  pipeline, not `X`.

- Components where the value is a registered eSim model XML (§4.8). Model XML
  wins over `.sub`: a stray `half_adder.sub` in the project directory must not
  demote the compiled ngveri block to a plain subcircuit call.

---

### 4.8 Model Detection: `_is_model_value()`

```python
def _is_model_value(value):
    root = _modelparam_dir()          # library/modelParamXML/
    target = value + '.xml'
    for _dirpath, _dirs, files in os.walk(root):
        if target in files:
            return True
    return False
```

eSim has three categories of compiled/behavioural models, all stored under
`library/modelParamXML/`:

| Subfolder | Contents | Processing step |
|---|---|---|
| `modelParamXML/` (root) | Built-in XSPICE primitives (`adc_bridge_N`, `dac_bridge_N`, `d_xor`, etc.) | Model tab |
| `modelParamXML/Ngveri/` | Verilog models compiled via ngveri/Makerchip | Ngspice Model tab |
| `modelParamXML/Nghdl/` | VHDL models compiled via nghdl/GHDL | Microcontroller tab |

All three use a `U` prefix in schematics. `_is_model_value()` walks the entire
tree with `os.walk` to catch all three namespaces in one check.

If a value matches a model XML, the `U` prefix is preserved and the subcircuit
`.sub` check is skipped. This is the "model XML wins" rule that prevents a stray
`.sub` file in the project directory from incorrectly overriding a compiled model.

---

### 4.9 KiCad 6 Compatibility: `Sim.Device` / `Sim.Params`

KiCad 6 introduced a partial migration toward `Sim.*` fields. When a KiCad 6
schematic that contains `Spice_Primitive=X` fields (used by ngveri/subcircuit
blocks to mark them as SPICE subcircuit calls) is opened and re-saved by KiCad 9,
that field is converted to:

```
Sim.Device = SPICE
Sim.Params = type="X" model="<value>"
```

The `.sub` file search (§4.7) misses these cases because the `.sub` file lives
in the IP library, not copied into the project directory.

The fix detects this pattern directly:

```python
_sd = fd.get('sim.device', '').lower()
_sp = fd.get('sim.params', '').lower()
if _sd == 'spice' and ('type="x"' in _sp or "type='x'" in _sp):
    ref_out = 'x' + ref_out
```

This applies only when the ref doesn't already start with `x` and the value is
not a registered model (§4.8). It covers all ngveri IP blocks and any subcircuit
whose schematic originated in KiCad 6 and was upgraded to KiCad 9 format.

---

## 5. The Output Format: What a `.cir` Looks Like

A minimal example — an RC low-pass filter:

```spice
* RC (eSim netlist via kicad-cli kicadxml)
* Sheet Name: /
r1 vin vout 10k
c1 vout gnd 1u
v1 vin gnd
.end
```

Rules:
- First line: `* <title> (eSim netlist via kicad-cli kicadxml)`
- Second line: `* Sheet Name: /`
- One line per component (excluding disabled ones)
- Format: `<ref> <net1> <net2> ... <netN> <value>`
- All lowercase (ngspice is case-insensitive; eSim's GUI parses lowercase)
- Last line: `.end`

The `.cir` produced here is intentionally minimal. eSim's `Processing.py` reads
it and adds the real source parameters, model `.include` paths, and analysis
commands before running ngspice. This separation keeps the netlister's job clean:
**just topology, nothing else**.

**What the `.cir` does NOT contain at this stage:**

- Source waveforms (`.tran`, `.dc`, `.ac`)
- Device model includes (`.include <name>.lib`)
- Actual voltage/current waveform parameters (amplitude, frequency, offset)

Those are added by the eSim GUI from `<proj>_Previous_Values.xml` after the user
fills in the source and analysis parameters through the eSim tabs.

**Cosmetic differences from legacy `.cir` that are harmless:**

- Net-name spelling (ngspice is case-insensitive; the netlister explicitly
  normalizes KiCad `GND` and eSim's `eSim_GND` power symbol to SPICE node `0`)
- Component order in the file (ngspice is order-independent)
- Unconnected pins: legacy lumps all as `?`; KiCad-9 emits distinct
  `unconnected-*` nodes — each is a distinct floating node, simulates the same
- Model/value spelling (`eSim_NJF` vs `NJF`): resolved by the eSim DeviceModel
  GUI step downstream

---

## 6. The Test Harness

All tests live in `src/kicadtoNgspice/tests/`.

```
tests/
    test_netlister_golden.py   — one test per fixture in golden/
    test_netlister_unit.py     — pure-function tests (no kicad-cli)
    netlist_compare.py         — topology equivalence logic
    golden/                    — 150 fixture pairs (.kicad_sch + .cir)
        RC/
            RC.kicad_sch
            RC.cir
        FET_Characteristic/
            ...
```

### 6.1 Golden Tests

**File:** `test_netlister_golden.py`

For each fixture under `tests/golden/<example>/`:

1. Copy `<example>.kicad_sch` to a temporary scratch directory.
2. Call `generate_netlist(scratch_dir, example)` to produce a fresh `.cir`.
3. Compare the generated `.cir` against the legacy ground-truth `.cir` using
   `netlist_compare.compare()`.
4. Assert `equivalent: True`.

The scratch copy prevents the golden `.cir` from ever being overwritten.
The test is parameterized: one pytest test case per fixture. A single failure
is immediately visible by name — no hunting through output.

**Ground truth:** the legacy `.cir` that shipped with each eSim example,
produced by the old KiCad-5/6 flow, known to simulate correctly. These are
checked in alongside the `.kicad_sch` fixtures and must **never** be edited.

### 6.2 Unit Tests

**File:** `test_netlister_unit.py`

Seven pure-function tests that do not need `kicad-cli`. They test the
lower-level helpers directly using minimal hand-crafted XML:

| Test | What it covers |
|---|---|
| `test_sanitize_safe_chars` | `_sanitize_net` on a clean name — passes through unchanged |
| `test_sanitize_special_chars` | `+`, `-`, `/`, `()` characters all map to `_` |
| `test_collision_safety` | Two nets that sanitize identically get different final names |
| `test_node_sequence_applied` | A valid `Spice_Node_Sequence` field reorders correctly |
| `test_node_sequence_malformed` | A malformed sequence field is silently ignored |
| `test_netlist_enabled_false` | A component with `Spice_Netlist_Enabled=N` is dropped |
| `test_netlist_enabled_true` | A component with `Spice_Netlist_Enabled=Y` is kept |

These cover behaviors the real schematics don't exercise — synthetic edge cases
that would be unreliable to test through a golden fixture.

### 6.3 Topology Equivalence: `netlist_compare.py`

A text diff between generated and legacy netlists is useless. The two netlists:

- Use different auto-net names (`net__q1_c` vs `Net-(C1-Pad1)`)
- Have different component order
- Use different casing

None of that changes the circuit. Two netlists are **topologically equivalent**
when they describe the same graph:

1. **Same set of component refs** (case-insensitive)
2. **Same node count (arity) per ref** — same number of pins per component
3. **Same connectivity up to net renaming** — for every net, the set of
   `(ref, pin_position)` it touches is identical between the two netlists

**Pin order rules:**
- **R, L, C** (2-terminal symmetric): pin position is irrelevant, both pins
  recorded at position `-1`. A terminal swap is electrically identical and must
  not count as a failure.
- **Everything else** (D, Q, M, J, V, I, X, U): pin position is significant.
  This is what catches a real node-order bug on a transistor or subcircuit.

**Floating/unconnected pins** get unique internal keys so that a component
with 3 floating pins does not appear to have them all on the same net (the legacy
netlister lumped all `?` nodes into one).

**Value strings** are reported but not part of the topology verdict, because
model name spelling (`eSim_NJF` vs `NJF`) differs harmlessly — the eSim
DeviceModel GUI step resolves the real model name downstream.

### 6.4 Running the Tests

```sh
# Full suite with pytest (150 golden + 7 unit):
pytest src/kicadtoNgspice/tests/

# Or standalone, no dependencies beyond Python + kicad-cli:
python3 src/kicadtoNgspice/tests/test_netlister_golden.py
python3 src/kicadtoNgspice/tests/test_netlister_unit.py
```

**Requirements:**
- `kicad-cli` (KiCad ≥7) on `PATH`, or set `$ESIM_KICAD_CLI` to the binary path.
- The golden test skips cleanly if `kicad-cli` is absent.

**Point at a different fixture set:**
```sh
ESIM_NETLIST_GOLDENS=/path/to/fixtures pytest src/kicadtoNgspice/tests/
```

---

## 7. How to Add a New Golden Fixture

When you verify that the netlister correctly handles a new schematic:

1. **Get the `.kicad_sch`** — must be KiCad 9 format (version 20250114 or later).
2. **Get the ground-truth `.cir`** — the legacy `.cir` from the same project,
   known to simulate correctly. Do **not** generate it with the new netlister.
3. **Verify** by running `netlist_compare.py` between the generated netlist and
   the legacy `.cir`. `equivalent: True` plus a manual sanity-check of a few
   key components is sufficient.
4. **Create the fixture directory:**
   ```
   tests/golden/<ProjectName>/
       <ProjectName>.kicad_sch
       <ProjectName>.cir
   ```
5. **Run the full test suite** to confirm the new test passes and no existing
   tests regress.
6. **Commit both files.** The fixture is the evidence.

---

## 8. Known Gaps and Edge Cases

The current test suite does not cover:

| Gap | Notes |
|---|---|
| **Multi-unit symbols** | Quad opamp (LM324) has units A/B/C/D sharing power pins on a separate "power unit". Not tested. |
| **Hierarchical sheets** | Schematics with sub-sheets. `kicadxml` flattens them, but the behavior has not been verified against a real hierarchical design. |
| **KiCad-9 native `Sim.*` fields** | No re-saved eSim example carries `Sim.*` properties. The `Sim.Device=SPICE, type="X"` path is covered by ngveri fixtures; the MOSFET/BJT `Sim.Device=M`/`Q` paths are not used by any eSim symbol. |
| **Raw spice directives** | Symbols that carry `.model`, `.include`, or `.param` text in a field. These pass through as the component's value string — not validated. |
| **Very large schematics** | The netlister uses `xml.etree` (DOM, entire file in memory). No practical limit has been hit, but schematics with thousands of components are untested. |

---

## 9. Validation History — What We Ran

This section records the four test campaigns that built confidence in the
netlister. The ground truth in every phase was the legacy `.cir` produced by
the old KiCad-5/6 eSim exporter, known to simulate correctly.

---

### Phase 1 — 52 Original eSim Bundled Examples

**Source:** `~/eSim-Workspace/` — all bundled eSim examples, manually re-saved
to KiCad 9 `.kicad_sch` format. Legacy `.cir` kept untouched.

**Result: 52/52 PASS** (after one schematic defect fix — see below).

**Hardening done in this phase:**

- `_sanitize_net`: broadened from stripping only `()` and spaces to mapping all
  non-`[a-z0-9_]` characters to `_`. Motivated by KiCad-9 auto-net names like
  `Net-(v1-+)` which embed arithmetic operators.
- Collision-safe net naming: distinct nets that sanitize identically are
  disambiguated by appending the net's unique `code`.
- Case-insensitive `Spice_*` field lookups.
- Broader `Spice_Netlist_Enabled` disable values: `{n, no, false, 0}`.

**Schematic defect fixed — `Precision_Rectifiers_using_LM741`:**
In the KiCad-9 re-save, opamp X3's V+ pin (pin 7) physically landed on the
inverting-input rail (both at y=114.3), creating a spurious short between the
+12 V supply and the inverting input. This was a re-save layout error, not a
netlister bug. Fix: removed two horizontal wires passing through pin 7 and
rerouted the inverting rail around it. The fixed schematic is the committed
test fixture; the original broken version is backed up locally.

**Simulation equivalence verified on ngspice-35 and ngspice-45.2:**

| Example | Analysis | Result |
|---|---|---|
| RC | `.tran` | Exact, Δ=0 |
| FET_Characteristic | `.dc` (66-point sweep) | Exact, Δ=0 |
| Differentiator | `.tran` (opamp subckt + floating pins) | 0.24% (adaptive-timestep noise on spiky output; final sample matches) |

**Committed:** `611c9093a` on `ubuntu-26.04-support`
(110 files: netlister + `tests/` + initial doc).

---

### Phase 2 — Subcircuit IC Workspace: 27 Circuits

**Source:** `~/subckt_workspace/` — 27 KiCad-9 schematics for standard 74xx/4000
series ICs and op-amp test circuits, with legacy `.cir` ground truth.

**Result: 16/27 PASS, 11/27 FAIL** (all failures were schematic-level issues).

**16 PASSing fixtures added to `tests/golden/`:**
SN54166, sn54ls293_test, MC14040B_test, SN5473_Test_Circuit,
LH0003_Test_Circuit, 74145_Test_Circuit, 74LS251_Test_Circuit, 74LS153_Test_Circuit,
74LS126_Test_Circuit, 3State_Buffer_Test_Circuit, 74HC4066_Test_Circuit,
74HC386_Test_Circuit, 74LS48_Test_Circuit, 74LS83_Test_Circuit1, 74LS85_Test_Circuit,
74LS112_Test_Circuit.

**11 failures — all schematic-level, not netlister bugs:**

| Root cause | Affected circuits |
|---|---|
| `Vv1`→`v1` ref prefix + value `sin(...)` → `sine` (old vs new eSim Sources symbol convention) | 10 circuits: LT1097_TEST, LT1007_test, LT1002_TEST, LM7810_TEST, LM1558_TEST, LM442_TEST, LM358B_test, LM335_test, LM334_test, LF356_test |
| Extra R1–R5 (1MΩ) added during re-save to terminate floating X1 pins | LT1002_TEST |
| Missing `plot_v1` symbol (removed during KiCad-9 re-save) | LM335_test, LM334_test |
| R1/R3 connectivity genuinely swapped vs golden | lmv7239_test3 |

**Suite after phase 2: 68/68 PASS.**

---

### Phase 3 — Student Projects Batch: 46 Schematics

**Source:** `~/Downloads/esim_valid_projects/` — 60 student project folders; 46
had both a KiCad-9 `.kicad_sch` (version ≥20250114) and a legacy `.cir`.

**Result: 33/46 PASS, 13/46 FAIL** (all failures were schematic-level issues).

**Netlister fix discovered — X-prefix auto-detection:**

The bug: a component with ref `U1` and value `lm_741` emitted `u1 ... lm_741`
instead of `xu1 ... lm_741`. The SPICE X-prefix was missing. ngspice silently
treated it as an unknown element type, and the eSim SubcircuitTab could not
find it (it detects subcircuit lines by `line[0] == 'x'`).

Fix: detect subcircuit values by `.sub` file presence and prepend `x` automatically
when the ref lacks it. See §4.7 for the full explanation.

**33 new fixtures added** (PS2_PROTOCOL, DALI_Protocol_Model, ClassABAmplifier,
transimp2, sinc3, 3x8_Decoder, Full_subtractor, Xor_via_Nand, Half_Adder,
counter, latch_block, latch_sch, latch_test, full_adder, half_adder, 4017,
lm555n, Digital_Dice_4017, Digital_Dice_lm555n, lm_741 variants ×7,
3_and variants ×4, 2x4_decoder ×2, FSK_Transceiver_lm_741).

**13 failures — all schematic-level:**

| Root cause | Circuits |
|---|---|
| Unannotated refs (`D?`, `Q?`) — KiCad-9 stripped instance numbers from sub-circuit definition | `LM393.kicad_sch` in 4 projects |
| Space inside net name in golden (old netlister emitted literal spaces — invalid SPICE; new netlister correctly sanitizes) | FSK_Transceiverrrrrr |
| Golden was hand-edited to contain behavioral sources not present in schematic | FSK_Transceiver |
| Topology changed during KiCad-9 re-save | VCO_ADC, dff, Sub1v_CMOS, scr |
| DAC bridge blocks + termination resistors removed during re-save | I2S_Protocol_Simulation |
| `Vv1`→`v1` prefix + R5 missing | shunt_res |
| Schematic completely redesigned with different models | CA3140_BIMOS_op-amp |

**Committed:** `3522d456b`. **Suite after phase 3: 101/101 PASS.**

---

### Phase 4 — ngveri / Digital-Verilog IP Library: 69 Circuits

**Source:** `~/eSim-IP-Library-Digital-Verilog-IPs/` — 81 IP folders, each with
`.v` (Verilog), Verilated `.cpp`, and a project subfolder with `.kicad_sch`,
`.cir`, `.sub`. Mixed KiCad 6 (version 20211123, 27 files) and KiCad 9
(version 20250114, 42 files).

**Result: 49/69 PASS, 20/69 FAIL** (all failures were schematic-level issues).

**Netlister fix discovered — KiCad 6 `Sim.Device=SPICE` detection:**

KiCad 6 schematics with `Spice_Primitive=X` (marking subcircuit/ngveri blocks)
have that field converted to `Sim.Device=SPICE, Sim.Params=type="X"` when
opened in KiCad 9. The `.sub` file check from Phase 3 missed these because the
IP library `.sub` is not copied into the project directory.

Fix: detect the `Sim.Device=SPICE` + `type="X"` pattern and prepend `x`
automatically. See §4.9 for details.

**49 new fixtures added** — suite grows to 150.

**20 failures — all schematic-level:**

| Root cause | Circuits |
|---|---|
| `Vv` vs `v` voltage source prefix (old EESchema eSim_Sources convention vs new symbol) | 10: I2C_Controller, advanced_pwm, bldc_commutator, digital_pid_controller, quadrature_encoder_interface, sd_modulator, soft_start_limiter, stepper_indexer, svpwm, windowed_watchdog_timer |
| Unannotated refs (`U?`, `V?`) in schematics | 5: Clock_Gating_Controller, bram, debounce_controller_subcircuit, fir_filter, sync_fifo |
| Ref prefix mismatch (golden uses `a`, `u_p`, `plot`/`print` prefixes) | alu_subcircuit, divider_8bit_subcircuit, spi_subcircuit |
| Other topology changes (value mismatch, extra component) | boothmultiplier_8bit_subcircuit, freq_mul |

**Suite after phase 4: 150/150 PASS.**

---

### Summary

| Phase | Source | Tested | PASS | FAIL | Key netlister fix | Suite total |
|---|---|---|---|---|---|---|
| 1 | eSim bundled examples | 52 | 52 | 0 | `_sanitize_net`, collision safety, case-insensitive fields | 52 |
| 2 | Subcircuit IC workspace | 27 | 16 | 11 | — | 68 |
| 3 | Student projects batch | 46 | 33 | 13 | X-prefix auto-detection via `.sub` lookup | 101 |
| 4 | ngveri/Digital-Verilog IPs | 69 | 49 | 20 | KiCad-6 `Sim.Device=SPICE`+`type="X"` detection | 150 |
| **Total** | | **194** | **150** | **44** | | **150** |

All 44 failures across all phases were **schematic-level issues** — wrong symbol
conventions, unannotated refs, topology changes during re-save, or hand-edited
golden files. Zero failures were netlister logic bugs after the fixes applied in
each phase.

---

## 10. Local Artifacts

These files exist on the development machine but are not in the repository:

| Path | Contents |
|---|---|
| `~/netlister_plan.md` | Original phased implementation plan |
| `~/netlister_diff.py` | Standalone topology-diff script (seed of `netlist_compare.py`) |
| `~/netlister_goldens_backup/` | Backup of all 81 legacy `.cir` files + the original (broken) `Precision_Rectifiers_using_LM741.kicad_sch` before the pin-7 fix |
| `~/subckt_workspace/` | 27 KiCad-9 schematics from Phase 2 (16 passing ones are in `tests/golden/`) |
| `~/Downloads/esim_valid_projects/` | 60 student project folders from Phase 3 |
| `~/eSim-IP-Library-Digital-Verilog-IPs/` | 81 ngveri IP library folders from Phase 4 |
