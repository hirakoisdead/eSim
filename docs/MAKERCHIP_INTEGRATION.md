# Makerchip browser integration

`Maker → Verilog → Author → Edit in Makerchip IDE` uses Makerchip's
[supported `IdePlugin` v2 browser API](https://makerchip.com/public/docs/plugin_api/).
It does not use the deprecated
`makerchip-app` Python package or Makerchip's retired public-project desktop
service.

## User flow

1. eSim materializes the in-memory Author design so Makerchip receives the
   current text.
2. For a `.v` / `.sv` design, one click generates and opens a Makerchip-ready
   `.tlv` wrapper beside the design. An existing `.tlv` opens directly. There
   is no mode-selection dialog on each launch.
3. eSim starts a session on `127.0.0.1` and opens its URL in the default
   browser. The page imports
   `https://makerchip.com/dist/makerchip-plugin.js`, then creates an editable
   IDE with the file contents.
4. Makerchip's `onCodeChange()` callback is debounced and saved to the exact
   file that was opened. For generated wrappers this is the `.tlv` copy; the
   original Author `.v` / `.sv` is not silently overwritten.

## Simulation wrapper

The wrapper is a small deterministic testbench, not a second implementation of
the design. It preserves the source under `\\SV`, instantiates the detected top
module, maps common clock/reset names to Makerchip's `clk` and `reset`, drives
scalar inputs from successive `cyc_cnt` bits, and drives vector inputs from
`cyc_cnt`. The `passed` signal ends the run after a short trace so Makerchip can
publish waveform data. Empty lines in the lint configuration are ignored;
emitting an empty `verilator lint_off` directive prevents Verilator from
running and therefore leaves Diagram/Viz/Waveform unavailable.

The page shows **Compiling simulation…**, then either **Simulation ready** or a
clear failure state with an **Open compile log** button. Once VCD data arrives,
eSim opens **Waveform** automatically. **Diagram** and **Viz** visualize
TL-Verilog hierarchy and Visual Debug objects; a plain Verilog design can leave
them empty until TL-Verilog constructs are added in the wrapper's `\\TLV`
section. They are not gate-level schematic generators.

Makerchip remains a third-party editor/simulator. Browser compilation does not
silently advance eSim to Verify or Convert, import a VCD, or build an ngspice
model.

## Conflict and failure behavior

Every read returns a SHA-256 revision of the file bytes. A browser save must
name the revision it edited. If eSim or another editor changed the file in the
meantime, the bridge returns `409 Conflict` and does not write. The browser
offers two explicit choices: reload the latest file or keep the browser edit.

The bridge reports browser/network initialization failures in its status bar.
eSim reports a missing design or failure to open the system browser before
returning control to the user.

## Security boundary

- The HTTP server binds to `127.0.0.1`, never a LAN or wildcard address.
- Every route contains a new 256-bit random session token.
- Writes accept JSON only, are capped at 10 MiB, and can reach only the single
  absolute file selected by eSim when the session was created.
- Responses disable caching and referrer transmission; no CORS permission is
  granted.
- Closing the Author widget shuts down the bridge. Reopening Makerchip replaces
  the previous session and invalidates its token.

The production plugin URL is intentional. Beta documentation and examples may
describe unreleased API additions, while the stable entry module pins its own
Makerchip IDE version.
