# ==============================================================================
#  test_convert_characterization.py -- the netlist guard for the grouping work.
#
#  Grouping only changes HOW the per-instance deviceModelTrack / subcircuitTrack
#  dicts get filled; Convert (which turns those dicts into netlist lines and
#  .include directives) is deliberately untouched. This pins Convert's output
#  for a known per-ref track, so if a future change to the grouping layer ever
#  feeds Convert something different, the emitted netlist change is caught here.
#
#  It exercises addSubcircuit end-to-end (line rewrite + .include + file copy),
#  the path most directly downstream of the grouped fan-out.
# ==============================================================================
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.dirname(PKG)
for _p in (SRC, PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kicadtoNgspice import Convert, TrackWidget               # noqa: E402
from kicadtoNgspice import Processing                          # noqa: E402


def test_two_adjacent_ic_components_are_both_processed():
    # convertICintoBasicBlocks removes each u* line and reinserts a comment
    # while walking schematicInfo. Two ADJACENT u* components is the case a
    # mutate-during-iteration bug would drop the second of -- pin that both
    # survive into modelList and get commented out of the netlist body.
    proc = Processing.PrcocessNetlist()
    schematic = ["u1 1 ic", "u2 2 ic"]      # 'ic' branch: no XML/lib lookup
    out_sch, _out_opt, model_list, unknown, multiple, _plot = \
        proc.convertICintoBasicBlocks(list(schematic), [], [], [])

    # Both ICs produced a model entry (compName is field index 3).
    ref_names = {entry[3] for entry in model_list}
    assert ref_names == {"u1", "u2"}, ref_names

    # Both original lines were commented out (not left live, not dropped).
    assert "* u1 1 ic" in out_sch
    assert "* u2 2 ic" in out_sch
    assert unknown == [] and multiple == []


def test_modelparamxml_indexed_with_a_single_walk(monkeypatch):
    # modelParamXML is now indexed ONCE up front, so N model components cost
    # one os.walk, not one per component. Count walks while converting several
    # ICs (unknown model type -> no XML parse, just the index build walk).
    calls = {"n": 0}
    real_walk = os.walk

    def counting_walk(path):
        calls["n"] += 1
        return real_walk(path)

    monkeypatch.setattr(Processing.os, "walk", counting_walk)
    proc = Processing.PrcocessNetlist()
    schematic = ["u1 1 2 zzznotamodel",
                 "u2 3 4 zzznotamodel",
                 "u3 5 6 zzznotamodel"]
    _s, _o, _m, unknown, _mult, _p = \
        proc.convertICintoBasicBlocks(list(schematic), [], [], [])
    assert calls["n"] == 1, calls["n"]
    assert unknown.count("zzznotamodel") == 3


def _sub_dir(name, nports):
    d = tempfile.mkdtemp(prefix="esim_char_")
    sub = os.path.join(d, name)
    os.makedirs(sub)
    ports = " ".join(str(i) for i in range(nports))
    with open(os.path.join(sub, name + ".sub"), "w") as f:
        f.write(".subckt %s %s\n.ends %s\n" % (name, ports, name))
    return sub


def _convert(schematic, kicad_file, track):
    return Convert.Convert(None, None, list(schematic), kicad_file, track)


def test_grouped_subcircuit_fanout_produces_one_include_and_rewrites_lines():
    sub = _sub_dir("myamp", 3)                       # dir basename != model tok
    proj = tempfile.mkdtemp(prefix="esim_proj_")
    kicad_file = os.path.join(proj, "proj.cir")
    try:
        schematic = ["x1 a b c lm_741", "x2 d e f lm_741"]
        # The converter's shared data bus, filled as the grouped tab would:
        # same dir for both instances.
        track = TrackWidget.TrackWidget()
        track.subcircuitTrack = {"x1": sub, "x2": sub}
        # subcircuitList must match in length (Convert's "all specified" guard).
        track.subcircuitList = {
            "projx1": schematic[0].split(),
            "projx2": schematic[1].split(),
        }

        conv = _convert(schematic, kicad_file, track)
        out = conv.addSubcircuit(list(schematic), kicad_file)

        # Exactly one .include despite two instances (Convert dedups).
        includes = [ln for ln in out if ln.startswith(".include")]
        assert includes == [".include myamp.sub"], includes

        # Both instance lines had their model token rewritten to the dir name.
        body = [ln for ln in out if ln and not ln.startswith(".include")]
        assert body[0].split()[-1] == "myamp"
        assert body[1].split()[-1] == "myamp"
        assert body[0].split()[0] == "x1"
        assert body[1].split()[0] == "x2"

        # The subcircuit file was copied into the project dir.
        assert os.path.exists(os.path.join(proj, "myamp.sub"))
    finally:
        shutil.rmtree(sub, ignore_errors=True)
        shutil.rmtree(proj, ignore_errors=True)


# -- standalone runner ---------------------------------------------------------
def _main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
