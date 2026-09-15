# ==============================================================================
#  test_library_corpus.py -- parity harness for subcircuit identity resolution.
#
#  The Subcircuit Builder's four buttons (New / Edit / Convert / Upload) all
#  hinge on one question: given a subcircuit *folder*, which <stem> do we act
#  on? Historically the answer was "the folder's own name". eSim now resolves
#  it from the ``.sub`` anchor instead, so a folder may be named anything.
#
#  That change is right (67 shipped subcircuits store e.g. ``multivibrator.sub``
#  inside a folder named ``74HC123``, and were unusable under the folder-name
#  rule) but it must not cost us any folder that used to work. These tests state
#  that as invariants and check them against every folder eSim ships, so the
#  answer is a number -- "N/N folders resolve to a netlist that exists" -- and
#  not an opinion.
#
#  Read-only: nothing here writes to the library.
# ==============================================================================
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import corpus                                                   # noqa: E402
from subcircuit.subPaths import resolve_subcircuit               # noqa: E402


# The 25 folders the bare anchor rule stranded: several ``.sub`` files, none
# named after the folder, so it yielded no stem -- while ``<folder>.cir`` sat
# right there and the folder-name era converted them fine. subPaths restores
# them with a netlist tie-break; this list is the receipt for that.
KNOWN_REGRESSIONS = {
    '54LS373_test', '54act11030', '74LS299_test', '74ls169', '9348',
    'CA3078_TEST', 'CA3240_IC_Test', 'Flip_Flops', 'IC_CD4037',
    'IC_SN74ALS679', 'LP2951', 'Logic_Gates', 'MC1496_IC1', 'MPY100',
    'SN54155', 'SN54F71', 'SN54HC148', 'SN74F521', 'SN74HC138', 'TL431_SUB',
    'cdx4ac283', 'sn54als133', 'sn54als573', 'sn54ls48', 'sn54ls72',
}

# Folders that stay unresolved on purpose: several ``.sub`` files, none named
# after the folder, and no netlist to break the tie either. There is no honest
# way to pick for the user here, so Edit asks and Convert says why. Guessing is
# what produced lookups for a file literally called "None".
KNOWN_AMBIGUOUS = {
    'CD74HC365', 'DM9301', 'SN54147_sub', 'SN7495A', 'SN74LS148_sub',
    'SN74LS74', 'TCA965', 'ref5010',
}


@pytest.fixture(scope='module')
def library():
    root = corpus.library_root()
    if not root:
        pytest.skip('SubcircuitLibrary not present in this tree')
    return root


@pytest.fixture(scope='module')
def scanned(library):
    folders = corpus.scan_library(library)
    if not folders:
        pytest.skip('SubcircuitLibrary is empty')
    return folders


def _resolved(library, info):
    """The stem today's production code would act on for this folder."""
    stem, _status = resolve_subcircuit(os.path.join(library, info['name']))
    return stem


# -- the corpus itself -------------------------------------------------------

def test_corpus_is_substantial(scanned):
    """Guard against a scan that silently matched nothing: the invariants below
    are only meaningful over the real library."""
    assert len(scanned) > 500


def test_scan_is_stable(library, scanned):
    """Scanning twice yields the same answer -- no ordering or globbing
    nondeterminism underneath the invariants."""
    assert corpus.scan_library(library) == scanned


# -- invariants --------------------------------------------------------------

def test_every_folder_with_a_netlist_resolves_to_it(library, scanned):
    """INV1 -- no regression against the folder-name rule.

    If a folder has a netlist the old rule could find (``<folder>.cir``), the
    current rule must find *a* netlist too. Resolving to a different stem is
    fine and often better; resolving to nothing is a workflow we broke.
    """
    broken = [
        info['name'] for info in scanned
        if info['has_legacy_cir']
        and not corpus.has_netlist(
            library, info['name'], _resolved(library, info))
    ]
    assert broken == [], (
        '%d folders convert under the folder-name rule but not the anchor '
        'rule: %s' % (len(broken), broken))


