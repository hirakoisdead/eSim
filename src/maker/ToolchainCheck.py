# ==============================================================================
#             FILE: ToolchainCheck.py
#
#      DESCRIPTION: The simulation-toolchain "doctor". One module that probes
#                   every external tool the eSim simulation flows depend on --
#                   ngspice (with its code-model dir, the ivlng d_cosim
#                   adapter and the nghdl ghdl.cm), Icarus Verilog (iverilog +
#                   vvp + libvvp), Verilator, make, gcc, GHDL (including the
#                   mcode-backend trap), the nghdl home tree and, on Windows,
#                   the MSYS2 toolchain -- and reports found/missing with the
#                   EXACT path that was probed and a one-line fix hint.
#
#                   Three surfaces share this module:
#                     1. CLI     : `python Application.py --doctor`
#                                  (or `esim --doctor`) prints report().
#                     2. GUI     : Help menu -> "Check simulation toolchain",
#                                  see show_dialog().
#                     3. Runtime : every flow calls require(flow, ...) BEFORE
#                                  shelling out, so a missing tool produces an
#                                  actionable message instead of a mid-build
#                                  make/gcc explosion or a silent no-op.
#
#                   The probing core is Qt-free on purpose (the CLI must work
#                   headless); the dialog imports Qt lazily. Everything reads
#                   os.name and the filesystem at CALL time so tests can fake
#                   Windows and fake install trees with monkeypatching.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# ==============================================================================

import os
import shutil
import subprocess
from dataclasses import dataclass, field

try:
    from . import CosimConfig            # package import (app runtime)
except ImportError:                      # flat import (CLI: python -m, tests)
    from maker import CosimConfig

# Flow identifiers. Every check declares which flows need it, so a flow can be
# gated on exactly its own dependencies (a missing GHDL must not block a plain
# ngspice run).
SIMULATION = 'simulation'   # plain ngspice run (KicadToNgspice -> NgspiceWidget)
VERIFIER = 'verifier'       # Verilog Verifier (iverilog compile + vvp run)
DCOSIM = 'dcosim'           # NgVeri d_cosim (Icarus) build + mixed-signal run
NGVERI = 'ngveri'           # NgVeri legacy Verilator code-model build
NGHDL = 'nghdl'             # NGHDL / GHDL VHDL co-simulation
ALL_FLOWS = (SIMULATION, VERIFIER, DCOSIM, NGVERI, NGHDL)

FLOW_LABELS = {
    SIMULATION: 'ngspice simulation',
    VERIFIER: 'Verilog Verifier',
    DCOSIM: 'NgVeri d_cosim (Icarus) co-simulation',
    NGVERI: 'NgVeri Verilator code-model build',
    NGHDL: 'NGHDL / GHDL VHDL co-simulation',
}


@dataclass
class Check:
    key: str            # stable machine id, e.g. 'ngspice'
    label: str          # human name shown in the report
    ok: bool
    path: str           # what was probed / where it was found
    detail: str = ''    # version string or failure specifics
    hint: str = ''      # one-line fix, only meaningful when not ok
    flows: tuple = field(default_factory=tuple)


def _win():
    return os.name == 'nt'


def _exe(name):
    return name + ('.exe' if _win() else '')


def _run_version(cmd, timeout=10, match=None, env=None):
    """Run `cmd` (list) and return the first non-empty output line (preferring
    one containing `match`, e.g. 'ngspice' -- version banners often start with
    decoration), or '' on any failure. Never raises; never opens a console
    window on Windows."""
    kwargs = {}
    if _win():
        # CREATE_NO_WINDOW: the doctor must never flash consoles at the user.
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if env is not None:
        kwargs['env'] = env
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, text=True, errors='replace', **kwargs)
        lines = [ln.strip() for ln in (res.stdout or '').splitlines()
                 if ln.strip()]
        if match:
            for line in lines:
                if match.lower() in line.lower():
                    return line
        return lines[0] if lines else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _loader_env(libdir):
    """Environment with `libdir` prepended to the dynamic-loader path, the way
    the app runs vvp/ngspice at simulation time (libvvp is not on the system
    loader path in prefix installs)."""
    if not libdir:
        return None
    env = dict(os.environ)
    var = CosimConfig.loader_path_var()
    env[var] = libdir + (os.pathsep + env[var] if env.get(var) else '')
    return env


