"""Qt-free Icarus Verilog backend: compile + simulate.

Both the Verilog Simulator IDE (syntax check / simulate-and-wave) and the
d_cosim build shell out to ``iverilog``/``vvp`` in nearly the same way. This
module is the single, PyQt-free place that actually runs them, returning plain
result objects so the UI layer only deals with files, logging and widgets.

Keeping this synchronous and Qt-free is deliberate: callers that must stay
responsive run these functions on a worker thread (see hdl.jobs), and the pure
shape makes them unit-testable (integration tests skip when iverilog is absent).
"""
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .procs import kill_process_tree

# The eSim GUI process has no console, so console children (iverilog, vvp)
# would each pop up a blank console window on Windows -- and closing one
# aborts the run via CTRL_CLOSE_EVENT. 0 on POSIX.
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def vpi_load_failed(output: str) -> bool:
    """True when iverilog/vvp reported a VPI module it could not load, e.g.
    "error: Failed to open '...\\system.vpi' because: The specified module
    could not be found." (a runtime DLL of the .vpi missing from the loading
    exe's dir/PATH). Icarus treats this as NON-fatal -- it still exits 0 and
    writes an artifact -- but every $-task is broken and the same load fails
    again inside ngspice at d_cosim time, so eSim must treat it as a hard
    toolchain failure instead of reporting a bogus success."""
    return 'Failed to open' in output and '.vpi' in output


_UNKNOWN_MODULE_RE = re.compile(r'Unknown module type:\s*([\w$]+)')

#: ``file.v:12: error: message``, and the same shape with the severity token
#: absent -- iverilog's own parse errors read ``file.v:2: syntax error``, with
#: no ``error:`` at all, so requiring one would miss the single most common
#: failure. The filename stops at a path separator, so a diagnostic that did
#: come back with a full path still yields the bare source name.
_DIAG_RE = re.compile(
    r'([^\s:\\/]+\.s?v):(\d+):\s*(?:(error|warning|sorry)\s*:\s*)?(.*)',
    re.IGNORECASE)


