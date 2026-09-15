# =========================================================================
#             FILE: uninstall_cleanup.py
#
#      DESCRIPTION: The PER-USER half of an eSim uninstall.
#
#                   installer.iss removes the machine-wide install tree, but
#                   everything windows_bootstrap.py writes lives in the user's
#                   own profile and is invisible to the installer's log:
#
#                     ~/.esim            config.ini, kicad_symbols/, caches
#                     ~/.nghdl           config.ini
#                     %APPDATA%/kicad/<ver>/sym-lib-table
#                                        eSim rows plus bundled KiCad stock
#                                        rows added by windows_bootstrap.py;
#                                        their uris point INTO the install dir
#                                        that is about to be deleted -- left
#                                        behind they make KiCad raise "library
#                                        not found" on every schematic next.
#
#                   So the uninstaller runs this script (as the ORIGINAL,
#                   non-elevated user -- see installer.iss CurUninstallStep-
#                   Changed) before it deletes any files, while the bundled
#                   python is still on disk.
#
#                   Policy, mirroring what a Windows user expects:
#                     * rows pointing into the install tree are ALWAYS removed
#                       -- those files are going away regardless;
#                     * ~/.esim and ~/.nghdl (which hold the symbol libraries
#                       for models the user BUILT) are removed only with
#                       --purge-user-data, i.e. only when the user said yes.
#                       Their sym-lib-table rows follow the same answer: kept
#                       data stays usable from a plain KiCad.
#
#                   Pure stdlib and OS-independent (same reason as
#                   windows_bootstrap.py: the test suite covers it on Linux
#                   CI). Ubuntu/install-eSim.sh --uninstall calls it too, for
#                   the sym-lib-table rows its rm -rf cannot reach.
#
#                   Best effort ALWAYS: an uninstall must never fail because a
#                   config file was read-only or a directory was in use. Every
#                   step is guarded and main() returns 0 unless --strict.
#
#            USAGE: python uninstall_cleanup.py --esim-root DIR
#                                               [--purge-user-data] [--dry-run]
#
#     ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

import argparse
import os
import re
import shutil
import sys

# Same three libraries kicad_symlib.GENERATED_LIBS names: eSim REWRITES these
# at model-build time, so they live in ~/.esim/kicad_symbols and hold the
# user's own models. Their fate follows the user-data answer, not the tree.
GENERATED_LIBS = ("eSim_Ngveri", "eSim_NgVeriCosim", "eSim_Nghdl")

# One row of a KiCad sym-lib-table, e.g.
#   (lib (name "eSim_Devices")(type "KiCad")(uri "C:/...")(options "")
#    (descr ""))            <- really one line; wrapped here for the 79 cols
# Written by kicad_symlib.ensure_lib_registered one per line; KiCad itself
# writes the same shape. Anchored per line so nothing else is ever touched.
_LIB_ROW = re.compile(
    r'^[ \t]*\(lib \(name "(?P<name>[^"]*)"\).*\r?\n?', re.MULTILINE)
_URI = re.compile(r'\(uri "(?P<uri>[^"]*)"\)')

# A table with no libraries left, in the exact minimal form
# kicad_symlib._atomic_write seeds when KiCad has never been started. Only
# THIS shape is removed -- a table the user has otherwise edited stays.
_EMPTY_TABLE = re.compile(r'^\(sym_lib_table\s*(\(version \d+\)\s*)?\)\s*$')


def _home():
    return os.path.expanduser('~')


def kicad_config_root():
    """Per-user KiCad config root: %APPDATA%/kicad on Windows, ~/.config/kicad
    elsewhere. Same resolution as kicad_symlib._kicad_config_dir, repeated
    here rather than imported: this script must still work when the install
    tree (and with it src/maker) is half deleted."""
    if os.name == 'nt':
        return os.path.join(os.environ.get('APPDATA', ''), 'kicad')
    return os.path.join(_home(), '.config', 'kicad')


