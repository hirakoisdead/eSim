"""Integration: the guards actually reach the netlist eSim writes.

test_dcosim_netlist.py proves the two transforms in isolation. This file drives
the real ``MainWindow.createNetlistFile`` -- the single funnel every conversion
goes through -- and reads the ``.cir.out`` it leaves on disk, so a fix that is
correct but not wired up cannot pass.

The instance is built with ``__new__`` and given only the seven attributes the
method touches (``optionInfo``, ``outputOption``, ``kicadFile``, ``infoline``,
``obj_appconfig``, ``modelList``, ``microcontrollerList``). That is the whole
input surface: no schematic parse, no Qt window, no dialogs.
"""
import pytest

from configuration.Appconfig import Appconfig
from kicadtoNgspice.KicadtoNgspice import MainWindow

# schematicInfo as Convert leaves it: a-devices, then the .model cards.
COSIM_NETLIST = [
    'v1 clk_a gnd pulse(0 5 0 1u 1u 0.5m 1m)',
    'a1 [clk_a rst_a] [clk_d rst_d] u1',
    'a2 [clk_d rst_d] [cnt0_d] u2',
    'a3 [cnt0_d] [cnt0] u3',
    '.model u1 adc_bridge(in_low=1.0 in_high=2.0 rise_delay=1.0e-9 ) ',
    '.model u2 d_cosim simulation="ivlng" sim_args=["counter"] ',
    '.model u3 dac_bridge(out_low=0.0 out_high=5.0 ) ',
]

#: modelList rows are [index, compline, modelname, card, comment, title, type,
#: params] -- only the card name and the type matter here.
def model_row(card, mtype, modelname='counter'):
    return [0, '', modelname, card, '', '', mtype, {}]


@pytest.fixture
def converter(tmp_path):
    """A MainWindow with just enough state to run createNetlistFile.

    No QApplication: the method is pure file work, which is exactly why it is
    the right seam to test the wiring at."""
    project = tmp_path / "tb.cir"
    project.write_text("* tb\n")
    (tmp_path / "analysis").write_text(".tran 10e-06 15e-03 0e-00\n")

    window = MainWindow.__new__(MainWindow)
    window.kicadFile = str(project)
    window.infoline = "* tb"
    window.optionInfo = []
    window.outputOption = []
    window.modelList = []
    window.microcontrollerList = []
    window.obj_appconfig = Appconfig()
    return window, project


def written(project):
    with open(str(project) + ".out") as fh:
        return fh.read()


def test_a_d_cosim_netlist_keeps_the_adc_bridge_card_2_5_wrote(converter):
    """The converter must not touch adc_bridge, for any backend.

    collapse_adc_band_for_hdl() would rewrite in_low/in_high to their midpoint
    here, and it is a correct fix for a real defect (NGVERI_ACCURACY D1/D5) --
    but it changes numbers eSim 2.5 produced, so it is parked pending a
    maintainer decision (docs/UPSTREAM_DECISIONS.md item 1). This test is the
    guard on that decision: if the pass is ever wired back in silently, it
    fails here."""
    window, project = converter
    window.createNetlistFile(list(COSIM_NETLIST), [])

    text = written(project)
    assert 'in_low=1.0 in_high=2.0' in text
    assert '1.5' not in text
    assert 'rise_delay=1.0e-9' in text
    assert 'd_cosim' in text


def test_an_ngveri_block_named_in_modellist_is_untouched_too(converter):
    """The Verilator backend cannot be spotted in the netlist text -- the card
    type is the HDL entity name -- so a pass that wanted to find it would have
    to read modelList. Nothing does, and the netlist must come out as 2.5."""
    window, project = converter
    netlist = [ln.replace('.model u2 d_cosim simulation="ivlng" '
                          'sim_args=["counter"] ',
                          '.model u2 counter(instance_id=1 ) ')
               for ln in COSIM_NETLIST]
    window.modelList = [model_row('u2', 'Ngveri')]
    window.createNetlistFile(netlist, [])

    assert 'in_low=1.0 in_high=2.0' in written(project)


