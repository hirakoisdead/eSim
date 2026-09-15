# ==============================================================================
#  test_devicemodel_grouping.py -- integration tests for the grouped Device
#  Modeling tab (DeviceModel.eSim_general_libs).
#
#  Builds the real DeviceModel widget headless (Qt offscreen) and checks that
#  grouping fans a library choice out to every instance via the per-ref
#  deviceModelTrack that Convert reads, that MOSFET W/L/M stay per-instance,
#  that the switch branch (which used to reference an undefined `root`) works,
#  and that Previous_Values.xml restore + the path-exists guard round-trip.
# ==============================================================================
import os
import sys
import tempfile
from xml.etree import ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                       # .../src/kicadtoNgspice
SRC = os.path.dirname(PKG)                        # .../src
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6 import QtWidgets                                    # noqa: E402
from kicadtoNgspice import DeviceModel                        # noqa: E402
from kicadtoNgspice.ModelGroupWidget import ModelGroupWidget  # noqa: E402
from projManagement.projectPaths import previous_values_path  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _build(schematic, kicad_file):
    return DeviceModel.DeviceModel(schematic, kicad_file)


def _groups(dm):
    """Map model title -> ModelGroupWidget for the built tab."""
    out = {}
    for w in dm.findChildren(ModelGroupWidget):
        out[w._title_text] = w
    return out


def _group_with_ref(dm, ref):
    for w in dm.findChildren(ModelGroupWidget):
        if any(r.ref == ref for r in w._rows):
            return w
    raise KeyError(ref)


def _tmp_cir():
    d = tempfile.mkdtemp(prefix="esim_dm_")
    return os.path.join(d, "proj.cir")


# -- grouping + fan-out --------------------------------------------------------

def test_same_model_transistors_form_one_group():
    schematic = [
        "q1 a b c eSim_NPN",
        "q2 a b c eSim_NPN",
        "q3 a b c eSim_PNP",
        "q4 a b c eSim_NPN",
    ]
    dm = _build(schematic, _tmp_cir())
    titles = list(_groups(dm))
    assert any("eSim_NPN".lower() in t.lower() for t in titles)
    assert any("eSim_PNP".lower() in t.lower() for t in titles)
    npn = _group_with_ref(dm, "q1")
    assert sorted(r.ref for r in npn._rows) == ["q1", "q2", "q4"]


def test_group_assign_fans_out_to_deviceModelTrack():
    schematic = ["q1 a b c eSim_NPN", "q2 a b c eSim_NPN",
                 "q5 a b c eSim_NPN"]
    dm = _build(schematic, _tmp_cir())
    grp = _group_with_ref(dm, "q1")
    grp.set_group_path("/lib/bc547.lib")
    track = dm.obj_trac.deviceModelTrack
    assert track["q1"] == "/lib/bc547.lib"
    assert track["q2"] == "/lib/bc547.lib"
    assert track["q5"] == "/lib/bc547.lib"


def test_override_one_instance_only():
    schematic = ["q1 a b c eSim_NPN", "q2 a b c eSim_NPN"]
    dm = _build(schematic, _tmp_cir())
    grp = _group_with_ref(dm, "q1")
    grp.set_group_path("/lib/a.lib")
    grp.override("q2", "/lib/special.lib")
    track = dm.obj_trac.deviceModelTrack
    assert track["q1"] == "/lib/a.lib"
    assert track["q2"] == "/lib/special.lib"


def test_empty_path_is_not_tracked():
    # An instance left blank must not appear in deviceModelTrack (Convert would
    # otherwise try to .include an empty library).
    schematic = ["q1 a b c eSim_NPN"]
    dm = _build(schematic, _tmp_cir())
    grp = _group_with_ref(dm, "q1")
    grp.set_group_path("/lib/a.lib")
    assert "q1" in dm.obj_trac.deviceModelTrack
    grp.set_group_path("")
    assert "q1" not in dm.obj_trac.deviceModelTrack


