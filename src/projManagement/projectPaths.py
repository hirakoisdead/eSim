# =========================================================================
#          FILE: projectPaths.py
#
#   DESCRIPTION: Single source of truth for an eSim project's identity.
#
#                eSim historically derived a project's "stem" (the basename
#                shared by <stem>.proj/.cir/.sch/.cir.out/.sub/... ) from the
#                *folder name*. That breaks whenever the folder is renamed or
#                differs from the files inside it (e.g. IP-Library circuits
#                shipped in a folder named "eSim_Project_Files" containing
#                MACProject.*). The real, unique anchor is the project file
#                itself: exactly one ``*.proj`` per project folder (subcircuits
#                use ``*.sub``). These helpers resolve the stem from that anchor
#                instead of the folder name, so the folder may be named anything.
#
#                Dependency-free (os, glob) on purpose: imported from
#                Validation, Appconfig and the kicadtoNgspice tabs without
#                pulling in Qt.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================

import os
import sys
import glob
import json
import shutil
import hashlib


def canonical_path(path):
    """
    Return the canonical identity key for a project folder.

    Two path strings that point at the *same* folder on disk collapse to the
    same key, so a project can be registered/opened exactly once. This is the
    single source of truth for "is this the same project?" -- compare canonical
    keys, never raw strings or basenames.

    Normalisation applied:
        - expand ``~`` and ``$ENV`` references
        - make absolute (against the current working directory)
        - resolve symlinks and collapse ``..`` / ``.`` segments (realpath)
        - strip trailing separators
        - case-fold ONLY on case-insensitive filesystems (Windows, macOS);
          never on Linux, where ``Foo`` and ``foo`` are distinct directories.

    The folded/resolved result is meant for *identity comparison and dict
    keys*. Keep the original string for anything user-facing (use the project
    stem or basename for display labels).

    @params
        :path   => any path string (raw, relative, symlinked, ...) or None

    @return
        the canonical key string, or '' when path is falsy
    """
    if not path:
        return ''
    p = os.path.expanduser(os.path.expandvars(str(path)))
    p = os.path.realpath(os.path.abspath(p))
    p = p.rstrip(os.sep) or os.sep
    if os.name == 'nt':
        p = os.path.normcase(p)
    elif sys.platform == 'darwin':
        p = p.lower()
    return p


def same_project(a, b):
    """True when paths ``a`` and ``b`` resolve to the same project folder."""
    return canonical_path(a) == canonical_path(b)


def find_anchors(directory, ext='proj'):
    """
    Return the sorted list of anchor files (``*.<ext>``) directly inside
    ``directory``. ``ext`` is given without a leading dot ('proj', 'sub').

    @params
        :directory  => the folder to scan
        :ext        => anchor extension without dot (default 'proj')

    @return
        sorted list of absolute/!relative paths (as given by glob)
    """
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(glob.glob(os.path.join(directory, '*.' + ext)))


def stem_from_file(path):
    """
    Return the stem (basename without its final extension) of a concrete
    file path. Use this in code that is already handed the project's ``.cir``
    (or ``.sch``/``.sub``) file -- the stem is right there in the filename and
    needs no folder lookup.

    Note: strips a single extension, so pass a ``.cir`` (not ``.cir.out``).

    @params
        :path   => a file path such as '/ws/weird_folder/MACProject.cir'

    @return
        the stem, e.g. 'MACProject'
    """
    return os.path.splitext(os.path.basename(str(path)))[0]


def previous_values_path(kicad_file):
    """
    Return the on-disk path of a project's ``*_Previous_Values.xml`` cache.

    The kicadtoNgspice converter remembers the model parameters and library/
    subcircuit paths a user last chose, so re-converting the same project does
    not force them to re-enter everything. Historically this cache lived
    *inside the project folder* (``<projdir>/<stem>_Previous_Values.xml``),
    which meant it travelled with the project whenever it was zipped or shared.
    That leaked one author's *local* library paths into another user's
    converter fields: they would see pre-filled paths that don't exist on their
    machine, or -- worse -- happen to exist and silently point at the wrong
    file. These remembered values are a per-user, per-machine convenience, not
    project data, so they belong under the user's ``~/.esim`` area (where eSim
    already keeps ``workspace.txt``, ``config.ini``, ``history/`` ...), never
    in the shared project.

    The cache is keyed by the project's *canonical path* plus its stem, so two
    projects that happen to share a stem (e.g. ``MACProject``) in different
    folders never collide, and the same project always resolves to the same
    cache file regardless of how its path was spelled (symlinks, ``..``,
    trailing separators -- see :func:`canonical_path`).

    Lazy, non-destructive migration: the first time a project's new-location
    cache is requested and does not yet exist, any legacy in-project
    ``<stem>_Previous_Values.xml`` is copied across so users keep their
    remembered values after upgrading. The legacy file is left untouched.

    @params
        :kicad_file => the project's ``.cir`` (or ``.sch`` / ``.cir.out``) path

    @return
        absolute path to the cache file under ``~/.esim/prevvalues/``. The file
        itself may not exist yet; callers already treat a missing or
        parse-failing file as "no previous values".
    """
    proj_dir = os.path.dirname(os.path.abspath(str(kicad_file)))
    stem = stem_from_file(kicad_file)
    key = hashlib.sha1(
        (canonical_path(proj_dir) + os.sep + stem).encode('utf-8')
    ).hexdigest()[:16]
    base = os.path.join(os.path.expanduser('~'), '.esim', 'prevvalues')
    os.makedirs(base, exist_ok=True)
    new_path = os.path.join(base, key + '_Previous_Values.xml')

    # Lazy, non-destructive migration from the legacy in-project location.
    if not os.path.exists(new_path):
        legacy = os.path.join(proj_dir, stem + '_Previous_Values.xml')
        if os.path.isfile(legacy):
            try:
                shutil.copy2(legacy, new_path)
            except (IOError, OSError):
                pass
    return new_path


