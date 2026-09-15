"""Verilog structural analysis: module discovery, port extraction, dependency
ordering, and testbench-stub generation.

Pure functions (no Qt), so the Verify stage's design-side actions can be tested
without driving the GUI. The guiding rule here is *be comment- and string-proof*
and *degrade to something usable* rather than silently emitting garbage:

- ``strip_comments`` neutralises ``//``/``/* */`` comments and string literals
  before any structural regex, so a module name mentioned in a comment can never
  be mistaken for real code.
- ``extract_ports`` prefers ``hdlparse`` but falls back to an in-house regex
  parser whenever hdlparse yields nothing -- notably for *single-line* ANSI
  headers (``module m(input a, output b);``), which hdlparse silently parses as
  zero ports. Bus widths (``[3:0]``) are carried through so the stub declares
  matching-width regs/wires instead of truncating to one bit.
- ``order_modules`` topologically orders multi-module designs (parent before the
  modules it instantiates), tolerant of ``#(...)`` parameter overrides, comments,
  duplicate names, and dependency cycles.
"""
import re

# Net/type keywords that may sit between a direction keyword and the port name.
_TYPE_KW = {'wire', 'reg', 'logic', 'bit', 'signed', 'unsigned', 'var',
            'tri', 'wand', 'wor', 'integer', 'time', 'real'}
_DIR_KW = {'input', 'output', 'inout'}
_KW = _TYPE_KW | _DIR_KW

_MODULE_RE = re.compile(r'\bmodule\s+(\w+)')

#: Verilog gate primitives. ``module nand (...)`` is not a naming preference
#: eSim disagrees with -- it is a redeclaration of a built-in, and iverilog
#: rejects it with a bare "syntax error" pointing at the module line, which
#: reads as if the *design* were malformed. These are the names people
#: actually reach for (nand, buf, xor) when they build a gate, so the case is
#: common enough to be worth naming outright.
RESERVED_PRIMITIVES = frozenset({
    'and', 'nand', 'or', 'nor', 'xor', 'xnor', 'buf', 'not',
    'bufif0', 'bufif1', 'notif0', 'notif1',
    'nmos', 'pmos', 'cmos', 'rnmos', 'rpmos', 'rcmos',
    'tran', 'tranif0', 'tranif1', 'rtran', 'rtranif0', 'rtranif1',
    'pullup', 'pulldown',
})

#: Other Verilog/SystemVerilog keywords that cannot name a module. Not the
#: complete grammar -- just the ones a design is plausibly named after.
RESERVED_KEYWORDS = frozenset({
    'module', 'endmodule', 'begin', 'end', 'wire', 'reg', 'logic', 'input',
    'output', 'inout', 'assign', 'always', 'initial', 'function', 'task',
    'parameter', 'localparam', 'generate', 'endgenerate', 'case', 'endcase',
    'if', 'else', 'for', 'while', 'repeat', 'forever', 'posedge', 'negedge',
    'signed', 'unsigned', 'integer', 'real', 'time', 'event', 'table',
    'primitive', 'specify', 'default', 'defparam', 'disable', 'force',
    'release', 'fork', 'join', 'wait', 'interface', 'package', 'class',
    'bit', 'byte', 'int', 'string', 'type', 'const', 'static', 'automatic',
})

#: Every identifier a module may not be called.
RESERVED_MODULE_NAMES = RESERVED_PRIMITIVES | RESERVED_KEYWORDS


def reserved_name_reason(name):
    """Why ``name`` cannot be a module name, in the user's terms -- or "".

    Said in eSim's own words *before* the compiler says it in its own, because
    the compiler's version ("syntax error" on the module line) describes the
    symptom and not the cause: the name is already taken by the language."""
    low = str(name or "").strip().lower()
    if not low:
        return ""
    if low in RESERVED_PRIMITIVES:
        return ("'%s' is a built-in Verilog gate primitive, so a module "
                "cannot be named that -- the compiler reads 'module %s' as a "
                "redeclaration of the gate and reports a syntax error on that "
                "line. Rename the module (for example '%s_gate')."
                % (name, name, low))
    if low in RESERVED_KEYWORDS:
        return ("'%s' is a reserved Verilog keyword, so a module cannot be "
                "named that. Rename the module (for example '%s_mod')."
                % (name, low))
    return ""