def missing_modules(output: str) -> List[str]:
    """Module names iverilog could not resolve, in first-seen order -- e.g.
    ``["counter"]`` for ``error: Unknown module type: counter``.

    This is an *elaboration* failure, not a syntax one: every source parsed
    fine, some instantiated module simply is not among the compiled sources.
    Callers use it to tell "your code is broken" apart from "the module this
    instance needs was never loaded"."""
    seen: List[str] = []
    for m in _UNKNOWN_MODULE_RE.finditer(output or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def unknown_module_sites(output: str) -> List[Tuple[str, int, str]]:
    """``(filename, line, module)`` for every unresolved instantiation that
    iverilog located, so a caller can tell *which source* asked for the missing
    module -- a testbench left over from another design reads very differently
    from a design that instantiates a submodule nobody loaded."""
    sites = []
    for fname, line, _sev, msg in diagnostics(output):
        m = _UNKNOWN_MODULE_RE.search(msg)
        if m:
            sites.append((fname, line, m.group(1)))
    return sites


def diagnostics(output: str) -> List[Tuple[str, int, str, str]]:
    """Every located diagnostic in ``output`` as
    ``(filename, line, severity, message)``, in emission order.

    Severity is lower-cased, and defaults to ``'error'`` when the line carried
    no severity token -- iverilog only omits it on hard parse failures
    (``file.v:2: syntax error``). Lets a UI say *where* a run failed without the
    reader having to spot a ``:8:`` inside a long compiler line."""
    return [(m.group(1), int(m.group(2)),
             (m.group(3) or 'error').lower(), m.group(4).strip())
            for m in _DIAG_RE.finditer(output or "")]


def error_locations(output: str) -> List[str]:
    """De-duplicated ``file.v:line`` strings for the *errors* in ``output``, in
    emission order. Empty when the failure carried no location (e.g. a
    link-stage summary), which callers should treat as "nothing to point at".

    Intended for output already known to be a failure: an untagged located line
    counts as an error there (see :func:`diagnostics`), which is right for a
    run that failed and would over-report on one that did not."""
    seen: List[str] = []
    for fname, line, sev, _ in diagnostics(output):
        if sev == 'warning':
            continue
        loc = f"{fname}:{line}"
        if loc not in seen:
            seen.append(loc)
    return seen


@dataclass
class CompileResult:
    """Outcome of an ``iverilog`` invocation."""
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    out_path: Optional[str]          # compiled artifact, or None on failure
    cmd: List[str] = field(default_factory=list)
    written: List[str] = field(default_factory=list)   # source files written

    @property
    def output(self) -> str:
        """Combined stdout+stderr, for logging."""
        return (self.stdout or "") + (self.stderr or "")


@dataclass
class SimResult:
    """Outcome of a ``vvp`` run."""
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    vcd_path: Optional[str]          # produced VCD, or None if none written


class CancelToken:
    """Lets a long compile/sim be killed from another thread.

    Qt-free on purpose: the UI hands one of these to the backend (run on a
    worker thread) and calls :meth:`cancel` from the GUI thread when the user
    clicks Cancel. The backend binds its live subprocess; binding after a cancel
    has already been requested kills it immediately, closing the race."""

    def __init__(self):
        self._proc = None
        self._cancelled = False

    def bind(self, proc):
        self._proc = proc
        if self._cancelled:
            self._terminate()

    def cancel(self):
        self._cancelled = True
        self._terminate()

    def _terminate(self):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            # Kill the whole tree: iverilog is a driver that spawns ivlpp/ivl,
            # and those grandchildren keep the output file open after a plain
            # Popen.kill() -- the next compile then fails on a locked artifact.
            kill_process_tree(proc)

    @property
    def cancelled(self):
        return self._cancelled


def _stream(proc, timeout, on_line):
    """Drain a live process's pipes, forwarding each line to ``on_line``.

    One reader thread per pipe: reading them in sequence would deadlock as soon
    as the other pipe's OS buffer filled -- which a chatty ``$display`` loop
    does in well under a second. Returns ``(stdout, stderr)`` and raises
    ``subprocess.TimeoutExpired`` if the process outlives ``timeout``."""
    import threading
    import time

    collected = {'stdout': [], 'stderr': []}

    def pump(pipe, key):
        try:
            for line in iter(pipe.readline, ''):
                collected[key].append(line)
                if on_line is not None:
                    try:
                        on_line(key, line.rstrip('\n'))
                    except Exception:
                        pass        # a broken sink must not kill the run
        except (ValueError, OSError):
            pass                    # pipe closed under us (cancel / kill)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    threads = [threading.Thread(target=pump, args=(proc.stdout, 'stdout'),
                                daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, 'stderr'),
                                daemon=True)]
    for t in threads:
        t.start()

    deadline = None if timeout is None else time.monotonic() + timeout
    while proc.poll() is None:
        if deadline is not None and time.monotonic() > deadline:
            kill_process_tree(proc)
            for t in threads:
                t.join(1.0)
            raise subprocess.TimeoutExpired(proc.args, timeout)
        time.sleep(0.05)
    for t in threads:
        t.join(2.0)
    return ''.join(collected['stdout']), ''.join(collected['stderr'])


def _run_cmd(cmd, cwd, timeout, cancel, env=None, on_line=None):
    """Run ``cmd`` and return (returncode, stdout, stderr).

    Uses subprocess.run when nothing needs a live handle (simplest, fully
    buffered); otherwise a Popen the cancel token can kill and, with
    ``on_line``, whose output is forwarded as it arrives. Raises
    subprocess.TimeoutExpired on timeout in every mode."""
    if cancel is None and on_line is None:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True,
            timeout=timeout, creationflags=NO_WINDOW)
        return proc.returncode, proc.stdout, proc.stderr

    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=NO_WINDOW)
    if cancel is not None:
        cancel.bind(proc)
    if on_line is not None:
        out, err = _stream(proc, timeout, on_line)
        return proc.returncode, out, err
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        proc.communicate()
        raise
    return proc.returncode, out, err


def run_iverilog(
    iverilog_bin: str,
    src_paths: Sequence[str],
    out_path: str,
    *,
    cwd: Optional[str] = None,
    std: str = "-g2012",
    warnings: bool = False,
    extra_flags: Sequence[str] = (),
    timeout: Optional[float] = None,
    cancel: Optional[CancelToken] = None,
) -> CompileResult:
    """Invoke iverilog on already-on-disk sources, producing ``out_path``.

    The lowest-level entry point, shared by :func:`compile_design` (IDE) and the
    d_cosim build. ``ok`` requires both a zero exit AND the artifact actually
    existing, so "compiler said 0 but wrote nothing" is reported as failure."""
    cmd = [iverilog_bin, std]
    if warnings:
        cmd.append("-Wall")
    cmd += list(extra_flags)
    cmd += ["-o", out_path] + list(src_paths)

    rc, out, err = _run_cmd(cmd, cwd, timeout, cancel)
    ok = (rc == 0 and os.path.isfile(out_path)
          and not vpi_load_failed((out or "") + (err or "")))
    return CompileResult(
        ok=ok, returncode=rc, stdout=out, stderr=err,
        out_path=out_path if ok else None, cmd=cmd, written=list(src_paths))