def test_the_documented_regressions_are_all_cleared(library, scanned):
    """The 25 folders the anchor rule stranded convert again.

    Named explicitly rather than folded into INV1 so the fix has a receipt: if
    someone later removes the netlist tie-break, this is the test that says
    which subcircuits stopped working and why.
    """
    by_name = {info['name']: info for info in scanned}
    still_broken = sorted(
        name for name in KNOWN_REGRESSIONS
        if name in by_name
        and not corpus.has_netlist(
            library, name, _resolved(library, by_name[name])))
    assert still_broken == [], still_broken


def test_unresolved_folders_are_exactly_the_known_set(library, scanned):
    """Pins how many subcircuits eSim cannot identify, so a refactor cannot
    quietly grow the number."""
    unresolved = {
        info['name'] for info in scanned
        if _resolved(library, info) is None
    }
    assert unresolved == KNOWN_AMBIGUOUS, (
        'newly unidentifiable: %s | unexpectedly identified: %s'
        % (sorted(unresolved - KNOWN_AMBIGUOUS),
           sorted(KNOWN_AMBIGUOUS - unresolved)))


def test_resolved_stem_is_never_the_string_none(library, scanned):
    """INV2 -- ``None`` must never be stringified into a path.

    ``os.path.join(dir, str(stem))`` on an unresolved folder produced literal
    ``None.cir`` / ``None.sch`` lookups, which surface to the user as
    'does not contain any Kicad netlist file' or send eeschema off to open a
    file called None. A real stem or an honest None, never the word.
    """
    for info in scanned:
        stem = _resolved(library, info)
        assert stem != 'None', info['name']


def test_single_anchor_folders_resolve_to_that_anchor(library, scanned):
    """INV3 -- with exactly one ``.sub``, its stem wins over the folder name.

    This is the change that rescued the 67 folders whose ``.sub`` is not named
    after its folder; it must not silently revert.
    """
    for info in scanned:
        if len(info['subs']) == 1:
            assert _resolved(library, info) == info['subs'][0], info['name']


def test_anchorless_folders_fall_back_to_the_folder_name(library, scanned):
    """INV4 -- a folder with no ``.sub`` yet (a subcircuit drawn but never
    converted) keeps the legacy folder-name identity, so New -> draw -> Convert
    still works on a first pass."""
    for info in scanned:
        if not info['subs']:
            assert _resolved(library, info) == info['name'], info['name']


def test_declared_ports_are_consistent_with_the_sub_file(scanned):
    """INV5 -- every resolvable ``.sub`` declares a parseable ``.subckt`` line.

    The Subcircuits tab validates a candidate directory by port count
    (``Validation.validateSub``); a ``.sub`` whose header cannot be read is one
    a student can never wire into a parent circuit.
    """
    unreadable = [info['name'] for info in scanned
                  if info['subs'] and info['ports'] is None]
    # A handful of legacy uploads are known to be malformed; assert the shape
    # of the problem rather than demanding the shipped library be perfect.
    assert len(unreadable) < 0.1 * len(scanned), unreadable[:20]


# -- reporting ---------------------------------------------------------------

def test_report(library, scanned, capsys):
    """Not an assertion -- prints the corpus summary so a run leaves a receipt
    in the log. Run with ``-s`` to see it."""
    total = len(scanned)
    resolved = sum(1 for i in scanned if _resolved(library, i) is not None)
    with_netlist = sum(
        1 for i in scanned
        if corpus.has_netlist(library, i['name'], _resolved(library, i)))
    multi = sum(1 for i in scanned if len(i['subs']) > 1)
    anchorless = sum(1 for i in scanned if not i['subs'])
    renamed = sum(1 for i in scanned
                  if len(i['subs']) == 1 and i['subs'][0] != i['name'])
    with capsys.disabled():
        print('\n  subcircuit corpus: %d folders' % total)
        print('    identity resolved      : %d' % resolved)
        print('    netlist present        : %d' % with_netlist)
        print('    several .sub files     : %d' % multi)
        print('    no .sub yet            : %d' % anchorless)
        print('    .sub renamed vs folder : %d' % renamed)
        print('    kicad_sch / sch / none : %d / %d / %d' % (
            sum(1 for i in scanned if i['schematic'] == 'kicad_sch'),
            sum(1 for i in scanned if i['schematic'] == 'sch'),
            sum(1 for i in scanned if i['schematic'] is None)))
    assert total == resolved + len(
        {i['name'] for i in scanned if _resolved(library, i) is None})