def reserved_modules(code):
    """Every module in ``code`` whose name is reserved, in source order."""
    return [m for m in find_modules(code or "")
            if str(m).strip().lower() in RESERVED_MODULE_NAMES]


def strip_comments(code, blank_strings=True):
    """Return ``code`` with ``//`` line comments, ``/* */`` block comments and
    ``"..."`` string literals blanked to spaces, newlines preserved. Structural
    scans run on the result so a ``module``/instance name inside a comment or
    string is never seen as code.

    ``blank_strings=False`` keeps string literals intact, for the scans that
    are looking *for* one -- the filename in ``$dumpfile("wave.vcd")``."""
    out = []
    i, n = 0, len(code)
    state = None  # None | 'line' | 'block' | 'string'
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ''
        if state is None:
            if c == '/' and nxt == '/':
                state = 'line'; out.append('  '); i += 2; continue
            if c == '/' and nxt == '*':
                state = 'block'; out.append('  '); i += 2; continue
            if c == '"':
                if not blank_strings:
                    # Copy the literal through verbatim, escapes included.
                    j = i + 1
                    while j < n and code[j] != '"':
                        j += 2 if code[j] == '\\' else 1
                    j = min(j + 1, n)
                    out.append(code[i:j]); i = j; continue
                state = 'string'; out.append(' '); i += 1; continue
            out.append(c); i += 1
        elif state == 'line':
            if c == '\n':
                state = None; out.append('\n')
            else:
                out.append(' ')
            i += 1
        elif state == 'block':
            if c == '*' and nxt == '/':
                state = None; out.append('  '); i += 2
            else:
                out.append('\n' if c == '\n' else ' '); i += 1
        else:  # string
            if c == '\\' and nxt:
                out.append('  '); i += 2
            elif c == '"':
                state = None; out.append(' '); i += 1
            else:
                out.append('\n' if c == '\n' else ' '); i += 1
    return ''.join(out)


def find_modules(code):
    """Names of every ``module`` definition in ``code``, in source order.
    Comments/strings are ignored."""
    return _MODULE_RE.findall(strip_comments(code))


def _strip_param_overrides(code):
    """Blank ``#( ... )`` parameter-override blocks (balanced parens) so an
    instantiation always reads as ``ModuleName instanceName (`` regardless of
    its parameter list, which may itself contain parentheses."""
    out = []
    i, n = 0, len(code)
    while i < n:
        if code[i] == '#':
            j = i + 1
            while j < n and code[j] in ' \t\r\n':
                j += 1
            if j < n and code[j] == '(':
                depth = 0
                k = j
                while k < n:
                    if code[k] == '(':
                        depth += 1
                    elif code[k] == ')':
                        depth -= 1
                        if depth == 0:
                            k += 1
                            break
                    k += 1
                out.append(' ' * (k - i))
                i = k
                continue
        out.append(code[i]); i += 1
    return ''.join(out)


def _instantiated_names(clean_no_params, candidates):
    """Subset of ``candidates`` (module names) instantiated in
    ``clean_no_params`` (comments AND ``#(...)`` already stripped). An
    instantiation reads ``ModuleName instanceName [array] (`` -- the required
    instance identifier between the type and ``(`` is what separates it from the
    module's own header (``module m (``) and from function calls (``m(``)."""
    found = set()
    for nm in candidates:
        if re.search(rf'\b{re.escape(nm)}\b\s+\w+\s*(?:\[[^\]]*\]\s*)?\(',
                     clean_no_params):
            found.add(nm)
    return found


def _pick_top(code, names):
    """The top-level module among ``names``: the one no sibling instantiates.
    Ties (or none) resolve to the last-defined, the usual place for a top
    module. A single-module file returns that module."""
    if len(names) == 1:
        return names[0]
    clean = _strip_param_overrides(strip_comments(code))
    instantiated = _instantiated_names(clean, set(names))
    tops = [n for n in names if n not in instantiated]
    return tops[-1] if tops else names[-1]


def _norm_width(data_type):
    """Pull the bus range out of an hdlparse ``data_type`` (e.g. ``'reg [3:0]'``
    -> ``'[3:0]'``; packed dims preserved). '' when scalar."""
    return ''.join(re.findall(r'\[[^\]]*\]', data_type or ''))


