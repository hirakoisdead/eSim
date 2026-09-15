# =========================================================================
#             FILE: windows_bootstrap.py
#
#      DESCRIPTION: First-run (and every-run, idempotent) setup for the
#                   Windows install of eSim. Invoked by the esim.bat launcher
#                   BEFORE Application.py, with the bundled Python.
#
#                   Everything here is per-user state, which is why it runs at
#                   launch time and not from the machine-wide installer: a
#                   multi-user PC gets a correct ~/.esim for EVERY user who
#                   launches eSim, and reinstalls/upgrades self-heal.
#
#                   Responsibilities:
#                     1. ~/.esim/config.ini          (eSim_HOME + resource
#                        keys, mirrors install-eSim.sh createConfigFile)
#                     2. ~/.esim/kicad_symbols/      seed the 3 generated
#                        symbol libraries once (never clobber user models)
#                     3. ~/.nghdl/config.ini         NGHDL_HOME/DIGITAL_MODEL/
#                        RELEASE/SRC_HOME/MSYS_HOME/[COSIM] for whichever
#                        toolchain pieces this install actually has
#                     4. spinit                      rewrite the bundled
#                        ngspice's codemodel paths for this install location
#                     5. KiCad sym-lib-table         seed every library from
#                        bundled KiCad's own template disabled-by-default,
#                        then register eSim libraries active-by-default
#                        (static -> install dir, generated -> ~/.esim) in the
#                        user's %APPDATA%/kicad/<ver>/sym-lib-table
#
#                   Pure stdlib + eSim's own kicad_symlib helpers; no Qt. The
#                   logic is OS-independent on purpose so the test suite covers
#                   it on Linux CI even though only Windows ships it.
#
#            USAGE: python windows_bootstrap.py [--esim-root DIR]
#                   (esim.bat passes the install root; default = two levels up)
#
#     ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

import argparse
import configparser
import os
import re
import shutil
import sys


def esim_root_default():
    """Install root = the dir holding VERSION + src/ (this file lives in
    <root>/windows/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_dir(*parts):
    return os.path.join(os.path.expanduser('~'), *parts)


GENERATED_LIBS = ("eSim_Ngveri", "eSim_NgVeriCosim", "eSim_Nghdl")


def write_esim_config(esim_root):
    """~/.esim/config.ini — same keys the Ubuntu installer writes."""
    cfg_dir = _user_dir('.esim')
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, 'config.ini')
    cfg = configparser.ConfigParser()
    cfg.read(path)
    if not cfg.has_section('eSim'):
        cfg.add_section('eSim')
    # eSim_HOME is authoritative for this install; rewrite it every launch
    # so a moved/upgraded install self-heals. Keys mirror install-eSim.sh.
    cfg.set('eSim', 'eSim_HOME', esim_root)
    cfg.set('eSim', 'LICENSE', '%(eSim_HOME)s/LICENSE')
    cfg.set('eSim', 'KicadLib', '%(eSim_HOME)s/library/kicadLibrary')
    cfg.set('eSim', 'IMAGES', '%(eSim_HOME)s/images')
    cfg.set('eSim', 'VERSION', '%(eSim_HOME)s/VERSION')
    cfg.set('eSim', 'MODELICA_MAP_JSON',
            '%(eSim_HOME)s/library/ngspicetoModelica/Mapping.json')
    with open(path, 'w') as fh:
        cfg.write(fh)
    return path


def seed_generated_symbols(esim_root):
    """Copy the 3 runtime-rewritten symbol libs to ~/.esim/kicad_symbols once.
    Never overwrite: the user's built models accumulate inside these files."""
    src_dir = os.path.join(esim_root, 'library', 'kicadLibrary',
                           'eSim-symbols')
    dst_dir = _user_dir('.esim', 'kicad_symbols')
    os.makedirs(dst_dir, exist_ok=True)
    for lib in GENERATED_LIBS:
        src = os.path.join(src_dir, lib + '.kicad_sym')
        dst = os.path.join(dst_dir, lib + '.kicad_sym')
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    return dst_dir


