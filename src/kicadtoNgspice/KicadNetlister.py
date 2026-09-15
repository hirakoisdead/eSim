# ==============================================================================
#             FILE: KicadNetlister.py
#
#      DESCRIPTION: Generate an eSim-compatible spice netlist (<proj>.cir) from a
#                   KiCad schematic, independent of KiCad's own spice exporter.
#
#                   KiCad >= 7 rewrote `--format spice` around its Simulation
#                   Model system; symbols without a Sim.* model (every eSim
#                   symbol: plots, behavioural u-blocks, sources, custom models)
#                   are exported with their connectivity stripped, e.g.
#                   "U2 __U2" / "v3 __v3" (one placeholder node, no nets).
#                   That is unrecoverable, so we never use `--format spice`.
#
#                   Instead we use `--format kicadxml`, the generic netlist that
#                   always lists every comp + every net + pin->net mapping
#                   regardless of simulation models, and rewrite it into the flat
#                   spice form eSim's Processing expects:
#                       "<ref> <net-per-pin-in-node-order> <value>"
#                   Node order is pin-number order (eSim symbols number pins in
#                   spice node order); an optional `Spice_Node_Sequence` user
#                   field reorders when present. `Spice_Netlist_Enabled=N` drops
#                   a component.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET


def _kicad_cli():
    """Locate kicad-cli (KiCad >= 7). ESIM_KICAD_CLI overrides PATH lookup."""
    return os.environ.get('ESIM_KICAD_CLI') or shutil.which('kicad-cli')