def _ports_hdlparse(code, module_name):
    """Ports of ``module_name`` via hdlparse, as ``(mode, name, width)``. Empty
    on any failure or when hdlparse finds no ports (its single-line-ANSI blind
    spot) so the caller can fall back to the regex parser."""
    try:
        import hdlparse.verilog_parser as vlog
        objs = vlog.VerilogExtractor().extract_objects_from_source(code)
        for obj in objs:
            if obj.name == module_name:
                return [(p.mode, p.name, _norm_width(p.data_type))
                        for p in obj.ports]
    except Exception as e:
        print("hdlparse failed, falling back to regex:", e)
    return []


def _module_region(clean, name):
    """``(header, body)`` for module ``name`` in already-comment-stripped
    ``clean``: ``header`` is the text inside the port-list parens (after any
    ``#(...)``), ``body`` runs to the matching ``endmodule``."""
    m = re.search(rf'\bmodule\s+{re.escape(name)}\b', clean)
    if not m:
        return '', ''
    n = len(clean)
    j = m.end()
    while j < n and clean[j] in ' \t\r\n':
        j += 1
    # skip optional #( ... ) parameter block
    if j < n and clean[j] == '#':
        k = j + 1
        while k < n and clean[k] in ' \t\r\n':
            k += 1
        if k < n and clean[k] == '(':
            depth = 0
            while k < n:
                if clean[k] == '(':
                    depth += 1
                elif clean[k] == ')':
                    depth -= 1
                    if depth == 0:
                        k += 1
                        break
                k += 1
            j = k
    while j < n and clean[j] in ' \t\r\n':
        j += 1
    header = ''
    if j < n and clean[j] == '(':
        depth = 0
        start = j + 1
        while j < n:
            if clean[j] == '(':
                depth += 1
            elif clean[j] == ')':
                depth -= 1
                if depth == 0:
                    header = clean[start:j]
                    j += 1
                    break
            j += 1
    end = re.search(r'\bendmodule\b', clean[j:])
    body = clean[j:j + end.start()] if end else clean[j:]
    return header, body


def _split_commas(s):
    """Split on top-level commas only (commas inside ``()``/``[]``/``{}`` stay)."""
    out, cur, depth = [], [], 0
    for c in s:
        if c in '([{':
            depth += 1; cur.append(c)
        elif c in ')]}':
            depth -= 1; cur.append(c)
        elif c == ',' and depth == 0:
            out.append(''.join(cur)); cur = []
        else:
            cur.append(c)
    if ''.join(cur).strip():
        out.append(''.join(cur))
    return out


def _names_in(decl_fragment):
    """Identifier names in a declaration fragment, with ranges and keywords
    removed -- e.g. ``'wire [3:0] a'`` -> ``['a']``."""
    no_range = re.sub(r'\[[^\]]*\]', ' ', decl_fragment)
    return [t for t in re.findall(r'[A-Za-z_]\w*', no_range) if t not in _KW]


def _ports_regex(clean, module_name):
    """In-house port parser over comment-stripped ``clean``. Handles both ANSI
    headers (``module m(input [3:0] a, output b)``, incl. single-line, which
    hdlparse misses) and non-ANSI (names in header, directions declared in the
    body). Returns ``(mode, name, width)`` with bus widths preserved."""
    header, body = _module_region(clean, module_name)
    ports, seen = [], set()

    if re.search(r'\b(input|output|inout)\b', header):
        # ANSI: each comma item carries (or inherits) a direction.
        mode, width = None, ''
        for item in _split_commas(header):
            s = item.strip()
            if not s:
                continue
            mm = re.match(r'(input|output|inout)\b', s)
            rng = ''.join(re.findall(r'\[[^\]]*\]', s))
            if mm:
                mode = mm.group(1)
                width = rng  # new direction resets the width
            elif rng:
                width = rng  # continuation may restate a width
            if mode is None:
                continue
            names = _names_in(s)
            if names and names[-1] not in seen:
                seen.add(names[-1])
                ports.append((mode, names[-1], width))
    else:
        # Non-ANSI: direction declarations live in the body, one per ';'.
        for stmt in body.split(';'):
            mm = re.match(r'\s*(input|output|inout)\b', stmt)
            if not mm:
                continue
            mode = mm.group(1)
            width = ''.join(re.findall(r'\[[^\]]*\]', stmt))
            for nm in _names_in(stmt):
                if nm not in seen:
                    seen.add(nm)
                    ports.append((mode, nm, width))
    return ports