def write_nghdl_config(esim_root):
    """~/.nghdl/config.ini — every key the simulation flows read, mirroring
    what nghdl/install-nghdl.sh writes on Ubuntu (absolute paths instead of
    %()s interpolation so a configparser round-trip stays lossless):

      [NGHDL]    NGHDL_HOME    tools/nghdl (the built nghdl-simulator tree)
                 DIGITAL_MODEL <NGHDL_HOME>/src/xspice/icm  (model sources
                               land here at build time)
                 RELEASE       <NGHDL_HOME>/release (configured build tree
                               where runtime `make` rebuilds the .cm)
      [SRC]      SRC_HOME      <root>/nghdl (ngspice_ghdl.py resolves its
                               ghdlserver sources under SRC_HOME/src/)
                 LICENSE       <SRC_HOME>/LICENSE
      [COMPILER] MSYS_HOME     tools/msys64 (mingw32-make/gcc/verilator/ghdl)
      [COSIM]    IVERILOG/VVP/IVERILOG_LIB — the bundled libvvp Icarus

    Sections are written only for the pieces actually installed, so the
    in-app doctor reports the truth for Compact installs."""
    nghdl_home = os.path.join(esim_root, 'tools', 'nghdl')
    msys_home = os.path.join(esim_root, 'tools', 'msys64')
    if not (os.path.isdir(nghdl_home) or os.path.isdir(msys_home)):
        return None
    cfg_dir = _user_dir('.nghdl')
    os.makedirs(cfg_dir, exist_ok=True)
    path = os.path.join(cfg_dir, 'config.ini')
    cfg = configparser.ConfigParser()
    cfg.read(path)

    if os.path.isdir(nghdl_home):
        for section in ('NGHDL', 'SRC'):
            if not cfg.has_section(section):
                cfg.add_section(section)
        cfg.set('NGHDL', 'NGHDL_HOME', nghdl_home)
        cfg.set('NGHDL', 'DIGITAL_MODEL',
                os.path.join(nghdl_home, 'src', 'xspice', 'icm'))
        cfg.set('NGHDL', 'RELEASE', os.path.join(nghdl_home, 'release'))
        src_home = os.path.join(esim_root, 'nghdl')
        cfg.set('SRC', 'SRC_HOME', src_home)
        cfg.set('SRC', 'LICENSE', os.path.join(src_home, 'LICENSE'))

    if os.path.isdir(msys_home):
        if not cfg.has_section('COMPILER'):
            cfg.add_section('COMPILER')
        cfg.set('COMPILER', 'MSYS_HOME', msys_home)

    iv_root = os.path.join(esim_root, 'library', 'bin', 'iverilog')
    iv_bin = os.path.join(iv_root, 'bin', 'iverilog.exe')
    if os.path.isfile(iv_bin):
        if not cfg.has_section('COSIM'):
            cfg.add_section('COSIM')
        cfg.set('COSIM', 'IVERILOG', iv_bin)
        cfg.set('COSIM', 'VVP', os.path.join(iv_root, 'bin', 'vvp.exe'))
        # mingw puts runtime DLLs in bin/, POSIX-style builds in lib/; record
        # whichever holds libvvp so ngspice's ivlng adapter can dlopen it.
        for sub in ('bin', 'lib'):
            libdir = os.path.join(iv_root, sub)
            try:
                names = os.listdir(libdir)
            except OSError:
                continue
            if any(n.startswith('libvvp') or n == 'vvp.dll' for n in names):
                cfg.set('COSIM', 'IVERILOG_LIB', libdir)
                break

    with open(path, 'w') as fh:
        cfg.write(fh)
    return path


def _atomic_write(path, data):
    """Replace ``path`` with ``data`` atomically (temp file + os.replace).

    Reuses kicad_symlib._atomic_write (stdlib-only, vendored in the source tree
    beside this script) so there is one implementation of this. When the source
    tree is not importable -- this script is also runnable standalone -- fall
    back to a plain rewrite: degraded, never fatal."""
    sys.path.insert(0, os.path.join(esim_root_default(), 'src', 'maker'))
    try:
        from kicad_symlib import _atomic_write as _aw  # noqa: E402
    except ImportError:
        _aw = None
    finally:
        sys.path.pop(0)
    if _aw is not None:
        _aw(path, data)
        return
    with open(path, 'w') as fh:
        fh.write(data)


def fix_spinit(esim_root):
    """Self-heal the bundled ngspice's spinit for THIS install location.

    spinit's `codemodel` lines carry absolute paths baked in at build time
    (the build machine's staging dir). ngspice loads .cm code models ONLY
    through these lines, so after installation they must point at
    <esim_root>/tools/nghdl/install_dir/lib/ngspice. Idempotent: rewriting an
    already-correct file is a no-op. Returns the number of rewritten lines."""
    spinit = os.path.join(esim_root, 'tools', 'nghdl', 'install_dir',
                          'share', 'ngspice', 'scripts', 'spinit')
    cmdir = os.path.join(esim_root, 'tools', 'nghdl', 'install_dir',
                         'lib', 'ngspice')
    if not (os.path.isfile(spinit) and os.path.isdir(cmdir)):
        return 0
    pattern = re.compile(
        r'^(\s*codemodel\s+).*[/\\]([^/\\]+\.cm)\s*$', re.IGNORECASE)
    changed = 0
    out_lines = []
    with open(spinit, 'r', errors='replace') as fh:
        for line in fh:
            m = pattern.match(line)
            if m:
                target = os.path.join(cmdir, m.group(2)).replace('\\', '/')
                new = '%s%s\n' % (m.group(1), target)
                if new != line:
                    changed += 1
                line = new
            out_lines.append(line)
    if changed:
        # Atomic: spinit is how ngspice finds EVERY .cm code model. A crash
        # part-way through this rewrite leaves a truncated file and then every
        # simulation fails with "codemodel not found", nowhere near the cause.
        _atomic_write(spinit, ''.join(out_lines))
    return changed


