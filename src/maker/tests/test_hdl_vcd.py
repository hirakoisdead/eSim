"""Tests for the Qt-free VCD parser (maker.hdl.vcd)."""
from maker.hdl.vcd import format_vcd_val, parse_vcd_for_plot, to_csv


VCD = """\
$timescale 1ns $end
$var wire 1 ! clk $end
$var wire 4 # count $end
$enddefinitions $end
#0
0!
b0000 #
#5
1!
#10
0!
b0001 #
"""


def test_parse_basic_forward_fill():
    ts, signals, types, raw, timescale = parse_vcd_for_plot(VCD)
    assert ts == [0, 5, 10]
    # clk toggles 0 -> 1 -> 0 across the three recorded times
    assert signals['clk'] == [0, 1, 0]
    # count holds 0 until it changes to 1 at t=10 (forward fill, not reset)
    assert signals['count'] == [0, 0, 1]
    assert types == {'clk': 'wire', 'count': 'wire'}
    assert timescale == '1ns'


def test_parse_empty_returns_all_none():
    assert parse_vcd_for_plot("") == (None, None, None, None, None)


def test_format_single_bit_passthrough():
    assert format_vcd_val('0', 1) == '0'
    assert format_vcd_val('1', 1) == '1'


def test_format_xz_passthrough():
    assert format_vcd_val('x', 1) == 'x'
    assert format_vcd_val('z', 4) == 'z'


def test_format_multibit_is_hex():
    assert format_vcd_val('1010', 4) == '0xa'


def test_format_ascii_only_when_named_and_wide():
    # "Hey" = 0x48 0x65 0x79, 24 bits, var name hints a string -> decoded.
    bits = format(0x48, '08b') + format(0x65, '08b') + format(0x79, '08b')
    assert format_vcd_val(bits, 24, 'msg') == '"Hey"'
    # Same bits but a neutral counter name -> stays hex (no false positive).
    assert format_vcd_val(bits, 24, 'counter') == hex(int(bits, 2))


# Ugly-but-valid VCDs ------------------------------------------------------ #

REAL_VCD = """\
$timescale 1ns $end
$var real 64 ! temp $end
$var wire 1 # clk $end
$enddefinitions $end
#0
r0.0 !
0#
#5
r2.5 !
1#
#10
r-1.25 !
0#
"""


def test_reals_are_parsed_not_flatlined():
    # Real-valued signals used to be dropped: their 'r3.14' change lines were
    # not in the value-line dispatch set, so the signal stayed 'x' all run.
    ts, signals, types, raw, _ = parse_vcd_for_plot(REAL_VCD)
    assert ts == [0, 5, 10]
    assert types['temp'] == 'real'
    assert signals['temp'] == [0.0, 2.5, -1.25]
    assert raw['temp'] == ['0.0', '2.5', '-1.25']
    # the wire alongside it still parses normally
    assert signals['clk'] == [0, 1, 0]


def test_multibit_bus_with_x_bits_does_not_crash():
    vcd = ("$var wire 4 # bus $end\n$enddefinitions $end\n"
           "#0\nb10x1 #\n#5\nb0000 #\n")
    ts, signals, _, raw, _ = parse_vcd_for_plot(vcd)
    # An x-containing bus can't be a number -> plotted as 0, raw keeps the truth.
    assert signals['bus'] == [0, 0]
    assert raw['bus'][0] == '10x1'


def test_malformed_lines_are_tolerated_not_fatal():
    # A junk time marker, a sized $var with a bad width, a vector change with no
    # symbol, and a $dumpall checkpoint must not abort the whole parse.
    vcd = ("$var wire 1 ! clk $end\n"
           "$var wire bad % junk $end\n"     # non-int width: skipped
           "$enddefinitions $end\n"
           "#0\n0!\n"
           "#bogus\n"                          # malformed time: skipped
           "b101\n"                            # vector, no symbol: skipped
           "$dumpall\n1!\n$end\n")
    ts, signals, _, _, _ = parse_vcd_for_plot(vcd)
    assert 'junk' not in signals               # the bad $var was dropped
    assert signals['clk'][-1] == 1             # post-$dumpall value still landed


def test_missing_timescale_defaults():
    vcd = "$var wire 1 ! clk $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n"
    _, _, _, _, timescale = parse_vcd_for_plot(vcd)
    assert timescale == "Time"


# CSV export (pure) -------------------------------------------------------- #

def test_to_csv_matches_known_waveform():
    _, _, _, raw, timescale = parse_vcd_for_plot(VCD)
    csv = to_csv([0, 5, 10], raw, timescale)
    assert csv == (
        "Time (1ns),clk,count\n"
        "0,0,0x0\n"
        "5,1,0x0\n"
        "10,0,0x1\n"
    )