def top_module_name(verilog_code):
    """Name of the top module in ``verilog_code``, or '' when none is found.

    The cheap half of :func:`extract_ports`: pure regex over comment-stripped
    source, with no hdlparse pass. Everything that only needs the design's
    *identity* -- the tab label, the library filename, the model name -- should
    use this. hdlparse is heavy enough that calling the full extractor from a
    keystroke handler is felt as typing lag on a large design."""
    names = find_modules(verilog_code or "")
    if not names:
        return ""
    return _pick_top(verilog_code, names)


def extract_ports(verilog_code, top=None):
    """``(top_module_name, ports)`` for ``verilog_code``. ``ports`` is a list of
    ``(mode, name, width)`` where ``width`` is '' or a range like ``'[3:0]'``.
    The *top* module is chosen when several are present. Returns ``(None, [])``
    when no module is found.

    ``top`` names a module to describe instead of the automatically chosen one,
    and is ignored unless the source defines it -- so a caller can pass a stale
    or user-supplied name without having to check it first."""
    module_name = top_module_name(verilog_code)
    if top and top in find_modules(verilog_code or ""):
        module_name = top
    if not module_name:
        return None, []
    ports = _ports_hdlparse(verilog_code, module_name)
    if not ports:
        ports = _ports_regex(strip_comments(verilog_code), module_name)
    return module_name, ports


def order_modules(named_codes):
    """Dependency-order design units for display/serialisation: a unit appears
    before the units defining modules it instantiates (top-down).

    ``named_codes``: ``[(key, code), ...]`` -- ``key`` is the caller's id (a tab
    label). Every key is returned exactly once; independent units keep input
    order; dependency cycles terminate (each unit visited once) instead of
    recursing forever."""
    units = []
    for key, code in named_codes:
        units.append({
            'key': key,
            'clean': _strip_param_overrides(strip_comments(code)),
            'defines': set(find_modules(code)),
        })
    all_names = set()
    for u in units:
        all_names |= u['defines']

    name_to_units = {}
    for idx, u in enumerate(units):
        for nm in u['defines']:
            name_to_units.setdefault(nm, []).append(idx)

    deps = {i: set() for i in range(len(units))}
    for idx, u in enumerate(units):
        for nm in _instantiated_names(u['clean'], all_names - u['defines']):
            for dep_idx in name_to_units.get(nm, ()):
                if dep_idx != idx:
                    deps[idx].add(dep_idx)

    order, visited = [], set()

    def emit(i):
        if i in visited:
            return
        visited.add(i)
        order.append(i)                 # parent first ...
        for d in sorted(deps[i]):       # ... then what it instantiates
            emit(d)

    # Start only from top-level units (nobody instantiates them) so a child that
    # happens to come earlier in the input isn't emitted before its parent;
    # children are reached through their parent's recursion. Roots are taken in
    # input order, keeping independent units stable.
    has_parent = set().union(*deps.values()) if deps else set()
    for i in range(len(units)):
        if i not in has_parent:
            emit(i)
    # Anything left is inside a dependency cycle: emit in input order, no hang.
    for i in range(len(units)):
        emit(i)
    return [units[i]['key'] for i in order]


def _p3(p):
    """Normalise a port tuple to ``(mode, name, width)``."""
    return p if len(p) == 3 else (p[0], p[1], '')


# --------------------------------------------------------------------------- #
#  Testbench generation
#
#  The generated testbench is the whole product for most users: the realistic
#  path is "paste a module, press Simulate, look at the waveform". A stub that
#  merely *compiles* is worthless there -- an input that is declared and never
#  assigned stays X for the entire run, so every output driven by it is X too
#  and the waveform is a flat wall of red. So the generator's contract is
#  stronger than "valid Verilog": every input is driven, and the stimulus is
#  chosen to make the design's behaviour visible.
# --------------------------------------------------------------------------- #

#: Ports whose *name* marks them as a clock. Usage-based detection (a
#: ``posedge <name>`` anywhere in the design) covers everything else.
_CLK_NAMES = {'clk', 'clock', 'clk_i', 'clki', 'clkin', 'clk_in', 'sysclk',
              'sys_clk', 'iclk', 'mclk', 'pclk', 'aclk'}

