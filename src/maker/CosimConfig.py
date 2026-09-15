# ==============================================================================
#             FILE: CosimConfig.py
#
#      DESCRIPTION: Locate the d_cosim (Icarus Verilog) co-simulation toolchain
#                   without any hardcoded paths, on Linux and Windows, wherever
#                   eSim happens to be installed.
#
#                   d_cosim needs two things at simulation time:
#                     1. an ngspice >= 44 built with the `ivlng` adapter (eSim's
#                        bundled nghdl-simulator already ships ivlng.so/.vpi);
#                     2. iverilog built with libvvp (`--enable-libvvp`), which
#                        ngspice's ivlng adapter dlopens at runtime, plus the
#                        `iverilog` compiler used to build the per-model vvp.
#
#                   Every path is resolved at call time in this order:
#                       explicit env override
#                     -> ~/.nghdl/config.ini  ([COSIM] / [NGHDL])
#                     -> PATH / standard install location relative to the binary
#                     -> None (caller shows a clear "not installed" message).
#
#                   Nothing here is eSim-install-location specific: the installer
#                   records the real paths in config.ini, and developers can
#                   override with ESIM_NGSPICE / ESIM_IVERILOG / ESIM_IVERILOG_LIB.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

import os
import shutil
from configparser import ConfigParser, Error as ConfigError

_WIN = os.name == 'nt'
_EXE = '.exe' if _WIN else ''

# Cached capability probe (filesystem checks only; safe to memoize per process).
_dcosim_capable = None


def _config_path():
    """Path to eSim's nghdl config.ini under the per-user ``~/.nghdl`` dir on
    every platform (see configuration.paths)."""
    from configuration import paths
    return paths.nghdl_config_path()


def nghdl_config_path():
    """Public path used by legacy callers that still need a full parser."""
    return _config_path()


def _cfg_get(section, key):
    """Read one config.ini value, or None if absent/unreadable."""
    parser = ConfigParser()
    try:
        parser.read(_config_path())
        value = parser.get(section, key)
        return value or None
    except (ConfigError, OSError):
        return None


def nghdl_cfg(section, key, default=""):
    """Return one NGHDL config value, safely falling back when unavailable."""
    value = _cfg_get(section, key)
    return value if value is not None else default


def digital_model_root():
    """Configured model-library root, or the safe per-user default."""
    return nghdl_cfg(
        'NGHDL',
        'DIGITAL_MODEL',
        os.path.join(os.path.expanduser('~'), '.nghdl',
                     'DigitalModelLibrary'),
    )


def _prefix_of(binary):
    """<prefix> for a <prefix>/bin/<tool> path, following symlinks first so a
    /usr/bin/ngspice symlink resolves to the real install tree."""
    real = os.path.realpath(binary)
    return os.path.dirname(os.path.dirname(real))


# --------------------------------------------------------------------------- #
#  ngspice (the eSim / nghdl-simulator build that carries d_cosim + ivlng)
# --------------------------------------------------------------------------- #
def ngspice_binary():
    """Resolve eSim's ngspice executable. Used for ALL simulations (the bundled
    nghdl-simulator build is the one that has d_cosim + ivlng)."""
    env = os.environ.get('ESIM_NGSPICE')
    if env and os.path.isfile(env):
        return env
    nghdl_home = _cfg_get('NGHDL', 'NGHDL_HOME')
    if nghdl_home:
        cand = os.path.join(nghdl_home, 'install_dir', 'bin', 'ngspice' + _EXE)
        if os.path.isfile(cand):
            return cand
    return shutil.which('ngspice') or 'ngspice'


def ngspice_gui_binary():
    """Windows only: the --with-wingui ngspice, or None.

    The ngspice eSim runs for simulations is a console build (X_DISPLAY_MISSING,
    no HAS_WINGUI) because eSim drives it through QProcess and parses its stdout,
    which a wingui binary swallows into its own window. That build has no
    graphics device at all, so its `plot` command only ever answers "Can't open
    viewport for graphics". The interactive plot session therefore runs a second,
    wingui-only binary shipped beside it. On Windows ngspice resolves its lib
    dir relative to the executable (src/misc/ivars.c: dirname(argv0) +
    ../share/ngspice), so the twin sitting in the same bin finds spinit --
    whose absolute codemodel lines then load the *.cm -- exactly like
    ngspice.exe does.
    """
    if not _WIN:
        return None
    env = os.environ.get('ESIM_NGSPICE_GUI')
    if env and os.path.isfile(env):
        return env
    cand = os.path.join(_prefix_of(ngspice_binary()), 'bin', 'ngspice_gui.exe')
    return cand if os.path.isfile(cand) else None


def ngspice_codemodel_dir():
    """Directory holding ngspice's *.cm code models + the ivlng adapter
    (<prefix>/lib/ngspice), or None."""
    cand = os.path.join(_prefix_of(ngspice_binary()), 'lib', 'ngspice')
    return cand if os.path.isdir(cand) else None


