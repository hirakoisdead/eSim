# =========================================================================
#             FILE: model_teardown.py
#
#      DESCRIPTION: Pure, dependency-free helpers for removing generated block
#                   models (NgVeri / d_cosim / NGHDL) from the shared ngspice
#                   install. Kept out of NgVeri.py (which imports Qt + hdlparse
#                   via Maker) so the teardown core -- the part that does the
#                   irreversible file surgery -- is unit-testable in isolation
#                   with nothing but stdlib.
#
#            NOTES: stdlib only (os). Do NOT add Qt / config / hdlparse imports
#                   here; that is the whole point of the split.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

import os


def _safe_model_subdir(base, name):
    """Resolve ``<base>/<name>`` for deletion, but ONLY when it is provably a
    single-component subdirectory strictly inside ``base``.

    Returns the absolute path, or ``None`` when ``name`` is empty/blank, holds a
    path separator, is ``.``/``..``, or resolves to ``base`` itself or outside
    it. Callers MUST treat ``None`` as "do not delete anything".

    This is the guard that stops a blank model name from collapsing
    ``os.path.join(base, "")`` to ``"base/"`` and ``shutil.rmtree`` wiping the
    whole models directory.
    """
    if not name or not str(name).strip():
        return None
    name = str(name).strip()
    if (os.sep in name or (os.altsep and os.altsep in name)
            or name in ('.', '..')):
        return None
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, name))
    if target == base_abs:
        return None
    try:
        if os.path.commonpath([base_abs, target]) != base_abs:
            return None
    except ValueError:
        # Different drives (Windows) -> not a subpath.
        return None
    return target


def _atomic_write_text(path, data):
    """Replace ``path`` with ``data`` atomically (temp file + os.replace).

    Delegates to kicad_symlib._atomic_write so there is ONE implementation of
    this. kicad_symlib is stdlib-only, so importing it does not break this
    module's "no Qt/config/hdlparse" contract, and the dual import handles both
    layouts exactly like _nghdl_sym_path below: packaged (maker.*) and the flat
    vendored NGHDL tarball.

    modpath.lst is tiny but load-bearing: a crash / full disk part-way through
    a rewrite leaves a truncated list, and cmpp then aborts the WHOLE
    code-model build with an error that points nowhere near here."""
    try:
        from .kicad_symlib import _atomic_write
    except ImportError:                 # flat vendored layout (NGHDL package)
        from kicad_symlib import _atomic_write
    _atomic_write(path, data)