def compile_design(
    iverilog_bin: str,
    sources: Sequence[Tuple[str, str]],
    workdir: str,
    *,
    std: str = "-g2012",
    warnings: bool = False,
    extra_flags: Sequence[str] = (),
    out_name: str = "out.bin",
    timeout: Optional[float] = None,
    cancel: Optional[CancelToken] = None,
) -> CompileResult:
    """Write ``sources`` into ``workdir`` and compile them with iverilog.

    ``sources`` is an ordered sequence of ``(filename, content)``; each is
    written under ``workdir`` with that exact name so iverilog's diagnostics
    reference the caller's filenames (the IDE relies on this to map an error
    back to the right editor tab). Returns a :class:`CompileResult`; never
    raises for an ordinary compile failure (only a timeout/OS error surfaces).

    iverilog is handed the *bare* names and run with ``cwd=workdir``, because it
    echoes back whatever it was given: absolute paths turned every diagnostic
    into ``C:\\Users\\...\\AppData\\Local\\Temp\\tmp8f3k\\tb_design.v:8: error:``,
    which buries the one thing the reader needs -- the line number -- behind a
    temp path they can neither read nor act on. ``written`` still carries the
    absolute paths for callers that need the files on disk.
    """
    written: List[str] = []
    for fname, content in sources:
        path = os.path.join(workdir, fname)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        written.append(path)

    res = run_iverilog(
        iverilog_bin, [fname for fname, _ in sources],
        os.path.join(workdir, out_name),
        cwd=workdir, std=std, warnings=warnings, extra_flags=extra_flags,
        timeout=timeout, cancel=cancel)
    res.written = written
    return res


def find_dump(workdir: str, preferred: str = "sim_out.vcd") -> Optional[str]:
    """Path to the waveform a run produced, whatever the testbench called it.

    ``preferred`` is checked first; otherwise the newest ``*.vcd`` in
    ``workdir`` wins. Insisting on one hard-coded name is why a perfectly good
    run used to report "No VCD output" for every testbench that dumped to
    ``dump.vcd`` / ``wave.vcd`` / anything else -- which is most testbenches
    written by anyone other than eSim."""
    direct = os.path.join(workdir, preferred)
    if os.path.isfile(direct):
        return direct
    try:
        found = [os.path.join(workdir, n) for n in os.listdir(workdir)
                 if n.lower().endswith('.vcd')]
    except OSError:
        return None
    found = [p for p in found if os.path.isfile(p)]
    if not found:
        return None
    return max(found, key=os.path.getmtime)


#: Language standards tried in order. ``-g2012`` (SystemVerilog) is the most
#: permissive for modern code, but it also *reserves* words that older Verilog
#: used freely as identifiers -- ``bit``, ``logic``, ``do``, ``final``. A
#: perfectly good 2001-era file then dies on "syntax error" at the line that
#: declares ``wire [15:0] bit``, which reads as if the user's code were broken.
#: Falling back to the older standards fixes those without the user having to
#: know what a language standard is.
STD_FALLBACKS = ("-g2012", "-g2005", "-g2001")


def compile_with_fallback(
    iverilog_bin: str,
    sources: Sequence[Tuple[str, str]],
    workdir: str,
    *,
    stds: Sequence[str] = STD_FALLBACKS,
    **kwargs,
) -> Tuple[CompileResult, str]:
    """Compile ``sources``, retrying under older language standards.

    Returns ``(result, std_used)``. On success ``result`` is the run that
    worked; when every standard fails, the FIRST failure is returned -- its
    diagnostics are against the standard eSim actually targets, so they are the
    ones worth showing."""
    first = None
    for std in stds:
        res = compile_design(iverilog_bin, sources, workdir, std=std, **kwargs)
        if res.ok:
            return res, std
        if first is None:
            first = res
        # Only a parse-level rejection can be a standard mismatch; a missing
        # module or a bad port map fails identically everywhere, so stop.
        if 'syntax error' not in res.output.lower():
            break
    return first, stds[0]


