"""Windows launcher helpers.

Set up the tool environment and run the per-user bootstrap IN-PROCESS, so eSim
can start from a single interpreter (pythonw Application.py) instead of
esim.bat spawning python.exe for windows_bootstrap and then a second pythonw
for the GUI. Everything here is a no-op off Windows.
"""
import glob
import os
import sys

_ENV_SENTINEL = "ESIM_ENV_READY"


def esim_root():
    """Install root = the dir holding VERSION + src/ + tools/. This file lives
    at <root>/src/frontEnd/launcher_windows.py."""
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _prepend_path(entry):
    if entry and os.path.isdir(entry):
        cur = os.environ.get("PATH", "")
        os.environ["PATH"] = entry + os.pathsep + cur if cur else entry


def setup_environment(root=None):
    """Replicate esim.bat's PATH / SPICE_LIB_DIR setup in-process.

    Guarded by the ESIM_ENV_READY sentinel so it runs exactly once: esim.bat
    sets the sentinel after doing the setup itself (so this is skipped), and a
    direct ``pythonw Application.py`` launch does it here. No-op off Windows.
    """
    if os.name != "nt":
        return
    if os.environ.get(_ENV_SENTINEL):
        return
    root = root or esim_root()
    tools = os.path.join(root, "tools")
    # Bundled ngspice first; the custom nghdl ngspice (d_cosim/ivlng) is
    # prepended after so it wins over the fallback copy.
    _prepend_path(os.path.join(tools, "ngspice", "bin"))
    nghdl_bin = os.path.join(tools, "nghdl", "install_dir", "bin")
    if os.path.isfile(os.path.join(nghdl_bin, "ngspice.exe")):
        _prepend_path(nghdl_bin)
        # lib\ngspice also goes on PATH: it holds ivlng.dll, which d_cosim's
        # cosim_dlopen resolves via a plain LoadLibrary("ivlng") (PATH
        # search) before falling back to its compile-time NGSPICELIBDIR --
        # a build-machine path that does not exist on user installs.
        _prepend_path(os.path.join(
            tools, "nghdl", "install_dir", "lib", "ngspice"))
        # Where this ngspice finds spinit (and the .cm code models).
        os.environ["SPICE_LIB_DIR"] = os.path.join(
            tools, "nghdl", "install_dir", "share", "ngspice")
    # KiCad: a system install is the fallback; the bundled pruned KiCad is
    # prepended last so eSim runs the KiCad it shipped with and was tested on.
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    for kdir in sorted(glob.glob(os.path.join(program_files, "KiCad", "*"))):
        if os.path.isfile(os.path.join(kdir, "bin", "eeschema.exe")):
            _prepend_path(os.path.join(kdir, "bin"))
    bundled_kicad = os.path.join(tools, "kicad", "bin")
    if os.path.isfile(os.path.join(bundled_kicad, "eeschema.exe")):
        _prepend_path(bundled_kicad)
    os.environ[_ENV_SENTINEL] = "1"


def run_bootstrap(root=None):
    """Run windows_bootstrap in-process (idempotent, pure stdlib) instead of
    spawning a second interpreter. Best-effort: a failure must never stop the
    GUI from starting. No-op off Windows."""
    if os.name != "nt":
        return
    root = root or esim_root()
    try:
        wdir = os.path.join(root, "windows")
        if wdir not in sys.path:
            sys.path.insert(0, wdir)
        import windows_bootstrap
        windows_bootstrap.main(["--esim-root", root])
    except Exception as e:
        print("eSim bootstrap skipped:", e)
