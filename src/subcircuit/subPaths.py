# ==============================================================================
#          FILE: subPaths.py
#
#   DESCRIPTION: Single source of truth for a *subcircuit's* identity.
#
#                A subcircuit folder is acted on by three of the Subcircuit
#                Builder's four buttons, and each of them needs the same
#                answer: which ``<stem>`` inside this folder are we working on?
#                Everything else -- the schematic eeschema opens, the netlist
#                Convert reads, the ``.sub`` it writes -- is derived from it.
#
#                Historically each button worked that out for itself, and they
#                could disagree: Edit would open ``half_adder`` (chosen by the
#                user from a folder holding several ``.sub`` files) while
#                Convert independently picked ``2bitmul`` and rebuilt the wrong
#                model, silently. Resolution now happens here, once, and both
#                buttons pass the same answer around.
#
#                ``projManagement.projectPaths.resolve_stem`` remains the
#                generic anchor resolver for *projects*. This module is the
#                subcircuit-shaped layer over it, because subcircuits have two
#                properties projects do not:
#
#                  - a brand-new subcircuit has no ``.sub`` at all (the file is
#                    the *output* of Convert, not an input), so the folder name
#                    has to remain a legitimate identity, and
#                  - a subcircuit folder legitimately contains the ``.sub`` of
#                    every nested subcircuit it uses (``2bitmul`` ships
#                    ``half_adder.sub`` beside its own), so "several anchors"
#                    is normal here rather than a malformed project.
#
#                Dependency-free (os, glob) on purpose: imported from the Qt
#                widgets and from tests that never start a QApplication.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

import os
import glob

from projManagement.projectPaths import find_anchors, stem_from_file

#: Extensions that make a stem "real" inside a folder, newest schematic first.
#: A stem is trusted when the folder holds at least one file named after it.
STEM_EXTENSIONS = ('.sub', '.cir', '.kicad_sch', '.sch')


def stem_exists(folder, stem):
    """True when ``folder`` holds any file named ``<stem>.<known extension>``.

    Used to sanity-check a remembered stem before acting on it: the selection
    the user made in Edit is authoritative, but only for the folder it was made
    in. A stem carried over from a previous selection must not silently rename
    the subcircuit that is open now.
    """
    if not folder or not stem:
        return False
    return any(os.path.isfile(os.path.join(folder, str(stem) + ext))
               for ext in STEM_EXTENSIONS)


def list_stems(folder):
    """Every subcircuit stem this folder plausibly offers, sorted.

    The ``.sub`` anchors, plus the folder's own name when a schematic or
    netlist is named after it -- so a subcircuit that has been drawn but never
    converted still appears in a chooser.
    """
    if not folder or not os.path.isdir(folder):
        return []
    stems = {stem_from_file(p) for p in find_anchors(folder, 'sub')}
    own = os.path.basename(os.path.normpath(str(folder)))
    if stem_exists(folder, own):
        stems.add(own)
    return sorted(stems)


def subckt_ports(sub_file):
    """Port names declared on a ``.sub`` file's ``.subckt`` line.

    Returns ``None`` when there is no ``.subckt`` line (a truncated or
    hand-written file that never was a subcircuit), so callers can tell "no
    ports" from "not a subcircuit". Comments and blank lines are skipped, the
    way ngspice itself reads the file.
    """
    try:
        with open(sub_file, errors='replace') as fh:
            for line in fh:
                words = line.strip().split()
                if words and words[0].lower() == '.subckt':
                    # .subckt <name> <port> <port> ...
                    return words[2:]
    except OSError:
        return None
    return None