def _msys_home():
    """MSYS_HOME from ~/.nghdl/config.ini [COMPILER], or ''. Windows-only
    concept, but read unconditionally so tests can exercise it anywhere."""
    return CosimConfig.nghdl_cfg('COMPILER', 'MSYS_HOME', '')


def _mingw_tool(name):
    """<MSYS_HOME>/mingw64/bin/<name>.exe if it exists, else None."""
    home = _msys_home()
    if not home:
        return None
    cand = os.path.join(home, 'mingw64', 'bin', _exe(name))
    return cand if os.path.isfile(cand) else None


def _find_tool(name, mingw_first=False):
    """Resolve a build tool: on Windows prefer the bundled MSYS2 mingw64 tree
    (that is the toolchain the flows actually invoke), then PATH; on POSIX
    just PATH. Returns (path_or_None, probed_description)."""
    probes = []
    if _win() or mingw_first:
        cand = _mingw_tool(name)
        home = _msys_home()
        probes.append(os.path.join(home or '<MSYS_HOME unset>',
                                   'mingw64', 'bin', _exe(name)))
        if cand:
            return cand, probes[-1]
    found = shutil.which(name)
    probes.append('PATH')
    return found, ' -> '.join(probes)


# --------------------------------------------------------------------------- #
#  Individual checks. Each returns one Check (or a list).
# --------------------------------------------------------------------------- #
def _check_ngspice():
    binary = CosimConfig.ngspice_binary()
    exists = bool(binary) and os.path.isfile(binary)
    detail = ''
    if exists:
        detail = _run_version([binary, '--version'], match='ngspice')
    return Check(
        key='ngspice', label='ngspice (eSim/nghdl-simulator build)',
        ok=exists, path=binary or '<none>',
        detail=detail or ('' if not exists else 'present ('
                          '--version did not answer; GUI-only build?)'),
        hint=('Install the eSim simulator: on Ubuntu re-run '
              'Ubuntu/install-eSim.sh (builds nghdl-simulator); on Windows '
              'reinstall eSim with the "Full" component set.'),
        flows=(SIMULATION, DCOSIM, NGVERI, NGHDL))


def _check_codemodels():
    cmdir = CosimConfig.ngspice_codemodel_dir()
    checks = []
    ok = bool(cmdir)
    checks.append(Check(
        key='codemodel_dir', label='ngspice code-model dir (lib/ngspice)',
        ok=ok, path=cmdir or '<prefix>/lib/ngspice not found',
        detail=('' if not ok else
                ', '.join(sorted(n for n in os.listdir(cmdir)
                                 if n.endswith(('.cm',)))) or 'empty'),
        hint=('The resolved ngspice has no lib/ngspice code-model directory. '
              'XSPICE models (adc/dac bridges, d_cosim, ghdl) will not load. '
              'Reinstall the eSim simulator build.'),
        flows=(SIMULATION, DCOSIM, NGVERI, NGHDL)))

    names = os.listdir(cmdir) if ok else []
    ivlng = any(n.startswith('ivlng') for n in names)
    checks.append(Check(
        key='ivlng', label='ivlng adapter (d_cosim Verilog bridge)',
        ok=ivlng,
        path=os.path.join(cmdir or '<codemodel dir>', 'ivlng*'),
        detail='' if not ivlng else 'found',
        hint=('This ngspice build has no ivlng adapter. d_cosim needs the '
              'eSim/nghdl-simulator ngspice (>= 44, built with '
              '--enable-xspice). Reinstall the eSim simulator.'),
        flows=(DCOSIM,)))

    ghdl_cm = 'ghdl.cm' in names
    checks.append(Check(
        key='ghdl_cm', label='ghdl.cm code model (NGHDL bridge)',
        ok=ghdl_cm,
        path=os.path.join(cmdir or '<codemodel dir>', 'ghdl.cm'),
        detail='' if not ghdl_cm else 'found',
        hint=('ghdl.cm missing: NGHDL VHDL models cannot load. Re-run the '
              'nghdl installer (Ubuntu) or reinstall eSim Full (Windows).'),
        flows=(NGHDL,)))
    return checks