def cosim_model_id(model_name):
    """The ONE canonical identity of a d_cosim model: the stripped, lowercased
    name. Symbol, param XML, build dir, vvp filename and netlist all key off
    this, so a case-sensitive filesystem cannot split one model into two.

    Returns "" for a blank name -- callers MUST treat that as "no model" and
    never join it onto a base path (os.path.join(base, "") collapses to the
    base directory, which is how a teardown wipes every model at once)."""
    return str(model_name or "").strip().lower()


def cosim_build_root():
    """Root of the d_cosim build tree: <DIGITAL_MODEL>/NgVeriCosim.

    Deliberately a SIBLING of the legacy Ngveri/ tree, not a subdirectory of
    it. The two backends used to build into one directory per model name, so
    tearing down a d_cosim model rmtree'd the Verilator backend's sources for
    the model of that name (and vice versa) -- a data-loss bug that no amount
    of guarding fully closes, because on Windows the filesystem compares names
    case-insensitively while every guard compares them exactly. Separate roots
    make the collision structurally impossible instead of merely unlikely.

    The legacy tree's layout is untouched: eSim 2.5 NgVeri models stay exactly
    where they were built."""
    return os.path.join(digital_model_root(), 'NgVeriCosim')


def cosim_build_dir(model_name):
    """Per-model d_cosim build directory (<cosim root>/<id>), or None for a
    blank name. This is the directory the teardown may delete -- it holds
    nothing but d_cosim artifacts."""
    model_id = cosim_model_id(model_name)
    return os.path.join(cosim_build_root(), model_id) if model_id else None


def cosim_vvp_target(model_name):
    """Where a d_cosim build MUST write its vvp: <cosim root>/<id>/<id>.

    Distinct from cosim_vvp_path, which also accepts a pre-split model still
    sitting in the old shared location. Builders and the teardown use this
    one; readers use cosim_vvp_path."""
    build_dir = cosim_build_dir(model_name)
    if not build_dir:
        return None
    return os.path.join(build_dir, cosim_model_id(model_name))


def legacy_cosim_vvp_path(model_name):
    """The pre-split vvp location, <DIGITAL_MODEL>/Ngveri/<id>/<id>, shared
    with the legacy NgVeri build tree.

    Kept only so models built before the trees were separated still simulate
    and can still be torn down. NOTHING may delete this file's *directory* --
    it may be a legacy NgVeri build dir. Returns None for a blank name."""
    model_id = cosim_model_id(model_name)
    if not model_id:
        return None
    return os.path.join(digital_model_root(), 'Ngveri', model_id, model_id)


def cosim_vvp_path(model_name):
    """A model's compiled Icarus vvp for READERS (the netlister, the simulation
    staging, cosim_merge): the canonical location if it holds a build, else the
    pre-split shared location if that one does, else the canonical path so the
    "not built" error names where the file should be.

    One helper so the build step and every consumer agree on one path without
    storing it anywhere. Returns None only for a blank name."""
    target = cosim_vvp_target(model_name)
    if not target:
        return None
    if os.path.isfile(target):
        return target
    legacy = legacy_cosim_vvp_path(model_name)
    if legacy and os.path.isfile(legacy):
        return legacy
    return target


# --------------------------------------------------------------------------- #
#  iverilog (with libvvp)
# --------------------------------------------------------------------------- #
def _repo_root():
    """eSim repo root (this file lives at <root>/src/maker/CosimConfig.py)."""
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bundled_tool(name):
    """Path to a bundled Icarus tool under library/bin, or None."""
    cand = os.path.join(_repo_root(), 'library', 'bin', 'iverilog', 'bin',
                        name + _EXE)
    return cand if os.path.isfile(cand) else None


# Standard Windows install locations to probe after PATH (iverilog installer
# defaults). Empty/irrelevant on POSIX.
_WIN_TOOL_DIRS = (
    r"C:\Program Files\iverilog\bin",
    r"C:\Program Files (x86)\iverilog\bin",
    r"C:\iverilog\bin",
)


def _win_fallback(name):
    if not _WIN:
        return None
    for d in _WIN_TOOL_DIRS:
        cand = os.path.join(d, name + _EXE)
        if os.path.isfile(cand):
            return cand
    return None


def _resolve_tool(name, env_var, cfg_key):
    """Resolve an Icarus tool: explicit env override -> config.ini [COSIM] ->
    bundled (library/bin) -> PATH -> platform-standard install dir -> None.
    Single, shared resolution order for every caller (verifier + d_cosim)."""
    env = os.environ.get(env_var)
    if env and os.path.isfile(env):
        return env
    cfg = _cfg_get('COSIM', cfg_key)
    if cfg and os.path.isfile(cfg):
        return cfg
    bundled = _bundled_tool(name)
    if bundled:
        return bundled
    return shutil.which(name) or _win_fallback(name)


def iverilog_binary():
    """Resolve the iverilog compiler, or None if not installed."""
    return _resolve_tool('iverilog', 'ESIM_IVERILOG', 'IVERILOG')