# -- MOSFET keeps W/L/M per instance ------------------------------------------

def test_mosfet_groups_lib_but_keeps_per_instance_dims():
    schematic = ["m1 d g s b eSim_MOS_N", "m2 d g s b eSim_MOS_N"]
    dm = _build(schematic, _tmp_cir())
    grp = _group_with_ref(dm, "m1")
    grp.set_group_path("/lib/nmos.lib")
    # Give m1 a custom width via its per-instance extra widget.
    beg1 = dm.devicemodel_dict_beg["m1"]
    dm.entry_var[beg1 + 1].setText("10u")          # W of m1
    track = dm.obj_trac.deviceModelTrack
    assert track["m1"] == "/lib/nmos.lib:W=10u L=100u M=1"
    assert track["m2"] == "/lib/nmos.lib:W=100u L=100u M=1"


# -- switch branch (formerly an undefined-`root` NameError) --------------------

def test_switch_branch_builds_and_groups():
    schematic = ["s1 a b c d sw_model", "s2 a b c d sw_model"]
    dm = _build(schematic, _tmp_cir())
    grp = _group_with_ref(dm, "s1")
    assert sorted(r.ref for r in grp._rows) == ["s1", "s2"]
    grp.set_group_path("/lib/sw.lib")
    track = dm.obj_trac.deviceModelTrack
    assert track["s1"] == "/lib/sw.lib"
    assert track["s2"] == "/lib/sw.lib"


# -- Previous_Values.xml restore + exists guard -------------------------------

def _write_prevvalues(kicad_file, entries):
    """entries: {ref: [field_text, ...]}; write a devicemodel cache file."""
    root = ET.Element("KicadtoNgspice")
    dm = ET.SubElement(root, "devicemodel")
    for ref, fields in entries.items():
        node = ET.SubElement(dm, ref)
        for txt in fields:
            ET.SubElement(node, "field").text = txt
    path = previous_values_path(kicad_file)
    ET.ElementTree(root).write(path)
    return path


def test_restore_keeps_existing_path_blanks_missing():
    real_lib = tempfile.NamedTemporaryFile(
        suffix=".lib", delete=False).name
    try:
        cir = _tmp_cir()
        _write_prevvalues(cir, {
            "q1": [real_lib],
            "q2": ["/does/not/exist.lib"],
        })
        dm = _build(["q1 a b c eSim_NPN", "q2 a b c eSim_NPN"], cir)
        b1 = dm.devicemodel_dict_beg["q1"]
        b2 = dm.devicemodel_dict_beg["q2"]
        assert dm.entry_var[b1].text() == real_lib       # exists -> kept
        assert dm.entry_var[b2].text() == ""             # missing -> blanked
        track = dm.obj_trac.deviceModelTrack
        assert track.get("q1") == real_lib
        assert "q2" not in track                          # blanked -> untracked
        # Both share the same restored value? Only q1 has one, so the group is
        # mixed -> expanded with q1 overridden.
        grp = _group_with_ref(dm, "q1")
        assert grp.is_expanded()
        assert grp.is_overridden("q1")
        os.remove(previous_values_path(cir))
    finally:
        os.remove(real_lib)


def test_restore_uniform_becomes_group_default():
    real_lib = tempfile.NamedTemporaryFile(
        suffix=".lib", delete=False).name
    try:
        cir = _tmp_cir()
        _write_prevvalues(cir, {"q1": [real_lib], "q2": [real_lib]})
        dm = _build(["q1 a b c eSim_NPN", "q2 a b c eSim_NPN"], cir)
        grp = _group_with_ref(dm, "q1")
        assert grp.group_path() == real_lib
        assert not grp.is_overridden("q1")
        assert not grp.is_overridden("q2")
        os.remove(previous_values_path(cir))
    finally:
        os.remove(real_lib)


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