def ensure_unversioned_libvvp(esim_root):
    """Self-heal the libvvp DLL name for ngspice's d_cosim ivlng adapter.

    ivlng does LoadLibrary("libvvp") -- the UNVERSIONED name (eSim netlists
    pass no lib_args) -- but the MinGW iverilog build ships only
    libvvp-<N>.dll. Keep a plain libvvp.dll copy beside it. Idempotent;
    returns True when the plain name exists afterwards."""
    bindir = os.path.join(esim_root, 'library', 'bin', 'iverilog', 'bin')
    plain = os.path.join(bindir, 'libvvp.dll')
    if os.path.isfile(plain):
        return True
    if not os.path.isdir(bindir):
        return False
    for name in sorted(os.listdir(bindir)):
        if name.startswith('libvvp-') and name.endswith('.dll'):
            shutil.copy2(os.path.join(bindir, name), plain)
            return True
    return False


def _kicad_config_root():
    if os.name == 'nt':
        return os.path.join(os.environ.get('APPDATA', ''), 'kicad')
    return _user_dir('.config', 'kicad')


def _bundled_kicad_config_dir(esim_root):
    """Return the config dir for bundled KiCad's stamped major.minor."""
    stamp = os.path.join(esim_root, 'tools', 'kicad', 'KICAD-VERSION')
    try:
        with open(stamp) as fh:
            version = fh.read().strip()
    except OSError:
        return None
    m = re.match(r'(\d+)\.(\d+)', version)
    if not m:
        return None
    return os.path.join(_kicad_config_root(),
                        '%s.%s' % (m.group(1), m.group(2)))


def ensure_kicad_config_dir(esim_root):
    """Pre-create the per-user KiCad config version dir for the BUNDLED KiCad
    (tools/kicad), e.g. %APPDATA%/kicad/9.0.

    KiCad only creates this dir on its own first launch, and
    register_kicad_libraries() can only register eSim's symbol libraries into
    version dirs that exist -- without this, a fresh user's first schematic
    opens with no eSim symbols at all. The bundled KiCad's exact version is
    stamped into tools/kicad/KICAD-VERSION by Stage-Kicad; its config dir is
    <major>.<minor>. Creating the dir (and letting ensure_lib_registered seed
    a minimal sym-lib-table in it) is safe: KiCad treats both as its own on
    first launch and merges, never clobbers. No-op when there is no bundled
    KiCad (dev tree) or the stamp is unreadable."""
    cfg_dir = _bundled_kicad_config_dir(esim_root)
    if cfg_dir is None:
        return None
    os.makedirs(cfg_dir, exist_ok=True)
    return cfg_dir


def register_kicad_stock_libraries(esim_root):
    """Add bundled KiCad's standard symbol libraries disabled-by-default.

    The official payload already carries both ``share/kicad/symbols`` and its
    matching ``share/kicad/template/sym-lib-table``. Copy each template row
    into bundled KiCad's user table with ``(disabled)`` appended, preserving
    KiCad's nickname and description while pointing its URI at eSim's private
    symbol directory. Absolute owned paths let uninstall remove these rows
    without touching a separate system KiCad installation. Existing rows are
    never rewritten: once a user checks Active, later eSim launches must not
    turn it off again.

    Only the bundled KiCad version is touched. A machine may also have KiCad 8
    or 10 installed, and a KICAD9_SYMBOL_DIR row is invalid in those tables.
    """
    cfg_dir = _bundled_kicad_config_dir(esim_root)
    template = os.path.join(esim_root, 'tools', 'kicad', 'share', 'kicad',
                            'template', 'sym-lib-table')
    if cfg_dir is None or not os.path.isdir(cfg_dir) or \
            not os.path.isfile(template):
        return False

    sys.path.insert(0, os.path.join(esim_root, 'src', 'maker'))
    try:
        from kicad_symlib import _atomic_write, _balanced_end  # noqa: E402
    except ImportError:
        return False
    finally:
        sys.path.pop(0)

    with open(template) as fh:
        stock_table = fh.read()
    entry_re = re.compile(r'\(lib\s+\(name\s+"([^"]+)"\)')
    uri_re = re.compile(r'\(uri\s+"[^"]*[/\\]([^/\\"]+\.kicad_sym)"\)')
    symbol_dir = os.path.join(esim_root, 'tools', 'kicad', 'share', 'kicad',
                              'symbols')
    stock_entries = []
    for match in entry_re.finditer(stock_table):
        end = _balanced_end(stock_table, match.start())
        if end != -1:
            entry = stock_table[match.start():end].strip()
            uri_match = uri_re.search(entry)
            if uri_match:
                owned_uri = os.path.join(symbol_dir, uri_match.group(1))
                entry = uri_re.sub(lambda _match: '(uri "%s")' % owned_uri,
                                   entry, count=1)
                stock_entries.append((match.group(1), entry))
    if not stock_entries:
        return False

    table = os.path.join(cfg_dir, 'sym-lib-table')
    try:
        with open(table) as fh:
            content = fh.read()
    except FileNotFoundError:
        content = '(sym_lib_table\n  (version 7)\n)\n'

    existing = set(entry_re.findall(content))
    additions = []
    for name, entry in stock_entries:
        if name in existing:
            continue
        if '(disabled)' not in entry:
            entry = entry[:-1] + '(disabled))'
        additions.append('  ' + entry.replace('\n', '\n  ') + '\n')
    if not additions:
        return True

    idx = content.rstrip().rfind(')')
    if idx == -1:
        return False
    _atomic_write(table, content[:idx] + ''.join(additions) + content[idx:])
    return True