def vvp_binary():
    """Resolve the vvp runtime, or None. After explicit env/config overrides,
    prefer the vvp sitting next to the resolved iverilog (matches prefix
    builds) before the generic bundled/PATH search."""
    env = os.environ.get('ESIM_VVP')
    if env and os.path.isfile(env):
        return env
    cfg = _cfg_get('COSIM', 'VVP')
    if cfg and os.path.isfile(cfg):
        return cfg
    iv = iverilog_binary()
    if iv:
        cand = os.path.join(os.path.dirname(iv), 'vvp' + _EXE)
        if os.path.isfile(cand):
            return cand
    bundled = _bundled_tool('vvp')
    if bundled:
        return bundled
    return shutil.which('vvp') or _win_fallback('vvp')


def set_manual_paths(iverilog_path=None, vvp_path=None):
    """Persist manually-located tool paths into ~/.nghdl/config.ini [COSIM] so
    BOTH the verifier and the d_cosim build share them (replacing the verifier's
    private QSettings). Also records IVERILOG_LIB from the iverilog prefix so
    has_iverilog() can find libvvp. Best-effort; returns True on success."""
    parser = ConfigParser()
    cfg = _config_path()
    try:
        parser.read(cfg)
        if not parser.has_section('COSIM'):
            parser.add_section('COSIM')
        if iverilog_path:
            parser.set('COSIM', 'IVERILOG', iverilog_path)
            libdir = os.path.join(_prefix_of(iverilog_path), 'lib')
            if os.path.isdir(libdir):
                parser.set('COSIM', 'IVERILOG_LIB', libdir)
        if vvp_path:
            parser.set('COSIM', 'VVP', vvp_path)
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, 'w') as fh:
            parser.write(fh)
        return True
    except (OSError, ConfigError):
        return False


def iverilog_libdir():
    """Resolve the dir containing the libvvp shared library (ngspice's ivlng
    dlopens it), or None. Falls back to <iverilog_prefix>/lib derived from the
    compiler path; on Windows, mingw-built DLLs land in <prefix>/bin instead,
    so prefer whichever of the two actually holds libvvp."""
    env = os.environ.get('ESIM_IVERILOG_LIB')
    if env and os.path.isdir(env):
        return env
    cfg = _cfg_get('COSIM', 'IVERILOG_LIB')
    if cfg and os.path.isdir(cfg):
        return cfg
    binary = iverilog_binary()
    if binary:
        prefix = _prefix_of(binary)
        candidates = [os.path.join(prefix, 'lib')]
        if _WIN:
            candidates.insert(0, os.path.join(prefix, 'bin'))
        for cand in candidates:
            if _has_libvvp(cand):
                return cand
        # No libvvp anywhere: keep the POSIX-conventional lib dir when it
        # exists so callers can still report the probed location.
        if os.path.isdir(candidates[-1]):
            return candidates[-1]
    return None


def _has_libvvp(libdir):
    """True if a libvvp shared object is present in libdir (any OS naming)."""
    if not libdir or not os.path.isdir(libdir):
        return False
    try:
        return any(name.startswith('libvvp') or name == 'vvp.dll'
                   for name in os.listdir(libdir))
    except OSError:
        return False


# --------------------------------------------------------------------------- #
#  Capability gates (used by the UI / runtime to fail clearly, never crash)
# --------------------------------------------------------------------------- #
def has_iverilog():
    """True if iverilog AND its libvvp are available (needed to BUILD a model
    and for ivlng to run it)."""
    return bool(iverilog_binary()) and _has_libvvp(iverilog_libdir())


def has_dcosim(force=False):
    """True if a full d_cosim run is possible here: ngspice carries the ivlng
    adapter AND iverilog/libvvp are present. Cached after first call."""
    global _dcosim_capable
    if _dcosim_capable is None or force:
        cmdir = ngspice_codemodel_dir()
        ngspice_ok = bool(cmdir) and any(
            name.startswith('ivlng') for name in os.listdir(cmdir))
        _dcosim_capable = ngspice_ok and has_iverilog()
    return _dcosim_capable


def loader_path_var():
    """Name of the dynamic-loader search-path env var for this OS (so ngspice's
    ivlng adapter can find libvvp): PATH on Windows, LD_LIBRARY_PATH elsewhere."""
    return 'PATH' if _WIN else 'LD_LIBRARY_PATH'


def missing_reason():
    """Human-readable reason d_cosim is unavailable, for UI messages. Empty
    string when everything is present."""
    if not has_iverilog():
        if not iverilog_binary():
            return ("iverilog not found. d_cosim needs Icarus Verilog built "
                    "with libvvp (--enable-libvvp).")
        return ("libvvp not found next to iverilog. Rebuild Icarus Verilog "
                "with --enable-libvvp.")
    cmdir = ngspice_codemodel_dir()
    if not (cmdir and any(n.startswith('ivlng') for n in os.listdir(cmdir))):
        return ("This ngspice build has no ivlng adapter. d_cosim needs the "
                "eSim/nghdl-simulator ngspice (>= 44, --enable-xspice).")
    return ""