def resolve_subcircuit(folder, preferred=None):
    """Resolve the stem to act on inside ``folder``.

    @params
        :folder     => the subcircuit folder
        :preferred  => a stem the user already chose for THIS folder (e.g. via
                       the Edit chooser). Honoured when it still exists there.

    @return
        ``(stem, status)`` where status is one of:

            'preferred'    => ``preferred`` was given and is real; used as-is
            'anchor'       => exactly one ``.sub``; its stem is the identity
            'folder-match' => several ``.sub``, one named after the folder
            'netlist'      => several ``.sub``, none matching the folder, but
                              ``<folder>.cir`` exists -- the identity the
                              folder-name era used, kept so those subcircuits
                              keep converting
            'fallback'     => no ``.sub`` yet (new, or never converted); the
                              folder name is the identity
            'ambiguous'    => several ``.sub``, nothing to prefer among them.
                              stem is None: the caller must ask the user rather
                              than guess (guessing here is what produced
                              lookups for a file literally called "None")
            'nodir'        => ``folder`` is not a directory. stem is None.
    """
    if not folder or not os.path.isdir(str(folder)):
        return None, 'nodir'

    folder = str(folder)
    own = os.path.basename(os.path.normpath(folder))

    if preferred and stem_exists(folder, preferred):
        return str(preferred), 'preferred'

    anchors = [stem_from_file(p) for p in find_anchors(folder, 'sub')]

    if len(anchors) == 1:
        return anchors[0], 'anchor'

    if len(anchors) > 1:
        if own in anchors:
            return own, 'folder-match'
        # No anchor names the folder. Before declaring the folder ambiguous,
        # honour the identity the folder-name era used: if <folder>.cir is
        # sitting there, that IS this subcircuit's netlist and Convert used to
        # rebuild it happily. 25 shipped subcircuits depend on this.
        if os.path.isfile(os.path.join(folder, own + '.cir')):
            return own, 'netlist'
        return None, 'ambiguous'

    return own, 'fallback'


def schematic_path(folder, stem):
    """Path of the schematic to open for ``stem``.

    Prefers KiCad 6+ ``.kicad_sch`` over the KiCad 4 ``.sch`` when both exist
    (KiCad migrates by writing the new file beside the old one and leaving the
    original in place). Returns the ``.kicad_sch`` candidate when neither
    exists, which is what a *new* subcircuit wants: modern KiCad creates the
    file on first save.
    """
    base = os.path.join(str(folder), str(stem))
    kicad6 = base + '.kicad_sch'
    kicad4 = base + '.sch'
    if os.path.isfile(kicad6):
        return kicad6
    if os.path.isfile(kicad4):
        return kicad4
    return kicad6


def netlist_path(folder, stem):
    """Path of the KiCad netlist Convert reads for ``stem``."""
    return os.path.join(str(folder), str(stem) + '.cir')


def model_path(folder, stem):
    """Path of the ngspice model Convert writes for ``stem``."""
    return os.path.join(str(folder), str(stem) + '.sub')


def describe(folder, stem=None):
    """One-line, user-facing description of what is selected.

    Kept here so the Subcircuit tab, the log and any future status bar all
    phrase the selection identically.
    """
    if not folder:
        return 'No subcircuit selected'
    if stem is None:
        stem, _status = resolve_subcircuit(folder)
    if stem is None:
        return os.path.basename(os.path.normpath(str(folder)))
    return '%s  (%s)' % (stem, folder)


def has_schematic(folder, stem):
    """True when a drawable schematic already exists for ``stem``."""
    base = os.path.join(str(folder), str(stem))
    return os.path.isfile(base + '.kicad_sch') or os.path.isfile(base + '.sch')


def scan_library(root):
    """Summarise every subcircuit folder under ``root`` for a picker UI.

    Returns a list of dicts sorted by name, each carrying the folder path, the
    resolved stem (None when genuinely ambiguous), and whether the subcircuit
    has a schematic, a netlist and a built model. Never raises on an
    unreadable entry -- a library folder a user cannot stat is simply reported
    with whatever is known.
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return out
    for name in entries:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        stem, status = resolve_subcircuit(path)
        out.append({
            'name': name,
            'path': path,
            'stem': stem,
            'status': status,
            'has_schematic': bool(stem) and has_schematic(path, stem),
            'has_netlist': bool(stem) and os.path.isfile(
                netlist_path(path, stem)),
            'has_model': bool(stem) and os.path.isfile(model_path(path, stem)),
            'stems': sorted({stem_from_file(p)
                             for p in glob.glob(os.path.join(path, '*.sub'))}),
        })
    return out