def _check_icarus():
    checks = []
    iverilog = CosimConfig.iverilog_binary()
    checks.append(Check(
        key='iverilog', label='iverilog (Icarus Verilog compiler)',
        ok=bool(iverilog), path=iverilog or 'env/config/bundled/PATH',
        detail=_run_version([iverilog, '-V']) if iverilog else '',
        hint=('Icarus Verilog not found. Ubuntu: re-run install-eSim.sh (it '
              'builds iverilog with libvvp) or `sudo apt install iverilog` '
              '(Verifier only). Windows: reinstall eSim (bundled under '
              'library/bin/iverilog).'),
        flows=(VERIFIER, DCOSIM, NGVERI)))

    vvp = CosimConfig.vvp_binary()
    # vvp links libvvp in prefix builds; probe it with the same loader path
    # the app uses at run time or the version call fails spuriously.
    vvp_env = _loader_env(CosimConfig.iverilog_libdir())
    checks.append(Check(
        key='vvp', label='vvp (Icarus Verilog runtime)',
        ok=bool(vvp), path=vvp or 'next to iverilog / PATH',
        detail=_run_version([vvp, '-V'], env=vvp_env) if vvp else '',
        hint='vvp should sit next to iverilog; reinstall Icarus Verilog.',
        flows=(VERIFIER, DCOSIM)))

    libdir = CosimConfig.iverilog_libdir()
    has_lib = CosimConfig._has_libvvp(libdir)
    checks.append(Check(
        key='libvvp', label='libvvp (dlopen-ed by ngspice ivlng)',
        ok=has_lib,
        path=(libdir or '<iverilog prefix>/lib') + os.sep + 'libvvp*',
        detail='' if not has_lib else 'found in ' + (libdir or ''),
        hint=('libvvp missing: this iverilog was built without '
              '--enable-libvvp (apt/Bleyer builds are). d_cosim cannot run. '
              'Ubuntu: re-run install-eSim.sh. Windows: reinstall eSim.'),
        flows=(DCOSIM,)))
    return checks


def _check_build_tools():
    checks = []

    verilator, probed_v = _find_tool('verilator')
    if not verilator and _win():
        # MSYS2's verilator front-end is a script; the real binary is
        # verilator_bin.exe. Accept either.
        verilator, probed_v = _find_tool('verilator_bin')
    checks.append(Check(
        key='verilator', label='Verilator (Verilog -> C++ for NgVeri)',
        ok=bool(verilator), path=verilator or probed_v,
        detail=_run_version([verilator, '--version']) if verilator else '',
        hint=('Verilator not found. Ubuntu: `sudo apt install verilator`. '
              'Windows: reinstall eSim with the HDL-toolchain component '
              '(MSYS2 mingw64 verilator).'),
        flows=(NGVERI,)))

    make_name = 'mingw32-make' if _win() else 'make'
    make, probed_m = _find_tool(make_name)
    checks.append(Check(
        key='make', label=make_name + ' (code-model builds)',
        ok=bool(make), path=make or probed_m,
        detail=_run_version([make, '--version']) if make else '',
        hint=('Ubuntu: `sudo apt install make`. Windows: reinstall eSim with '
              'the HDL-toolchain component (provides MSYS2 mingw32-make).'),
        flows=(NGVERI, NGHDL)))

    gcc, probed_g = _find_tool('gcc')
    checks.append(Check(
        key='gcc', label='gcc (C compiler for code models/ghdlserver)',
        ok=bool(gcc), path=gcc or probed_g,
        detail=_run_version([gcc, '--version']) if gcc else '',
        hint=('Ubuntu: `sudo apt install gcc g++`. Windows: reinstall eSim '
              'with the HDL-toolchain component (MSYS2 mingw64 gcc).'),
        flows=(NGVERI, NGHDL)))
    return checks


def _check_ghdl():
    ghdl, probed = _find_tool('ghdl')
    version = _run_version([ghdl, '--version']) if ghdl else ''
    mcode = 'mcode' in version.lower()
    ok = bool(ghdl) and not mcode
    if not ghdl:
        detail = ''
        hint = ('GHDL not found. Ubuntu: `sudo apt install ghdl-llvm` (NEVER '
                'the plain `ghdl` meta-package - it pulls the mcode backend). '
                'Windows: reinstall eSim with the HDL-toolchain component.')
    elif mcode:
        detail = version + '  <-- mcode backend'
        hint = ('The active GHDL backend is mcode (JIT). nghdl links its VHDL '
                'socket server with `ghdl -e -Wl,...`, which mcode rejects, so '
                'simulation fails silently. Install ghdl-llvm or ghdl-gcc and '
                'purge ghdl-mcode (see nghdl/install-nghdl-scripts/'
                'GHDL-BACKEND-26.04.md).')
    else:
        detail = version
        hint = ''
    return Check(
        key='ghdl', label='GHDL (VHDL compiler, llvm/gcc backend)',
        ok=ok, path=ghdl or probed, detail=detail, hint=hint,
        flows=(NGHDL,))


