# ==============================================================================
#          FILE: corpus.py
#
#   DESCRIPTION: Read-only scanner over the shipped Subcircuit Library, used by
#                the subcircuit parity tests.
#
#                eSim ships ~727 subcircuit folders under
#                ``library/SubcircuitLibrary``. They are the ground truth for
#                "what a real subcircuit looks like": built by students over
#                years, in every KiCad generation, with every naming habit
#                (folder name matching the ``.sub`` or not, one ``.sub`` or
#                several nested ones, netlist present or not).
#
#                Any change to how eSim resolves a subcircuit's *identity* --
#                the stem shared by ``<stem>.sub`` / ``.cir`` / ``.sch`` --
#                must be checked against that whole corpus, not against a
#                hand-written fixture, or a refactor silently breaks a slice of
#                the library nobody has open right now.
#
#                This module only *reads*. It never imports Qt, so it can run
#                in a plain pytest process, and it never resolves anything
#                itself: resolution comes from the production helpers so the
#                tests measure shipping behaviour rather than a copy of it.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

import os
import glob

from subcircuit import subPaths


def library_root():
    """Absolute path of the shipped SubcircuitLibrary, or None if absent.

    Resolved relative to this file so the scan works from any working
    directory, and returns None (rather than raising) on a source tree without
    the library so the tests can skip instead of erroring.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(
        os.path.join(here, '..', '..', '..', 'library', 'SubcircuitLibrary'))
    return root if os.path.isdir(root) else None


def sub_stems(folder):
    """Stems of every ``*.sub`` directly inside ``folder``, sorted."""
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(folder, '*.sub')))


#: Port parsing is production code (the picker shows port counts), so the
#: corpus measures the shipping implementation rather than a copy of it.
subckt_ports = subPaths.subckt_ports


def scan_folder(path):
    """Describe one subcircuit folder as a plain dict.

    Every field is a fact read off disk; no judgement is applied here so the
    tests can state the invariants themselves.

    Keys:
        name            folder basename
        subs            stems of the ``.sub`` files present
        legacy_stem     what pre-anchor eSim used: the folder basename
        has_legacy_cir  whether ``<folder>/<folder>.cir`` exists
        schematic       'kicad_sch' | 'sch' | None (newest generation present)
        ports           port list from ``<stem>.sub`` when resolvable,
                        else None
    """
    name = os.path.basename(os.path.normpath(path))
    stems = sub_stems(path)
    info = {
        'name': name,
        'subs': stems,
        'legacy_stem': name,
        'has_legacy_cir': os.path.isfile(os.path.join(path, name + '.cir')),
        'schematic': None,
        'ports': None,
    }
    if glob.glob(os.path.join(path, '*.kicad_sch')):
        info['schematic'] = 'kicad_sch'
    elif glob.glob(os.path.join(path, '*.sch')):
        info['schematic'] = 'sch'
    anchor = name if name in stems else (stems[0] if len(stems) == 1 else None)
    if anchor:
        info['ports'] = subckt_ports(os.path.join(path, anchor + '.sub'))
    return info


def scan_library(root=None):
    """Scan every subcircuit folder under ``root`` (default: shipped library).

    Returns a list of :func:`scan_folder` dicts sorted by folder name, or an
    empty list when the library is not present.
    """
    root = root or library_root()
    if not root:
        return []
    out = []
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if os.path.isdir(path):
            out.append(scan_folder(path))
    return out


def has_netlist(root, folder_name, stem):
    """True when ``<root>/<folder_name>/<stem>.cir`` exists.

    ``stem`` may be None (an unresolved folder); that is reported as False
    rather than being coerced into the string "None", which is precisely the
    bug this corpus exists to catch.
    """
    if stem is None:
        return False
    return os.path.isfile(os.path.join(root, folder_name, str(stem) + '.cir'))