def register_kicad_libraries(esim_root):
    """Register every eSim library in the user's KiCad sym-lib-table(s):
    static libs -> <install>/library/kicadLibrary/eSim-symbols, generated
    libs -> ~/.esim/kicad_symbols. Reuses kicad_symlib.ensure_lib_registered
    (append-or-rewrite, idempotent, best-effort).

    On Windows eSim does NOT copy static libs into KiCad's own install tree
    (that was the old tribal-installer behaviour); they are referenced in
    place from the eSim install dir. KiCad's standard libraries are registered
    separately by register_kicad_stock_libraries().

    If KiCad has never been started (%APPDATA%/kicad absent) there is nothing
    to register into yet; runtime ensure_lib_registered calls in the model
    builders cover the generated libs later, and this function runs again on
    every eSim launch anyway."""
    sys.path.insert(0, os.path.join(esim_root, 'src', 'maker'))
    try:
        from kicad_symlib import ensure_lib_registered  # noqa: E402
    except ImportError:
        return False
    finally:
        sys.path.pop(0)

    base = _kicad_config_root()
    if not os.path.isdir(base):
        return False

    static_dir = os.path.join(esim_root, 'library', 'kicadLibrary',
                              'eSim-symbols')
    gen_dir = _user_dir('.esim', 'kicad_symbols')
    if os.path.isdir(static_dir):
        for fname in sorted(os.listdir(static_dir)):
            m = re.fullmatch(r'(eSim_\w+)\.kicad_sym', fname)
            if not m:
                continue
            lib = m.group(1)
            target = (os.path.join(gen_dir, fname) if lib in GENERATED_LIBS
                      else os.path.join(static_dir, fname))
            ensure_lib_registered(lib, target)
        legacy_dir = os.path.join(static_dir, 'legacy')
        if os.path.isdir(legacy_dir):
            for fname in sorted(os.listdir(legacy_dir)):
                if not fname.endswith('.lib'):
                    continue
                lib = os.path.splitext(fname)[0]
                ensure_lib_registered(lib, os.path.join(legacy_dir, fname))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--esim-root', default=esim_root_default())
    args = ap.parse_args(argv)
    root = os.path.abspath(args.esim_root)

    # Every step is an INDEPENDENT self-heal, so one failure must not skip the
    # rest. installer.iss no longer grants users-modify on the whole {app}
    # tree, only on the two dirs eSim writes -- so a step that touches the
    # install tree (fix_spinit, ensure_unversioned_libvvp) can now legitimately
    # raise PermissionError on a hand-tightened, roaming or repackaged install.
    # Run straight-line, that aborted the remaining steps, and the user lost
    # register_kicad_libraries(): eSim's symbols silently missing from KiCad,
    # with nothing anywhere pointing back at spinit. Report and carry on.
    steps = (
        ('config.ini', write_esim_config),
        ('generated symbol seeding', seed_generated_symbols),
        ('nghdl config.ini', write_nghdl_config),
        ('spinit code-model paths', fix_spinit),
        ('libvvp.dll', ensure_unversioned_libvvp),
        ('kicad config dir', ensure_kicad_config_dir),
        ('kicad stock sym-lib-table', register_kicad_stock_libraries),
        ('eSim sym-lib-table', register_kicad_libraries),
    )
    failed = 0
    for label, step in steps:
        try:
            step(root)
        except Exception as exc:            # noqa: BLE001 - best effort
            failed += 1
            print('eSim bootstrap: %s skipped (%s: %s)'
                  % (label, type(exc).__name__, exc))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