def _check_nghdl_home():
    checks = []
    cfg = CosimConfig.nghdl_config_path()
    cfg_ok = os.path.isfile(cfg)
    checks.append(Check(
        key='nghdl_config', label='nghdl config (~/.nghdl/config.ini)',
        ok=cfg_ok, path=cfg,
        detail='' if not cfg_ok else 'present',
        hint=('~/.nghdl/config.ini missing. Ubuntu: re-run install-eSim.sh. '
              'Windows: launch eSim once via eSim.bat (the bootstrap writes '
              'it) and reinstall with the HDL-toolchain component.'),
        flows=(NGVERI, NGHDL)))

    home = CosimConfig.nghdl_cfg('NGHDL', 'NGHDL_HOME', '')
    release = CosimConfig.nghdl_cfg('NGHDL', 'RELEASE', '')
    # The per-model code-model rebuild runs make inside the configured ngspice
    # build tree; without it NGHDL model uploads cannot compile.
    rel_ok = bool(release) and os.path.isdir(
        os.path.join(release, 'src', 'xspice', 'icm'))
    checks.append(Check(
        key='nghdl_release', label='nghdl release tree (icm build dir)',
        ok=rel_ok,
        path=(os.path.join(release, 'src', 'xspice', 'icm') if release
              else '<config [NGHDL] RELEASE unset>  home=' + (home or '?')),
        detail='' if not rel_ok else 'present',
        hint=('The nghdl-simulator build tree is missing, so NGHDL/NgVeri '
              'model builds cannot run make. Ubuntu: re-run install-eSim.sh. '
              'Windows: reinstall eSim with the HDL-toolchain component.'),
        flows=(NGHDL,)))
    return checks


def _check_msys():
    """Windows-only: the MSYS2 tree that hosts bash, mintty and the mingw64
    toolchain used by every nt build/run branch."""
    home = _msys_home()
    checks = []
    bash = os.path.join(home, 'usr', 'bin', 'bash.exe') if home else ''
    bash_ok = bool(bash) and os.path.isfile(bash)
    checks.append(Check(
        key='msys_bash', label='MSYS2 bash (build shell)',
        ok=bash_ok,
        path=bash or '~/.nghdl/config.ini [COMPILER] MSYS_HOME unset',
        detail='' if not bash_ok else 'found',
        hint=('MSYS2 not found. Reinstall eSim and enable the '
              '"HDL toolchain (MSYS2)" component; then launch eSim once so '
              'the bootstrap records MSYS_HOME.'),
        flows=(NGVERI, NGHDL)))

    mintty = os.path.join(home, 'usr', 'bin', 'mintty.exe') if home else ''
    mintty_ok = bool(mintty) and os.path.isfile(mintty)
    checks.append(Check(
        key='msys_mintty', label='mintty (terminal for ghdlserver)',
        ok=mintty_ok,
        path=mintty or '<MSYS_HOME>/usr/bin/mintty.exe',
        detail='' if not mintty_ok else 'found',
        hint='Reinstall the eSim HDL-toolchain (MSYS2) component.',
        flows=(SIMULATION, NGHDL)))
    return checks


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def run_checks(flow=None):
    """Run every probe (or only the ones a given flow needs) and return the
    list of Check results. Purely filesystem/subprocess probing; no Qt."""
    checks = []
    checks.append(_check_ngspice())
    checks.extend(_check_codemodels())
    checks.extend(_check_icarus())
    checks.extend(_check_build_tools())
    checks.append(_check_ghdl())
    checks.extend(_check_nghdl_home())
    if _win():
        checks.extend(_check_msys())
    if flow:
        checks = [c for c in checks if flow in c.flows]
    return checks


def failures(flow=None):
    return [c for c in run_checks(flow) if not c.ok]


def ok_for(flow):
    """True when every dependency of `flow` is present."""
    return not failures(flow)