def test_to_csv_collapses_unchanged_rows_but_keeps_first_and_last():
    csv = to_csv([0, 5, 10, 15], {'a': ['0', '0', '0', '1']}, '1 ns / 1 ps')
    assert csv == "Time (1ns/1ps),a\n0,0\n15,1\n"


def test_to_csv_orders_clk_and_reset_first():
    csv = to_csv([0], {'z': ['0'], 'clk': ['1'], 'rst': ['0']}, '1ns')
    assert csv.splitlines()[0] == "Time (1ns),clk,rst,z"


# --- name collisions across scopes --------------------------------------- #
# $dumpvars(0, tb) dumps the testbench AND everything under it, so the same
# signal name appears in several scopes. Keying the result by bare name meant
# one trace silently overwrote the other -- signals vanished from the waveform
# list for no visible reason.

SCOPED_VCD = """\
$timescale 1ns $end
$scope module tb_counter $end
$var wire 1 ! clk $end
$var wire 1 " done $end
$scope module uut $end
$var wire 1 # clk $end
$var wire 4 $ count $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
1#
b0001 $
#5
1!
0#
"""


def test_duplicate_names_are_scope_qualified_not_dropped():
    ts, signals, _types, _raw, _ = parse_vcd_for_plot(SCOPED_VCD)
    # Both 'clk' records survive: the testbench's keeps the bare name, the
    # instance's is qualified by its scope.
    assert 'clk' in signals and 'uut.clk' in signals
    assert signals['clk'] == [0, 1]          # tb clk: 0 then 1
    assert signals['uut.clk'] == [1, 0]      # instance clk: the other one
    # Unique names are left alone.
    assert 'done' in signals and 'count' in signals
    assert ts == [0, 5]


def test_aliased_symbol_yields_one_trace_named_at_the_shallowest_scope():
    # A net dumped in two scopes shares one VCD symbol. It is one signal, so it
    # gets one trace, named where the user declared it (not in the instance).
    vcd = ("$scope module tb $end\n$var wire 1 ! a $end\n"
           "$scope module uut $end\n$var wire 1 ! a_internal $end\n"
           "$upscope $end\n$upscope $end\n$enddefinitions $end\n"
           "#0\n0!\n#5\n1!\n")
    _, signals, _, _, _ = parse_vcd_for_plot(vcd)
    assert list(signals) == ['a']
    assert signals['a'] == [0, 1]


def test_parse_cost_is_linear_not_quadratic():
    """The freeze this parser used to cause was algorithmic, not incidental.

    Every sample searched the entire change history for its most recent
    snapshot, so doubling the run quadrupled the work -- a few thousand clock
    edges took minutes, on the GUI thread. Doubling the input here must not
    much more than double the time; a quadratic parser fails this by a mile.
    """
    import time

    def bench(n_times, n_sig=12):
        syms = [chr(33 + i) for i in range(n_sig)]
        out = ["$timescale 1ns $end", "$scope module tb $end"]
        out += [f"$var wire 1 {s} sig{i} $end" for i, s in enumerate(syms)]
        out += ["$upscope $end", "$enddefinitions $end"]
        for t in range(n_times):
            out.append(f"#{t * 10}")
            out += [f"{t % 2}{s}" for s in syms[:3]]
        text = "\n".join(out)
        start = time.perf_counter()
        parse_vcd_for_plot(text)
        return time.perf_counter() - start

    bench(200)                       # warm up the interpreter
    small = bench(1000)
    large = bench(4000)              # 4x the timestamps
    # Linear would be ~4x; quadratic ~16x. Allow generous headroom for a loaded
    # machine and still catch a return to quadratic behaviour.
    assert large < max(small, 0.01) * 8


def test_vector_range_is_dropped_from_the_label_but_a_bit_select_is_kept():
    # Icarus writes '$var wire 4 ! count [3:0] $end' for every vector. Carrying
    # that range into the label ('count[3:0]') breaks every lookup by name --
    # including the "did this output ever move?" check -- for no benefit; the
    # width is already known. A genuine 1-bit select IS part of the identity.
    vcd = ("$scope module tb $end\n"
           "$var wire 4 ! count [3:0] $end\n"
           "$var wire 1 \" q [2] $end\n"
           "$upscope $end\n$enddefinitions $end\n"
           "#0\nb0000 !\n0\"\n#5\nb0011 !\n1\"\n")
    _, signals, _, _, _ = parse_vcd_for_plot(vcd)
    assert 'count' in signals and 'count[3:0]' not in signals
    assert 'q[2]' in signals
    assert signals['count'] == [0, 3]