def _ensure_modpath(path):
    """Make sure the modpath.lst at ``path`` exists, together with its parent
    directory, creating an empty list when it does not. Returns ``path``.

    The digital-model root is built lazily -- on a fresh tree it appears only
    once the remove dialog has listed models, or once a build has run -- so
    every reader and appender has to be able to conjure it. Without this, the
    first-ever convert on a fresh install died on a bare FileNotFoundError that
    surfaced as a generic "Error in Ngspice code model generation"."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # 'a' creates the file when absent and is a no-op when it already exists --
    # unlike 'w', which would truncate a list another process just wrote.
    with open(path, 'a'):
        pass
    return path


def _strip_modpath_line(path, name):
    """Remove every line equal to ``name`` from the modpath.lst at ``path``
    (idempotent). Returns True if a line was dropped. Safe when the file is
    absent or ``name`` is blank (both -> no change)."""
    name = (name or "").strip()
    if not name:
        return False
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return False
    kept = [ln for ln in lines if ln.strip() != name]
    if len(kept) == len(lines):
        return False
    _atomic_write_text(path, ''.join(kept))
    return True


def _append_modpath_line(path, name):
    """Append ``name`` to the modpath.lst at ``path`` unless it is already
    listed (idempotent). Returns True only when a line was written; ``name``
    blank -> no change.

    Guarantees the new entry starts on its own line. A hand-edited file whose
    last line lacks a trailing newline would otherwise be glued to the new name
    ("oldnamenewname") -- a single ghost entry like that makes cmpp abort the
    WHOLE ghdl.cm build, the exact failure _prune_modpath exists to clean up."""
    name = (name or "").strip()
    if not name:
        return False
    try:
        with open(path) as f:
            content = f.read()
    except OSError:
        content = ""
    if name in (ln.strip() for ln in content.splitlines()):
        return False
    prefix = "" if (not content or content.endswith("\n")) else "\n"
    with open(path, 'a') as f:
        f.write(prefix + name + "\n")
    return True


def _prune_modpath(path, base, marker="ifspec.ifs"):
    """Rewrite the modpath.lst at ``path`` keeping only entries whose build dir
    ``<base>/<name>/<marker>`` still exists, de-duplicated. Returns the dropped
    (ghost / duplicate) names. A single orphaned entry makes cmpp abort the
    WHOLE code-model build, so this runs before every .cm rebuild."""
    try:
        with open(path) as f:
            entries = [ln.strip() for ln in f]
    except OSError:
        return []
    kept, dropped, seen = [], [], set()
    for name in entries:
        if not name:
            continue
        if name in seen:
            dropped.append(name)            # duplicate line
            continue
        if os.path.isfile(os.path.join(base, name, marker)):
            kept.append(name)
            seen.add(name)
        else:
            dropped.append(name)            # ghost: build dir / marker gone
    if dropped:
        _atomic_write_text(path, ''.join(name + "\n" for name in kept))
    return dropped


def _dir_has_name(directory, filename):
    """True if ``directory`` holds an entry named EXACTLY ``filename``.

    Deliberately not ``os.path.isfile``: on Windows that answers True for
    ``counter.xml`` when asked about ``Counter.xml``, so a backend probe keyed
    on a param XML would claim ownership of a name whose XML belongs to a
    differently-cased model -- and then the wrong dismantler runs. Listing the
    directory gives the same answer on Windows and Linux."""
    try:
        return filename in os.listdir(directory)
    except OSError:
        return False


def _actual_subdir_name(base, name):
    """The entry in ``base`` that IS ``name`` on this filesystem: an exact
    match if there is one, otherwise a unique case-insensitive match (which on
    Windows is the same directory the OS would open). ``None`` when nothing
    matches or the fold is ambiguous.

    Teardown deletes by the name the *dialog* showed, which may be a modpath
    line or a symbol name rather than a directory entry. rmtree on the wrong
    case is a silent no-op on Linux -- the model comes back on the next
    listing, and it looks like remove is broken."""
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    if name in entries:
        return name
    low = str(name).strip().lower()
    folded = [e for e in entries if e.lower() == low]
    return folded[0] if len(folded) == 1 else None


def _resolve_backend(xml_loc, name, cosim_sym=None, nghdl_sym=None):
    """Resolve which backend owns model ``name`` from the on-disk modelParamXML
    layout -- the single source of truth that survives restarts and backend
    switches::

        NgVeriCosim/<name>.xml -> "cosim"   (Icarus d_cosim)
        Nghdl/<name>.xml       -> "nghdl"   (GHDL/NGHDL)
        otherwise              -> "ngveri"  (legacy Verilator)

    cosim wins over nghdl wins over ngveri if xml files ever coexist (they
    should not -- one name, one backend -- but a deterministic precedence keeps
    teardown from running the wrong dismantler and silently leaving a model).

    The XML probe lists the directory rather than calling ``os.path.isfile``
    (see _dir_has_name): Windows' case-insensitive filesystem otherwise hands
    ownership of "Counter" to the model whose XML is "counter.xml", so the
    dialog badges a row NgVeri and the d_cosim dismantler runs on it.

    ``cosim_sym``/``nghdl_sym`` are optional .kicad_sym paths consulted with the
    SAME precedence when no param XML answers. A model built by an older eSim
    (or half-removed by one) can own a KiCad symbol with no XML beside it; going
    by the XML alone then calls such a leftover "ngveri" and the wrong
    dismantler runs, leaving the symbol in KiCad forever -- which is exactly how
    the orphans in eSim_Ngveri / eSim_NgVeriCosim became unremovable."""
    if xml_loc:
        if _dir_has_name(os.path.join(xml_loc, 'NgVeriCosim'),
                         name + '.xml'):
            return "cosim"
        if _dir_has_name(os.path.join(xml_loc, 'Nghdl'), name + '.xml'):
            return "nghdl"
    if cosim_sym and name in _lib_part_names(cosim_sym):
        return "cosim"
    if nghdl_sym and name in _lib_part_names(nghdl_sym):
        return "nghdl"
    return "ngveri"


# =========================================================================
#  Discovery: what is ACTUALLY on this machine
#
#  modpath.lst was long treated as the list of installed models, so the remove
#  dialogs only ever offered what the running version had registered there. A
#  model built by an older eSim -- or one whose teardown was interrupted -- can
#  survive as any subset of {modpath line, param XML, KiCad symbol, source
#  build dir, release build dir}, and every one of those pieces the dialog
#  cannot name is a piece the user cannot delete from the GUI.
#
#  So discovery is a UNION over all five traces: if anything of a model is left
#  anywhere, it gets listed and can be removed. The teardown helpers are each
#  idempotent and absence-tolerant, so tearing down a model that owns only one
#  trace is safe and cleans exactly that trace.
# =========================================================================

# Files that mark a directory as a generated model build dir rather than some
# unrelated folder that happens to sit in the icm tree. Source dirs hold the
# cmpp inputs (ifspec.ifs / cfunc.mod); release dirs hold their compiled
# counterparts (ifspec.c / cfunc.c and the .o files next to them).
_MODEL_DIR_MARKERS = ('ifspec.ifs', 'cfunc.mod', 'ifspec.c', 'cfunc.c',
                      'sim_main.cpp', 'connection_info.txt')


def _kicad_symlib():
    """The kicad_symlib module for whichever layout this copy is packaged in
    (``maker.kicad_symlib`` in eSim, flat ``kicad_symlib`` in the NGHDL
    tarball). stdlib-only, so this keeps the no-Qt contract."""
    try:
        from . import kicad_symlib
    except ImportError:                 # flat vendored layout (NGHDL package)
        import kicad_symlib
    return kicad_symlib


def _lib_part_names(sym_path):
    """Model names that still own a symbol block in the .kicad_sym at
    ``sym_path``. Absent/unreadable/corrupt file -> empty list (never raises:
    this feeds a listing, and a listing must not be what breaks)."""
    if not sym_path:
        return []
    try:
        return list(_kicad_symlib()._read_parts(sym_path))
    except OSError:
        return []


def _xml_model_names(xml_loc, subdir):
    """Model names with a param XML under ``<xml_loc>/<subdir>``."""
    if not xml_loc:
        return []
    try:
        return sorted(n[:-4] for n in os.listdir(os.path.join(xml_loc, subdir))
                      if n.endswith('.xml'))
    except OSError:
        return []


def _modpath_names(path):
    """Non-blank entries of the modpath.lst at ``path`` (absent -> empty)."""
    try:
        with open(path) as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def _build_dir_model_names(base):
    """Immediate subdirectories of ``base`` that look like a generated model
    build dir: they hold one of the cmpp inputs/outputs, or the d_cosim vvp
    (which is named exactly like its directory). The marker test keeps shared
    scratch dirs in the same icm tree from being offered as removable models."""
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return []
    names = []
    for name in entries:
        model_dir = os.path.join(base, name)
        if not os.path.isdir(model_dir):
            continue
        marked = any(os.path.exists(os.path.join(model_dir, m))
                     for m in _MODEL_DIR_MARKERS)
        if marked or os.path.isfile(os.path.join(model_dir, name)):
            names.append(name)
    return names


def discover_ngveri_models(digital_home, release_dir, xml_loc,
                           ngveri_sym=None, cosim_sym=None, cosim_home=None):
    """Every Verilog-side model with ANY trace left on disk, as
    ``{name: "NgVeri" | "d_cosim"}`` (the RemoveItemsDialog badge).

    ``cosim_home`` is the d_cosim build tree (<DIGITAL_MODEL>/NgVeriCosim), a
    SIBLING of ``digital_home``. Scanning it separately is what lets a failed
    or interrupted d_cosim build -- a directory with sources but no vvp -- be
    listed and removed at all; it also means a build dir can only ever be
    attributed to the backend that owns the tree it sits in.

    d_cosim evidence is applied last so it wins the badge for a name that shows
    up under both, matching _resolve_backend's precedence -- the badge and the
    dismantler must never disagree."""
    badges = {}
    for name in _modpath_names(os.path.join(digital_home, 'modpath.lst')):
        badges[name] = "NgVeri"
    for name in _build_dir_model_names(digital_home):
        badges[name] = "NgVeri"
    if release_dir:
        for name in _build_dir_model_names(
                os.path.join(release_dir, 'src', 'xspice', 'icm', 'Ngveri')):
            badges[name] = "NgVeri"
    for name in _xml_model_names(xml_loc, 'Ngveri'):
        badges[name] = "NgVeri"
    for name in _lib_part_names(ngveri_sym):
        badges[name] = "NgVeri"
    # --- d_cosim last (wins the badge) ---
    if cosim_home:
        for name in _build_dir_model_names(cosim_home):
            badges[name] = "d_cosim"
    for name in _xml_model_names(xml_loc, 'NgVeriCosim'):
        badges[name] = "d_cosim"
    for name in _lib_part_names(cosim_sym):
        badges[name] = "d_cosim"
    return badges


def discover_nghdl_models(ghdl_home, release_dir, xml_loc, nghdl_sym=None):
    """Every NGHDL (GHDL) model with any trace left on disk, sorted.

    Same union as discover_ngveri_models against the ghdl/ tree: modpath line,
    source build dir, release build dir, Nghdl/<name>.xml and eSim_Nghdl
    symbol."""
    names = set(_modpath_names(os.path.join(ghdl_home, 'modpath.lst')))
    names.update(_build_dir_model_names(ghdl_home))
    if release_dir:
        names.update(_build_dir_model_names(
            os.path.join(release_dir, 'src', 'xspice', 'icm', 'ghdl')))
    names.update(_xml_model_names(xml_loc, 'Nghdl'))
    names.update(_lib_part_names(nghdl_sym))
    return sorted(names, key=lambda s: s.lower())


def _nghdl_sym_path(src_home):
    """Absolute path of the shared eSim_Nghdl.kicad_sym, in eSim's generated
    symbol-lib dir (~/.esim/kicad_symbols) -- mirroring where createkicad now
    puts eSim_Ngveri. Lazily migrates a legacy /usr/share (or old Windows)
    copy in on first use so existing users keep their accumulated models.

    kicad_symlib is stdlib-only, so importing it does not break this module's
    "no Qt/config/hdlparse" contract. The dual import handles both layouts:
    packaged (maker.*) and the flat vendored NGHDL tarball."""
    try:
        from .kicad_symlib import generated_symlib_path
    except ImportError:                 # flat vendored layout (NGHDL package)
        from kicad_symlib import generated_symlib_path
    legacy = []
    if os.name == 'nt':
        inst_dir = (src_home or "").replace('\\eSim', '')
        legacy.append(inst_dir + '/KiCad/share/kicad/symbols')
    return generated_symlib_path("eSim_Nghdl", legacy_dirs=legacy)