def report(flow=None):
    """Plain-text doctor report (the CLI/GUI/log surface)."""
    checks = run_checks(flow)
    lines = []
    title = 'eSim simulation-toolchain check'
    if flow:
        title += ' - ' + FLOW_LABELS.get(flow, flow)
    lines.append(title)
    lines.append('=' * len(title))
    for c in checks:
        mark = 'OK ' if c.ok else 'MISSING'
        lines.append('[%s] %s' % (mark.strip(), c.label))
        lines.append('        path : %s' % c.path)
        if c.detail:
            lines.append('        found: %s' % c.detail)
        if not c.ok and c.hint:
            lines.append('        fix  : %s' % c.hint)
    bad = [c for c in checks if not c.ok]
    lines.append('')
    if bad:
        lines.append('%d problem(s) found. Affected flows:' % len(bad))
        affected = sorted({f for c in bad for f in c.flows})
        for f in affected:
            lines.append('  - ' + FLOW_LABELS.get(f, f))
    else:
        lines.append('All checks passed.')
    return '\n'.join(lines)


def failure_message(flow):
    """Short, actionable multi-line message for dialogs/log sinks when `flow`
    cannot run: each missing tool with its probed path and fix hint. Empty
    string when the flow is runnable."""
    bad = failures(flow)
    if not bad:
        return ''
    lines = ['%s cannot run - missing dependencies:'
             % FLOW_LABELS.get(flow, flow), '']
    for c in bad:
        lines.append(u'• %s' % c.label)
        lines.append('   probed: %s' % c.path)
        lines.append('   fix   : %s' % c.hint)
    lines.append('')
    lines.append('Help menu -> "Check simulation toolchain" shows the full '
                 'report.')
    return '\n'.join(lines)


def require(flow, parent=None, dialogs=None):
    """Gate a flow: True when all its dependencies are present; otherwise show
    (or log) the actionable failure message and return False.

    `dialogs`: optional callable(title, text) used to surface the message.
    When None and `parent` is given, configuration.Dialogs.warning is used
    (imported lazily so headless callers never touch Qt)."""
    msg = failure_message(flow)
    if not msg:
        return True
    if dialogs is not None:
        dialogs('Simulation toolchain incomplete', msg)
    elif parent is not None:
        from configuration import Dialogs
        Dialogs.warning(parent, 'Simulation toolchain incomplete', msg)
    else:
        print(msg)
    return False


# --------------------------------------------------------------------------- #
#  GUI dialog (lazy Qt import; Help menu -> "Check simulation toolchain")
# --------------------------------------------------------------------------- #
def show_dialog(parent=None):
    """Modal doctor dialog: monospace report + Re-check + Copy buttons."""
    from PyQt6 import QtGui, QtWidgets

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle('Simulation toolchain check')
    dlg.setMinimumSize(720, 480)
    lay = QtWidgets.QVBoxLayout(dlg)

    view = QtWidgets.QPlainTextEdit(dlg)
    view.setReadOnly(True)
    # Same mono stack the QSS uses for every other console in eSim. The old
    # QFont('Monospace') named a family that does not exist on Windows, so the
    # style hint fell through to Courier New -- thin, badly hinted, and nothing
    # like the rest of the app. Size is left alone: it inherits the app font,
    # which already tracks zoom.
    mono = QtGui.QFont()
    mono.setFamilies(['JetBrains Mono', 'Cascadia Mono', 'Consolas',
                      'DejaVu Sans Mono', 'Monospace'])
    mono.setStyleHint(QtGui.QFont.StyleHint.TypeWriter)
    view.setFont(mono)
    lay.addWidget(view)

    row = QtWidgets.QHBoxLayout()
    recheck = QtWidgets.QPushButton('Re-check', dlg)
    copy = QtWidgets.QPushButton('Copy report', dlg)
    close = QtWidgets.QPushButton('Close', dlg)
    close.setDefault(True)
    row.addWidget(recheck)
    row.addWidget(copy)
    row.addStretch(1)
    row.addWidget(close)
    lay.addLayout(row)

    def refresh():
        view.setPlainText(report())

    recheck.clicked.connect(refresh)
    copy.clicked.connect(
        lambda: QtWidgets.QApplication.clipboard().setText(
            view.toPlainText()))
    close.clicked.connect(dlg.accept)

    refresh()
    dlg.exec()


if __name__ == '__main__':
    print(report())