def _no_window_kwargs():
    """subprocess kwargs that fully suppress the console flash on Windows.

    CREATE_NO_WINDOW alone still lets a console exe (kicad-cli) blink a black
    box when the GUI parent has no console. Pairing it with a STARTUPINFO that
    forces SW_HIDE kills the flash for good. No-op on non-Windows.
    """
    if os.name != 'nt':
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {
        'startupinfo': si,
        'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    }


def _esim_subckt_lib():
    """Return the eSim SubcircuitLibrary root, or None if not installed."""
    here = os.path.dirname(os.path.abspath(__file__))
    lib = os.path.normpath(os.path.join(here, '../../library/SubcircuitLibrary'))
    return lib if os.path.isdir(lib) else None


def _modelparam_dir():
    """Return the eSim modelParamXML root, or None if not installed.

    Holds the XML definition of every eSim *model* block: ngspice behavioural
    primitives (adc_bridge_N, dac_bridge_N, d_xor, …) and ngveri/makerchip
    Verilog models (modelParamXML/Ngveri/<name>.xml, written by
    createkicad.AutoSchematic.createXML).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.normpath(os.path.join(here, '../../library/modelParamXML'))
    return d if os.path.isdir(d) else None


def _is_model_value(value):
    """True if `value` is a registered eSim model (a <value>.xml exists under
    library/modelParamXML/**).

    Covers all model namespaces via os.walk:
      - modelParamXML/Ngveri/<name>.xml  — Verilog models built with ngveri/makerchip
      - modelParamXML/Nghdl/<name>.xml   — VHDL models built with nghdl/ghdl
      - modelParamXML/*.xml              — built-in eSim behavioural primitives

    All three keep their 'u' prefix; Processing.convertICintoBasicBlocks routes
    Ngveri → modelList (Ngspice Model tab) and Nghdl → microcontrollerList
    (Microcontroller tab).  A model XML wins over a same-named .sub — a stray
    .sub in the project dir must not demote a compiled model to a subcircuit.
    """
    if not value:
        return False
    root = _modelparam_dir()
    if not root:
        return False
    target = value + '.xml'
    for _dirpath, _dirs, files in os.walk(root):
        if target in files:
            return True
    return False


def _is_subcircuit_value(value, proj_dir):
    """True if `value` is a known eSim subcircuit (a .sub file exists for it).

    Checks the project directory first (local copy of the .sub), then the eSim
    system library (library/SubcircuitLibrary/<value>/<value>.sub). Returns
    False for plain device values (10k, 1e-6, eSim_PNP) and for eSim
    behavioural block names (plot_v1, PORT, adc_bridge_1, d_dff, …) which have
    no .sub file, so those keep their original U prefix unchanged.
    """
    if not value:
        return False
    if os.path.isfile(os.path.join(proj_dir, value + '.sub')):
        return True
    lib = _esim_subckt_lib()
    if lib and os.path.isfile(os.path.join(lib, value, value + '.sub')):
        return True
    return False


def _sanitize_net(name):
    """Make a KiCad net name a safe, consistent ngspice node.

    Lowercases (ngspice is case-insensitive; the historical eSim netlist used
    lowercase) and maps every character that is not [a-z0-9_] to '_'. KiCad
    auto-net names embed '(', ')', '+', '-' and '/' (taken from pin names like
    'v1-+' and from hierarchical sheet paths). Of these, '+', '-' and '/' are
    arithmetic operators *inside* ngspice 'v()'/'i()' vector references, so an
    internal node such as 'Net-(v1-+)' could be simulated but never plotted by
    name. Mapping them to '_' keeps such nodes addressable. User-named nets
    (in, out, gnd, v_out, c_out) contain none of these and are unaffected.
    Topology is preserved; only the spelling of auto-named internal nets changes.

    Returns '' for a name with no usable characters so the caller can fall back
    to a code-based name. Distinct nets that collapse to the same string are
    disambiguated by the caller (see xml_to_spice_lines); never short here.
    """
    raw = name.strip().lower()
    # The bundled eSim power symbol exports its value as ``eSim_GND``.  Unlike
    # KiCad's stock ``GND`` spelling, ngspice does not treat ``esim_gnd`` as
    # its reference node, so the previously generated circuit floated and
    # failed with a singular matrix.  Normalize both spellings explicitly;
    # SPICE node 0 is the only portable ground representation.
    if raw in ('0', 'gnd', 'esim_gnd'):
        return '0'
    safe = ''.join(c if (c.isalnum() or c == '_') else '_'
                   for c in raw)
    return safe.strip('_')


def _node_sort_key(pin, seen_index):
    """Order a component's pins: numeric pin numbers first (ascending), then any
    non-numeric/blank pins (e.g. eSim plot markers expose a blank pin) in the
    order encountered, so single-pin parts and oddities never crash."""
    if pin.isdigit():
        return (0, int(pin), seen_index)
    return (1, 0, seen_index)


def _apply_node_sequence(nodes, seq_field):
    """Reorder `nodes` (already in default pin order) by a Spice_Node_Sequence
    field: a comma/space list of 0-based indices, e.g. '2,1,0'. Ignored if it
    is malformed or not a permutation of range(len(nodes))."""
    tokens = seq_field.replace(',', ' ').split()
    try:
        order = [int(t) for t in tokens]
    except ValueError:
        return nodes
    if sorted(order) != list(range(len(nodes))):
        return nodes
    return [nodes[i] for i in order]


def xml_to_spice_lines(xml_path, title="KiCad schematic", proj_dir=None):
    """Convert a KiCad `kicadxml` netlist into eSim flat-spice component lines."""
    root = ET.parse(xml_path).getroot()

    # Components in document order: ref -> value, ref -> {field name: value}
    order_refs = []
    value = {}
    fields = {}
    comps_el = root.find('components')
    for comp in (comps_el.findall('comp') if comps_el is not None else []):
        ref = comp.get('ref')
        order_refs.append(ref)
        v = comp.find('value')
        value[ref] = (v.text or '').strip() if v is not None else ''
        fd = {}
        fel = comp.find('fields')
        if fel is not None:
            for f in fel.findall('field'):
                # Lower-case field-name keys so Spice_* lookups are
                # case-insensitive (KiCad lets users type the field name).
                fd[(f.get('name') or '').strip().lower()] = (f.text or '').strip()
        fields[ref] = fd

    # Connectivity: ref -> [(sort_key, net_name), ...]
    # First assign every net a collision-free, ngspice-safe name. Two distinct
    # KiCad nets must never collapse to the same node (that would short them), so
    # any sanitized name clash is disambiguated with the net's unique code.
    pins = {}
    seen = {}
    nets_el = root.find('nets')
    net_name = {}
    used = set()
    for net in (nets_el.findall('net') if nets_el is not None else []):
        code = net.get('code') or '0'
        raw = net.get('name') or ('net' + code)
        safe = _sanitize_net(raw) or ('net' + code)
        # All accepted ground spellings intentionally collapse to SPICE node
        # zero.  Other sanitized collisions must remain distinct nets.
        if safe != '0' and safe in used:
            safe = safe + '_' + code
        used.add(safe)
        net_name[net] = safe

    for net in (nets_el.findall('net') if nets_el is not None else []):
        net_clean = net_name[net]
        for node in net.findall('node'):
            ref = node.get('ref')
            pin = node.get('pin') or ''
            idx = seen.get(ref, 0)
            seen[ref] = idx + 1
            pins.setdefault(ref, []).append((_node_sort_key(pin, idx), net_clean))

    lines = ['* ' + title + ' (eSim netlist via kicad-cli kicadxml)',
             '* Sheet Name: /']
    # Values that disable a component, matching the legacy Spice_Netlist_Enabled
    # convention (N) plus the obvious boolean spellings.
    disabled = ('n', 'no', 'false', '0')
    for ref in order_refs:
        fd = fields.get(ref, {})
        if fd.get('spice_netlist_enabled', '').strip().lower() in disabled:
            continue
        ordered = [n for _, n in sorted(pins.get(ref, []), key=lambda t: t[0])]
        seq = fd.get('spice_node_sequence', '').strip()
        if seq:
            ordered = _apply_node_sequence(ordered, seq)
        nets = ' '.join(ordered)
        val = value.get(ref, '')
        ref_out = ref.lower()
        # A registered eSim model (a <value>.xml under library/modelParamXML/**)
        # is a behavioural / ngveri-Verilog block that Processing expands into an
        # XSPICE 'a' device; it must keep its 'u' prefix. The model XML wins over
        # a same-named .sub — a stray half_adder.sub in the project dir must not
        # turn the ngveri half_adder block into a subcircuit instantiation.
        is_model = _is_model_value(val)
        # Prepend 'x' when the value is an eSim subcircuit (.sub exists) but
        # the schematic ref doesn't already carry the X prefix.  In SPICE,
        # subcircuit instantiation requires the X prefix; students often use U1
        # for an opamp (lm_741) whose golden .cir correctly has XU1.
        if ref_out and ref_out[0] != 'x' and not is_model \
                and _is_subcircuit_value(val, proj_dir or ''):
            ref_out = 'x' + ref_out
        # KiCad 6→kicadxml: Spice_Primitive=X becomes Sim.Device=SPICE with
        # Sim.Params containing type="X".  Detect ngveri/subcircuit blocks that
        # have no .sub in the project dir but carry the Spice_Primitive field.
        if ref_out and ref_out[0] != 'x' and not is_model:
            _sd = fd.get('sim.device', '').lower()
            _sp = fd.get('sim.params', '').lower()
            if _sd == 'spice' and ('type="x"' in _sp or "type='x'" in _sp):
                ref_out = 'x' + ref_out
        lines.append((ref_out + ' ' + nets + ' ' + val).strip())
    lines.append('.end')
    return lines


def generate_netlist(proj_dir, proj_name):
    """Regenerate <proj>.cir from <proj>.kicad_sch via kicad-cli kicadxml.

    Returns (ok, message). Leaves any existing .cir untouched on failure so the
    legacy/manual workflow still applies on KiCad < 7 or odd installs.
    """
    sch = os.path.join(proj_dir, proj_name + '.kicad_sch')
    if not os.path.isfile(sch):
        return False, "No .kicad_sch found; using existing .cir if present."

    cli = _kicad_cli()
    if not cli:
        return False, "kicad-cli not found; using existing .cir if present."

    xml_path = os.path.join(proj_dir, proj_name + '.netlist.xml')
    try:
        proc = subprocess.run(
            [cli, 'sch', 'export', 'netlist', '--format', 'kicadxml',
             '-o', xml_path, sch],
            capture_output=True, text=True, timeout=120,
            # No blank console window on Windows (GUI parent has no console).
            **_no_window_kwargs())
        if proc.returncode != 0 or not os.path.isfile(xml_path):
            return False, "kicad-cli netlist export failed: " + proc.stderr.strip()

        lines = xml_to_spice_lines(xml_path, title=proj_name, proj_dir=proj_dir)

        # Never overwrite a working netlist with an empty one. A .kicad_sch can
        # legitimately exist and contain no components: KiCad 6+ migration
        # writes a sibling .kicad_sch beside a legacy .sch, and some of those
        # in eSim's own Subcircuit Library are empty stubs (3_nor is one) next
        # to a perfectly good hand-made .cir. Export "succeeds" on them, and
        # writing the result would destroy the netlist the subcircuit is built
        # from. Decline instead, exactly as when there is no schematic at all.
        components = [ln for ln in lines
                      if ln and not ln.startswith('*') and ln != '.end']
        if not components:
            return False, ("Schematic has no components; keeping the existing "
                           ".cir.")

        cir_path = os.path.join(proj_dir, proj_name + '.cir')
        with open(cir_path, 'w') as fh:
            fh.write('\n'.join(lines) + '\n')
        return True, "Generated " + cir_path + " from schematic (KiCad 7-10 safe)."
    except Exception as e:
        return False, "Netlist generation error: " + str(e)
    finally:
        if os.path.isfile(xml_path):
            os.remove(xml_path)


if __name__ == '__main__':
    import sys
    d, n = os.path.split(os.path.abspath(sys.argv[1]))
    name = n[:-len('.kicad_sch')] if n.endswith('.kicad_sch') else n
    ok, msg = generate_netlist(d, name)
    print(msg)
    if ok:
        with open(os.path.join(d, name + '.cir')) as fh:
            print(fh.read())
