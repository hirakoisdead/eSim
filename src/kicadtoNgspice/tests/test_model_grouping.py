# ==============================================================================
#  test_model_grouping.py -- unit tests for ModelGrouping (pure, no Qt).
#
#  Run with pytest:    pytest src/kicadtoNgspice/tests/test_model_grouping.py
#  Or standalone:      python3 src/kicadtoNgspice/tests/test_model_grouping.py
# ==============================================================================
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                       # .../src/kicadtoNgspice
for _p in (HERE, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ModelGrouping as MG                         # noqa: E402


# -- model name is the LAST token, robust to node count ------------------------

def test_transistor_model_is_last_token_3_nodes():
    comps = MG.parse_device_components(["q1 c b e eSim_NPN"])
    assert len(comps) == 1
    assert comps[0].ref == "q1"
    assert comps[0].kind == "q"
    assert comps[0].model == "esim_npn"
    assert comps[0].nodes == ["c", "b", "e"]


def test_transistor_model_is_last_token_with_substrate():
    # 4 nodes (substrate): a fixed words[4] index would grab a NODE, not the
    # model. Last-token must still return the model.
    comps = MG.parse_device_components(["q1 c b e s eSim_NPN"])
    assert comps[0].model == "esim_npn"
    assert comps[0].nodes == ["c", "b", "e", "s"]


def test_diode_jfet_mosfet_models():
    lines = [
        "d1 in out D",
        "j1 out g s NJF",
        "m2 d g s b mosfet_n",
    ]
    comps = MG.parse_device_components(lines)
    assert [(c.kind, c.model) for c in comps] == [
        ("d", "d"), ("j", "njf"), ("m", "mosfet_n")]


def test_subcircuit_variable_node_count():
    line = ("x1 " + " ".join("n%d" % i for i in range(16)) + " 74ls48")
    comps = MG.parse_subcircuit_components([line])
    assert len(comps) == 1
    assert comps[0].kind == "x"
    assert comps[0].model == "74ls48"
    assert len(comps[0].nodes) == 16


# -- arity guards mirror DeviceModel.eSim_general_libs -------------------------

def test_too_short_lines_ignored():
    # 'q1 a b NPN' has only 4 tokens; eSim_general_libs requires > 4.
    assert MG.parse_device_components(["q1 a b NPN"]) == []
    # 'd1 a D' has 3 tokens; diode requires > 3.
    assert MG.parse_device_components(["d1 a D"]) == []


def test_non_device_lines_ignored():
    lines = [
        "* a comment",
        "v1 in 0 dc 5",
        "r1 a b 1k",
        "",
        ".tran 1m 10m",
    ]
    assert MG.parse_device_components(lines) == []


def test_subcircuit_parser_ignores_devices():
    assert MG.parse_subcircuit_components(["q1 c b e eSim_NPN"]) == []


# -- grouping ------------------------------------------------------------------

def test_group_buckets_same_model():
    lines = [
        "q1 a b c eSim_NPN",
        "q2 a b c eSim_PNP",
        "q5 a b c eSim_NPN",
        "q6 a b c eSim_PNP",
        "q8 a b c eSim_NPN",
    ]
    groups = MG.group_by_model(MG.parse_device_components(lines))
    npn = groups[("q", "esim_npn")]
    pnp = groups[("q", "esim_pnp")]
    assert [c.ref for c in npn] == ["q1", "q5", "q8"]
    assert [c.ref for c in pnp] == ["q2", "q6"]


def test_group_order_is_first_appearance():
    lines = ["q2 a b c modelb", "q1 a b c modela", "q3 a b c modelb"]
    groups = MG.group_by_model(MG.parse_device_components(lines))
    assert list(groups.keys()) == [("q", "modelb"), ("q", "modela")]


def test_grouping_case_insensitive():
    lines = ["q1 a b c eSim_NPN", "q2 a b c esim_npn", "q3 a b c ESIM_NPN"]
    groups = MG.group_by_model(MG.parse_device_components(lines))
    assert len(groups) == 1
    assert [c.ref for c in groups[("q", "esim_npn")]] == ["q1", "q2", "q3"]


def test_different_kinds_same_name_do_not_collide():
    # Contrived, but proves the key includes kind.
    groups = MG.group_by_model(
        MG.parse_device_components(["d1 a b foo", "q1 a b c foo"]))
    assert ("d", "foo") in groups
    assert ("q", "foo") in groups


# -- standalone runner (no pytest required) ------------------------------------
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
            print("ERROR " + fn.__name__ + "  " + repr(e))
    print("\n==== %d / %d PASS ====" % (len(fns) - failed, len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
