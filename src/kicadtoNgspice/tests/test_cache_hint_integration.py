# ==============================================================================
#  test_cache_hint_integration.py -- the cross-project model_cache hint as the
#  Device Modeling / Subcircuits tabs actually use it.
#
#  HOME is redirected to a temp dir so both the model_cache and the relocated
#  Previous_Values cache stay out of the real ~/.esim.
# ==============================================================================
import os
import sys
import shutil
import tempfile
from xml.etree import ElementTree as ET

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_TMP_HOME = tempfile.mkdtemp(prefix="esim_home_")
os.environ["HOME"] = _TMP_HOME

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6 import QtWidgets                                    # noqa: E402
from kicadtoNgspice import DeviceModel, SubcircuitTab         # noqa: E402
from kicadtoNgspice.ModelGroupWidget import ModelGroupWidget   # noqa: E402
from projManagement import modelCache                          # noqa: E402
from projManagement.projectPaths import previous_values_path   # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _reset_cache():
    p = os.path.join(_TMP_HOME, ".esim", "model_cache.json")
    if os.path.exists(p):
        os.remove(p)


def _group_with_ref(tab, ref):
    for w in tab.findChildren(ModelGroupWidget):
        if any(r.ref == ref for r in w._rows):
            return w
    raise KeyError(ref)


def _tmp_cir():
    return os.path.join(tempfile.mkdtemp(prefix="esim_cache_"), "proj.cir")


def _real_lib():
    return tempfile.NamedTemporaryFile(suffix=".lib", delete=False).name


def _build_dm(schematic, cir):
    return DeviceModel.DeviceModel(schematic, cir)


def _write_prevvalues_device(cir, entries):
    root = ET.Element("KicadtoNgspice")
    dm = ET.SubElement(root, "devicemodel")
    for ref, fields in entries.items():
        node = ET.SubElement(dm, ref)
        for txt in fields:
            ET.SubElement(node, "field").text = txt
    ET.ElementTree(root).write(previous_values_path(cir))


# -- device hint ---------------------------------------------------------------

def test_cache_hint_prefills_blank_group():
    _reset_cache()
    lib = _real_lib()
    try:
        modelCache.remember("eSim_NPN", lib)
        dm = _build_dm(["q1 a b c eSim_NPN", "q2 a b c eSim_NPN"], _tmp_cir())
        grp = _group_with_ref(dm, "q1")
        assert grp.group_path() == lib
        track = dm.obj_trac.deviceModelTrack
        assert track["q1"] == lib and track["q2"] == lib
    finally:
        os.remove(lib)


def test_prevvalues_wins_over_cache():
    _reset_cache()
    cache_lib, proj_lib = _real_lib(), _real_lib()
    try:
        modelCache.remember("eSim_NPN", cache_lib)
        cir = _tmp_cir()
        _write_prevvalues_device(cir, {"q1": [proj_lib], "q2": [proj_lib]})
        dm = _build_dm(["q1 a b c eSim_NPN", "q2 a b c eSim_NPN"], cir)
        grp = _group_with_ref(dm, "q1")
        # The project's own remembered value, not the global cache, is used.
        assert grp.group_path() == proj_lib
        os.remove(previous_values_path(cir))
    finally:
        os.remove(cache_lib)
        os.remove(proj_lib)


def test_missing_cached_path_not_applied():
    _reset_cache()
    lib = _real_lib()
    modelCache.remember("eSim_NPN", lib)
    os.remove(lib)                       # remembered path no longer exists
    dm = _build_dm(["q1 a b c eSim_NPN"], _tmp_cir())
    grp = _group_with_ref(dm, "q1")
    assert grp.group_path() == ""        # silently dropped, blank not wrong


def test_remembered_models_reports_uniform_groups():
    _reset_cache()
    dm = _build_dm(["q1 a b c eSim_NPN", "q2 a b c eSim_NPN",
                    "q3 a b c eSim_PNP"], _tmp_cir())
    _group_with_ref(dm, "q1").set_group_path("/lib/npn.lib")
    _group_with_ref(dm, "q3").set_group_path("/lib/pnp.lib")
    learned = dm.remembered_models()
    assert learned == {"esim_npn": "/lib/npn.lib", "esim_pnp": "/lib/pnp.lib"}


# -- subcircuit hint must respect ports ----------------------------------------

def _make_sub_dir(nports):
    d = tempfile.mkdtemp(prefix="esim_sub_")
    ports = " ".join(str(i) for i in range(nports))
    with open(os.path.join(d, "foo.sub"), "w") as f:
        f.write(".subckt foo %s\n.ends foo\n" % ports)
    return d


def _line(ref, nports, name):
    return ref + " " + " ".join("n%d" % i for i in range(nports)) + " " + name


def test_subcircuit_hint_applied_when_ports_match():
    _reset_cache()
    sub_dir = _make_sub_dir(3)
    try:
        modelCache.remember("foo", sub_dir)
        tab = SubcircuitTab.SubcircuitTab(
            [_line("x1", 3, "foo"), _line("x2", 3, "foo")], _tmp_cir())
        grp = _group_with_ref(tab, "x1")
        assert grp.group_path() == sub_dir
    finally:
        shutil.rmtree(sub_dir, ignore_errors=True)


def test_subcircuit_hint_skipped_when_ports_mismatch():
    _reset_cache()
    sub_dir = _make_sub_dir(3)           # subckt declares 3 ports
    try:
        modelCache.remember("foo", sub_dir)
        # Instance uses 4 ports -> hint must NOT be applied.
        tab = SubcircuitTab.SubcircuitTab([_line("x1", 4, "foo")], _tmp_cir())
        grp = _group_with_ref(tab, "x1")
        assert grp.group_path() == ""
    finally:
        shutil.rmtree(sub_dir, ignore_errors=True)


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
