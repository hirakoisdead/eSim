"""Importing the Verilog verifier must not pull matplotlib.

VerilogVerifier used to subclass plotWindow at module scope, so
`import maker.VerilogVerifier` dragged in matplotlib (+numpy) -- the first
Model-Creation / Makerchip open then froze for that cold import even though
plots only appear in the Verify stage. The subclass is now built lazily by
make_vcd_plot_window().

This must run in a CLEAN interpreter (pytest's shared process may already have
matplotlib loaded), so it spawns a subprocess.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))


def test_importing_verifier_does_not_import_matplotlib():
    code = (
        "import sys; import maker.VerilogVerifier as v; "
        "assert hasattr(v, 'make_vcd_plot_window'); "
        "print('MATPLOTLIB' if 'matplotlib' in sys.modules else 'CLEAN')"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=SRC,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("CLEAN"), out.stdout + out.stderr
