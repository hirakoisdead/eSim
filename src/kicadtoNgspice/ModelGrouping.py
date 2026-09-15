# ==============================================================================
#  ModelGrouping.py -- pure, UI-free helpers that bucket netlist component
#  lines by the model/library they share.
#
#  Why this exists:
#    The KiCad->ngspice converter assigns a model/library file per *instance*
#    (q1, q2, ... q10). Real schematics reuse one model across many instances
#    (e.g. five eSim_NPN transistors), so the user is forced to locate and add
#    the SAME file once per instance. The netlist already encodes which
#    instances share a model -- it is the last token of the component line.
#    These helpers surface that grouping so the Device Modeling / Subcircuits
#    tabs can let the user assign once and fan the choice out to every instance,
#    while still allowing a per-instance override.
#
#  Design notes:
#    * No Qt here on purpose. This is unit-tested in isolation; the GUI tabs
#      (DeviceModel, SubcircuitTab) consume it and own all widget concerns.
#    * The model name is words[-1] (the last token), NOT a fixed index. Fixed
#      indices (words[4] etc.) misread a line the moment a BJT/MOSFET carries a
#      substrate node, and subcircuits have a variable node count. Last-token is
#      correct for q/d/j/m and x alike (verified against the netlister goldens).
#    * Grouping is case-insensitive on the model name to match the rest of the
#      pipeline (the netlist comparator lowercases everything).
# ==============================================================================
from collections import OrderedDict

# Single-letter device kinds handled by DeviceModel.eSim_general_libs, mapped to
# the minimum token count each line needs (ref + nodes + model). These mirror
# the arity guards in eSim_general_libs exactly:
#   q/j/m: len(words) > 4   d: len(words) > 3   s: len(words) > 5
_DEVICE_MIN_TOKENS = {'q': 5, 'd': 4, 'j': 5, 's': 6, 'm': 5}


class Component:
    """One parsed component instance line.

    ref   : lowercased reference designator (q1, d3, x1, ...)
    kind  : grouping kind -- a single-letter device kind ('q'..'m') or 'x'
    model : lowercased model/subcircuit name (the last token of the line)
    words : the original whitespace-split tokens (case preserved)
    nodes : the node tokens between ref and model
    """

    __slots__ = ('ref', 'kind', 'model', 'words', 'nodes')

    def __init__(self, ref, kind, model, words):
        self.ref = ref
        self.kind = kind
        self.model = model
        self.words = words
        self.nodes = words[1:-1]

    def __repr__(self):
        return "Component(ref=%r, kind=%r, model=%r)" % (
            self.ref, self.kind, self.model)

    def __eq__(self, other):
        return (isinstance(other, Component)
                and self.ref == other.ref
                and self.kind == other.kind
                and self.model == other.model
                and self.words == other.words)


def device_kind(words):
    """Return the general-library device kind for a line, or None.

    Mirrors the dispatch in DeviceModel.eSim_general_libs: first character of
    the reference plus a minimum arity. Returns None for anything that tab does
    not build a row for (sources, comments, too-short lines, subcircuits, the
    PDK 'sc'/'ihp' flows which are routed to other methods upstream).
    """
    if not words:
        return None
    ref = words[0].lower()
    kind = ref[0]
    need = _DEVICE_MIN_TOKENS.get(kind)
    if need is None or len(words) < need:
        return None
    return kind


def _split(line):
    """Whitespace-split a raw netlist line into tokens (empty -> [])."""
    return str(line).split()


def parse_device_components(schematic_info):
    """Parse the device-model instance lines (q/d/j/s/m) from schematic_info.

    Returns a list of Component in source order. Lines that are not general
    device-model rows are skipped.
    """
    comps = []
    for line in schematic_info:
        words = _split(line)
        kind = device_kind(words)
        if kind is None:
            continue
        comps.append(Component(words[0].lower(), kind, words[-1].lower(), words))
    return comps


def parse_subcircuit_components(schematic_info):
    """Parse the subcircuit instance lines (x...) from schematic_info.

    Returns a list of Component (kind 'x') in source order. The model field is
    the subcircuit name (last token); nodes are everything between, which the
    caller still validates per instance against the subcircuit's port count.
    """
    comps = []
    for line in schematic_info:
        words = _split(line)
        if not words:
            continue
        ref = words[0].lower()
        # A subcircuit instance needs at least ref + one node + name.
        if ref[0] == 'x' and len(words) >= 3:
            comps.append(Component(ref, 'x', words[-1].lower(), words))
    return comps


def group_by_model(components):
    """Bucket components by shared model.

    Returns an OrderedDict keyed by (kind, model) -> [Component, ...], with both
    group order and within-group order following first appearance in the netlist
    (so the UI is stable and matches the schematic). Keying on (kind, model)
    keeps unrelated kinds that happen to share a name from colliding.
    """
    groups = OrderedDict()
    for comp in components:
        groups.setdefault((comp.kind, comp.model), []).append(comp)
    return groups