#: A reset port: ``rst``/``reset``, optionally asynchronous (``arst``), negated
#: (``n_rst``, ``rst_n``, ``rstn``, ``rst_b``) or interface-suffixed (``rst_i``).
_RST_RE = re.compile(
    r'^(?:n_?)?a?(?:rst|reset)(?:_?(?:n|ni|nin|b|i|in|sync))?$', re.IGNORECASE)
#: …and of those, the ones asserted LOW (leading or trailing negation marker).
_RST_LOW_RE = re.compile(r'(?:^n_?|_?n$|_?ni$|_?nin$|_?b$)', re.IGNORECASE)

#: Inputs that gate a design's operation. Random-toggling these makes a core
#: sit idle for most of the run; holding them asserted makes it actually work,
#: which is what the user wants to see on the waveform.
_ENABLE_NAMES = {'en', 'ena', 'enable', 'en_i', 'start', 'go', 'run', 'valid',
                 'valid_in', 'in_valid', 'req', 'request', 'cs', 'ce',
                 'chip_enable', 'chip_select', 'load', 'trigger'}

#: Exhaustively sweeping N stimulus bits costs 2**N vectors. 10 bits = 1024
#: vectors -- instant, and it gives a truth-table-complete waveform. Above
#: that, switch to corner cases + pseudorandom vectors.
_SWEEP_BITS_COMB = 10
#: Clocked designs spend a vector per clock, so keep the swept space smaller.
_SWEEP_BITS_SEQ = 6
#: Vectors driven when the input space is too large to sweep.
_RANDOM_VECTORS = 40

_WIDTH_RE = re.compile(r'^\[\s*(\d+)\s*:\s*(\d+)\s*\]$')


def _width_bits(width):
    """Bit count for a width string, or None when it is not a plain numeric
    range (``[WIDTH-1:0]``, packed multi-dimensional, …). None means "cannot
    reason about the size", which downgrades the stimulus to random."""
    if not width:
        return 1
    m = _WIDTH_RE.match(width.strip())
    if not m:
        return None
    hi, lo = int(m.group(1)), int(m.group(2))
    return abs(hi - lo) + 1


def _find_clock(ports, design_code=None):
    """The clock input, by name first and then by use.

    Usage detection matters because real designs are full of ``i_clk``,
    ``clk_50m`` and ``core_clk``: a name whitelist alone leaves them undriven,
    which is exactly the silent all-X waveform this generator exists to
    prevent."""
    scalars = [n for m, n, wd in ports if m == 'input' and _width_bits(wd) == 1]
    for name in scalars:
        if name.lower() in _CLK_NAMES:
            return name
    if design_code:
        clean = strip_comments(design_code)
        for name in scalars:
            if re.search(rf'\b(?:pos|neg)edge\s+{re.escape(name)}\b', clean):
                return name
    return None


def _find_reset(ports, clk):
    """``(name, active_low)`` for the reset input, or ``(None, False)``."""
    for mode, name, wd in ports:
        if mode != 'input' or name == clk or _width_bits(wd) != 1:
            continue
        if _RST_RE.match(name):
            return name, bool(_RST_LOW_RE.search(name))
    return None, False


def _all_ones(bits):
    return "{%d{1'b1}}" % bits if bits and bits > 1 else "1'b1"


_PARAM_KW_RE = re.compile(r'\b(?:parameter|localparam)\b')
_IDENT_RE = re.compile(r'[A-Za-z_]\w*')


def _split_param_items(text):
    """``(range, name, expr)`` for each ``NAME = expr`` in a parameter
    declaration body (``[1:0] A = 2'b00, B = 3``). The range, when present,
    applies to the items that follow it, as in Verilog."""
    items = []
    rng = ''
    for chunk in _split_commas(text):
        s = chunk.strip()
        if not s or '=' not in s:
            continue
        lhs, _, expr = s.partition('=')
        # A leading type/range on the first item carries to the rest.
        found = re.findall(r'\[[^\]]*\]', lhs)
        if found:
            rng = ''.join(found)
            lhs = re.sub(r'\[[^\]]*\]', ' ', lhs)
        lhs = re.sub(r'\b(?:parameter|localparam|signed|unsigned|integer|'
                     r'real|time|realtime)\b', ' ', lhs)
        names = _IDENT_RE.findall(lhs)
        if names:
            items.append((rng, names[-1], expr.strip()))
    return items


