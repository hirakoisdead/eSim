"""VCD (Value Change Dump) parsing for waveform display.

Pure functions, extracted verbatim from VerilogVerifier so they can be unit
tested without Qt. The Verilog Simulator IDE feeds the output of
:func:`parse_vcd_for_plot` straight into eSim's native plot window.
"""
import re


def format_vcd_val(bin_str, size, var_name=""):
    """Format a raw binary VCD string to a human-readable value.

    Only decodes as ASCII if the signal is >= 24 bits (3+ characters), all
    decoded bytes are printable, AND the variable name hints it is a string
    (contains 'name', 'str', 'msg', 'text', 'label', or 'char').
    Everything else is rendered as hexadecimal to prevent false positives on
    opcodes, counters, and single-byte data registers.
    """
    if bin_str.lower() in ('x', 'z'):
        return bin_str

    if size == 1:
        return bin_str

    # Only attempt ASCII decoding if the signal is at least 24 bits (3 chars)
    # AND the variable name explicitly suggests a string type.
    STRING_NAME_HINTS = ('name', 'str', 'msg', 'text', 'label', 'char')
    is_named_string = any(h in var_name.lower() for h in STRING_NAME_HINTS)

    if is_named_string and size >= 24:
        try:
            if len(bin_str) % 8 != 0:
                padded_str = bin_str.zfill((len(bin_str) // 8 + 1) * 8)
            else:
                padded_str = bin_str
            bytes_list = [int(padded_str[i:i+8], 2) for i in range(0, len(padded_str), 8)]
            clean_bytes = [b for b in bytes_list if b != 0]
            if clean_bytes and all(32 <= b <= 126 for b in clean_bytes):
                return '"' + "".join(chr(b) for b in clean_bytes) + '"'
        except Exception:
            pass

    try:
        val = int(bin_str, 2)
        return hex(val)
    except Exception:
        return bin_str


_FULL_RANGE_RE = re.compile(r'^\[(\d+):(\d+)\]$')


def _is_full_range(token, size):
    """True when ``token`` is a ``[hi:lo]`` covering all ``size`` bits."""
    m = _FULL_RANGE_RE.match(token)
    return bool(m) and abs(int(m.group(1)) - int(m.group(2))) + 1 == size


def _decode(raw_val, size, name, var_type):
    """``(plot_value, display_value)`` for one raw VCD value."""
    if raw_val in ('x', 'X', 'z', 'Z'):
        return 0, raw_val
    if var_type == 'real':
        # Real values are decimal floats, not base-2 — plot the float and show
        # it verbatim (format_vcd_val would mangle it to 0/hex).
        try:
            return float(raw_val), raw_val
        except ValueError:
            return 0, raw_val
    try:
        dec = int(raw_val, 2)
    except Exception:
        dec = 0
    return dec, format_vcd_val(raw_val, size, name)


def _display_names(var_list):
    """Map each kept var index to the label shown in the waveform list.

    A bare signal name is used when it is unique. It usually is not: with
    ``$dumpvars(0, tb)`` the testbench's ``clk`` and the instance's ``clk`` are
    two different ``$var`` records, and keying the result dict by bare name
    silently dropped one of every such pair. Duplicates therefore fall back to
    their scope path (``uut.clk``), which is also what every other waveform
    viewer shows."""
    counts = {}
    for v in var_list:
        counts[v['name']] = counts.get(v['name'], 0) + 1
    labels, used = [], set()
    for v in var_list:
        label = v['name']
        if counts[label] > 1:
            # Drop the outermost scope (the testbench itself): 'uut.clk' reads
            # better than 'tb_counter.uut.clk' and stays unambiguous, and a
            # signal declared in the testbench keeps its plain name.
            label = '.'.join(list(v['scope'][1:]) + [v['name']])
        base, n = label, 2
        while label in used:            # last-resort disambiguation
            label = f"{base}#{n}"
            n += 1
        used.add(label)
        labels.append(label)
    return labels


def parse_vcd_for_plot(vcd_content):
    """Parse a VCD into plot-ready arrays.

    Returns ``(timestamps, signals_data, signal_types, raw_signals_data,
    timescale)``, or five ``None`` when the dump holds no value changes.

    The cost of this is linear in (value changes + timestamps x signals). That
    is worth stating because it used to be *quadratic*: every sample searched
    the whole change history for the most recent snapshot, so a run with a few
    thousand clock edges took minutes -- on the GUI thread, which is what the
    "the verifier freezes for 2-3 minutes" reports actually were.
    """
    timescale = "Time"
    timescale_match = re.search(r'\$timescale\s+(.*?)\s+\$end', vcd_content,
                                re.DOTALL)
    if timescale_match:
        timescale = timescale_match.group(1).strip()

    # -- pass 1: header (vars + scopes) and the change stream ---------------- #
    var_list = []                 # kept $var records, in declaration order
    sym_index = {}                # VCD symbol -> index into var_list
    changes = {}                  # index -> [(time, raw_value), ...]
    scope = []
    in_header = True
    current_time = 0
    times = set()

    for line in vcd_content.splitlines():
        line = line.strip()
        if not line:
            continue
        first = line[0]

        if in_header:
            if line.startswith('$scope'):
                parts = line.split()
                if len(parts) >= 3:
                    scope.append(parts[2])
                continue
            if line.startswith('$upscope'):
                if scope:
                    scope.pop()
                continue
            if line.startswith('$var'):
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        size = int(parts[2])
                    except ValueError:
                        continue      # malformed $var; skip, don't abort
                    symbol = parts[3]
                    # The reference may carry a range: '$var wire 4 ! q [3:0]'.
                    # A range spanning the whole signal is noise -- every
                    # vector has one -- so it is dropped and the plain name
                    # kept; a genuine bit-select ('q [0]' of a 1-bit $var) is
                    # part of the identity and stays.
                    tail = [t for t in parts[4:] if t != '$end']
                    name = tail[0] if tail else parts[4]
                    if len(tail) > 1 and not _is_full_range(tail[1], size):
                        name += tail[1]
                    if symbol in sym_index:
                        # Same net, dumped again under another scope. Keep the
                        # first (shallowest) record rather than the last: one
                        # trace per real signal, named where the user declared
                        # it.
                        continue
                    sym_index[symbol] = len(var_list)
                    var_list.append({'name': name, 'size': size,
                                     'type': parts[1], 'scope': tuple(scope)})
                continue
            if line.startswith('$enddefinitions'):
                in_header = False
                continue
            if not line.startswith(('$dumpvars', '$dumpall')):
                continue
            in_header = False
            # fall through: $dumpvars is followed by value lines

        if first == '#':
            try:
                current_time = int(line[1:])
            except ValueError:
                continue              # tolerate a malformed time marker
            continue
        if first in 'bBrR':
            # Vector ('b1010 sym') or real ('r3.14 sym') value change.
            parts = line.split()
            if len(parts) < 2:
                continue              # malformed change line; skip
            idx = sym_index.get(parts[1])
            if idx is None:
                continue
            changes.setdefault(idx, []).append((current_time, parts[0][1:]))
            times.add(current_time)
        elif first in '01xXzZ':
            # Scalar change: '<value><identifier>'.
            idx = sym_index.get(line[1:])
            if idx is None:
                continue
            changes.setdefault(idx, []).append((current_time, first))
            times.add(current_time)

    if not times:
        return None, None, None, None, None

    timestamps = sorted(times | {0})
    labels = _display_names(var_list)

    # -- pass 2: forward-fill each signal onto the shared time axis ---------- #
    # One walk per signal, advancing a cursor through its own change list --
    # never a search back through the history. Values are decoded once per
    # change and reused for the run of timestamps that holds them.
    signals_data = {}
    raw_signals_data = {}
    signal_types = {}
    n = len(timestamps)

    for idx, info in enumerate(var_list):
        label = labels[idx]
        signal_types[label] = info['type']
        events = changes.get(idx, ())
        y_values = [0] * n
        raw_values = ['x'] * n
        if not events:
            signals_data[label] = y_values
            raw_signals_data[label] = raw_values
            continue

        cur_plot, cur_raw = 0, 'x'
        ev = 0
        n_ev = len(events)
        for i, t in enumerate(timestamps):
            changed = False
            while ev < n_ev and events[ev][0] <= t:
                changed = True
                ev += 1
            if changed:
                cur_plot, cur_raw = _decode(
                    events[ev - 1][1], info['size'], info['name'],
                    info['type'])
            y_values[i] = cur_plot
            raw_values[i] = cur_raw

        signals_data[label] = y_values
        raw_signals_data[label] = raw_values

    return timestamps, signals_data, signal_types, raw_signals_data, timescale


def to_csv(timestamps, raw_signals, timescale="Time"):
    """Render parsed waveform data as CSV text.

    Pure counterpart of the IDE's Export CSV (the GUI only picks a path and
    writes the string). Column order: clk/clock/reset/rst first, then the rest
    alphabetically. Consecutive rows whose signal values are unchanged are
    collapsed, but the first and last samples are always emitted so the trace's
    start and end are never lost.

    ``raw_signals`` maps signal name -> per-timestamp value list (the
    ``raw_signals_data`` returned by :func:`parse_vcd_for_plot`).
    """
    all_signals = list(raw_signals.keys())
    priority = [s for s in ('clk', 'clock', 'reset', 'rst') if s in all_signals]
    signals = priority + sorted(s for s in all_signals if s not in priority)

    timescale_norm = re.sub(r'\s+', '', timescale or "Time")
    lines = [','.join([f"Time ({timescale_norm})"] + signals)]

    last_vals = None
    total = len(timestamps)
    for i, t in enumerate(timestamps):
        row_vals = [str(raw_signals[s][i]) for s in signals]
        is_last = (i == total - 1)
        if last_vals is not None and row_vals == last_vals and not is_last:
            continue
        last_vals = row_vals
        lines.append(','.join([str(t)] + row_vals))

    return '\n'.join(lines) + '\n'