def simulate(
    vvp_bin: str,
    out_path: str,
    workdir: str,
    *,
    env: Optional[dict] = None,
    vcd_name: str = "sim_out.vcd",
    timeout: Optional[float] = None,
    cancel: Optional[CancelToken] = None,
    on_line=None,
) -> SimResult:
    """Run a compiled design under ``vvp`` in ``workdir``.

    Returns a :class:`SimResult`; ``vcd_path`` is whatever waveform the run
    left behind (``vcd_name`` first, else any ``*.vcd``), so the caller can
    tell "no $dumpfile at all" apart from a crash. ``env`` lets the caller fix
    up the loader path (e.g. prepend the vvp dir to PATH on Windows for its
    DLLs). ``on_line`` receives output as it is produced, so a long run can
    show progress instead of looking hung."""
    rc, out, err = _run_cmd(
        [vvp_bin, out_path], workdir, timeout, cancel, env=env,
        on_line=on_line)
    ok = rc == 0 and not vpi_load_failed((out or "") + (err or ""))
    return SimResult(
        ok=ok, returncode=rc, stdout=out, stderr=err,
        vcd_path=find_dump(workdir, vcd_name))


def vvp_env(vvp_bin: str, base_env: Optional[dict] = None,
            libdir: Optional[str] = None) -> dict:
    """Build an environment for running vvp so its shared library (libvvp)
    resolves regardless of how Icarus was installed.

    Prepends ``libdir`` (the iverilog ``lib/`` holding libvvp) to the OS dynamic
    loader path -- PATH on Windows, LD_LIBRARY_PATH elsewhere -- which is what a
    prefix build (e.g. ~/iverilog) needs but is not on the default loader path.
    On Windows the directory holding vvp itself is also added for its MinGW
    DLLs. Pass ``libdir`` from CosimConfig.iverilog_libdir()."""
    env = dict(base_env if base_env is not None else os.environ)
    loader = 'PATH' if os.name == 'nt' else 'LD_LIBRARY_PATH'
    extra = []
    if libdir and os.path.isdir(libdir):
        extra.append(libdir)
    if os.name == 'nt' and vvp_bin:
        extra.append(os.path.dirname(os.path.abspath(vvp_bin)))
    if extra:
        existing = env.get(loader, "")
        env[loader] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


@dataclass
class RunResult:
    """Combined outcome of compile + simulate, returned by
    :func:`build_and_simulate`. ``vcd_content`` is read on the worker thread so
    the GUI thread never has to touch the (about-to-be-deleted) temp dir."""
    compile: CompileResult
    sim: Optional[SimResult] = None
    vcd_content: Optional[str] = None
    #: language standard the compile actually used (see STD_FALLBACKS)
    std: str = STD_FALLBACKS[0]
    #: name of the waveform file found, when it was not the expected one
    vcd_name: Optional[str] = None

    @property
    def ok(self):
        return self.compile.ok and self.sim is not None and self.sim.ok


def build_and_simulate(
    iverilog_bin: str,
    vvp_bin: str,
    sources: Sequence[Tuple[str, str]],
    workdir: str,
    *,
    libdir: Optional[str] = None,
    std: Optional[str] = None,
    out_name: str = "sim.out",
    vcd_name: str = "sim_out.vcd",
    compile_timeout: Optional[float] = None,
    sim_timeout: Optional[float] = None,
    cancel: Optional[CancelToken] = None,
    on_line=None,
    on_phase=None,
) -> RunResult:
    """Compile ``sources`` then run the result under vvp, reading back any VCD.

    The single blocking unit of work the IDE runs on a worker thread: it does no
    Qt and no logging, so the GUI thread can drive it and render the result.
    Stops early (sim=None) if compilation fails. With ``std`` unset the
    language standard falls back through :data:`STD_FALLBACKS`; ``on_line``
    receives simulator output live and ``on_phase`` is told when the run moves
    from compiling to simulating."""
    stds = (std,) if std else STD_FALLBACKS
    if on_phase:
        on_phase('compile')
    cres, used = compile_with_fallback(
        iverilog_bin, sources, workdir, stds=stds, out_name=out_name,
        timeout=compile_timeout, cancel=cancel)
    if not cres.ok:
        return RunResult(compile=cres, std=used)

    if on_phase:
        on_phase('simulate')
    sres = simulate(
        vvp_bin, cres.out_path, workdir,
        env=vvp_env(vvp_bin, libdir=libdir), vcd_name=vcd_name,
        timeout=sim_timeout, cancel=cancel, on_line=on_line)
    vcd_content = None
    found_name = None
    if sres.vcd_path:
        found_name = os.path.basename(sres.vcd_path)
        with open(sres.vcd_path, "r", encoding="utf-8",
                  errors="replace") as fh:
            vcd_content = fh.read()
    return RunResult(compile=cres, sim=sres, vcd_content=vcd_content,
                     std=used, vcd_name=found_name)
