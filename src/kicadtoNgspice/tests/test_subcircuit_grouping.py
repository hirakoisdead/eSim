# ==============================================================================
#  test_subcircuit_grouping.py -- integration tests for the grouped Subcircuits
#  tab (SubcircuitTab).
#
#  Builds the real tab headless (Qt offscreen) and checks grouping/fan-out via
#  the per-ref subcircuitTrack that Convert reads, the subcircuitList count
#  contract Convert validates against, override isolation, and Previous_Values
#  restore with the exists guard + exact-ref match (x1 must not match x10).
# ==============================================================================
import os
import sys
import shutil
import tempfile
from xml.etree import ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6 import QtWidgets                                    # noqa: E402
from kicadtoNgspice import SubcircuitTab                       # noqa: E402
from kicadtoNgspice.ModelGroupWidget import ModelGroupWidget   # noqa: E402
from projManagement.projectPaths import previous_values_path   # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _build(schematic, kicad_file):
    return SubcircuitTab.SubcircuitTab(schematic, kicad_file)


def _group_with_ref(tab, ref):
    for w in tab.findChildren(ModelGroupWidget):
        if any(r.ref == ref for r in w._rows):
            return w
    raise KeyError(ref)


def _tmp_cir():
    d = tempfile.mkdtemp(prefix="esim_sub_")
    return os.path.join(d, "proj.cir")


def _line(ref, nports, name):
    return ref + " " + " ".join("n%d" % i for i in range(nports)) + " " + name


# -- grouping + fan-out --------------------------------------------------------

def test_same_subcircuit_groups_and_fans_out():
    schematic = [_line("x1", 5, "lm_741"),
                 _line("x2", 5, "lm_741"),
                 _line("x3", 5, "lm_741")]
    tab = _build(schematic, _tmp_cir())
    grp = _group_with_ref(tab, "x1")
    assert sorted(r.ref for r in grp._rows) == ["x1", "x2", "x3"]
    grp.set_group_path("/subs/lm741")
    track = tab.obj_trac.subcircuitTrack
    assert track["x1"] == track["x2"] == track["x3"] == "/subs/lm741"


def test_override_one_subcircuit():
    schematic = [_line("x1", 3, "buf"), _line("x2", 3, "buf")]
    tab = _build(schematic, _tmp_cir())
    grp = _group_with_ref(tab, "x1")
    grp.set_group_path("/subs/buf")
    grp.override("x2", "/subs/buf_alt")
    track = tab.obj_trac.subcircuitTrack
    assert track["x1"] == "/subs/buf"
    assert track["x2"] == "/subs/buf_alt"


def test_empty_not_tracked():
    tab = _build([_line("x1", 3, "buf")], _tmp_cir())
    grp = _group_with_ref(tab, "x1")
    grp.set_group_path("/subs/buf")
    assert "x1" in tab.obj_trac.subcircuitTrack
    grp.set_group_path("")
    assert "x1" not in tab.obj_trac.subcircuitTrack


def test_subcircuitList_count_matches_when_all_assigned():
    # Convert compares len(subcircuitList) to len(subcircuitTrack); every
    # instance must register in both.
    schematic = [_line("x1", 4, "a"), _line("x2", 4, "a"),
                 _line("x3", 2, "b")]
    tab = _build(schematic, _tmp_cir())
    assert len(tab.obj_trac.subcircuitList) == 3
    for ref in ("x1", "x2", "x3"):
        _group_with_ref(tab, ref).set_group_path("/subs/x")
    assert (len(tab.obj_trac.subcircuitList)
            == len(tab.obj_trac.subcircuitTrack) == 3)


# -- restore: exists guard + exact-ref match ----------------------------------

def _write_prevvalues(kicad_file, entries):
    root = ET.Element("KicadtoNgspice")
    sub = ET.SubElement(root, "subcircuit")
    for ref, path in entries.items():
        node = ET.SubElement(sub, ref)
        ET.SubElement(node, "field").text = path
    p = previous_values_path(kicad_file)
    ET.ElementTree(root).write(p)
    return p


def test_restore_exact_ref_no_x1_x10_collision():
    real_dir = tempfile.mkdtemp(prefix="esim_realsub_")
    try:
        cir = _tmp_cir()
        # Only x1 has a remembered value; x10 must NOT inherit it.
        _write_prevvalues(cir, {"x1": real_dir})
        tab = _build([_line("x1", 3, "buf"), _line("x10", 3, "buf")], cir)
        b1 = tab.subcircuit_dict_beg["x1"]
        b10 = tab.subcircuit_dict_beg["x10"]
        assert tab.entry_var[b1].text() == real_dir
        assert tab.entry_var[b10].text() == ""        # exact match, no bleed
        os.remove(previous_values_path(cir))
    finally:
        shutil.rmtree(real_dir, ignore_errors=True)


def test_restore_blanks_missing_dir():
    cir = _tmp_cir()
    _write_prevvalues(cir, {"x1": "/no/such/subdir"})
    tab = _build([_line("x1", 3, "buf")], cir)
    b1 = tab.subcircuit_dict_beg["x1"]
    assert tab.entry_var[b1].text() == ""
    assert "x1" not in tab.obj_trac.subcircuitTrack
    os.remove(previous_values_path(cir))


def test_restore_uniform_becomes_group_default():
    real_dir = tempfile.mkdtemp(prefix="esim_realsub_")
    try:
        cir = _tmp_cir()
        _write_prevvalues(cir, {"x1": real_dir, "x2": real_dir})
        tab = _build([_line("x1", 3, "buf"), _line("x2", 3, "buf")], cir)
        grp = _group_with_ref(tab, "x1")
        assert grp.group_path() == real_dir
        assert not grp.is_overridden("x1")
        assert not grp.is_overridden("x2")
        os.remove(previous_values_path(cir))
    finally:
        shutil.rmtree(real_dir, ignore_errors=True)


# -- standalone runner ---------------------------------------------------------
def _main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS  " + fn.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL  " + fn.__name__ + "  " + str(e))
        except Exception as e:                       # noqa: BLE001
            failed += 1
            import traceback
            print("ERROR " + fn.__name__ + "  " + repr(e))
            traceback.print_exc()
    print("\n==== %d / %d PASS ====" % (len(fns) - failed, len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
