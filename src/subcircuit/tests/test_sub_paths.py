# ==============================================================================
#  test_sub_paths.py -- unit tests for subcircuit identity resolution.
#
#  The corpus test proves the rules hold across the shipped library; these prove
#  each rule in isolation, including the cases the library happens not to
#  contain (a stale remembered stem, a folder that does not exist).
# ==============================================================================
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from subcircuit import subPaths                                  # noqa: E402


def _touch(folder, *names):
    for name in names:
        with open(os.path.join(str(folder), name), 'w') as fh:
            fh.write('* test\n')


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / 'half_adder'
    d.mkdir()
    return str(d)


# -- resolve_subcircuit ------------------------------------------------------

def test_single_anchor_wins_over_folder_name(tmp_path):
    d = tmp_path / '74HC123'
    d.mkdir()
    _touch(d, 'multivibrator.sub', 'multivibrator.cir')
    assert subPaths.resolve_subcircuit(str(d)) == ('multivibrator', 'anchor')


def test_folder_name_match_wins_among_several_anchors(tmp_path):
    d = tmp_path / '2bitmul'
    d.mkdir()
    _touch(d, '2bitmul.sub', 'half_adder.sub')
    assert subPaths.resolve_subcircuit(str(d)) == ('2bitmul', 'folder-match')


def test_netlist_breaks_the_tie_when_no_anchor_matches(tmp_path):
    """The 25-folder regression: several nested models, none named after the
    folder, but the folder's own netlist is right there."""
    d = tmp_path / 'Logic_Gates'
    d.mkdir()
    _touch(d, 'and2.sub', 'or2.sub', 'Logic_Gates.cir')
    assert subPaths.resolve_subcircuit(str(d)) == ('Logic_Gates', 'netlist')


def test_genuinely_ambiguous_folder_yields_no_stem(tmp_path):
    d = tmp_path / 'TCA965'
    d.mkdir()
    _touch(d, 'a.sub', 'b.sub')
    stem, status = subPaths.resolve_subcircuit(str(d))
    assert stem is None and status == 'ambiguous'


def test_never_returns_the_string_none(tmp_path):
    """Guards the specific defect: a None stem stringified into a path made
    eSim look for 'None.cir' and open 'None.sch'."""
    d = tmp_path / 'amb'
    d.mkdir()
    _touch(d, 'a.sub', 'b.sub')
    stem, _ = subPaths.resolve_subcircuit(str(d))
    assert stem is None
    assert stem != 'None'


def test_new_subcircuit_without_any_sub_uses_the_folder_name(folder):
    """A subcircuit that has been drawn but never converted has no .sub -- that
    file is Convert's output. The folder name has to stay a valid identity or
    New -> draw -> Convert can never complete a first pass."""
    _touch(folder, 'half_adder.sch')
    assert subPaths.resolve_subcircuit(folder) == ('half_adder', 'fallback')


def test_empty_folder_still_resolves_to_its_own_name(folder):
    assert subPaths.resolve_subcircuit(folder) == ('half_adder', 'fallback')


def test_missing_directory_is_reported_not_guessed(tmp_path):
    stem, status = subPaths.resolve_subcircuit(str(tmp_path / 'nope'))
    assert stem is None and status == 'nodir'


def test_none_folder_is_safe():
    assert subPaths.resolve_subcircuit(None) == (None, 'nodir')


# -- preferred stem ----------------------------------------------------------

def test_preferred_stem_wins_when_it_exists(tmp_path):
    """Edit's choice is authoritative: the user picked half_adder inside the
    2bitmul folder, so Convert must rebuild half_adder, not 2bitmul."""
    d = tmp_path / '2bitmul'
    d.mkdir()
    _touch(d, '2bitmul.sub', 'half_adder.sub')
    assert subPaths.resolve_subcircuit(str(d), preferred='half_adder') == \
        ('half_adder', 'preferred')


def test_stale_preferred_stem_is_ignored(tmp_path):
    """A remembered stem from another subcircuit must not rename this one."""
    d = tmp_path / '2bitmul'
    d.mkdir()
    _touch(d, '2bitmul.sub')
    assert subPaths.resolve_subcircuit(str(d), preferred='lm741') == \
        ('2bitmul', 'anchor')


def test_preferred_stem_counts_when_only_a_schematic_exists(tmp_path):
    """A subcircuit being drawn for the first time has no .sub yet; the name
    the user typed in New is still a real identity."""
    d = tmp_path / 'work'
    d.mkdir()
    _touch(d, 'my_block.kicad_sch')
    assert subPaths.resolve_subcircuit(str(d), preferred='my_block') == \
        ('my_block', 'preferred')


# -- derived paths -----------------------------------------------------------

def test_schematic_prefers_kicad6_over_kicad4(folder):
    _touch(folder, 'half_adder.sch', 'half_adder.kicad_sch')
    assert subPaths.schematic_path(folder, 'half_adder').endswith('.kicad_sch')


def test_schematic_falls_back_to_kicad4(folder):
    _touch(folder, 'half_adder.sch')
    assert subPaths.schematic_path(folder, 'half_adder').endswith('.sch')
    assert not subPaths.schematic_path(
        folder, 'half_adder').endswith('.kicad_sch')


def test_schematic_for_a_new_subcircuit_is_the_modern_extension(folder):
    assert subPaths.schematic_path(folder, 'half_adder').endswith('.kicad_sch')


def test_netlist_and_model_paths(folder):
    assert subPaths.netlist_path(folder, 'x').endswith('x.cir')
    assert subPaths.model_path(folder, 'x').endswith('x.sub')


# -- chooser support ---------------------------------------------------------

def test_list_stems_offers_every_sub_plus_the_folders_own(tmp_path):
    d = tmp_path / '2bitmul'
    d.mkdir()
    _touch(d, 'half_adder.sub', 'full_adder.sub', '2bitmul.cir')
    assert subPaths.list_stems(str(d)) == ['2bitmul', 'full_adder',
                                           'half_adder']


def test_list_stems_of_an_untouched_folder_is_empty(folder):
    assert subPaths.list_stems(folder) == []


def test_stem_exists_checks_only_this_folder(tmp_path, folder):
    _touch(tmp_path, 'elsewhere.sub')
    assert not subPaths.stem_exists(folder, 'elsewhere')
    _touch(folder, 'here.cir')
    assert subPaths.stem_exists(folder, 'here')


# -- library scan (feeds the picker) -----------------------------------------

def test_scan_library_reports_build_state(tmp_path):
    lib = tmp_path / 'SubcircuitLibrary'
    lib.mkdir()
    drawn = lib / 'drawn'
    drawn.mkdir()
    _touch(drawn, 'drawn.kicad_sch')
    built = lib / 'built'
    built.mkdir()
    _touch(built, 'built.kicad_sch', 'built.cir', 'built.sub')

    rows = {r['name']: r for r in subPaths.scan_library(str(lib))}
    assert rows['drawn']['has_schematic'] and not rows['drawn']['has_model']
    assert rows['built']['has_model'] and rows['built']['has_netlist']
    assert rows['built']['stem'] == 'built'


def test_scan_library_of_a_missing_root_is_empty(tmp_path):
    assert subPaths.scan_library(str(tmp_path / 'nope')) == []
