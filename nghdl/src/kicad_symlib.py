# =========================================================================
#             FILE: kicad_symlib.py
#
#      DESCRIPTION: Robust S-expression helpers for the shared eSim KiCad
#                   symbol libraries (eSim_Ngveri / eSim_NgVeriCosim /
#                   eSim_Nghdl .kicad_sym). Each library is one KiCad symbol
#                   file appended to by every generated model. The original
#                   code mutated it with raw byte/line surgery (content[:-2],
#                   lines[0:-2], line.startswith("(symbol")) which, on repeated
#                   add/overwrite/delete, glued blocks together
#                   ("))(symbol ..."), shed a part's opening "(symbol" line, and
#                   left unbalanced parens. KiCad then rejects the whole file and
#                   the library disappears. These helpers parse the file into
#                   balanced top-level part blocks keyed by model name, so
#                   add/overwrite/delete are idempotent and always re-serialize a
#                   valid, balanced file (also healing an already-corrupted file
#                   on the next write).
#
#            NOTES: Self-contained on purpose (stdlib only: re/os/tempfile).
#                   This file is vendored byte-for-byte into BOTH the eSim source
#                   tree (src/maker/kicad_symlib.py) and the separately-packaged
#                   NGHDL tarball (nghdl/src/kicad_symlib.py). Each package
#                   imports its OWN copy, so a broken/missing NGHDL install can
#                   never break eSim and vice-versa. A drift-guard test asserts
#                   the two copies stay identical -- if you edit one, copy it to
#                   the other.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

import re
import os
import shutil
import tempfile


_LIB_HEADER = ('(kicad_symbol_lib (version 20211014) '
               '(generator kicad_symbol_editor)')

# A *part* opener is distinctively '(symbol "<name>" (pin_names'. Sub-units
# '(symbol "<name>_0_1"(rectangle' / '(symbol "<name>_1_1"' are nested inside it
# and never match this, so they are carried along inside their parent's balanced
# block rather than treated as separate parts.
_PART_RE = re.compile(r'\(symbol\s+"([^"]+)"\s+\(pin_names')


def _balanced_end(text, start):
    '''Index just past the ")" that closes the "(" at text[start], honoring
       quoted strings. Returns -1 if it never balances (truncated/corrupt).'''
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _extract_parts(content):
    '''Parse a (possibly corrupt) kicad_sym into an ordered {name: block}.
       Only well-formed balanced part blocks are kept; orphaned/duplicate
       blocks are dropped and the last definition of a name wins (freshest).'''
    parts = {}
    for m in _PART_RE.finditer(content):
        end = _balanced_end(content, m.start())
        if end != -1:
            parts[m.group(1)] = content[m.start():end].strip()
    return parts


def _read_parts(path):
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        content = ''
    return _extract_parts(content)