def _norm(path):
    """Comparable form of a path that may have arrived from a KiCad table
    (forward slashes, trailing separator, mixed case on Windows)."""
    if not path:
        return ''
    path = os.path.expandvars(os.path.expanduser(path))
    if os.name == 'nt':
        path = path.replace('/', os.sep)
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _under(path, root):
    """True when ``path`` is inside ``root`` (or is it). Pure string work on
    normalised paths -- neither may exist any more by the time this runs."""
    p, r = _norm(path), _norm(root)
    if not p or not r:
        return False
    return p == r or p.startswith(r + os.sep)


def _atomic_write(path, data):
    """Replace ``path`` with ``data`` via temp file + os.replace.

    A sym-lib-table truncated by a crash mid-rewrite makes KiCad error on
    EVERY launch -- long after eSim is gone and with nothing pointing back
    here. Same guarantee kicad_symlib gives when adding the rows."""
    tmp = path + '.esim-uninstall.tmp'
    try:
        with open(tmp, 'w') as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _row_is_owned(name, uri, esim_root, purge_user_data):
    """Should this sym-lib-table row go?

    Rows are removed only when their target is one eSim owns:
      * inside the install tree, including bundled
        KiCad's disabled stock symbol rows           -> always (it is going)
      * a generated lib under ~/.esim/kicad_symbols  -> only when the user
                                                        asked for that data to
                                                        be removed as well
      * an eSim static library under ~/.esim/kicad_static
                                                    -> only with user-data purge
      * a legacy ${KICAD*_SYMBOL_DIR} row eSim wrote before the libraries
        moved into an eSim-owned directory           -> always (dangling now)
    Anything else -- including a system KiCad stock row, or an eSim_* library
    the user copied somewhere of their own -- is left alone."""
    if esim_root and _under(uri, esim_root):
        return True
    static_dir = os.path.join(_home(), '.esim', 'kicad_static')
    if _under(uri, static_dir):
        # Legacy converter libraries retain their historical names (CONNECT,
        # analog, source, and so on), so ownership is established by this
        # directory rather than by an eSim_ name prefix.
        return purge_user_data
    if not name.startswith('eSim_'):
        return False
    if uri.startswith('${KICAD') and 'SYMBOL_DIR' in uri:
        return True
    gen_dir = os.path.join(_home(), '.esim', 'kicad_symbols')
    if _under(uri, gen_dir):
        return purge_user_data or name not in GENERATED_LIBS
    return False


def clean_sym_lib_table(table, esim_root, purge_user_data=False,
                        dry_run=False):
    """Strip eSim's rows from one sym-lib-table. Returns the number removed
    (-1 when the file could not be read/written)."""
    try:
        with open(table, errors='replace') as fh:
            content = fh.read()
    except OSError:
        return -1

    removed = []

    def drop(m):
        uri_m = _URI.search(m.group(0))
        uri = uri_m.group('uri') if uri_m else ''
        if _row_is_owned(m.group('name'), uri, esim_root, purge_user_data):
            removed.append(m.group('name'))
            return ''
        return m.group(0)

    new_content = _LIB_ROW.sub(drop, content)
    if not removed or dry_run:
        return len(removed)
    try:
        _atomic_write(table, new_content)
    except OSError:
        return -1
    return len(removed)