def module_parameters(code, module_name):
    """``(range, name, expr)`` for every parameter/localparam of a module, in
    source order -- from its ``#(...)`` header block and its body.

    A generated testbench needs these because port widths reference them:
    ``output reg [Bits-1:0] Result`` is meaningless in a testbench that has
    never heard of ``Bits``, and iverilog rejects it with "Unable to bind
    parameter" against a file the user never wrote."""
    clean = strip_comments(code or "")
    m = re.search(rf'\bmodule\s+{re.escape(module_name)}\b', clean)
    if not m:
        return []
    end = re.search(r'\bendmodule\b', clean[m.end():])
    region = clean[m.end():m.end() + end.start()] if end else clean[m.end():]

    params = []
    # Header ``#( ... )`` block, when present, before the port list.
    hm = re.match(r'\s*#\s*\(', region)
    if hm:
        depth, k = 0, hm.end() - 1
        while k < len(region):
            if region[k] == '(':
                depth += 1
            elif region[k] == ')':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        params += _split_param_items(region[hm.end():k])
        region = region[k + 1:]

    # Body declarations, each terminated by ';'.
    for m2 in _PARAM_KW_RE.finditer(region):
        semi = region.find(';', m2.end())
        if semi == -1:
            continue
        params += _split_param_items(region[m2.end():semi])

    seen, out = set(), []
    for rng, name, expr in params:
        if name not in seen:
            seen.add(name)
            out.append((rng, name, expr))
    return out


def _needed_parameters(code, module_name, ports):
    """Parameter declarations a testbench must mirror to declare ``ports``.

    Only the ones actually referenced by a port width are emitted (plus the
    parameters those expressions in turn reference), so a design's unrelated
    constants never leak into the testbench."""
    declared = module_parameters(code, module_name)
    if not declared:
        return []
    by_name = {name: (rng, expr) for rng, name, expr in declared}

    wanted, pending = set(), []
    for _mode, _name, width in ports:
        pending += [t for t in _IDENT_RE.findall(width or "") if t in by_name]
    while pending:
        nm = pending.pop()
        if nm in wanted:
            continue
        wanted.add(nm)
        pending += [t for t in _IDENT_RE.findall(by_name[nm][1])
                    if t in by_name]
    return [(rng, name, expr) for rng, name, expr in declared
            if name in wanted]


def is_self_contained_testbench(code):
    """True when ``code`` is already a runnable testbench: its top module has
    no ports and drives stimulus itself.

    Pasting one of these (an ``iverilog`` example, a downloaded ``tb_*.v``) is
    common, and wrapping it in a generated testbench would instantiate a
    port-less module and drive nothing. It is simulated as-is instead."""
    module, ports = extract_ports(code or "")
    if not module or ports:
        return False
    clean = strip_comments(code)
    return bool(re.search(r'\binitial\b', clean))


#: First line of every testbench eSim writes. It is the *only* thing that
#: distinguishes "a testbench eSim put here" from "a testbench the user wrote",
#: and that distinction decides whether a stale testbench may be replaced
#: silently or must be reported and left alone. Editing the line out is a
#: legitimate way for a user to claim ownership of the file.
TB_PROVENANCE_MARKER = "// Generated by eSim -- testbench stub."


def is_generated_testbench(tb_code):
    """True when ``tb_code`` still carries eSim's provenance marker.

    Deliberately a marker and not a text comparison against a fresh
    generation: by the time this is asked the design has usually changed, so
    there is nothing left to compare against. The marker survives exactly as
    long as the user leaves it there."""
    for line in (tb_code or "").splitlines():
        if line.strip():
            return line.strip().startswith(TB_PROVENANCE_MARKER)
    return False


