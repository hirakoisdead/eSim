"""Corpus gate for the auto-generated testbench.

Not a pytest module (it needs a real iverilog and an external corpus of HDL);
it is the regression harness for :func:`maker.hdl.ports.generate_stub_testbench`
and the piece of eSim that decides whether "paste a module, press Simulate"
actually produces a waveform.

For every ``*.v`` under a corpus directory it does exactly what the Verify
stage does -- extract ports, generate a testbench, compile with iverilog, run
under vvp, parse the VCD -- and then asks the only question that matters:

    did the design's OUTPUTS actually move, or is the waveform a wall of X?

A stub that compiles but leaves every input undriven passes a "does it build"
test and is still useless to the user, so the verdict here is behavioural.

Usage::

    python -m maker.tests.corpus_testbench_check <dir> [--verbose] [--keep]

Run it from ``src/`` (or with ``src`` on PYTHONPATH). Exit code is non-zero
when any file regresses to a non-simulating verdict.
"""
import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from maker import CosimConfig                                   # noqa: E402
from maker.hdl import icarus                                    # noqa: E402
from maker.hdl.ports import (autodump_source, extract_ports,    # noqa: E402
                             generate_stub_testbench, has_dump, has_finish,
                             is_self_contained_testbench)
from maker.hdl.vcd import parse_vcd_for_plot                    # noqa: E402

# Verdicts, worst first -- the summary is ordered by these.
FAIL_PARSE = "no-module"
FAIL_COMPILE = "compile-fail"
FAIL_SIM = "sim-fail"
FAIL_NOVCD = "no-vcd"
FAIL_ALLX = "all-X"
OK_IDLE = "ok-static"
OK = "ok"

FAILURES = (FAIL_COMPILE, FAIL_SIM, FAIL_NOVCD, FAIL_ALLX)


def _outputs_of(ports):
    return [n for m, n, _ in ports if m in ('output', 'inout')]


def check_file(path, iverilog, vvp, keep=False):
    """Run one design end-to-end. Returns ``(verdict, detail, stats)``."""
    with open(path, 'rb') as fh:
        code = fh.read().decode('utf-8', 'replace')

    module, ports = extract_ports(code)
    if not module:
        return FAIL_PARSE, "no module declaration", {}

    # Mirror the Verify stage: a file that is already a runnable testbench is
    # simulated as-is; anything else gets a generated testbench.
    sources = [(os.path.basename(path), code)]
    if is_self_contained_testbench(code):
        ports = []
        if not has_dump(code):
            sources.append(("esim_autodump.v", autodump_source(
                guard_ns=None if has_finish(code) else 200000)))
    else:
        sources.append(("tb_design.v", generate_stub_testbench(
            module, ports, design_code=code)))

    workdir = tempfile.mkdtemp(prefix="esim_corpus_")
    try:
        run = icarus.build_and_simulate(
            iverilog, vvp, sources, workdir,
            libdir=CosimConfig.iverilog_libdir(),
            compile_timeout=60, sim_timeout=60)

        if not run.compile.ok:
            first = next((ln for ln in run.compile.output.splitlines()
                          if 'error' in ln.lower()), "")
            return FAIL_COMPILE, first.strip()[:110], {}
        if run.sim is None or not run.sim.ok:
            rc = run.sim.returncode if run.sim else "?"
            return FAIL_SIM, f"vvp exit {rc}", {}
        if not run.vcd_content:
            return FAIL_NOVCD, "no VCD written", {}

        stamps, signals, _types, raw, _ts = parse_vcd_for_plot(run.vcd_content)
        if not stamps:
            # A design with no ports and no internal state (a bare $display
            # example) has nothing to plot; that is honest, not a failure.
            if not ports:
                return OK_IDLE, "nothing to plot (no signals)", {}
            return FAIL_NOVCD, "VCD had no value changes", {}

        out_names = _outputs_of(ports)
        # An output counts as "alive" when it ever leaves X/Z. Match on the
        # bare name (the VCD may qualify duplicated names by scope).
        alive, dead = [], []
        for name in out_names:
            vals = None
            for key in (name, f"uut.{name}"):
                if key in raw:
                    vals = raw[key]
                    break
            if vals is None:
                vals = next((v for k, v in raw.items()
                             if k.split('.')[-1] == name), None)
            if vals is None:
                dead.append(name)
                continue
            (alive if any(str(v).lower() not in ('x', 'z') for v in vals)
             else dead).append(name)

        stats = {"signals": len(signals), "times": len(stamps),
                 "alive": len(alive), "outputs": len(out_names)}
        if out_names and not alive:
            return FAIL_ALLX, "every output stayed X: " + ", ".join(
                dead[:4]), stats
        if not out_names:
            return OK_IDLE, "no outputs to observe", stats
        if dead:
            return OK, "X outputs: " + ", ".join(dead[:3]), stats
        return OK, "", stats
    finally:
        if keep:
            print(f"    workdir kept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", help="directory of .v files (searched recursively)")
    ap.add_argument("--verbose", action="store_true",
                    help="print a line per file, not just the failures")
    ap.add_argument("--keep", action="store_true",
                    help="keep each run's temp dir for inspection")
    args = ap.parse_args(argv)

    iverilog = CosimConfig.iverilog_binary()
    vvp = CosimConfig.vvp_binary()
    if not iverilog or not vvp:
        print("iverilog/vvp not found -- install Icarus Verilog first.")
        return 2

    files = []
    for root, _dirs, names in os.walk(args.corpus):
        files += [os.path.join(root, n) for n in sorted(names)
                  if n.endswith(('.v', '.sv'))]
    if not files:
        print(f"no .v files under {args.corpus}")
        return 2

    tally = {}
    rows = []
    for path in files:
        verdict, detail, stats = check_file(path, iverilog, vvp, args.keep)
        tally[verdict] = tally.get(verdict, 0) + 1
        rows.append((verdict, os.path.relpath(path, args.corpus), detail, stats))
        if args.verbose or verdict in FAILURES:
            note = f"  {detail}" if detail else ""
            print(f"[{verdict:>12}] {os.path.relpath(path, args.corpus)}{note}")

    print("\n--- summary ---")
    for verdict in (OK, OK_IDLE, FAIL_PARSE, *FAILURES):
        if tally.get(verdict):
            print(f"  {verdict:>12}: {tally[verdict]}")
    bad = sum(tally.get(v, 0) for v in FAILURES)
    print(f"  {'total':>12}: {len(files)}   ({bad} failing)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
