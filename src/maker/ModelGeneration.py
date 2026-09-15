# =========================================================================
#             FILE: ModelGeneration.py
#
#            USAGE: ---
#
#      DESCRIPTION: This define all model generation processes of NgVeri.
#
#          OPTIONS: ---
#     REQUIREMENTS: ---
#             BUGS: ---
#            NOTES: ---
#           AUTHOR: Sumanto Kar, sumantokar@iitb.ac.in, FOSSEE, IIT Bombay
# ACKNOWLEDGEMENTS: Rahul Paknikar, rahulp@iitb.ac.in, FOSSEE, IIT Bombay
#                Digvijay Singh, digvijay.singh@iitb.ac.in, FOSSEE, IIT Bombay
#                Prof. Maheswari R. and Team, VIT Chennai
#     GUIDED BY: Steve Hoover, Founder Redwood EDA
#                Kunal Ghosh, VLSI System Design Corp.Pvt.Ltd
#                Anagha Ghosh, VLSI System Design Corp.Pvt.Ltd
# OTHER CONTRIBUTERS:
#                Prof. Madhuri Kadam, Shree L. R. Tiwari College of Engineering
#                Rohinth Ram, Madras Institue of Technology
#                Charaan S., Madras Institue of Technology
#                Nalinkumar S., Madras Institue of Technology
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
#       CREATED: Monday 29, November 2021
#      REVISION: Tuesday 2nd, September 2023
# =========================================================================


import re
import html
import os
import shutil
import subprocess
import sys
import threading
from PyQt6 import QtCore, QtWidgets
from configuration import Dialogs
from configuration import paths
from configparser import ConfigParser
from configuration import Appconfig

from . import createkicad
from . import CosimConfig
from .hdl import icarus
from .hdl.procs import kill_process_tree
from .CosimLogger import CosimLog
from .model_teardown import (
    _ensure_modpath, _append_modpath_line, _prune_modpath)
from .hdl.ports import (find_modules, reserved_name_reason, top_module_name)
import hdlparse.verilog_parser as vlog


#: A top module called this carries no identity of its own. It is what
#: sandpiper emits for EVERY TLV design, and the conventional name of a
#: hand-written wrapper, so it can never distinguish one model from another.
#: resolve_identity() falls back to the file name for it, which is also what
#: keeps verilogfile()'s `top` -> stem rewrite meaningful.
GENERIC_TOP_MODULE = 'top'


#: ``1ns`` / ``100 ps`` -- a Verilog time literal, as magnitude and unit.
_TIME_UNIT_EXP = {'s': 0, 'ms': -3, 'us': -6, 'ns': -9, 'ps': -12, 'fs': -15}
_TIMESCALE_RE = re.compile(
    r'(`timescale\s+)(1|10|100)\s*(s|ms|us|ns|ps|fs)'
    r'(\s*/\s*)(1|10|100)\s*(s|ms|us|ns|ps|fs)',
    re.IGNORECASE)

#: Finest precision d_cosim ever needs. Its default output delay is 1 ns and
#: SPICE event times land on picoseconds, so 1 ps resolves every edge the
#: analog side can produce.
_TARGET_PRECISION_EXP = -12


def normalise_timescale(text):
    """Sharpen every ``\\`timescale`` precision in ``text`` to at least 1 ps.

    Returns ``(text, ["1ms/1ms", ...])`` naming the directives that were too
    coarse; the list is empty (and the text unchanged) when all of them were
    already fine enough.

    ivlng advances VVP by ``(spice_time - vvp_time) / precision`` ticks and
    **truncates**. When one SPICE step is shorter than a single precision tick
    that quotient is 0, so VVP never runs: the design sits at its initial value
    for the whole simulation, ngspice reports success, and every output reads
    zero. A source that declares ``\\`timescale 1ms/1ms`` (legal, and fine
    under plain vvp) is silently dead under d_cosim -- measured on a probe
    design, every counter stayed at 0 for 10 ms.

    Only the *precision* field is rewritten. The time unit is what the design's
    own ``#`` delays are expressed in, so leaving it alone keeps their meaning
    exactly; a finer precision can only reduce rounding, never change it.
    """
    coarse = []

    def sharpen(m):
        exp = _TIME_UNIT_EXP[m.group(6).lower()] + len(m.group(5)) - 1
        if exp <= _TARGET_PRECISION_EXP:
            return m.group(0)
        coarse.append('%s%s/%s%s' % (m.group(2), m.group(3),
                                     m.group(5), m.group(6)))
        return m.group(1) + m.group(2) + m.group(3) + m.group(4) + '1ps'

    return _TIMESCALE_RE.sub(sharpen, text), coarse


#: Name of the generated top module d_cosim actually simulates. ivlng takes the
#: FIRST root module VVP reports (`vpi_iterate(vpiModule, NULL)` in
#: tools/nghdl/src/xspice/verilog/vpi.c), and a module that is instantiated is
#: not a root -- so wrapping the user's design leaves exactly one root and the
#: choice stops depending on compilation order.
COSIM_TOP_MODULE = 'esim_cosim_top'

#: The wrapper's two ports. ONE input vector and ONE output vector, whatever
#: the design underneath looks like -- see cosim_wrapper_source for why.
IN_PORT = 'esim_d_in'
OUT_PORT = 'esim_d_out'


def parse_connection_info(text):
    """``[(name, direction, bits), ...]`` from a connection_info.txt body,
    in the module's own port-declaration order.

    Order is wiring: eSim's netlist lists a block's nodes in this order (the
    KiCad symbol's pins are built from the same file), so a wrapper that
    reorders them silently rewires the design."""
    ports = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            bits = int(fields[2])
        except ValueError:
            continue
        if bits > 0:
            ports.append((fields[0], fields[1].lower(), bits))
    return ports


def port_widths(blocks):
    """``(input bits, output bits)`` across every block, in netlist order."""
    ins = sum(b for _l, _m, ports in blocks
              for _n, d, b in ports if d == 'input')
    outs = sum(b for _l, _m, ports in blocks
               for _n, d, b in ports if d == 'output')
    return ins, outs


def cosim_wrapper_source(blocks, timescale='`timescale 1ns/1ps'):
    """Generate the Verilog top module d_cosim simulates.

    ``blocks`` is ``[(instance_label, module_name, ports), ...]`` where
    ``ports`` comes from :func:`parse_connection_info`. Returns the source
    text; the caller compiles it together with the user's own file(s).

    The wrapper does two things.

    **It reads an ``x`` input as logic 1, exactly as the NgVeri (Verilator)
    backend already does.** NgVeri's generated C is literally
    ``if (INPUT_STATE(port) == ZERO) 0; else 1;`` -- anything that is not a
    definite 0 is a 1 -- so NgVeri never sees the ``x`` that XSPICE's
    adc_bridge emits between ``in_low`` and ``in_high``. Icarus does see it,
    because it is a real four-state simulator, and IEEE 1364 counts a
    transition to a higher value as a posedge: a clock ramping through the band
    arrives as ``0 -> x -> 1``, which is **two** posedges, and the design is
    clocked twice per analog edge (docs/NGVERI_ACCURACY.md D1). Mapping ``x``
    to 1 collapses that to ``0 -> 1 -> 1``: one posedge, taken as the voltage
    crosses ``in_low`` -- the same edge, at the same instant, that NgVeri
    takes. The two backends then agree, which is the point of d_cosim being an
    alternative to NgVeri rather than a second opinion.

    It reproduces NgVeri's *mistake* along with its behaviour: an input
    genuinely sitting at 1.2 V is undefined, and reading it as a confident 1 is
    wrong. Fixing that means changing the adc_bridge band eSim has emitted
    since 2.5 -- a maintainer decision, see docs/UPSTREAM_DECISIONS.md item 1.
    The netlist is left alone.

    The comparison is ``===`` (case equality) and per **bit**, because that is
    what NgVeri does: each bit carries its own ``INPUT_STATE``. A vector-wide
    ``==`` would return x and poison the whole port.

    **It presents exactly one input port and one output port**, with every
    block's ports sliced out of them, so the netlist's node order is the only
    thing that decides what is wired where. ivlng discovers ports by walking
    ``vpi_iterate(vpiPort, top)`` and assigning each one a running bit offset
    (``vpi.c`` ``start_cb``), then finds a bit's owner by scanning those
    offsets (``icarus_shim.c``). That makes the wiring depend on the order VVP
    reports ports in -- which is not the order they are declared in, and was
    observed to vary between compiles of the same source: a three-block design
    came out correct on one build and with one block's reset wired to a clock
    on the next. With a single vector there is one port at offset 0 and the
    mapping is arithmetic, so there is nothing left to vary.

    Node ``j`` of a group is bit ``width - 1 - j`` (``icarus_shim.c`` line 97,
    "Bit position for big-endian"), so a port occupying consecutive nodes maps
    to a contiguous slice with its own MSB first -- the convention the
    single-block netlist already used.
    """
    in_bits, out_bits = port_widths(blocks)

    def slices(direction, total):
        """``{(label, port): "[hi:lo]"}`` for one direction group."""
        out, taken = {}, 0
        for label, _module, ports in blocks:
            for name, pdir, bits in ports:
                if pdir != direction:
                    continue
                high = total - 1 - taken
                out[(label, name)] = ('[%d:%d]' % (high, high - bits + 1)
                                      if bits > 1 else '[%d]' % high)
                taken += bits
        return out

    in_slice = slices('input', in_bits)
    out_slice = slices('output', out_bits)

    header, decls = [], []
    if in_bits:
        header.append(IN_PORT)
        decls.append('  input  [%d:0] %s;' % (in_bits - 1, IN_PORT))
    if out_bits:
        header.append(OUT_PORT)
        decls.append('  output [%d:0] %s;' % (out_bits - 1, OUT_PORT))

    instances = []
    for label, module, ports in blocks:
        conns = []
        for name, pdir, _bits in ports:
            if pdir == 'input':
                conns.append('.%s(%s_lv%s)'
                             % (name, IN_PORT, in_slice[(label, name)]))
            else:
                conns.append('.%s(%s%s)'
                             % (name, OUT_PORT, out_slice[(label, name)]))
        instances.append('  %s %s (\n    %s\n  );'
                         % (module, 'u_' + label, ',\n    '.join(conns)))

    body = [
        timescale,
        '',
        '/* Generated by eSim. Do not edit -- rebuilt on every conversion.',
        ' *',
        ' * Runs every d_cosim block on the schematic in ONE Icarus engine,',
        ' * and reads an x input as logic 1, which is what the NgVeri',
        ' * (Verilator) backend does. See',
        ' * ModelGeneration.cosim_wrapper_source and',
        ' * docs/NGVERI_ACCURACY.md D1/D2.',
        ' */',
        'module %s (%s);' % (COSIM_TOP_MODULE, ', '.join(header)),
        '',
    ]
    body.extend(decls)
    if in_bits:
        body.append('')
        body.append('  wire [%d:0] %s_lv;' % (in_bits - 1, IN_PORT))
        body.append('  genvar gi;')
        body.append('  generate')
        body.append('    for (gi = 0; gi < %d; gi = gi + 1) begin : g_esim_lv'
                    % in_bits)
        body.append("      assign %s_lv[gi] = (%s[gi] === 1'b0) "
                    "? 1'b0 : 1'b1;" % (IN_PORT, IN_PORT))
        body.append('    end')
        body.append('  endgenerate')
    body.append('')
    body.extend(instances)
    body.append('')
    body.append('endmodule')
    return '\n'.join(body) + '\n'


def declared_timescale(text, default='`timescale 1ns/1ps'):
    """The first ``\\`timescale`` directive in ``text``, or ``default``.

    The wrapper must declare the same one as the design. ivlng derives its tick
    length from the simulation's global time unit
    (``vpi_get(vpiTimeUnit, NULL)``), so a wrapper carrying a different
    timescale could change how fast the design advances -- the D3 failure mode,
    reintroduced by the fix for D1."""
    match = _TIMESCALE_RE.search(text)
    return match.group(0) if match else default