def generate_stub_testbench(module_name, ports, design_code=None):
    """A ready-to-simulate, *driving* testbench for ``module_name``.

    ``ports`` is a list of ``(mode, name, width)`` tuples (2-tuples tolerated).
    ``design_code``, when given, is used to spot a clock by its ``posedge``
    usage rather than only by name.

    What it guarantees:

    - every input is assigned at time 0, so nothing is X by omission;
    - a clock (by name or by use) toggles, and a reset is asserted then
      released;
    - enable-like inputs are held asserted so the design actually runs;
    - remaining inputs are swept exhaustively when the space is small enough
      to be worth it, otherwise driven with corner cases + ``$random``;
    - ``$dumpfile``/``$dumpvars`` are wired, and the run always ``$finish``es.
    """
    ports = [_p3(p) for p in ports]
    inputs = [p for p in ports if p[0] == 'input']
    outputs = [p for p in ports if p[0] in ('output', 'inout')]

    def w(width):
        return (width + ' ') if width else ''

    regs_decl = "\n".join(f"  reg {w(wd)}{name};" for _, name, wd in inputs)
    wires_decl = "\n".join(f"  wire {w(wd)}{name};" for _, name, wd in outputs)
    # Port widths that reference the design's parameters need those parameters
    # to exist here too, or the testbench will not elaborate.
    params_decl = "\n".join(
        f"  localparam {w(rng)}{name} = {expr};"
        for rng, name, expr in _needed_parameters(design_code or "",
                                                  module_name, ports))
    if params_decl:
        params_decl = "  // Parameters mirrored from the design\n" + \
            params_decl + "\n"
    names = [name for _, name, _ in ports]
    port_mapping = ", ".join(f".{name}({name})" for name in names)
    instance = (f"{module_name} uut (\n    {port_mapping}\n  );"
                if names else f"{module_name} uut ();")

    clk = _find_clock(ports, design_code)
    rst, rst_low = _find_reset(ports, clk)
    clk_stimulus = f"\n  always #5 {clk} = ~{clk};\n" if clk else ""

    # Split the remaining inputs into "hold asserted" (enables) and "drive with
    # vectors" (everything else).
    enables, driven = [], []
    for _mode, name, wd in inputs:
        if name in (clk, rst):
            continue
        (enables if (name.lower() in _ENABLE_NAMES
                     and _width_bits(wd) == 1) else driven).append((name, wd))

    bits = [_width_bits(wd) for _, wd in driven]
    total_bits = None if any(b is None for b in bits) else sum(bits)

    body = []
    add = body.append

    # -- time 0: every input at a known value ------------------------------ #
    if clk:
        add(f"    {clk} = 0;")
    if rst:
        add(f"    {rst} = {'0' if rst_low else '1'};")
    for name in [n for n, _ in enables]:
        add(f"    {name} = 0;")
    for name, _wd in driven:
        add(f"    {name} = 0;")

    # -- reset release ----------------------------------------------------- #
    if rst:
        add(f"    #20 {rst} = {'1' if rst_low else '0'};")
    elif clk:
        add("    #20;")
    for name in [n for n, _ in enables]:
        add(f"    {name} = 1;")

    sweep_cap = _SWEEP_BITS_SEQ if clk else _SWEEP_BITS_COMB
    sweep = (total_bits is not None and 0 < total_bits <= sweep_cap)
    lhs = ("{" + ", ".join(n for n, _ in driven) + "}") if len(driven) > 1 \
        else (driven[0][0] if driven else None)

    if not driven:
        # Nothing to stimulate: just let the design run (a clocked design still
        # advances its own state; a purely combinational one is constant).
        add(f"    repeat (20) @(posedge {clk});" if clk else "    #200;")
    elif clk:
        add("    // one stimulus vector per clock, applied off the active edge")
        if sweep:
            add(f"    for (esim_i = 0; esim_i < {1 << total_bits}; "
                "esim_i = esim_i + 1) begin")
            add(f"      @(negedge {clk});")
            add(f"      {lhs} = esim_i;")
            add("    end")
        else:
            for name, wd in driven:                   # corner: all ones
                add(f"    @(negedge {clk}); {name} = "
                    f"{_all_ones(_width_bits(wd) or 1)};")
            add(f"    for (esim_i = 0; esim_i < {_RANDOM_VECTORS}; "
                "esim_i = esim_i + 1) begin")
            add(f"      @(negedge {clk});")
            for name, _wd in driven:
                add(f"      {name} = $random;")
            add("    end")
        add(f"    repeat (4) @(posedge {clk});")
    else:
        if sweep:
            add("    // exhaustive sweep of every input combination")
            add(f"    for (esim_i = 0; esim_i < {1 << total_bits}; "
                "esim_i = esim_i + 1) begin")
            add(f"      {lhs} = esim_i;")
            add("      #10;")
            add("    end")
        else:
            add("    // corner cases, then pseudorandom vectors")
            add("    #10;")
            for name, wd in driven:
                add(f"    {name} = {_all_ones(_width_bits(wd) or 1)};")
            add("    #10;")
            add(f"    for (esim_i = 0; esim_i < {_RANDOM_VECTORS}; "
                "esim_i = esim_i + 1) begin")
            for name, _wd in driven:
                add(f"      {name} = $random;")
            add("      #10;")
            add("    end")
        add("    #20;")

    add("    $finish;")

    loop_var = "  integer esim_i;\n" if "esim_i" in "\n".join(body) else ""
    stimulus = "\n".join(body)

    return f"""{TB_PROVENANCE_MARKER}
// Yours to edit -- once you change anything here, eSim stops replacing it and
// tells you when it no longer matches the design instead.
`timescale 1ns/1ps

module tb_{module_name};
{params_decl}  // Inputs
{regs_decl}

  // Outputs
{wires_decl}
{loop_var}
  // UUT Instance
  {instance}
{clk_stimulus}
  // Waveform capture
  initial begin
    $dumpfile("sim_out.vcd");
    $dumpvars(0, tb_{module_name});
  end

  // Stimulus
  initial begin
{stimulus}
  end

endmodule
"""