def resolve_stem(directory, ext='proj'):
    """
    Resolve the canonical stem of a project/subcircuit folder from its anchor
    file, independent of the folder's own name.

    @params
        :directory  => the project (or subcircuit) folder
        :ext        => anchor extension without dot ('proj' or 'sub')

    @return
        (stem, status) where status is one of:
            'ok'        => exactly one anchor; stem taken from it
            'ambiguous' => more than one anchor. stem is the one whose name
                           matches the folder name if present, else None
                           (caller should prompt the user to choose)
            'missing'   => no anchor found; stem falls back to the folder
                           basename so legacy/malformed projects still limp
                           along instead of hard-failing
    """
    anchors = find_anchors(directory, ext)
    folder = os.path.basename(os.path.normpath(str(directory)))

    if len(anchors) == 1:
        return stem_from_file(anchors[0]), 'ok'

    if len(anchors) > 1:
        for anchor in anchors:
            if stem_from_file(anchor) == folder:
                return folder, 'ambiguous'
        return None, 'ambiguous'

    return folder, 'missing'


def main_schematic(proj_dir, stem):
    """
    Resolve the project's main schematic file.

    Prefers the ``schematicFile`` token recorded inside the ``.proj`` (this is
    the authoritative pointer eSim already writes on project creation), then
    falls back to ``<stem>.kicad_sch`` (KiCad 6+) and finally ``<stem>.sch``
    (KiCad 4). Returns an existing path, or the best-guess ``<stem>.kicad_sch``
    path if nothing exists yet (caller decides how to treat a missing file).

    @params
        :proj_dir   => the project folder
        :stem        => the resolved project stem

    @return
        path to the main schematic (may not exist if the project is incomplete)
    """
    # 1. Authoritative pointer inside the .proj, if readable.
    for proj in find_anchors(proj_dir, 'proj'):
        try:
            with open(proj, 'r') as fh:
                for line in fh:
                    words = line.split()
                    if len(words) >= 2 and words[0] == 'schematicFile':
                        candidate = os.path.join(proj_dir, words[1])
                        # Legacy example projects pin a KiCad-4 ``.sch`` here.
                        # KiCad 6+ migrates by writing a sibling ``.kicad_sch``
                        # and leaving the old ``.sch`` in place; the ``.proj``
                        # is never repointed. If that migrated file exists,
                        # it is authoritative -- otherwise every open reopens
                        # the legacy file and re-triggers the rescue/migrate
                        # prompt, orphaning the user's saved schematic.
                        if candidate.endswith('.sch'):
                            migrated = candidate[:-len('.sch')] + '.kicad_sch'
                            if os.path.exists(migrated):
                                return migrated
                        if os.path.exists(candidate):
                            return candidate
        except (IOError, OSError):
            pass
        break  # only the first/only .proj is the anchor

    # 2 & 3. Convention-based fallbacks.
    kicad6 = os.path.join(proj_dir, str(stem) + '.kicad_sch')
    kicad4 = os.path.join(proj_dir, str(stem) + '.sch')
    if os.path.exists(kicad6):
        return kicad6
    if os.path.exists(kicad4):
        return kicad4
    return kicad6


def save_project_explorer(path, data):
    """Atomically persist the project-explorer registry (``data`` dict).

    The registry is the JSON list of every known project. A plain
    ``open(path,'w') + json.dump`` truncates the file the instant it starts;
    a crash mid-write leaves a truncated file that Appconfig then reads as
    ``{}`` -- the user's entire project tree silently vanishes. Write to a temp
    file in the same directory and ``os.replace`` it in (atomic on POSIX and
    Windows), so a reader always sees either the old or the new complete file.
    """
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    # Fixed temp name, ONE create attempt -- never tempfile.mkstemp here. On
    # Windows a directory this process may not write (e.g. admin-owned) makes
    # mkstemp retry its full TMP_MAX=10000 candidate names because
    # os.access(dir, W_OK) reports writable; called from ProjectExplorer on
    # the GUI thread that retry storm is a minutes-long "not responding"
    # white screen. A single open() surfaces PermissionError immediately and
    # the caller degrades gracefully. The registry is per-user, so a name
    # collision means an older attempt by the same app; overwriting it is fine.
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