def _atomic_write(path, data):
    '''Replace the contents of ``path`` with ``data`` atomically: write a temp
       file in the SAME directory, flush + fsync it, then os.replace (atomic on
       POSIX and Windows). A crash, full disk or kill -9 mid-write therefore
       leaves the previous file intact instead of a truncated one.

       eSim rewrites several small-but-load-bearing text files in place, each
       read by a DIFFERENT tool that then fails far from here when the file is
       half-written: the .kicad_sym libraries (KiCad drops the whole library),
       KiCad's sym-lib-table (every KiCad launch errors), modpath.lst (cmpp
       aborts the entire code-model build) and ngspice's spinit (no code model
       loads at all). They all go through this one helper.'''
    directory = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(
        dir=directory, prefix='.eSim_atomic_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)           # atomic on POSIX and Windows
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _write_lib(path, parts):
    '''Serialize {name: block} back into a valid, balanced kicad_sym file.
       Written atomically (see _atomic_write) so a crash, full disk, or kill -9
       mid-write can never leave the shared library truncated or empty -- the
       failure mode this module exists to fix.'''
    out = [_LIB_HEADER, '']
    for block in parts.values():
        out.append(block)
        out.append('')
    out.append(')')
    _atomic_write(path, '\n'.join(out) + '\n')


# =========================================================================
# Location of the runtime-generated libraries + KiCad table registration.
#
# eSim ships 17 static symbol libraries but *rewrites* three of them every
# time a user builds an HDL model (eSim_Ngveri / eSim_NgVeriCosim /
# eSim_Nghdl). Those three now live in the user's own ~/.esim/kicad_symbols
# so the app never needs write access to KiCad's root-owned
# /usr/share/kicad/symbols. The other 14 stay there untouched.
# =========================================================================

GENERATED_LIBS = ("eSim_Ngveri", "eSim_NgVeriCosim", "eSim_Nghdl")


def generated_symlib_dir():
    '''Directory holding eSim's runtime-generated KiCad symbol libraries:
       ~/.esim/kicad_symbols, created on demand. Same path on every OS
       (os.path.expanduser resolves ~ on Windows too).'''
    d = os.path.join(os.path.expanduser('~'), '.esim', 'kicad_symbols')
    os.makedirs(d, exist_ok=True)
    return d


def generated_symlib_path(libname, legacy_dirs=()):
    '''Absolute path of the generated library <libname>.kicad_sym under
       generated_symlib_dir(), performing a one-time lazy migration.

       A user's built models accumulate INSIDE the library file. When eSim
       used to write these libs into /usr/share/kicad/symbols (Linux) or
       <inst_dir>/KiCad/share/kicad/symbols (old Windows layout), an existing
       install already holds all of that user's models there. So: if the new
       ~/.esim location has no copy yet but a legacy copy exists, COPY (never
       move) the legacy file in, preserving those models. The legacy file is
       left behind on purpose -- uninstall/cleanup handles it; we never write
       to the legacy location.

       legacy_dirs adds extra probe directories (e.g. the old Windows install
       path) ahead of the default /usr/share one. copy2 is wrapped so a
       root-owned/unreadable legacy file just means "no migration" (a fresh
       empty lib is created on first write) rather than an error.'''
    new_path = os.path.join(generated_symlib_dir(), libname + '.kicad_sym')
    if not os.path.exists(new_path):
        for d in list(legacy_dirs) + ['/usr/share/kicad/symbols']:
            legacy = os.path.join(d, libname + '.kicad_sym')
            if os.path.isfile(legacy):
                try:
                    shutil.copy2(legacy, new_path)
                except OSError:
                    pass
                break
    return new_path


def _kicad_config_dir():
    '''KiCad per-user config root holding the version dirs with sym-lib-table:
       %APPDATA%/kicad on Windows, ~/.config/kicad elsewhere.'''
    if os.name == 'nt':
        return os.path.join(os.environ.get('APPDATA', ''), 'kicad')
    return os.path.join(os.path.expanduser('~'), '.config', 'kicad')


def ensure_lib_registered(libname, lib_path, descr=""):
    '''Ensure <libname> is registered in every KiCad per-user sym-lib-table,
       pointing at the absolute lib_path. Idempotent and best-effort.

       A library added AFTER install (eSim_NgVeriCosim) is missing from
       existing users' tables; a relocated library (the three generated libs,
       moved out of ${KICAD6_SYMBOL_DIR}) is present but STALE. So for each
       version dir that has a table:
         * no entry for libname   -> append one,
         * entry with a different uri (e.g. a stale ${KICAD6_SYMBOL_DIR} one)
           -> rewrite that single line's uri in place,
         * entry already correct   -> leave untouched.
       Failures here must NEVER block model creation (broad OSError guard).'''
    base = _kicad_config_dir()
    if not os.path.isdir(base):
        return
    lib_line = (
        '  (lib (name "%s")(type "KiCad")(uri "%s")'
        '(options "")(descr "%s"))\n' % (libname, lib_path, descr))
    entry_re = re.compile(
        r'^[ \t]*\(lib \(name "%s"\).*\)[ \t]*$' % re.escape(libname),
        re.MULTILINE)
    for ver in os.listdir(base):
        table = os.path.join(base, ver, 'sym-lib-table')
        if not os.path.isfile(table):
            # KiCad (>= 6) does not write a per-user sym-lib-table until the
            # user manually manages libraries once, so on a fresh KiCad
            # install the file is absent and skipping here would mean eSim's
            # libraries NEVER get registered. Seed an empty table in every
            # real version dir (N.M) instead; KiCad merges it with the global
            # table, so this only ever ADDs the eSim entries.
            if not re.fullmatch(r'\d+\.\d+', ver) or \
                    not os.path.isdir(os.path.join(base, ver)):
                continue
            try:
                _atomic_write(table, '(sym_lib_table\n  (version 7)\n)\n')
            except OSError:
                continue
        try:
            with open(table) as fh:
                content = fh.read()
            m = entry_re.search(content)
            if m:
                if ('(uri "%s")' % lib_path) in m.group(0):
                    continue                    # already correct
                new_content = (content[:m.start()] +
                               lib_line.rstrip('\n') + content[m.end():])
            else:
                idx = content.rstrip().rfind(')')   # final ) closes the table
                if idx == -1:
                    continue
                new_content = content[:idx] + lib_line + content[idx:]
            # Atomic: a crash mid-rewrite of the table leaves the user with a
            # truncated sym-lib-table, and KiCad then errors on EVERY launch.
            _atomic_write(table, new_content)
        except OSError:
            pass