class ModelGeneration(QtWidgets.QWidget):
    '''
        Class is used to generate the Ngspice Model
    '''

    # Generous cap (seconds) so big verilator/make builds are not guillotined
    # at the old 50 s limit, while a genuinely hung process is still killed and
    # reported instead of either freezing the GUI forever or silently
    # producing a half-built model. The whole legacy pipeline now runs off the
    # GUI thread (NgVeri.addverilog), so a slow build no longer freezes eSim;
    # this is only the per-step wall-clock safety net.
    PROCESS_TIMEOUT = 600           # 10 minutes, in seconds (subprocess.run)

    # eSim's GUI process has no console, so every console child (mingw32-make,
    # verilator, gcc) would otherwise allocate its own visible console window
    # -- a blank black box, since the output is piped. Worse than cosmetic:
    # closing that mystery window sends CTRL_CLOSE_EVENT to the child, which
    # aborts the build mid-link ("mingw32-make: *** Interrupt"). 0 on POSIX.
    NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    # Emitted for every line/block of build output. Connected to termedit in
    # __init__; because the connection is auto-typed, calls from the GUI thread
    # deliver synchronously while calls from the build worker thread are queued
    # back onto the GUI thread -- so the subprocess pipeline can stream output
    # without ever touching a widget off-thread.
    line = QtCore.pyqtSignal(str)

    # Emitted at the start of each build phase (the termtitle banner text) so
    # the NgVeri tab can drive a live progress indicator naming the current
    # step. Auto-typed like `line`: a call from the build worker thread is
    # queued back onto the GUI thread, so updating the label/bar is safe.
    phase = QtCore.pyqtSignal(str)

    def __init__(self, file, termedit):
        super().__init__()
        self.obj_Appconfig = Appconfig.Appconfig()
        print("Argument is : ", file)

        if os.name == 'nt':
            self.file = file.replace('\\', '/')
        else:
            self.file = file

        self.termedit = termedit
        # Route every termtext/termtitle/_run write through the line signal so
        # the same code path is safe whether it runs on the GUI thread (fast
        # file-generation steps) or the build worker thread (verilator/make).
        self.line.connect(self.termedit.append)
        # Dual-sink d_cosim logger: same events to the NgVeri GUI terminal
        # (this termedit) AND the OS terminal + ~/.esim/dcosim.log. Route the
        # GUI sink through the `line` signal (not termedit.append directly) so
        # build_cosim's log lines stay GUI-thread-safe when the build runs on a
        # worker thread.
        self.clog = CosimLog(termedit, sink=self.line.emit)
        self.cur_dir = os.getcwd()
        self.fname = os.path.basename(file)
        self.fname = self.fname.lower()
        # ONE canonical model stem for the whole pipeline. os.path.splitext
        # strips only the final extension, so "fir.v1.v" -> "fir.v1" (matching
        # the model directory verilogfile() creates), where the old
        # split('.')[0] read "fir" and split-brained the build (dir under one
        # name, cfunc/ifspec/sim_main/modpath under another). sandpiper()
        # rewrites fname .tlv->.sv but preserves this stem, so setting it once
        # here is safe.
        self.model_stem = os.path.splitext(self.fname)[0]
        # The module verilator should elaborate as top, in its declared case.
        # Until resolve_identity() reads the source this mirrors the stem --
        # which is exactly right for the fallback paths (TLV, a design whose
        # top really is called `top`), because those rewrite the module TO the
        # stem in the copied source.
        self.top_module = self.model_stem
        # Whether verilogfile() should still rewrite a standalone `top` token
        # in a .sv to the file stem. True preserves the historical behaviour
        # for every caller that never resolves an identity; resolve_identity()
        # clears it once the source names its own top, where rewriting `top`
        # would corrupt an unrelated identifier in the user's code.
        self._rename_top_to_stem = True
        print("Verilog/SystemVerilog/TL Verilog filename is : ", self.fname)

        # Diagnostic tally for the whole pipeline (see _classify_stderr): what
        # the closing summary reports, so the user reads a verdict instead of
        # judging the run by how much coloured text scrolled past.
        self.diag_errors = 0
        self.diag_warnings = 0
        # Severity the current diagnostic BLOCK opened with; continuation lines
        # inherit it. Reset per step in _run.
        self._diag_severity = None

        # Keep a parser for the legacy build methods below, but all constructor
        # values are read through CosimConfig's missing-safe boundary. This is
        # crucial for d_cosim-only installs, which intentionally have no NGHDL
        # config file.
        self.parser = ConfigParser()
        self.parser.read(CosimConfig.nghdl_config_path())
        self.nghdl_home = CosimConfig.nghdl_cfg('NGHDL', 'NGHDL_HOME')
        self.release_dir = CosimConfig.nghdl_cfg('NGHDL', 'RELEASE')
        self.src_home = CosimConfig.nghdl_cfg('SRC', 'SRC_HOME')
        self.licensefile = CosimConfig.nghdl_cfg('SRC', 'LICENSE')
        # The legacy NgVeri (Verilator) build tree. Every per-model path is
        # built from `digital_home`, and the d_cosim flow retargets it at its
        # own sibling tree (use_cosim_tree) so neither backend can ever delete
        # the other's build. `legacy_home` stays pinned here because
        # modpath.lst belongs to the legacy tree whichever flow is running.
        self.legacy_home = os.path.join(
            CosimConfig.digital_model_root(), 'Ngveri')
        self.digital_home = self.legacy_home

    def use_cosim_tree(self):
        '''
            Point this build at the d_cosim tree (<DIGITAL_MODEL>/NgVeriCosim)
            instead of the legacy Ngveri tree, so the sources, connection_info
            and vvp of a d_cosim model live somewhere no NgVeri teardown can
            reach -- and vice versa. Must be called BEFORE verilogfile().

            The per-model directory name needs no special-casing: __init__
            lowercases self.fname, so model_stem already equals the canonical
            d_cosim id (CosimConfig.cosim_model_id).
        '''
        self.digital_home = CosimConfig.cosim_build_root()

    @staticmethod
    def _stem_is_valid(stem):
        """A model stem is spliced verbatim into C function names (cm_<stem>),
        Verilog/VHDL entities, make targets and filesystem paths, so it must be
        a bare identifier: a letter/underscore followed by word chars. A dot
        (fir.v1), hyphen or space would silently break the build four layers
        deeper (invalid C identifier, broken make target); refuse it up front."""
        return bool(stem) and re.fullmatch(r'[A-Za-z_]\w*', stem) is not None

    @staticmethod
    def _port_width(item):
        """Bit width of a "name:bits" port entry, at least 1.

        The generated C sizes one array per port from this, so it must never
        return 0 (a zero-length array is a GNU extension and every loop over it
        would be an out-of-bounds write). Anything unparsable falls back to 1 --
        the scalar case -- rather than raising in the middle of file generation.
        """
        try:
            return max(1, int(str(item).split(':')[1]))
        except (IndexError, ValueError):
            return 1

    def require_legacy_toolchain(self):
        """Report a missing legacy toolchain cleanly instead of crashing.

        Two layers: the cheap config check (NGHDL_HOME/RELEASE/SRC_HOME keys
        present) and the full doctor probe (verilator/make/gcc/ngspice all
        actually on disk), so a half-installed toolchain fails HERE with the
        exact missing tool + fix hint instead of exploding mid-pipeline in
        make."""
        if not (self.nghdl_home and self.release_dir and self.src_home):
            message = (
                "NGHDL/NgVeri toolchain not configured — install NGHDL or "
                "use Dual Co-sim."
            )
            self.termtext(message)
            self.obj_Appconfig.print_error(message)
            return False
        from . import ToolchainCheck
        message = ToolchainCheck.failure_message(ToolchainCheck.NGVERI)
        if message:
            self.termtext(message)
            self.obj_Appconfig.print_error(message)
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Cross-platform build-tool resolution (single source for every step)
    # ------------------------------------------------------------------ #
    def _msys_home(self):
        return CosimConfig.nghdl_cfg('COMPILER', 'MSYS_HOME')

    def _nt_build_env(self):
        """Environment for build subprocesses on Windows: the MSYS2 mingw64
        and usr/bin dirs go FIRST on PATH (make's child gcc/g++/ar and the
        verilator wrapper resolve from there -- the eSim process itself never
        has them on PATH), plus VERILATOR_ROOT for the model Makefiles.
        Returns None on POSIX (inherit as-is)."""
        if os.name != 'nt':
            return None
        env = os.environ.copy()
        msys_home = self._msys_home()
        if msys_home:
            env["PATH"] = os.pathsep.join([
                os.path.join(msys_home, 'mingw64', 'bin'),
                os.path.join(msys_home, 'usr', 'bin'),
            ]) + os.pathsep + env.get("PATH", "")
            # MSYS2's verilator package keeps the runtime tree (include/
            # verilated.cpp, verilated_std.sv, lint waivers) under
            # share/verilator, not the mingw64 prefix itself -- pointing
            # VERILATOR_ROOT at the prefix makes every verilator run fail with
            # "Cannot find verilated_std_waiver.vlt".
            # Forward slashes: the value is spliced into verilator's generated
            # Makefile, where backslashes are escape characters (make eats
            # them, e.g. C:\FOSSEE\... becomes C:FOSSEE... and the includer
            # path collapses).
            env["VERILATOR_ROOT"] = os.path.join(
                msys_home, 'mingw64', 'share', 'verilator'
            ).replace('\\', '/')
        return env

    def _make_binary(self):
        """make (POSIX) / MSYS2 mingw32-make (Windows), or None with an
        actionable terminal message naming the exact probed path."""
        if os.name != 'nt':
            return "make"
        msys_home = self._msys_home()
        cand = (os.path.join(msys_home, 'mingw64', 'bin',
                             'mingw32-make.exe') if msys_home else '')
        if cand and os.path.isfile(cand):
            return cand
        self.termtext(
            "[NgVeri] mingw32-make not found (probed: " +
            (cand or "~/.nghdl/config.ini [COMPILER] MSYS_HOME unset") +
            "). Reinstall eSim with the HDL-toolchain (MSYS2) component.")
        return None

    def _python_for_make(self):
        """Windows: a `PYTHON3=<interpreter>` argument for verilator's
        generated Makefile, or None when the default should stand.

        verilated.mk hard-codes `PYTHON3 = python3` and runs
        `$(PYTHON3) $(VERILATOR_ROOT)/bin/verilator_includer` to concatenate
        the generated C++ into V<model>__ALL.cpp. MSYS2 ships no Python at all
        and eSim's bundled CPython is python.exe -- there is no python3.exe
        anywhere in a Windows install -- so that recipe died with
        `/usr/bin/sh: line 1: python3: command not found` (make Error 127)
        before one object was compiled. Reuse the interpreter eSim is already
        running under rather than adding a ~60 MB MSYS2 python to the
        installer.

        It has to travel as a COMMAND-LINE variable: a makefile's own
        `PYTHON3 = python3` assignment overrides the environment, but nothing
        overrides `make PYTHON3=...`.

        POSIX keeps make's default -- python3 is on PATH there, and the venv
        interpreter is not necessarily the one verilator's scripts expect.
        """
        if os.name != 'nt':
            return None
        exe = sys.executable or ''
        # A --no-console launch runs the GUI under pythonw.exe, whose stdout
        # the includer recipe redirects into V<model>__ALL.cpp; prefer the
        # console twin beside it so that redirection cannot come up empty.
        base = os.path.basename(exe).lower()
        if base.startswith('pythonw'):
            cand = os.path.join(os.path.dirname(exe),
                                base.replace('pythonw', 'python', 1))
            if os.path.isfile(cand):
                exe = cand
        if not exe or not os.path.isfile(exe):
            return None
        # Forward slashes: make splices the value into an sh recipe, where
        # backslashes are escapes (the same trap as VERILATOR_ROOT above).
        exe = exe.replace('\\', '/')
        if ' ' in exe:
            exe = '"' + exe + '"'
        return 'PYTHON3=' + exe

    def _verilator_binary(self):
        """verilator (POSIX) / the MSYS2 mingw64 verilator (Windows), or None
        with an actionable terminal message. On Windows the real binary is
        verilator_bin.exe (the `verilator` front-end is a perl script); with
        VERILATOR_ROOT set, invoking it directly is equivalent."""
        if os.name != 'nt':
            return "verilator"
        msys_home = self._msys_home()
        probed = []
        for name in ('verilator_bin.exe', 'verilator.exe'):
            cand = (os.path.join(msys_home, 'mingw64', 'bin', name)
                    if msys_home else '')
            probed.append(cand or name)
            if cand and os.path.isfile(cand):
                return cand
        self.termtext(
            "[NgVeri] Verilator not found (probed: " + ", ".join(probed) +
            "). Reinstall eSim with the HDL-toolchain (MSYS2) component.")
        return None

    def _run(self, cmd, title, cwd=None, env=None):
        '''
            Run one step of the model-build pipeline and return True only when
            the process exits cleanly with code 0.

            `cmd` is an argument LIST (never a shell string): the process is
            spawned directly, so a path with spaces or shell metacharacters can
            neither split into extra arguments nor be interpreted -- the old
            ``sh -c`` + string-concatenation was both fragile with spaced paths
            and an injection surface. The working directory is passed as
            ``cwd=`` instead of an ``os.chdir`` dance, so a failed step can
            never strand the whole app inside a model sub-directory and no
            longer races the CWD-relative paths elsewhere in eSim.

            stdout is streamed into the NgVeri terminal line-by-line as the
            tool produces it (via the ``line`` signal, so this is safe to call
            from the build worker thread -- the signal is queued back onto the
            GUI thread). A long make no longer looks like a hang: the user
            watches the compile progress live. stderr is drained on a helper
            thread (so neither pipe can fill up and deadlock the child) and
            coloured per line by severity, not painted red wholesale.
        '''
        # A new tool is a new diagnostic block: never let the last line of the
        # previous step's output decide the colour of this step's first one.
        self._diag_severity = None
        self.termtitle(title)
        self.termtext("Current Directory: " + (cwd or os.getcwd()))
        self.termtext("Command: " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env, text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=self.NO_WINDOW)
        except OSError as err:
            self.termtext("[NgVeri] '" + title + "' could not be started: " +
                          str(err))
            return False

        def _drain_stderr():
            # Stream stderr live, line by line, instead of buffering the whole
            # pipe and emitting it only after the step finishes. verilator, gcc
            # and make write their progress + warnings to stderr, so buffering
            # made a multi-minute step look frozen until it was already done.
            # Runs on its own thread (kept off the stdout loop) so neither pipe
            # can fill up and deadlock the child; every emit is queued to the
            # GUI thread via the `line` signal. Severity is per line
            # (_classify_stderr) -- this stream is mostly NOT errors.
            try:
                for err_line in proc.stderr:
                    err_line = err_line.rstrip()
                    if err_line:
                        self._emit_stderr(err_line)
            except Exception:
                pass

        drainer = threading.Thread(target=_drain_stderr, daemon=True)
        drainer.start()

        # Wall-clock safety net: unlike subprocess.run(timeout=...), a
        # streaming read has no built-in deadline, so a watchdog kills a
        # genuinely hung tool after PROCESS_TIMEOUT seconds.
        timed_out = threading.Event()

        def _kill_on_timeout():
            timed_out.set()
            # Kill the whole tree, not just the direct child: on Windows
            # Popen.kill() is TerminateProcess on mingw32-make alone, so the
            # gcc/ld it already spawned keep running and keep their handles on
            # the .o/.exe files in the model dir. The user's retry then fails
            # with "Permission denied" rewriting an object file -- a confusing
            # second bug with no visible link to the step that timed out.
            kill_process_tree(proc)

        watchdog = threading.Timer(self.PROCESS_TIMEOUT, _kill_on_timeout)
        watchdog.daemon = True
        watchdog.start()
        try:
            for out_line in proc.stdout:
                out_line = out_line.rstrip()
                if out_line:
                    self.termtext(out_line)
            proc.stdout.close()
            returncode = proc.wait()
        finally:
            watchdog.cancel()
            # Let the stderr streamer finish flushing the tail of the pipe
            # before we judge the step; it emits live, so nothing is emitted
            # here anymore.
            drainer.join(timeout=5)

        if timed_out.is_set():
            self.termtext("[NgVeri] '" + title +
                          "' timed out and was stopped.")
            return False
        if returncode != 0:
            self.termtext("[NgVeri] '" + title + "' failed (exit code " +
                          str(returncode) + ").")
            return False
        return True

    # -- stderr diagnostic classification -----------------------------------
    # gcc, mingw32-make and verilator write ALL of their progress to stderr,
    # not only their failures: "'x.o' is up to date", the `rm` echo of an
    # intermediate file, every -W warning and the multi-line source excerpt
    # under it. Painting that whole stream red made a build that SUCCEEDED end
    # in a wall of red, and the single most common question about the Windows
    # NgVeri flow was "what are these red lines?" -- asked about verilator's
    # own harmless STDOUT_FILENO redefinition warning (verilated.cpp redefines
    # a macro mingw's stdio.h already defines; windows/build-windows.ps1 now
    # patches that one at staging time, but the next toolchain bump will bring
    # another). Classify per line instead, so red keeps one meaning: this is
    # why your model was not built.
    _RE_DIAG_ERROR = re.compile(
        r'\b(?:fatal\s+)?error\s*:'          # gcc/g++/ld: foo.c:1:2: error: x
        r'|^%Error'                          # verilator
        r'|\*\*\*\s.*\bError\b'              # make: *** [x] Error 1
        r'|\bNo rule to make target\b'
        r'|\bundefined reference to\b'
        r'|\bcannot find -l',
        re.IGNORECASE)
    _RE_DIAG_WARN = re.compile(
        r'\bwarning\s*:'
        r'|^%Warning',
        re.IGNORECASE)
    # Lines that carry no severity of their own and belong to the diagnostic
    # above them: gcc's source echo, its caret ruler, the include chain, and
    # the trailing "note:" that explains the first line.
    _RE_DIAG_CONT = re.compile(
        r'\bnote\s*:'
        r'|^\s*In file included from\b'
        r'|^\s+from\b'                       # rest of the include chain
        r'|^\s*In (?:function|member function|instantiation of)\b'
        r'|^\s*required from\b'
        r'|^\s*\d+\s*\|'                     # source echo:  78 | # define X
        r'|^\s*\|'                           # caret ruler:     |       ^~~~
        r'|^\s*[\^~]+\s*$')
    # Theme-independent, and deliberately the same values CosimLogger uses for
    # the d_cosim half of this terminal.
    _DIAG_COLOR = {'error': '#ff0000', 'warning': '#E07B00'}

    def _classify_stderr(self, line):
        """``'error'`` / ``'warning'`` / ``None`` for one raw stderr line.

        A continuation line inherits the severity of the diagnostic it belongs
        to, so a warning's own source excerpt cannot come out in a different
        colour from its first line. Anything that matches nothing -- make's
        progress, the `rm` echo -- is plain terminal text, because it is.

        Only the line that OPENS a diagnostic is counted, so one gcc warning
        with five lines of excerpt tallies as one warning.
        """
        if self._RE_DIAG_ERROR.search(line):
            self._diag_severity = 'error'
            self.diag_errors += 1
        elif self._RE_DIAG_WARN.search(line):
            self._diag_severity = 'warning'
            self.diag_warnings += 1
        elif not self._RE_DIAG_CONT.search(line):
            self._diag_severity = None
        return self._diag_severity

    def _emit_stderr(self, textin):
        '''Append stderr text to the terminal, coloured by severity.

        Escaped, unlike the old raw-HTML emit: compiler output is full of
        ``<stdio.h>``, ``operator<<`` and ``std::vector<int>``, every one of
        which a QTextEdit parsed as an unknown tag and swallowed -- error text
        silently lost whole fragments exactly when it mattered most.
        '''
        for ln in textin.split("\n"):
            color = self._DIAG_COLOR.get(self._classify_stderr(ln))
            if color:
                style = ("font-size:12pt; font-weight:1000; color:" +
                         color + ";")
            else:
                # Same style termtext uses, so undistinguished tool chatter is
                # indistinguishable from the stdout it interleaves with.
                style = "font-size:12pt; font-weight:500;"
            self.line.emit('<span style="' + style + '">' +
                           html.escape(ln) + '</span>')

    def resolve_identity(self, prefer=None):
        '''
            Name this model after the top MODULE in the source, not after the
            file that happens to hold it. Call once, before anything derives a
            path or a prompt from the name; returns "No Error"/"Error".

            ``prefer`` names a module to build instead of the automatically
            chosen top, and is ignored unless the source actually defines it.
            The automatic choice (the module no sibling instantiates) is right
            for essentially every design, but it is a heuristic, and a user who
            can see it guessed wrong needs a way to say so that does not
            involve rearranging their code.

            eSim copies the design into its own build tree, so the copy can be
            called whatever the pipeline needs -- the user's own file is never
            read for its name again, and never renamed. That is what removes
            the old "File name and module name are not same" refusal: there is
            no longer anything for the two names to disagree about.

            Three cases fall back to the file stem, which is the historical
            behaviour and still correct:

            * ``.tlv`` -- sandpiper has not run yet, and what it emits is
              always ``module top``. There is no authored name to read.
            * a top module literally called ``top`` (see GENERIC_TOP_MODULE).
            * a source no parser can read a module out of. Reporting THAT is
              verilogParse's job, where the message can talk about ports;
              failing here would only trade one confusing error for another.

            The name is lowercased because every downstream consumer already
            treats the model id as lowercase (the KiCad symbol, the d_cosim
            vvp id, modpath.lst). ``top_module`` keeps the declared case, for
            the one consumer that needs it: verilator's --top-module.
        '''
        ext = os.path.splitext(self.fname)[1]
        if ext == ".tlv":
            return "No Error"

        try:
            with open(self.file, 'r', errors='replace') as fh:
                code = fh.read()
        except OSError as err:
            Dialogs.critical(
                None, "Error Message",
                "<b>Error: could not read '" + str(self.file) + "': " +
                str(err) + "</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                "NgVeri stopped: unreadable source " + str(self.file))
            return "Error"

        module = top_module_name(code)
        if prefer and prefer in find_modules(code):
            module = prefer
        if not module or module == GENERIC_TOP_MODULE:
            return "No Error"

        stem = module.lower()
        if not self._stem_is_valid(stem):
            # A Verilog identifier is already [A-Za-z_]\w*, so this only fires
            # for an escaped identifier (\bus[0] ). Name the module, not the
            # file: the file name has nothing to do with the problem anymore.
            Dialogs.critical(
                None, "Error Message",
                "<b>Error: '" + str(module) + "' cannot be used as a model "
                "name. Use only letters, digits and underscore, and do not "
                "start with a digit -- the module name becomes a C function, "
                "an HDL entity and a make target. Rename the module in your "
                "code and try again.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                "NgVeri stopped: invalid module name '" + str(module) + "'")
            return "Error"

        reason = reserved_name_reason(module)
        if reason:
            # Caught here rather than left to the compiler: iverilog reports a
            # redeclared primitive as a bare "syntax error" on the module line,
            # which reads as if the design were malformed rather than as "this
            # name belongs to the language".
            Dialogs.critical(
                None, "Error Message", "<b>" + reason + "</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                "NgVeri stopped: reserved module name '" + str(module) + "'")
            return "Error"

        self.model_stem = stem
        self.fname = stem + ext
        self.top_module = module
        # The source names its own top, so the `top` -> stem rewrite must not
        # run: here it would rename an unrelated identifier in the user's code.
        self._rename_top_to_stem = False
        return "No Error"

    def rename_model(self, stem):
        '''
            Build this design under a different MODEL name, leaving the design
            itself alone. Call after resolve_identity and before anything
            derives a path from the name.

            Only ``model_stem`` (and the build-copy filename derived from it)
            moves: ``top_module`` still names the module the wrapper
            instantiates and verilator is pointed at, and the user's own source
            is neither renamed nor edited. That separation is what lets eSim
            answer "that name is already taken" with a build instead of a
            refusal.
        '''
        stem = str(stem or "").strip().lower()
        if not stem or not self._stem_is_valid(stem):
            return False
        self.fname = stem + os.path.splitext(self.fname)[1]
        self.model_stem = stem
        return True

    def verilogfile(self):
        '''
            Reading the file and performing operations and
            copying it in the Ngspice folder
        '''
        Text = "<span style=\" font-size:25pt;\
         font-weight:1000; color:#008000;\" >"
        Text += ".................Running NgVeri..................."
        Text += "</span>"
        self.termedit.append(Text)

        # Refuse an unusable model name BEFORE creating dirs / copying source.
        # The stem becomes a C function, a make target and a path component;
        # a dotted (fir.v1), hyphenated or spaced name otherwise detonates deep
        # inside cmpp/make with a message that points nowhere near the cause.
        if not self._stem_is_valid(self.model_stem):
            Dialogs.critical(
                None, "Error Message",
                "<b>Error: '" + self.fname + "' is not a usable model name. "
                "Use only letters, digits and underscore and do not start with "
                "a digit (the name becomes a C function, an HDL entity and a "
                "make target). Rename the file and try again.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_error(
                "NgVeri stopped: invalid model name '" + self.fname + "'")
            return "Error"

        with open(self.file, 'r') as read_verilog:
            verilog_data = read_verilog.readlines()
        modname = os.path.splitext(self.fname)[0]
        self.modelpath = self.digital_home + "/" + modname + "/"
        # makedirs, not mkdir: on a fresh tree the PARENT (<DigitalModelLibrary>
        # /Ngveri) does not exist yet -- it is created lazily by the remove
        # dialog -- so a first-ever convert used to die here on FileNotFoundError
        # and surface as a generic "Error in Ngspice code model generation".
        os.makedirs(self.modelpath, exist_ok=True)

        # os.path.splitext keeps the true extension even for dotted/no-dot
        # names (the old .split('.')[1] IndexError'd on "counter" and read
        # "v" from "model.v.bak").
        if os.path.splitext(self.fname)[1] == ".tlv":
            self.sandpiper()
            # sandpiper() rewrote self.fname to "<model>.sv"
            modname = os.path.splitext(self.fname)[0]
            with open(self.modelpath + self.fname, 'r') as read_verilog:
                verilog_data = read_verilog.readlines()
        is_sv = os.path.splitext(self.fname)[1] == ".sv"
        # Only when the identity CAME from the file name (TLV output, or a
        # design whose top really is `top`). When resolve_identity() read a
        # real module name out of the source, `top` in that source is some
        # other identifier and renaming it would corrupt the user's design.
        rename_top = is_sv and self._rename_top_to_stem
        with open(self.modelpath + self.fname, 'w') as f:
            for item in verilog_data:
                if rename_top:
                    # Rename the SV top module to the file's stem. A bare
                    # substring replace mangled any identifier CONTAINING
                    # "top" (stop, laptop, top_val); a word-boundary regex
                    # only touches the standalone token.
                    string = re.sub(r'\btop\b', modname, item)
                else:
                    string = item
                f.write(string)
            f.write("\n")
        return "No Error"

    def sandpiper(self):
        '''
            This function calls the sandpiper to convert .tlv file to .sv file
        '''
        # Text="Running Sandpiper............"
        print("Running Sandpiper-Saas for TLV to SV Conversion")
        tlv = paths.library_path("tlv")
        # Pure-Python copy: no sh quoting problem when tlv/ or the workspace
        # sits under a spaced path (e.g. a "VLSI Lab" username on MSYS).
        self.termtitle("COPY TLV FILES")
        tlv_files = ["clk_gate.v", "pseudo_rand.sv", "sandpiper.vh",
                     "sandpiper_gen.vh", "sp_default.vh", "pseudo_rand_gen.sv",
                     "pseudo_rand.m4out.tlv"]
        for name in tlv_files:
            shutil.copy2(os.path.join(tlv, name), self.modelpath)
        shutil.copy2(self.file, self.modelpath)
        print("Copied the files required for TLV successfully")

        print("Running Sandpiper............")
        model = os.path.splitext(self.fname)[0]
        self._run(["sandpiper-saas", "-i", model + ".tlv",
                   "-o", model + ".sv"],
                  "RUN SANDPIPER-SAAS", cwd=self.modelpath)
        print("Ran Sandpiper successfully")
        self.fname = model + ".sv"

    def verilogParse(self, make_symbol=True):
        '''
            This function parses the module name and
            input/output ports of verilog code using HDL parse
            and writes to the "connection_info.txt".

            make_symbol=False skips creating the legacy "Ngveri" KiCad symbol,
            so the d_cosim flow can reuse the port parsing and then create its
            own "NgVeriCosim" symbol instead.
        '''
        with open(self.modelpath + self.fname, 'rt') as fh:
            code = fh.read()

        # Strip the standalone "wire"/"reg" keywords hdlparse chokes on. A
        # bare substring replace punched holes in any identifier CONTAINING
        # them (out_reg, wire_sel, addr_reg); a word-boundary regex only
        # touches the standalone tokens -- same fix already used for "top".
        code = re.sub(r'\b(wire|reg)\b', ' ', code)


        header_re = re.compile(r'module\s+\w+\s*\((.*?)\)\s*;', re.S)
        def _split_ports(match):
            # hdlparse only recognises a port declaration at the start of a
            # line, so put every header port on its own line: newline after
            # the opening '(' (else the FIRST port -- still on the "module"
            # line -- is silently dropped) and after every comma.
            return match.group(0).replace('(', '(\n', 1).replace(',', ',\n')
        code = header_re.sub(_split_ports, code)
        vlog_ex = vlog.VerilogExtractor()
        vlog_mods = vlog_ex.extract_objects_from_source(code)

        modname = os.path.splitext(self.fname)[0]
        # hdlparse returns nothing for an empty file, a syntax error or a
        # construct it cannot parse. The old code then indexed a loop variable
        # `m` that was never bound -> "NameError: m" instead of a useful
        # message. Bail early with a clear error.
        if not vlog_mods:
            Dialogs.critical(
                None, "Error Message",
                "<b>Error: No Verilog module could be parsed from " +
                self.fname + ". Check the file for syntax errors.</b>",
                QtWidgets.QMessageBox.StandardButton.Ok)
            self.obj_Appconfig.print_info(
                'NgVeri stopped: no parseable module in ' + self.fname)
            return "Error"

        matched = None
        with open(self.modelpath + "connection_info.txt", 'w') as f:
            for m in vlog_mods:
                if m.name.lower() == modname:
                    print(str(m.name) + " " + modname)
                    for p in m.ports:
                        print(p.data_type)
                        if str(p.data_type).find(':') == -1:
                            p.port_number = "1"
                        else:
                            x = p.data_type.split(":")
                            print(x)
                            y = x[0].split("[")
                            z = x[1].split("]")
                            z = int(y[1]) - int(z[0])
                            p.port_number = z + 1

            for m in vlog_mods:
                if m.name.lower() == modname:
                    m.name = m.name.lower()
                    matched = m
                    print('Module "{}":'.format(m.name))
                    for p in m.generics:
                        print('\t{:20}{:8}{}'.format(
                            p.name, p.mode, p.data_type))
                    print('  Ports:')
                    for p in m.ports:
                        print(
                            '\t{:20}{:8}{}'.format(
                                p.name, p.mode, p.port_number))
                        f.write(
                            '\t{:20}{:8}{}\n'.format(
                                p.name, p.mode, p.port_number))
                    break
        if matched is None:
            # NOT a name mismatch any more -- resolve_identity() names the
            # model after this very source, so the only way to get here is
            # hdlparse failing to read a module the identity parser could.
            # Say that, instead of sending the user off to rename a file that
            # has nothing to do with it.
            found = ", ".join(str(m.name) for m in vlog_mods)
            Dialogs.critical(
                None,
                "Error Message",
                "<b>Error: could not read the ports of module '" +
                str(modname) + "'.</b><br/><br/>"
                "eSim parsed this design as: " + (found or "(nothing)") +
                ".<br/>Check the module header and port declarations for a "
                "syntax error, then try again.",
                QtWidgets.QMessageBox.StandardButton.Ok)

            self.obj_Appconfig.print_info(
                "NgVeri stopped: could not read the ports of module '" +
                str(modname) + "'")
            return "Error"
        if make_symbol:
            modelname = str(matched.name)
            schematicLib = createkicad.AutoSchematic()
            schematicLib.init(modelname, self.modelpath)
            error = schematicLib.createKicadSymbol()
            if error == "Error":
                return "Error"
        return "No Error"

    def getPortInfo(self):
        '''
            This function is used to get the port information
            from "connection_info.txt"
        '''
        with open(self.modelpath + 'connection_info.txt', 'r') as readfile:
            data = readfile.readlines()
        self.input_list = []
        self.output_list = []
        # connection_info.txt lines are exactly "name direction bits" (the
        # writer emits hdlparse's p.mode: input / output / inout). Classify on
        # the direction FIELD, not a substring search of the whole line: the
        # old re.findall("INPUT"/"OUTPUT", line) matched the port NAME too, so
        # a port like "output_valid input 1" was counted as both an input and
        # an output. Skipping any line with < 3 fields also removes the old
        # crash where a leading blank line left in_items/out_items unbound.
        for line in data:
            parts = line.split()
            if len(parts) < 3:
                continue
            direction = parts[1].lower()
            if direction in ("input", "inout"):
                self.input_list.append(parts)
            elif direction == "output":
                self.output_list.append(parts)

        self.input_port = []
        self.output_port = []

        # creating list of input and output port with its weight
        for input in self.input_list:
            self.input_port.append(input[0] + ":" + input[2])
        for output in self.output_list:
            self.output_port.append(output[0] + ":" + output[2])

    # Widest port the Verilator/NgVeri flow can carry. Verilator represents a
    # port up to 64 bits as CData/SData/IData/QData -- plain unsigned integers,
    # which int2arr/arr2int convert exactly. Past 64 it becomes VlWide (an
    # array of uint32_t) that no integer conversion can carry: the generated
    # C++ either fails to compile with an unreadable template error or, worse,
    # silently truncates. Refuse it here, where the message can name the port.
    MAX_PORT_WIDTH = 64

    def validate_ports(self):
        '''
            PARKED -- not called by the build. See docs/UPSTREAM_DECISIONS.md
            items 2 and 3.

            Check the parsed port list against what the NgVeri (Verilator)
            backend can actually represent, and return an error string
            describing the first problem, or None if the model is buildable.

            Both shapes it catches produce a model that BUILDS and RUNS and is
            quietly wrong -- but eSim 2.5 built them just the same, so turning
            either into a refusal takes away something the user could do
            before. That is a maintainer decision. Kept and tested so the
            decision can be made on evidence; wire it into
            NgVeri.addverilog() after getPortInfo() to enable it.

            d_cosim has its own inout handling, so this gate is for the legacy
            NgVeri flow only.
        '''
        # inout: getPortInfo() files it under input_list because that is what
        # the rest of the legacy flow can drive. The ifspec then declares it
        # "Direction: in" and the driven half of the pin never reaches ngspice
        # -- the model appears to work and is simply wrong on that net.
        inouts = [p[0] for p in self.input_list
                  if len(p) > 1 and p[1].lower() == "inout"]
        if inouts:
            return ("This model declares inout port(s): " +
                    ", ".join(inouts) + ". The NgVeri (Verilator) backend "
                    "drives them as inputs only, so the output half of the "
                    "pin never reaches ngspice and the results are silently "
                    "wrong. Split the pin into separate in and out ports. "
                    "(The d_cosim backend refuses them for the same reason: "
                    "its code model has an inout group, but eSim's netlister "
                    "never fills it, which misaligns the other ports too.)")

        for item in self.input_port + self.output_port:
            width = self._port_width(item)
            if width > self.MAX_PORT_WIDTH:
                return ("Port '" + item.split(':')[0] + "' is " + str(width) +
                        " bits. The NgVeri (Verilator) backend carries ports "
                        "up to " + str(self.MAX_PORT_WIDTH) + " bits; wider "
                        "ones cannot be converted without truncation. Split "
                        "the port, or use the d_cosim backend.")

        return None

    def build_cosim(self, engine="icarus"):
        '''
            Build a d_cosim digital artifact for this Verilog model and return
            its absolute path (or "Error").

            Uses ngspice's upstream d_cosim code model (ngspice >= 44): the
            Verilog block is loaded at simulation time, so ngspice is never
            rebuilt -- unlike the legacy static Ngveri.cm flow that runs
            "make install".

            Icarus engine (default): iverilog compiles <model>.v to a vvp-format
            file named <model>. NO C/C++ compiler is needed on the user machine;
            at simulation time ngspice's ivlng adapter + libvvp run the vvp. The
            iverilog path is resolved via CosimConfig (env / config.ini / PATH),
            never hardcoded. Requires self.modelpath populated by verilogfile().
        '''
        import subprocess
        import tempfile
        import time
        import shlex

        log = self.clog
        log.phase("BUILD d_cosim MODEL (icarus)")

        if engine != "icarus":
            log.error("d_cosim engine '" + str(engine) + "' not supported. "
                      "Only the Icarus Verilog engine is available.")
            return "Error"

        # ----- [1/4] Resolve toolchain -----
        log.phase("[1/4] Resolve toolchain")
        iverilog = CosimConfig.iverilog_binary()
        if not iverilog or not CosimConfig.has_iverilog():
            log.error("d_cosim build FAILED: " +
                      (CosimConfig.missing_reason() or
                       "iverilog with libvvp not found."))
            log.fix("Install / rebuild Icarus Verilog with --enable-libvvp, "
                    "then retry.")
            return "Error"
        log.info("iverilog: " + iverilog)
        log.detail("version: " + self._tool_version(iverilog))

        model = self.model_stem
        src = os.path.abspath(os.path.join(self.modelpath, self.fname))
        # Build the vvp at the ONE canonical location the netlister also
        # derives (CosimConfig.cosim_vvp_target, keyed by the lowercased model
        # name). Decoupling it from modelpath's case is what stops the compiled
        # model from going missing at simulation time on case-sensitive
        # filesystems (build wrote <Model>/<Model>, lookup read <model>/<model>).
        out = CosimConfig.cosim_vvp_target(model)
        if out:
            os.makedirs(os.path.dirname(out), exist_ok=True)
        else:
            out = os.path.abspath(os.path.join(self.modelpath, model.lower()))
        # A pre-split build of this model left a vvp inside the LEGACY tree,
        # which cosim_vvp_path still resolves as a fallback. Drop that file (the
        # file only -- its directory may be a legacy NgVeri build) so the
        # rebuilt model cannot lose to a stale one at simulation time.
        stale = CosimConfig.legacy_cosim_vvp_path(model)
        if stale and stale != out and os.path.isfile(stale):
            try:
                os.remove(stale)
                log.detail("Removed the pre-split vvp at " + stale)
            except OSError as err:
                log.warn("Could not remove the pre-split vvp at " + stale +
                         ": " + str(err))
        log.info("Model:       " + model)
        log.info("Source:      " + src)
        log.info("Output vvp:  " + out)

        if not os.path.isfile(src):
            log.error("d_cosim build FAILED: source Verilog not found at " +
                      src)
            log.fix("The model dir was not populated (or was removed after a "
                    "backend switch). Re-run the build; verilogfile() should "
                    "copy the .v in first.")
            return "Error"

        # d_cosim's code model does have a d_inout group, but eSim's port
        # parser files `inout` under the inputs, so the netlist declares it as
        # a plain d_in and the group stays empty. ngspice then reports
        # "mismatched XSPICE/co-simulator input counts: 2/1" and "inout counts:
        # 0/1" -- two lines in a wall of output -- and carries on with the port
        # indices off by the width of the inout. Measured on a probe module
        # whose only inout is driven by the design: the inout never leaves the
        # simulation AND a sibling output declared `assign q = 1'b1;` toggled
        # with the clock. Every port is wrong, not just the bidirectional one,
        # so this is refused rather than warned about.
        # Read connection_info.txt directly rather than self.input_list: the
        # d_cosim flow never calls getPortInfo(). Lines are "name direction
        # bits", so match on the direction FIELD -- a port named "inout_en"
        # is not a bidirectional pin.
        inouts = []
        try:
            path = os.path.join(self.modelpath, 'connection_info.txt')
            with open(path) as fh:
                for entry in fh:
                    fields = entry.split()
                    if len(fields) > 1 and fields[1].lower() == 'inout':
                        inouts.append(fields[0])
        except OSError:
            pass
        if inouts:
            log.error("d_cosim build REFUSED: this module declares inout "
                      "port(s): " + ", ".join(inouts) + ".")
            log.fix("eSim cannot wire a bidirectional pin to either backend "
                    "yet -- the netlist declares it as an input, which "
                    "misaligns every port and silently corrupts the outputs "
                    "too. Split the pin into separate in and out ports.")
            return "Error"

        try:
            # ----- [2/4] Prepare source -----
            log.phase("[2/4] Prepare source")
            # d_cosim/ivlng needs a `timescale to advance VVP ticks; without one
            # the tick length defaults to 1 second and combinational logic never
            # re-evaluates. Inject one transparently if the source lacks it,
            # and sharpen a too-coarse one the source declares itself (see
            # normalise_timescale) -- both leave the design's delays alone.
            with open(src, 'r') as fh:
                verilog_text = fh.read()
            compile_src = src
            tmp_src = None
            if '`timescale' not in verilog_text:
                prepared = '`timescale 1ns/1ps\n' + verilog_text
                note = "Injected `timescale 1ns/1ps (absent in source)."
            else:
                prepared, coarse = normalise_timescale(verilog_text)
                note = ("Sharpened `timescale precision to 1ps (source "
                        "declared " + ", ".join(coarse) + "; VVP cannot "
                        "advance in steps shorter than one precision tick, "
                        "so the design would have stayed frozen)."
                        if coarse else "")
                if not coarse:
                    log.detail("`timescale present in source, precision OK.")
            if prepared != verilog_text:
                tmp_fd, tmp_src = tempfile.mkstemp(
                    suffix=os.path.splitext(self.fname)[1] or '.v',
                    dir=os.path.abspath(self.modelpath))
                os.write(tmp_fd, prepared.encode())
                os.close(tmp_fd)
                compile_src = tmp_src
                log.info(note)

            # The design is simulated through a generated wrapper that reads
            # an x input as logic 1, matching NgVeri bit-for-bit; see
            # cosim_wrapper_source. Without it, the x window adc_bridge emits
            # between in_low and in_high reaches Icarus as a second clock edge
            # and the design counts twice per period.
            wrapper_src = None
            try:
                with open(os.path.join(self.modelpath,
                                       'connection_info.txt')) as fh:
                    ports = parse_connection_info(fh.read())
            except OSError:
                ports = []
            if ports:
                wrapper_text = cosim_wrapper_source(
                    [(model.lower(), model, ports)],
                    declared_timescale(prepared))
                wrapper_src = os.path.join(
                    os.path.abspath(self.modelpath),
                    COSIM_TOP_MODULE + '.v')
                with open(wrapper_src, 'w') as fh:
                    fh.write(wrapper_text)
                log.info("Wrapped %d port(s) so an x input reads as logic 1 "
                         "(matches the NgVeri backend)." % len(ports))
            else:
                log.detail("No parsed ports; compiling the design directly.")

            # ----- [3/4] Compile -----
            log.phase("[3/4] Compile")
            # -y/-I/-Y: resolve submodules and `include files the user added
            # through "Add dependency files/folder", which land beside the top
            # source in modelpath. Without them iverilog sees one file and any
            # multi-file design dies on "Unknown module type". -y only pulls a
            # file in when a module is still unresolved, so a self-contained
            # design compiles exactly as before.
            libdir = os.path.abspath(self.modelpath)
            extra_flags = ["-y", libdir, "-I", libdir, "-Y", ".sv"]
            # The wrapper goes first so it is unambiguously the root module:
            # iverilog roots every module nothing instantiates, and the design
            # is instantiated by the wrapper. ivlng simulates whichever root
            # VVP reports first (vpi.c start_cb).
            sources = ([wrapper_src] if wrapper_src else []) + [compile_src]
            cmd = ([iverilog, "-g2012"] + extra_flags
                   + ["-o", out] + sources)
            log.info("$ " + " ".join(shlex.quote(c) for c in cmd))
            start = time.monotonic()
            try:
                # Same iverilog invocation path as the Verilog Simulator IDE
                # (hdl.icarus), so both features stay byte-for-byte consistent.
                res = icarus.run_iverilog(
                    iverilog, sources, out, extra_flags=extra_flags,
                    cwd=os.path.abspath(self.modelpath), timeout=300)
            finally:
                if tmp_src and os.path.isfile(tmp_src):
                    os.remove(tmp_src)
            elapsed = time.monotonic() - start
            log.output(res.stdout, 'stdout')
            log.output(res.stderr, 'stderr')
            log.info("iverilog exited rc=%d in %.2fs"
                     % (res.returncode, elapsed))

            # ----- [4/4] Verify artifact -----
            log.phase("[4/4] Verify artifact")
            if not res.ok:
                log.error("d_cosim model build FAILED (rc=%d)."
                          % res.returncode)
                if icarus.vpi_load_failed(res.output):
                    log.fix("A VPI module (e.g. system.vpi) failed to load: "
                            "the MinGW runtime DLLs next to iverilog are "
                            "missing or shadowed. Reinstall eSim -- the "
                            "installer ships them beside iverilog's binaries "
                            "(bin and lib\\ivl).")
                else:
                    log.fix("Check the compiler errors above (syntax, missing "
                            "module, or a construct Icarus -g2012 rejects).")
                return "Error"
            log.ok("Built d_cosim model: %s (%d bytes)"
                   % (out, os.path.getsize(out)))
            return out
        except subprocess.TimeoutExpired:
            log.error("iverilog timed out after 300s.")
            log.fix("Simplify the design or raise the build timeout.")
            return "Error"
        except Exception as e:
            log.error("d_cosim build error: " + str(e))
            return "Error"

    def _tool_version(self, binary):
        '''
            First line of "<binary> -V", or "unknown". Best-effort: identifies
            which compiler actually ran, and never raises.
        '''
        try:
            import subprocess
            res = subprocess.run([binary, "-V"], capture_output=True,
                                 text=True, timeout=10,
                                 creationflags=self.NO_WINDOW)
            lines = (res.stdout or res.stderr or "").strip().splitlines()
            return lines[0] if lines and lines[0].strip() else "unknown"
        except Exception:
            return "unknown"

    def cfuncmod(self):
        '''
            This function is used to create the "cfunc.mod" file
            in Ngspice folder automatically.
        '''

        # ############# Creating content for cfunc.mod file ############## #

        print("Starting With cfunc.mod file")
        cfunc = open(self.modelpath + 'cfunc.mod', 'w')
        print("Building content for cfunc.mod file")

        comment = '''/* This cfunc.mod file auto generated by gen_con_info.py
        Developed by Sumanto, Rahul at IIT Bombay */\n
                '''

        header = '''
        #include <stdio.h>
        #include <math.h>
        #include <string.h>
        #include "sim_main_''' + self.model_stem + '''.h"

        '''

        function_open = (
            '''void cm_''' + self.model_stem + '''(ARGS) \n{''')

        digital_state_output = []
        for item in self.output_port:
            digital_state_output.append(
                "Digital_State_t *_op_" + item.split(':')[0] +
                ", *_op_" + item.split(':')[0] + "_old;"
            )

        var_section = '''
    static int inst_count=0;
    int count=0;
        '''

        # Start of INIT function
        init_start_function = '''
    if(INIT)
    {
        inst_count++;
        PARAM(instance_id)=inst_count;
        foo_''' + self.model_stem + '''(0,inst_count);
        /* Allocate storage for output ports \
and set the load for input ports */

        '''
        port_init = []
        for i, item in enumerate(self.input_port + self.output_port):
            port_init.append(self.model_stem + '''_port_''' +
                             item.split(':')[0] + '''=PORT_SIZE(''' +
                             item.split(':')[0] + ''');
''')

        cm_event_alloc = []
        cm_count_output = 0
        for item in self.output_port:
            cm_event_alloc.append(
                "cm_event_alloc(" +
                str(cm_count_output) + "," + item.split(':')[1] +
                "*sizeof(Digital_State_t));"
            )
            cm_count_output = cm_count_output + 1

        load_in_port = []
        for item in self.input_port:
            load_in_port.append(
                "for(Ii=0;Ii<PORT_SIZE(" + item.split(':')[0] +
                ");Ii++)\n\t\t{\n\t\t\tLOAD(" + item.split(':')[0] +
                "[Ii])=PARAM(input_load); \n\t\t}"
            )

        cm_count_ptr = 0
        cm_event_get_ptr = []
        for item in self.output_port:
            cm_event_get_ptr.append(
                "_op_" + item.split(':')[0] + " = _op_" +
                item.split(':')[0] +
                "_old = (Digital_State_t *) cm_event_get_ptr(" +
                str(cm_count_ptr) + ",0);"
            )

            cm_count_ptr = cm_count_ptr + 1

        # cm_event_get_ptr(tag, timepoint): the two arguments are ORTHOGONAL.
        # `tag` selects the block cm_event_alloc'd for this port; `timepoint`
        # says how far BACK in the rotating state history to look -- 0 is the
        # current timestep, 1 the previous one (ngspice cm/cmevt.c, and every
        # stock code model: see d_dff, which uses (0,0)/(0,1) .. (3,0)/(3,1)
        # for its four tags).
        #
        # This loop used to carry a second counter that was initialised once
        # OUTSIDE it and bumped twice per port, so it tracked the tag index
        # instead of resetting: port 0 got the correct (0,0)/(0,1) but port 1
        # got (1,1)/(1,2), port 2 (2,2)/(2,3) and so on. Every port after the
        # first therefore wrote its new value into a PREVIOUS timestep's block
        # -- one ngspice has already copied forward, so the current block never
        # saw it -- and compared against a block two steps back which, since
        # ngspice 45 collapses the state history at every accepted timestep,
        # aliases onto the one just written. `_op_x[i] != _op_x_old[i]` is then
        # permanently false, OUTPUT_CHANGED stays FALSE, and the pin holds its
        # first transition forever.
        #
        # It is not a 2.6 regression: the same loop shipped in 2.5, where
        # ngspice 35 kept the full per-instance state history and the
        # out-of-range timepoint happened to land on a self-consistent block.
        # ngspice 45's state-recycling removed that padding and made a
        # long-latent bug live. Models built before this fix carry the bad
        # indices in their compiled cfunc.mod and must be rebuilt.
        els_evt_ptr = []
        for tag, item in enumerate(self.output_port):
            els_evt_ptr.append("_op_" + item.split(":")[0] +
                               " = (Digital_State_t *) cm_event_get_ptr(" +
                               str(tag) + ",0);")
            els_evt_ptr.append("_op_" + item.split(":")[0] + "_old" +
                               " = (Digital_State_t *) cm_event_get_ptr(" +
                               str(tag) + ",1);")

        # Assign bit value to every input
        assign_data_to_input = []
        for item in self.input_port:
            assign_data_to_input.append("\
    for(Ii=0;Ii<PORT_SIZE(" + item.split(':')[0] + ");Ii++)\n\
    {\n\
        if( INPUT_STATE(" + item.split(':')[0] + "[Ii])==ZERO )\n\
        {\n\
            " + self.model_stem +
                "_temp_" + item.split(':')[0] + "[Ii]=0;\
            }\n\
        else\n\
        {\n\
            " + self.model_stem +
                "_temp_" + item.split(':')[0] + "[Ii]=1;\n\
        }\n\
            }\n")

        # Scheduling output event
        sch_output_event = []

        for item in self.output_port:
            sch_output_event.append(
                "\t/* Scheduling event and processing them */\n\
    for(Ii=0;Ii<PORT_SIZE(" + item.split(':')[0] + ");Ii++)\n\
    {\n\
        if(" + self.model_stem + "_temp_" +
                item.split(':')[0] + "[Ii]==0)\n\
        {\n\
            _op_" + item.split(':')[0] + "[Ii]=ZERO;\n\
            }\n\
        else if(" + self.model_stem +
                "_temp_" + item.split(':')[0] + "[Ii]==1)\n\
        {\n\
            _op_" + item.split(':')[0] + "[Ii]=ONE;\n\
            }\n\
        else\n\
        {\n\
            /* Neither 0 nor 1. This used to printf and fall through, leaving\n\
               _op_ at whatever the previous timestep left there -- a stale\n\
               level silently presented as real data, once per timestep. Drive\n\
               the port to the X state the type actually has. */\n\
            _op_" + item.split(':')[0] + "[Ii]=UNKNOWN;\n\
                }\n\n\
        if(ANALYSIS == DC)\n\
        {\n\
            OUTPUT_STATE(" + item.split(':')[0] +
                "[Ii]) = _op_" + item.split(':')[0] + "[Ii];\n\
            }\n\
        else if(_op_" + item.split(':')[0] +
                "[Ii] != _op_" + item.split(':')[0] + "_old[Ii])\n\
        {\n\
            OUTPUT_STATE(" + item.split(':')[0] + "[Ii]) = _op_" +
                item.split(':')[0] + "[Ii];\n\
            OUTPUT_DELAY(" + item.split(':')[0] + "[Ii]) = ((_op_" +
                item.split(':')[0] +
                "[Ii] == ZERO) ? PARAM(fall_delay) : PARAM(rise_delay));\n\
            }\n\
        else\n\
        {\n\
            OUTPUT_CHANGED(" + item.split(':')[0] + "[Ii]) = FALSE;\n\
            }\n\
        OUTPUT_STRENGTH(" + item.split(':')[0] + "[Ii]) = STRONG;\n\
    }\n")

        # Writing content in cfunc.mod file
        cfunc.write(comment)
        cfunc.write(header)
        cfunc.write("\n")
        cfunc.write(function_open)
        cfunc.write("\n")

        # Adding digital state Variable
        for item in digital_state_output:
            cfunc.write("\t" + item + "\n")

        # Adding variable declaration section
        cfunc.write(var_section)

        # Adding INIT portion
        cfunc.write(init_start_function)
        for item in port_init:
            cfunc.write(item)
        for item in cm_event_alloc:
            cfunc.write(2 * "\t" + item)
            cfunc.write("\n")

        cfunc.write(2 * "\t" + "/* set the load for input ports. */")
        cfunc.write("\n")
        cfunc.write(2 * "\t" + "int Ii;")
        cfunc.write("\n")

        for item in load_in_port:
            cfunc.write(2 * "\t" + item)
            cfunc.write("\n")
        cfunc.write("\n")
        cfunc.write(2 * "\t" + "/*Retrieve Storage for output*/")
        cfunc.write("\n")
        for item in cm_event_get_ptr:
            cfunc.write(2 * "\t" + item)
            cfunc.write("\n")
        cfunc.write("\n")

        cfunc.write("\n\t}")
        cfunc.write("\n")
        cfunc.write("\telse\n\t{\n")

        for item in els_evt_ptr:
            cfunc.write(2 * "\t" + item)
            cfunc.write("\n")
        cfunc.write("\t}")
        cfunc.write("\n\n")

        cfunc.write("\t//Formating data for sending it to client\n")
        cfunc.write("\tint Ii;\n")
        cfunc.write("\tcount=(int)PARAM(instance_id);\n\n")
        for item in assign_data_to_input:
            cfunc.write(item)

        cfunc.write("\tfoo_" + self.model_stem + "(1,count);\n\n")

        for item in sch_output_event:
            cfunc.write(item)

        # Close cm_ function
        cfunc.write("\n}")
        cfunc.close()

    def ifspecwrite(self):
        '''
            This function creates the ifspec file
            automatically in Ngspice folder.
        '''
        print("Starting with ifspec.ifs file")
        ifspec = open(self.modelpath + 'ifspec.ifs', 'w')

        print("Gathering Al the content for ifspec file")

        ifspec_comment = '''
        /*
        SUMMARY: This file is auto generated and it contains the interface
         specification for the code model. */\n
        '''

        name_table = 'NAME_TABLE:\n\
        C_Function_Name: cm_' + self.model_stem + '\n\
        Spice_Model_Name: ' + self.model_stem + '\n\
        Description: "Model generated from Verilog code ' + self.fname + '" \n'

        # Input and Output Port Table
        in_port_table = []
        out_port_table = []

        for item in self.input_port:
            port_table = 'PORT_TABLE:\n'
            port_name = 'Port_Name:\t' + item.split(':')[0] + '\n'
            description = (
                'Description:\t"input port ' + item.split(':')[0] + '"\n'
            )
            direction = 'Direction:\tin\n'
            default_type = 'Default_Type:\td\n'
            allowed_type = 'Allowed_Types:\t[d]\n'
            vector = 'Vector:\tyes\n'
            vector_bounds = (
                'Vector_Bounds:\t[' + item.split(':')[1] +
                ' ' + item.split(":")[1] + ']\n'
            )
            null_allowed = 'Null_Allowed:\tno\n'

            # Insert detail in the list
            in_port_table.append(
                port_table + port_name + description +
                direction + default_type + allowed_type +
                vector + vector_bounds + null_allowed
            )

        for item in self.output_port:
            port_table = 'PORT_TABLE:\n'
            port_name = 'Port_Name:\t' + item.split(':')[0] + '\n'
            description = (
                'Description:\t"output port ' + item.split(':')[0] + '"\n'
            )
            direction = 'Direction:\tout\n'
            default_type = 'Default_Type:\td\n'
            allowed_type = 'Allowed_Types:\t[d]\n'
            vector = 'Vector:\tyes\n'
            vector_bounds = (
                'Vector_Bounds:\t[' + item.split(':')[1] +
                ' ' + item.split(":")[1] + ']\n'
            )
            null_allowed = 'Null_Allowed:\tno\n'

            # Insert detail in the list. This is the OUTPUT loop, so it must
            # feed out_port_table: it used to append to in_port_table and the
            # "for item in out_port_table" writer below was dead. The file came
            # out right purely because one list preserved the order -- any edit
            # touching only out_port_table silently did nothing.
            out_port_table.append(
                port_table + port_name + description +
                direction + default_type + allowed_type +
                vector + vector_bounds + null_allowed
            )

        parameter_table = '''

        PARAMETER_TABLE:
        Parameter_Name:     instance_id                  input_load
        Description:        "instance_id"                "input load value (F)"
        Data_Type:          real                         real
        Default_Value:      0                            1.0e-12
        Limits:             -                            -
        Vector:              no                          no
        Vector_Bounds:       -                           -
        Null_Allowed:       yes                          yes

        PARAMETER_TABLE:
        Parameter_Name:     rise_delay                  fall_delay
        Description:        "rise delay"                "fall delay"
        Data_Type:          real                        real
        Default_Value:      1.0e-9                      1.0e-9
        Limits:             [1e-12 -]                   [1e-12 -]
        Vector:              no                          no
        Vector_Bounds:       -                           -
        Null_Allowed:       yes                         yes

        '''

        # Writing all the content in ifspec file
        ifspec.write(ifspec_comment)
        ifspec.write(name_table + "\n\n")

        for item in in_port_table:
            ifspec.write(item + "\n")

        ifspec.write("\n")

        for item in out_port_table:
            ifspec.write(item + "\n")

        ifspec.write("\n")
        ifspec.write(parameter_table)
        ifspec.write("\n")
        ifspec.close()

    def sim_main_header(self):
        '''
            This function creates the header file of
            "sim_main" file automatically in Ngspice folder.
        '''
        print("Starting With sim_main_" + self.model_stem + ".h file")
        simh = open(
            self.modelpath +
            'sim_main_' +
            self.model_stem +
            '.h',
            'w')
        print("Building content for sim_main_" +
              self.model_stem + ".h file")
        simh.write("int foo_" + self.model_stem + "(int,int);")
        extern_var = []
        # One array per port, sized from the port's ACTUAL width instead of a
        # blanket [1024]. The ifspec pins Vector_Bounds to [width width], so
        # ngspice connects exactly `width` bits and every loop here runs
        # 0..PORT_SIZE-1 == 0..width-1. The old fixed size silently overflowed
        # for a port wider than 1024 bits (corrupt co-sim data, no diagnostic)
        # and wasted 4 KB per port for the ordinary 1-8 bit case.
        for i, item in enumerate(self.input_port + self.output_port):
            extern_var.append('''
        int ''' + self.model_stem + '''_temp_''' +
                              item.split(':')[0] + '''[''' +
                              str(self._port_width(item)) + '''];
        int ''' + self.model_stem + '''_port_''' +
                              item.split(':')[0] + ''';''')
        for item in extern_var:
            simh.write(item)
        simh.close()

    def sim_main(self):
        '''
            This function creates the "sim_main" file needed by verilator
            automatically in Ngspice folder.
        '''
        print(
            "Starting With sim_main_" +
            self.model_stem +
            ".cpp file")
        csim = open(
            self.modelpath +
            'sim_main_' +
            self.model_stem +
            '.cpp',
            'w')
        print(
            "Building content for sim_main_" +
            self.model_stem +
            ".cpp file")

        comment = \
            '''/* This is cfunc.mod file auto generated by gen_con_info.py
        Developed by Sumanto Kar at IIT Bombay */\n
        '''

        header = '''
        #include <memory>
        #include <verilated.h>
        #include "V''' + self.model_stem + '''.h"
        #include <stdio.h>
        #include <fstream>
        #include <stdlib.h>
        #include <string>
        #include <iostream>
        #include <cstring>
        #include <cstdint>
        using namespace std;

        /* Per-iteration port tracing. This model is evaluated once per ngspice
           timestep (hundreds to millions of times), so tracing it on stdout
           drowns the simulator's own output in the eSim console and costs a
           write() per line. Off by default; rebuild the model with
           -DESIM_NGVERI_TRACE to get the old behaviour back. */
        #ifdef ESIM_NGVERI_TRACE
        #define ESIM_TRACE(...) printf(__VA_ARGS__)
        #else
        #define ESIM_TRACE(...) ((void)0)
        #endif

        /* How many instances of this model one netlist may hold. The array
           below is indexed by ngspice's instance_id, which is not known when
           this file is generated, so the bound stays a compile-time constant --
           but it is now CHECKED (see foo_ below) instead of being written past
           silently. */
        #define ''' + self.model_stem + '''_MAX_INSTANCES 1024
        '''

        extern_var = []
        # Widths must match sim_main_<stem>.h, which owns the definitions.
        for i, item in enumerate(self.input_port + self.output_port):
            extern_var.append('''
        extern "C" int ''' + self.model_stem +
                              '''_temp_''' + item.split(':')[0] + '''[''' +
                              str(self._port_width(item)) + '''];
        extern "C" int ''' + self.model_stem +
                              '''_port_''' + item.split(':')[0] + ''';''')

        extern_var.append('''
        extern "C" int foo_''' + self.model_stem + '''(int,int);
        ''')
        # Verilator hands a port over as CData/SData/IData/QData -- all
        # UNSIGNED. These two took and returned `int`, which broke both
        # directions once a port reached 32 bits:
        #
        #   int2arr: a 32-bit output whose top bit was set arrived NEGATIVE,
        #   the loop's `num>=0` guard failed on iteration 0, the body never
        #   ran at all, and the temp array silently kept the PREVIOUS
        #   timestep's bits -- the port froze for the entire upper half of its
        #   range with no diagnostic. (ml_act_relu_64bit_q32_32's frac_out[31:0]
        #   is a real instance of this.)
        #
        #   arr2int: `k = 2*k + array[i]` over 32 bits is signed overflow,
        #   i.e. undefined behaviour, not merely a wrap.
        #
        # Both now work on uint64_t and extract/insert bits instead of
        # dividing, which is exact for every width up to 64, and bit-identical
        # to the old code for every width under 32 -- so no result that was
        # ever well-defined can move. Wider than 64 remains as broken as it was
        # in 2.5 (Verilator represents those as VlWide, which no integer
        # conversion can carry); validate_ports() would catch it but is parked,
        # see docs/UPSTREAM_DECISIONS.md item 3.
        convert_func = '''
        void int2arr''' + self.model_stem + \
            '''(uint64_t num, int array[], int n)
        {
            for (int i = 0; i < n; i++)
                array[n-i-1] = (int)((num >> i) & 1u);
        }
        uint64_t arr2int''' + self.model_stem + '''(const int array[], int n)
        {
            uint64_t k = 0;
            for (int i = 0; i < n; i++)
                k = (k << 1) | (uint64_t)(array[i] & 1);
            return k;
        }
        '''
        foo_func = '''
        int foo_''' + self.model_stem + '''(int init,int count)
        {
            int argc=1;
            const char* argv[]={"fullverbose"};
            Verilated::commandArgs(argc, argv);
            static VerilatedContext* contextp = new VerilatedContext;
            static V''' + self.model_stem + "* " + \
            self.model_stem + '''[''' + self.model_stem + \
            '''_MAX_INSTANCES];
            count--;
            if (count < 0 || count >= ''' + self.model_stem + \
            '''_MAX_INSTANCES)
            {
                fprintf(stderr, "''' + self.model_stem + ''': instance %d is \
beyond the %d instances this model was built for; skipping it.\\n",
                        count + 1, ''' + self.model_stem + \
            '''_MAX_INSTANCES);
                return -1;
            }
            if (init==0)
            {
                if (''' + self.model_stem + '''[count] != nullptr) {
                    ''' + self.model_stem + '''[count]->final();
                    delete ''' + self.model_stem + '''[count];
                    ''' + self.model_stem + '''[count] = nullptr;
                }
                contextp->time(0);
                ''' + self.model_stem + '''[count]=new V''' + \
            self.model_stem + '''{contextp};
                contextp->traceEverOn(true);
            }
            else
            {
                contextp->timeInc(1);
                ESIM_TRACE("=============''' + self.model_stem + \
            ''' : New Iteration===========");
                ESIM_TRACE("\\nInstance : %d\\n",count);
                ESIM_TRACE("\\nInside foo before eval.....\\n");
'''

        before_eval = []
        after_eval = []
        # %llu on an explicit cast: the port is CData/SData/IData/QData, so the
        # old "%d" was a format/type mismatch (undefined behaviour) for
        # anything wider than 31 bits whenever the trace was actually enabled.
        for i, item in enumerate(self.input_port + self.output_port):
            before_eval.append(
                '''\t\t\t\tESIM_TRACE("''' +
                item.split(':')[0] +
                '''=%llu\\n", (unsigned long long)(''' +
                self.model_stem +
                '''[count] ->''' +
                item.split(':')[0] +
                '''));\n''')
        for i, item in enumerate(self.input_port):

            before_eval.append(
                '''\t\t\t\t''' +
                self.model_stem +
                '''[count]->''' +
                item.split(':')[0] +
                ''' = arr2int''' +
                self.model_stem +
                '''(''' + self.model_stem + '''_temp_''' +
                item.split(':')[0] +
                ''', ''' + self.model_stem + '''_port_''' +
                item.split(':')[0] +
                ''');\n''')
        before_eval.append(
            "\t\t\t\t" +
            self.model_stem +
            "[count]->eval();\n")

        after_eval.append('''
                ESIM_TRACE("\\nInside foo after eval.....\\n");\n''')
        for i, item in enumerate(self.input_port + self.output_port):
            after_eval.append(
                '''\t\t\t\tESIM_TRACE("''' +
                item.split(':')[0] +
                '''=%llu\\n", (unsigned long long)(''' +
                self.model_stem +
                '''[count] ->''' +
                item.split(':')[0] +
                '''));\n''')

        for i, item in enumerate(self.output_port):
            after_eval.append(
                "\t\t\t\tint2arr" +
                self.model_stem +
                "(" +
                self.model_stem +
                '''[count] -> ''' +
                item.split(':')[0] +
                ''', ''' + self.model_stem + '''_temp_''' +
                item.split(':')[0] +
                ''', ''' + self.model_stem + '''_port_''' +
                item.split(':')[0] +
                ''');\n''')
        after_eval.append('''
            }
            return 0;
        }''')

        csim.write(comment)
        csim.write(header)
        for item in extern_var:
            csim.write(item)
        csim.write(convert_func)
        csim.write(foo_func)

        for item in before_eval:
            csim.write(item)
        for item in after_eval:
            csim.write(item)
        csim.close()

    def modpathlst(self):
        '''
            This function creates modpathlst in Ngspice folder.
        '''
        print("Editing modpath.lst file")
        # Create-if-missing before reading: the list (and its directory) is
        # built lazily, so on a fresh tree a convert that runs before the remove
        # dialog was ever opened used to hit FileNotFoundError here.
        path = _ensure_modpath(self.legacy_home + '/modpath.lst')
        # The shared appender does exact-LINE membership -- a plain "in text"
        # substring test wrongly treats "divider" as already present because
        # "divider_8bit" contains it, silently dropping the shorter model from
        # Ngveri.cm -- and guarantees the entry starts on its own line, so a
        # file whose last line lacks a trailing newline cannot be glued into
        # "oldmodelnewmodel" (one ghost entry like that makes cmpp abort the
        # ENTIRE build).
        _append_modpath_line(path, self.model_stem)
        # Self-heal: a stale entry whose build dir was deleted (an interrupted
        # teardown, or a tree removed outside eSim) makes cmpp abort the ENTIRE
        # Ngveri.cm build -- "Unable to open <model>/ifspec.ifs". Drop such
        # ghosts now so one dead entry can't take every other model down with
        # it. (Until the two backends were given separate trees, the usual
        # source of these was a d_cosim teardown rmtree'ing the shared
        # <model>/ dir out from under a legacy entry.)
        self.prune_modpathlst()

    def prune_modpathlst(self):
        '''
            Rewrite modpath.lst keeping only entries whose build dir still has
            an ifspec.ifs (what cmpp needs), and de-duplicating. Returns the
            list of dropped (ghost / duplicate) names; logs each via clog.

            This is the guard that keeps a single orphaned model -- the usual
            fallout of switching a model between the d_cosim and legacy NgVeri
            flows -- from breaking the build for all the others.

            The scan/rewrite itself lives in the stdlib-only shared helper, so
            it is atomic (a truncated list makes cmpp abort every later build)
            and byte-identical to the NGHDL-side teardown.
        '''
        dropped = _prune_modpath(
            self.legacy_home + '/modpath.lst', self.legacy_home)
        for name in dropped:
            self.clog.warn(
                'Pruned stale model "' + name + '" from modpath.lst '
                '(its build dir / ifspec.ifs is missing).')
        return dropped

    def run_verilator(self):
        '''
            This function is used to run the Verilator
            using the verilator commands.
        '''
        wno = []
        try:
            with open(paths.library_path("tlv/lint_off.txt")) as file:
                for item in file.readlines():
                    if item and item.strip():
                        wno.append("-Wno-" + item.strip())
        except OSError:
            # A missing lint_off.txt should degrade to "no extra -Wno" rather
            # than crash the whole verilator build with a raw exception.
            wno = []

        print("Running Verilator.............")
        self.release_home = self.parser.get('NGHDL', 'RELEASE')
        # print(self.modelpath)

        # Windows: VERILATOR_ROOT/PATH go into the environment (a shell
        # `export` has no meaning for a direct exec) rather than being glued
        # onto a `sh -c` string.
        env = self._nt_build_env()
        verilator = self._verilator_binary()
        if not verilator:
            return False

        model = os.path.splitext(self.fname)[0]
        # -DVL_TIME_CONTEXT: verilated.o is (re)built by the generated .mk
        # with these CFLAGS. Without it verilated.cpp leaves the weak
        # sc_time_stamp() reference undefined, which a Linux .so tolerates but
        # the Windows Ngveri.cm DLL link rejects (undefined reference).
        cmd = [
            verilator, "--stats", "-O3",
            "-CFLAGS", "-O3", "-CFLAGS", "-DVL_TIME_CONTEXT",
            "-LDFLAGS", "-static", "--x-assign", "fast",
            "--x-initial", "fast", "--noassert", "--bbox-sys", "-Wall",
        ] + wno + [
            # Pin the generated class/file prefix to OUR model stem. Verilator
            # names its output after the top module as DECLARED, so a design
            # whose module is `NAND_Gate` produced VNAND_Gate.mk while the make
            # step below (and sim_main's #include) looked for Vnand_gate.mk --
            # which a case-insensitive Windows filesystem hides and Linux does
            # not. With --prefix the two cannot drift apart.
            "--prefix", "V" + model,
            # Elaborate the SAME module the ifspec was generated from. The
            # generated sim_main drives the ports eSim parsed off our top; if
            # verilator picks a different root out of a multi-module file --
            # which it is free to do -- those ports do not exist and the build
            # fails somewhere far less obvious. Naming it makes the two agree
            # by construction.
            "--top-module", self.top_module,
            "--cc", "--exe", "--no-MMD", "--Mdir", ".", "-CFLAGS", "-fPIC",
            "-output-split", "0", "sim_main_" + model + ".cpp", "--autoflush",
            "-DBSV_RESET_FIFO_HEAD", "-DBSV_RESET_FIFO_ARRAY", self.fname,
        ]
        return self._run(cmd, "RUN VERILATOR", cwd=self.modelpath, env=env)

    def make_verilator(self):
        '''
            Running make verilator using this function
        '''
        print("Make Verilator.............")

        stale = os.path.join(self.modelpath, "..", "verilated.o")
        if os.path.exists(stale):
            os.remove(stale)

        make_bin = self._make_binary()
        if not make_bin:
            return False

        model = os.path.splitext(self.fname)[0]
        # Purge make-generated aggregates from any earlier (possibly failed)
        # build of this model: an interrupted verilator_includer leaves an
        # empty V<model>__ALL.cpp that make then treats as up to date, and the
        # resulting symbol-less archive only fails much later at the
        # Ngveri.cm link.
        for leftover in ("V" + model + "__ALL.cpp",
                         "V" + model + "__ALL.o",
                         "V" + model + "__ALL.a"):
            p = os.path.join(self.modelpath, leftover)
            if os.path.exists(p):
                os.remove(p)
        cmd = [make_bin, "-f", "V" + model + ".mk",
               "V" + model + "__ALL.a",
               "sim_main_" + model + ".o",
               "../verilated.o", "../verilated_threads.o"]
        python3 = self._python_for_make()
        if python3:
            cmd.append(python3)
        return self._run(cmd, "MAKE VERILATOR", cwd=self.modelpath,
                         env=self._nt_build_env())

    def copy_verilator(self):
        '''
            This function copies the verilator files/object files from
            "src/xspice/icm/Ngveri/ to release/src/xspice/icm/Ngveri/"
        '''
        print("Copying the required files to Release Folder.............")
        self.release_home = self.parser.get('NGHDL', 'RELEASE')
        ngveri_icm = self.release_home + "/src/xspice/icm/Ngveri/"
        model = os.path.splitext(self.fname)[0]
        # Per-model dir; keep a trailing slash so the os.remove guards below
        # actually target real files. Without it the paths glued to
        # ".../Ngveri/<model>sim_main_..." (note the missing slash), never
        # existed, so the stale-artifact cleanup was a silent no-op.
        path_icm = ngveri_icm + model + "/"
        if not os.path.isdir(path_icm):
            os.makedirs(path_icm, exist_ok=True)
        for stale in (path_icm + "sim_main_" + model + ".o",
                      ngveri_icm + "verilated.o",
                      ngveri_icm + "verilated_threads.o",
                      path_icm + "V" + model + "__ALL.a"):
            if os.path.exists(stale):
                os.remove(stale)
        # shutil instead of `cp` via sh -c: no quoting hazard for spaced
        # release paths, and a copy failure raises here (-> False) instead of
        # a silent nonzero exit that the old success search would have missed.
        self.termtitle("COPYING FILES")
        try:
            shutil.copy2(os.path.join(
                self.modelpath, "sim_main_" + model + ".o"), path_icm)
            shutil.copy2(os.path.join(
                self.modelpath, "V" + model + "__ALL.a"), path_icm)
            shutil.copy2(os.path.normpath(os.path.join(
                self.modelpath, "..", "verilated.o")), ngveri_icm)
            shutil.copy2(os.path.normpath(os.path.join(
                self.modelpath, "..", "verilated_threads.o")), ngveri_icm)
        except OSError as err:
            self.termtext(
                "[NgVeri] Copying build artifacts failed: " + str(err))
            return False
        print("Copied the files")
        return True

    def runMake(self):
        '''
            Running the make command for Ngspice
        '''
        print("run Make Called")
        self.release_home = self.parser.get('NGHDL', 'RELEASE')
        path_icm = os.path.join(self.release_home, "src/xspice/icm")

        make_bin = self._make_binary()
        if not make_bin:
            return False

        print("Running Make command in " + path_icm)
        return self._run([make_bin], "MAKE COMMAND", cwd=path_icm,
                         env=self._nt_build_env())

    def runMakeInstall(self):
        '''
            Running the make install command for Ngspice
        '''
        print("run Make Install Called")
        self.release_home = self.parser.get('NGHDL', 'RELEASE')
        path_icm = os.path.join(self.release_home, "src/xspice/icm")

        make_bin = self._make_binary()
        if not make_bin:
            return False
        print("Running Make Install")
        cmd = [make_bin, "install"]
        if os.name == 'nt':
            # The configured tree bakes the BUILD machine's absolute prefix
            # into makedefs (pkglibdir/pkgdatadir), so a stock `make install`
            # on an end-user PC would write the rebuilt code models into the
            # packager's path instead of this install's install_dir. Override
            # both on the command line from ~/.nghdl/config.ini (forward
            # slashes: these values are make variables).
            try:
                nghdl_home = self.parser.get('NGHDL', 'NGHDL_HOME')
            except Exception:
                nghdl_home = ''
            if nghdl_home:
                inst = os.path.join(nghdl_home, 'install_dir').replace(
                    '\\', '/')
                cmd += ["pkglibdir=" + inst + "/lib/ngspice",
                        "pkgdatadir=" + inst + "/share/ngspice"]
        return self._run(cmd,
                         "MAKE INSTALL COMMAND", cwd=path_icm,
                         env=self._nt_build_env())

    def addfile(self):
        '''
            This function is used to add additional files
            required by the verilog top module.
        '''
        print("Adding the files required by the top level module file")

        includefile = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getOpenFileName(
                Dialogs.resolve_parent(self),
                "Open adding other necessary files to be included",
                os.path.join(paths.repo_root(), "home"))[0])

        if includefile == "":
            reply = Dialogs.critical(
                None, "Error Message",
                "<b>Error: No File Chosen. Please chose a file</b>",
                QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
            )

            if reply == QtWidgets.QMessageBox.StandardButton.Ok:
                self.addfile()

                if includefile == "":
                    return

                self.obj_Appconfig.print_info('Add Other Files Called')

            elif reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                self.obj_Appconfig.print_info('No File Chosen')
                return

        # Esc / window-X on the dialog matches neither branch; without this
        # guard execution fell through with an empty path and wrote a blank
        # include file.
        if includefile == "":
            return

        filename = os.path.basename(includefile)
        self.modelpath = self.digital_home + \
            "/" + self.model_stem + "/"

        if not os.path.isdir(self.modelpath):
            os.mkdir(self.modelpath)
        with open(includefile) as fh:
            text = fh.read()
        text = text + '\n'
        with open(self.modelpath + filename, 'w') as f:
            for item in text:
                f.write(item)
            f.write("\n")
        print("Added the File:" + filename)
        self.termtitle("Added the File:" + filename)

    def addfolder(self):
        '''
            This function is used to add additional folder required
            by the verilog top module
        '''
        # self.cur_dir = os.getcwd()
        print("Adding the folder required by the top level module file")

        includefolder = QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getExistingDirectory(
                Dialogs.resolve_parent(self), "open", "home"
            )
        )

        if includefolder == "":
            reply = Dialogs.critical(
                None, "Error Message",
                "<b>Error: No Folder Chosen. Please chose a folder</b>",
                QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
            )

            if reply == QtWidgets.QMessageBox.StandardButton.Ok:
                self.addfolder()

                if includefolder == "":
                    return

                self.obj_Appconfig.print_info('Add Folder Called')

            elif reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                self.obj_Appconfig.print_info('No Folder Chosen')
                return

        # Esc / window-X matches neither branch; guard against falling through
        # with an empty path (would makedirs/copytree against a bad target).
        if includefolder == "":
            return

        self.modelpath = self.digital_home + \
            "/" + os.path.splitext(self.fname)[0] + "/"
        if not os.path.isdir(self.modelpath):
            os.makedirs(self.modelpath, exist_ok=True)

        reply = Dialogs.question(
            None, "Message",
            '''<b>If you want only the contents\
             of the folder to be added press "Yes".\
                    If you want complete folder \
                    to be added, press "No". </b>''',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        foldername = os.path.basename(os.path.normpath(includefolder))
        self.termtitle("Adding the Folder: " + foldername)
        # shutil.copytree instead of `cp` via sh -c: a user-picked folder with
        # spaces/metacharacters can neither split nor execute. Esc / window-X
        # returns neither Yes nor No -> do nothing, instead of the old code
        # falling through and re-running a stale self.cmd from a prior action.
        try:
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                shutil.copytree(includefolder, self.modelpath,
                                dirs_exist_ok=True)
                self.obj_Appconfig.print_info('Adding Contents of the Folder')
            elif reply == QtWidgets.QMessageBox.StandardButton.No:
                shutil.copytree(
                    includefolder,
                    os.path.join(self.modelpath, foldername),
                    dirs_exist_ok=True)
                self.obj_Appconfig.print_info('Adding the Folder')
            else:
                self.obj_Appconfig.print_info('Add Folder cancelled')
                return
        except OSError as err:
            self.termtext("[NgVeri] Could not add folder '" +
                          foldername + "': " + str(err))
            return
        print("Added the folder")

    def termtitle(self, textin):
        '''
            This function is used to print the titles
            in the terminal of Ngveri tab. Emitted via the ``line`` signal so
            it is safe from the build worker thread.
        '''
        # No hardcoded colour: the old #0000FF blue was near-invisible on the
        # dark theme. Weight + rule bars carry the emphasis; the text inherits
        # the palette so it reads in both themes.
        Text = "<span style=\"font-size:20pt; font-weight:1000;\">"
        Text += "<br>================================<br>"
        Text += textin
        Text += "<br>================================<br>"
        Text += "</span>"
        self.line.emit(Text)
        # Drive the NgVeri progress indicator with the plain banner text.
        self.phase.emit(textin)

    def termtext(self, textin):
        '''
            This function is used to print the text/commands
            in the terminal of Ngveri tab. Emitted via the ``line`` signal so
            it is safe from the build worker thread.
        '''
        # No hardcoded colour (was #000000, invisible on dark): inherit the
        # palette. stderr is coloured by severity in _emit_stderr.
        # Escaped for the same reason stderr is: a tool path or a stdout line
        # containing <...> was parsed as a tag and silently dropped.
        Text = "<span style=\"font-size:12pt; font-weight:500;\">"
        Text += html.escape(textin)
        Text += "</span>"
        self.line.emit(Text)