# --------------------------------------------------------------------------- #
#  Testbench inspection: what a *user-supplied* testbench is missing
#
#  The average path into this tool is "paste HDL from somewhere, press
#  Simulate". Whatever testbench comes along for the ride is frequently
#  missing the two things eSim needs to show a waveform at all -- a VCD dump
#  and a way to stop -- so the IDE detects both and supplies them rather than
#  reporting an empty plot or hanging until the watchdog fires.
# --------------------------------------------------------------------------- #

_DUMPFILE_RE = re.compile(r'\$dumpfile\s*\(\s*"([^"]*)"')

#: Root module injected alongside a testbench that never dumps. It is not
#: instantiated by anything, so iverilog elaborates it as a second root and its
#: initial block runs. ``$dumpvars`` with no arguments dumps every scope in the
#: design, so this needs to know nothing about the testbench's name.
AUTODUMP_MODULE = "esim_autodump"


def dump_file_name(tb_code):
    """The VCD filename a testbench dumps to, or None when it never calls
    ``$dumpfile``. eSim reads back whatever name the user actually used
    instead of insisting on ``sim_out.vcd``."""
    m = _DUMPFILE_RE.search(strip_comments(tb_code or "",
                                           blank_strings=False))
    return m.group(1) if m else None


def has_dump(tb_code):
    """True when the testbench asks for a VCD at all (``$dumpvars``)."""
    return '$dumpvars' in strip_comments(tb_code or "")


def has_finish(tb_code):
    """True when the testbench can stop itself (``$finish``/``$stop``)."""
    clean = strip_comments(tb_code or "")
    return '$finish' in clean or '$stop' in clean


def autodump_source(vcd_name="sim_out.vcd", guard_ns=None):
    """Verilog for the injected dump/watchdog root module.

    ``guard_ns`` adds a ``$finish`` backstop after that many nanoseconds, for a
    testbench with no ``$finish`` of its own -- without it such a run is only
    stopped by the simulate watchdog, i.e. after the full timeout with nothing
    to show for it."""
    guard = ""
    if guard_ns:
        guard = (f"\n  initial begin\n    #{guard_ns};\n"
                 f"    $display(\"eSim: stopping after {guard_ns} ns "
                 f"(testbench has no $finish)\");\n    $finish;\n  end\n")
    return f"""`timescale 1ns/1ps
// Generated by eSim: this testbench did not capture a waveform on its own.
module {AUTODUMP_MODULE};
  initial begin
    $dumpfile("{vcd_name}");
    $dumpvars;
  end
{guard}endmodule
"""


def instantiated_modules(code, candidates):
    """Which of ``candidates`` (module names) ``code`` instantiates."""
    return _instantiated_names(
        _strip_param_overrides(strip_comments(code or "")), set(candidates))


def testbench_matches(tb_code, design_modules):
    """True when ``tb_code`` looks like a testbench for this design.

    A testbench that instantiates none of the design's modules is either empty
    or left over from something else; simulating with it produces an
    "Unknown module type" wall against a file the user never wrote."""
    if not tb_code or not tb_code.strip():
        return False
    return bool(instantiated_modules(tb_code, design_modules))
