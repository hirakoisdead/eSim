"""Netlist-level guards for the HDL co-simulation backends.

Two silent-wrong-answer / crash traps live between the schematic and ngspice,
and both are decided purely from the assembled netlist:

* an ``adc_bridge`` with ``in_low < in_high`` emits x for every input inside
  the band. Icarus counts ``0 -> x`` and ``x -> 1`` as two ``posedge`` events
  (the design is clocked twice per analog edge); Verilator and GHDL read the x
  as a confident logic 1, which puts their single edge at ``in_low`` on both
  the rising and the falling side;
* Icarus's libvvp engine is process-global, so a second d_cosim block in one
  netlist segfaults ngspice.

These are text transforms over the schematicInfo list, so they need neither a
schematic nor a simulator.
"""
from kicadtoNgspice.KicadtoNgspice import (
    collapse_adc_band_for_hdl, dcosim_instance_count, _get_event_plot_nodes)


def netlist(adc_params="in_low=1.0 in_high=2.0 rise_delay=1.0e-9",
            extra=()):
    return [
        'a1 [clk_a rst_a vdd gnd] [clk_d rst_d logic1_d logic0_d] u1',
        'a2 [clk_d rst_d logic1_d] [cnt0_d wraps0_d] u2',
        'a3 [cnt0_d wraps0_d] [cnt0 wraps0] u3',
        '.model u1 adc_bridge(' + adc_params + ' ) ',
        '.model u2 d_cosim simulation="ivlng" sim_args=["counter"] ',
        '.model u3 dac_bridge(out_low=0.0 out_high=5.0 ) ',
    ] + list(extra)


def adc_line(lines):
    return next(ln for ln in lines if ln.startswith('.model u1'))


# --------------------------------------------------------------------------- #
# collapse_adc_band_for_hdl
# --------------------------------------------------------------------------- #
def test_band_feeding_cosim_collapses_to_its_midpoint():
    out, collapsed = collapse_adc_band_for_hdl(netlist())
    assert collapsed == [('u1', 1.0, 2.0, '1.5')]
    assert 'in_low=1.5' in adc_line(out)
    assert 'in_high=1.5' in adc_line(out)


def test_collapse_keeps_every_other_parameter():
    out, _ = collapse_adc_band_for_hdl(
        netlist("in_low=0.8 in_high=2.4 rise_delay=3e-9 fall_delay=4e-9"))
    line = adc_line(out)
    assert 'rise_delay=3e-9' in line and 'fall_delay=4e-9' in line
    assert 'in_low=1.6' in line and 'in_high=1.6' in line


def test_collapse_reads_exponent_notation():
    out, collapsed = collapse_adc_band_for_hdl(
        netlist("in_low=1.0e0 in_high=2.0e0"))
    assert collapsed[0][1:] == (1.0, 2.0, '1.5')
    assert 'in_low=1.5' in adc_line(out)


def test_already_single_threshold_is_left_alone():
    lines = netlist("in_low=2.5 in_high=2.5")
    out, collapsed = collapse_adc_band_for_hdl(lines)
    assert collapsed == []
    assert out == lines


def test_bridge_that_feeds_no_cosim_is_left_alone():
    """The rewrite is targeted: an adc_bridge wired only to stock XSPICE
    digital models keeps the thresholds the user asked for."""
    lines = [ln for ln in netlist() if not ln.startswith('a2')]
    lines = [ln for ln in lines if 'd_cosim' not in ln]
    out, collapsed = collapse_adc_band_for_hdl(lines)
    assert collapsed == []
    assert out == lines


def test_second_bridge_not_wired_to_the_cosim_is_left_alone():
    lines = netlist(extra=[
        'a4 [sense_a] [sense_d] u4',
        'a5 [sense_d] [sense_o] u5',
        '.model u4 adc_bridge(in_low=1.0 in_high=2.0 ) ',
        '.model u5 dac_bridge(out_low=0.0 ) ',
    ])
    out, collapsed = collapse_adc_band_for_hdl(lines)
    assert [c[0] for c in collapsed] == ['u1']
    assert 'in_low=1.0 in_high=2.0' in next(
        ln for ln in out if ln.startswith('.model u4'))


def test_inverted_band_is_not_rewritten():
    """in_high < in_low is a user error, not a band to average; leave it so
    ngspice reports on it rather than eSim silently inventing a threshold."""
    lines = netlist("in_low=3.0 in_high=1.0")
    out, collapsed = collapse_adc_band_for_hdl(lines)
    assert collapsed == []
    assert out == lines


# --------------------------------------------------------------------------- #
# Ngveri / Nghdl blocks, which the netlist text cannot identify on its own
# --------------------------------------------------------------------------- #
def ngveri_netlist():
    """The same schematic built through Verilator instead of Icarus: the
    block's .model type is just the HDL entity name."""
    return [
        'a1 [clk_a rst_a] [clk_d rst_d] u1',
        'a2 [clk_d rst_d] [cnt0_d] u2',
        'a3 [cnt0_d] [cnt0] u3',
        '.model u1 adc_bridge(in_low=1.0 in_high=2.0 ) ',
        '.model u2 universal_counter_8bit(instance_id=1 ) ',
        '.model u3 dac_bridge(out_low=0.0 ) ',
    ]


def test_an_ngveri_block_is_invisible_without_its_card_name():
    """Guards the reason hdl_cards exists at all: nothing in the netlist marks
    u2 as HDL-backed, so the pass must be told."""
    out, collapsed = collapse_adc_band_for_hdl(ngveri_netlist())
    assert collapsed == []
    assert out == ngveri_netlist()


def test_a_named_ngveri_block_gets_the_same_collapse_as_d_cosim():
    """A backend swap must not change the analog half of the netlist -- that
    is what makes NgVeri-vs-d_cosim an apples-to-apples comparison."""
    out, collapsed = collapse_adc_band_for_hdl(ngveri_netlist(), ['u2'])
    assert collapsed == [('u1', 1.0, 2.0, '1.5')]
    assert 'in_low=1.5 in_high=1.5' in adc_line(out)


def test_hdl_card_names_are_matched_case_insensitively():
    out, collapsed = collapse_adc_band_for_hdl(ngveri_netlist(), ['U2'])
    assert [c[0] for c in collapsed] == ['u1']
    assert 'in_low=1.5' in adc_line(out)


def test_naming_an_unrelated_card_changes_nothing():
    out, collapsed = collapse_adc_band_for_hdl(ngveri_netlist(), ['u3'])
    assert collapsed == []
    assert out == ngveri_netlist()


# --------------------------------------------------------------------------- #
# dcosim_instance_count
# --------------------------------------------------------------------------- #
def test_counts_zero_when_no_cosim_block():
    assert dcosim_instance_count(
        [ln for ln in netlist() if 'd_cosim' not in ln]) == 0


def test_counts_one_for_a_single_block():
    assert dcosim_instance_count(netlist()) == 1


def test_counts_instances_not_model_cards():
    """Two placements of the same Verilog block share one .model card and are
    still two co-simulations -- which is the case that crashes ngspice."""
    assert dcosim_instance_count(
        netlist(extra=['a4 [clk_d rst_d logic1_d] [c2_d w2_d] u2'])) == 2


# --------------------------------------------------------------------------- #
# the shared a-device/.model scan the collapse pass reuses
# --------------------------------------------------------------------------- #
def test_event_plot_nodes_still_select_digital_nodes_only():
    nodes = _get_event_plot_nodes(
        netlist(), ['plot v(cnt0_d)', 'plot v(clk_d)', 'plot v(cnt0)'])
    assert nodes == ['cnt0_d', 'clk_d']