def prune_empty_kicad_config(base=None, dry_run=False):
    """Drop the config skeleton eSim itself created.

    windows_bootstrap.ensure_kicad_config_dir pre-creates
    %APPDATA%/kicad/<ver> (and lets kicad_symlib seed a minimal sym-lib-table
    in it) so eSim's symbols are registered even for a user who has never
    started KiCad. On such a machine, removing eSim's rows leaves exactly that
    skeleton behind -- an empty table for a KiCad the user may not even have.
    Remove it, but ONLY when it is still untouched: a table with any library
    row left, or a version dir holding any other KiCad setting, is the user's
    and stays."""
    base = base or kicad_config_root()
    dropped = []
    if not os.path.isdir(base):
        return dropped
    try:
        vers = sorted(os.listdir(base))
    except OSError:
        return dropped
    for ver in vers:
        vdir = os.path.join(base, ver)
        table = os.path.join(vdir, 'sym-lib-table')
        if not (os.path.isdir(vdir) and os.path.isfile(table)):
            continue
        try:
            with open(table, errors='replace') as fh:
                body = fh.read()
        except OSError:
            continue
        if not _EMPTY_TABLE.match(body.strip()):
            continue
        try:
            if os.listdir(vdir) != ['sym-lib-table']:
                continue
            if not dry_run:
                os.remove(table)
                os.rmdir(vdir)
            dropped.append(vdir)
        except OSError:
            continue
    try:
        if not dry_run and not os.listdir(base):
            os.rmdir(base)
            dropped.append(base)
    except OSError:
        pass
    return dropped


def clean_kicad_tables(esim_root, purge_user_data=False, dry_run=False,
                       base=None):
    """Every per-user sym-lib-table KiCad may have (one per version dir)."""
    base = base or kicad_config_root()
    report = []
    if not os.path.isdir(base):
        return report
    try:
        vers = sorted(os.listdir(base))
    except OSError:
        return report
    for ver in vers:
        table = os.path.join(base, ver, 'sym-lib-table')
        if os.path.isfile(table):
            report.append((table, clean_sym_lib_table(
                table, esim_root, purge_user_data, dry_run)))
    return report


def purge_user_dirs(dry_run=False):
    """~/.esim and ~/.nghdl -- ONLY on the user's explicit yes.

    ~/.esim holds kicad_symbols/, i.e. the symbol libraries every NgVeri /
    NGHDL model the user built was written into, so this is real user work,
    not scratch state. That is also why a reinstall must not need it gone:
    keeping it makes the next install pick up exactly where this one left."""
    removed = []
    for name in ('.esim', '.nghdl'):
        path = os.path.join(_home(), name)
        if not os.path.isdir(path):
            continue
        if dry_run:
            removed.append(path)
            continue
        try:
            shutil.rmtree(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--esim-root', default='',
                    help='install tree being removed; rows pointing into it '
                         'are unregistered from KiCad')
    ap.add_argument('--purge-user-data', action='store_true',
                    help='also delete ~/.esim and ~/.nghdl')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--strict', action='store_true',
                    help='exit non-zero on any failure (tests only -- the '
                         'uninstaller must never see a failure exit)')
    args = ap.parse_args(argv)
    root = os.path.abspath(args.esim_root) if args.esim_root else ''

    failed = 0
    try:
        for table, n in clean_kicad_tables(root, args.purge_user_data,
                                           args.dry_run):
            if n < 0:
                failed += 1
                print('eSim uninstall: could not update %s' % table)
            elif n:
                print('eSim uninstall: removed %d eSim entr%s from %s'
                      % (n, 'y' if n == 1 else 'ies', table))
    except Exception as exc:                    # noqa: BLE001 - best effort
        failed += 1
        print('eSim uninstall: KiCad cleanup skipped (%s: %s)'
              % (type(exc).__name__, exc))

    if args.purge_user_data:
        try:
            for path in purge_user_dirs(args.dry_run):
                print('eSim uninstall: removed %s' % path)
        except Exception as exc:                # noqa: BLE001 - best effort
            failed += 1
            print('eSim uninstall: user data skipped (%s: %s)'
                  % (type(exc).__name__, exc))

    try:
        for path in prune_empty_kicad_config(dry_run=args.dry_run):
            print('eSim uninstall: removed empty %s' % path)
    except Exception as exc:                    # noqa: BLE001 - best effort
        failed += 1
        print('eSim uninstall: KiCad config prune skipped (%s: %s)'
              % (type(exc).__name__, exc))

    return 1 if (failed and args.strict) else 0


if __name__ == '__main__':
    sys.exit(main())