def test_an_nghdl_block_from_the_microcontroller_list_is_untouched(converter):
    """Nghdl rows are moved out of modelList during the parse. Same guard: a
    VHDL block's analog boundary is 2.5's, unchanged."""
    window, project = converter
    netlist = [ln.replace('.model u2 d_cosim simulation="ivlng" '
                          'sim_args=["counter"] ',
                          '.model u2 counter(instance_id=1 ) ')
               for ln in COSIM_NETLIST]
    window.microcontrollerList = [model_row('u2', 'Nghdl')]
    window.createNetlistFile(netlist, [])

    assert 'in_low=1.0 in_high=2.0' in written(project)


def test_a_plain_analog_netlist_is_untouched(converter):
    window, project = converter
    netlist = [ln for ln in COSIM_NETLIST if 'd_cosim' not in ln]
    netlist = [ln for ln in netlist if not ln.startswith('a2')]
    window.createNetlistFile(netlist, [])

    assert 'in_low=1.0 in_high=2.0' in written(project)


def test_two_cosim_blocks_are_merged_into_one_device(converter, monkeypatch):
    """Icarus's engine is process-global, so two d_cosim devices segfault
    ngspice. The converter therefore emits ONE device running a wrapper that
    instantiates both blocks, with the node vectors concatenated."""
    from maker import cosim_merge
    from kicadtoNgspice import KicadtoNgspice as ktn

    ports = [('clk', 'input', 1), ('rst', 'input', 1), ('cnt0', 'output', 1)]
    monkeypatch.setattr(cosim_merge, 'model_ports', lambda _m: ports)
    built = {}
    monkeypatch.setattr(cosim_merge, 'build_merged_vvp',
                        lambda blocks, workdir, log=None:
                        built.setdefault('blocks', blocks))

    window, project = converter
    netlist = COSIM_NETLIST + ['a4 [clk_d rst_d] [cnt1_d] u2']
    window.createNetlistFile(netlist, [])

    text = written(project)
    # One d_cosim card, holding both blocks' nodes: a2's inputs then a4's,
    # then a2's outputs then a4's -- the order the wrapper declares its ports.
    assert text.count('d_cosim') == 1
    assert ('a_esim_cosim [clk_d rst_d clk_d rst_d] [cnt0_d cnt1_d] '
            + ktn.MERGED_CARD) in text
    assert 'sim_args=["%s"]' % cosim_merge.MERGED_VVP in text
    # Both schematic instances reach the wrapper builder under their own
    # a-device names. Labelling them by .model card instead would give both
    # copies the same name AND the same nodes -- they share the card.
    assert [b[0] for b in built['blocks']] == ['a2', 'a4']


def test_a_merge_failure_stops_the_conversion(converter, monkeypatch):
    """A merge that cannot be done correctly must not write a netlist: every
    alternative ends in a simulation that runs and is wrong."""
    from maker import cosim_merge

    def boom(_model):
        raise cosim_merge.MergeError("port list for \"counter\" is empty")

    monkeypatch.setattr(cosim_merge, 'model_ports', boom)

    window, project = converter
    netlist = COSIM_NETLIST + ['a4 [clk_d rst_d] [cnt1_d] u2']

    with pytest.raises(RuntimeError) as excinfo:
        window.createNetlistFile(netlist, [])

    assert "counter" in str(excinfo.value)
    import os
    assert not os.path.exists(str(project) + ".out")


def test_a_single_cosim_block_is_left_alone(converter):
    """Nothing to merge: the per-model vvp the build produced is used as-is,
    and the netlist keeps the card the converter wrote."""
    window, project = converter
    window.createNetlistFile(list(COSIM_NETLIST), [])

    text = written(project)
    assert 'a2 [clk_d rst_d] [cnt0_d] u2' in text
    assert 'sim_args=["counter"]' in text
    assert 'esim_cosim' not in text


def test_the_analysis_card_still_moves_into_control_for_d_cosim(converter):
    """Pre-existing behaviour the collapse pass must not disturb: a d_cosim
    netlist runs its analysis once, inside .control, because the vvp cannot be
    re-run."""
    window, project = converter
    window.createNetlistFile(list(COSIM_NETLIST), [])

    text = written(project)
    assert '\ntran 10e-06 15e-03 0e-00' in text
    assert '\n.tran' not in text
