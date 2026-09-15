"""Snapshot storage backend for eSim's Project Snapshots feature.

A *snapshot* is a point-in-time copy of a project's files, kept so the user
can experiment freely and roll back if a change breaks something. This module
is the on-disk model; it carries no Qt and is unit-testable on its own. The
:class:`~frontEnd.TimeExplorer.TimeExplorer` widget is the view on top of it.

Layout (one folder per snapshot, never loose files)::

    ~/.esim/history/<project_name>/<snapshot_id>/
        manifest.json     # metadata: label, time, kind, project_path, files
        files/<file>      # the captured bytes (subdir avoids name clashes)

``snapshot_id`` is the creation time as ``YYYYmmdd-HHMMSS`` (with a ``-N``
suffix on collision) so the directory sorts chronologically.

Backwards compatibility: the original feature stored loose files named
``<file>(<timestamp>)`` directly under ``<project_name>/``. :meth:`migrate`
groups those by timestamp into proper snapshot folders the first time a
project is read, so no history is lost.
"""

import os
import re
import json
import shutil
from datetime import datetime
from configuration import paths as app_paths


# Legacy filename: ``<file>(I.MM AM/PM dd-mm-yyyy)``.
_LEGACY_RE = re.compile(
    r"^(.+)\((\d{1,2}\.\d{2} [APM]{2} \d{2}-\d{2}-\d{4})\)$")
_LEGACY_TIME_FMT = "%I.%M %p %d-%m-%Y"


def _history_root():
    """Root that holds every project's snapshot history."""
    return app_paths.esim_config_path("history")


class Snapshot(object):
    """A single snapshot, wrapping its ``manifest.json``."""

    def __init__(self, store, project, sid, meta):
        self.store = store
        self.project = project
        self.id = sid
        self.meta = meta or {}

    @property
    def label(self):
        return self.meta.get("label", "Snapshot")

    @property
    def kind(self):
        # full | single | partial | auto (pre-restore safety copy)
        return self.meta.get("kind", "full")

    @property
    def files(self):
        return list(self.meta.get("files", []))

    @property
    def project_path(self):
        return self.meta.get("project_path")

    @property
    def created_iso(self):
        return self.meta.get("created", "")

    @property
    def created_display(self):
        """Human label for the snapshot list, e.g. ``26 Jun 2026, 03:26 AM``."""
        raw = self.created_iso
        try:
            return datetime.fromisoformat(raw).strftime("%d %b %Y, %I:%M %p")
        except (ValueError, TypeError):
            return raw

    @property
    def dir(self):
        return self.store.snapshot_dir(self.project, self.id)

    @property
    def files_dir(self):
        return os.path.join(self.dir, "files")


class SnapshotStore(object):
    """CRUD over the snapshot history tree. Stateless beyond ``root``."""

    def __init__(self, root=None):
        self.root = root or _history_root()

    # ------------------------------------------------------------ paths
    def project_dir(self, project):
        return os.path.join(self.root, project)

    def snapshot_dir(self, project, sid):
        return os.path.join(self.root, project, sid)

    def _manifest_path(self, project, sid):
        return os.path.join(self.snapshot_dir(project, sid), "manifest.json")

    # ------------------------------------------------------------ listing
    def list_projects(self):
        """Project names that actually hold snapshots (migrated first)."""
        if not os.path.isdir(self.root):
            return []
        names = []
        for entry in sorted(os.listdir(self.root)):
            pdir = os.path.join(self.root, entry)
            if not os.path.isdir(pdir):
                continue
            self.migrate(entry)
            has_snapshot = any(
                os.path.isfile(self._manifest_path(entry, sid))
                for sid in os.listdir(pdir)
                if os.path.isdir(os.path.join(pdir, sid)))
            if has_snapshot:
                names.append(entry)
        return names

    def list_snapshots(self, project):
        """Snapshots for one project, newest first."""
        self.migrate(project)
        pdir = self.project_dir(project)
        if not os.path.isdir(pdir):
            return []
        snaps = []
        for sid in os.listdir(pdir):
            mpath = self._manifest_path(project, sid)
            if not os.path.isfile(mpath):
                continue
            try:
                with open(mpath, "r") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                continue
            snaps.append(Snapshot(self, project, sid, meta))
        snaps.sort(key=lambda s: s.created_iso, reverse=True)
        return snaps

    def get_snapshot(self, project, sid):
        mpath = self._manifest_path(project, sid)
        if not os.path.isfile(mpath):
            return None
        try:
            with open(mpath, "r") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            return None
        return Snapshot(self, project, sid, meta)

    # ------------------------------------------------------------ create
    def _unique_id(self, project, when):
        base = when.strftime("%Y%m%d-%H%M%S")
        sid = base
        n = 1
        while os.path.exists(self.snapshot_dir(project, sid)):
            sid = "%s-%d" % (base, n)
            n += 1
        return sid

    def create(self, project, project_path, files=None, label=None,
               kind=None, when=None):
        """Capture ``files`` from ``project_path`` as a new snapshot.

        ``files`` None  -> every top-level file in the project (a *full*
        snapshot). Otherwise a list of basenames (a *single*/*partial* one).
        Returns ``(snapshot_id, captured_count)``.
        """
        if not project_path or not os.path.isdir(project_path):
            raise ValueError("project path does not exist: %r" % project_path)

        if files is None:
            files = sorted(
                f for f in os.listdir(project_path)
                if os.path.isfile(os.path.join(project_path, f)))
            kind = kind or "full"
        else:
            kind = kind or ("single" if len(files) == 1 else "partial")

        when = when or datetime.now()
        sid = self._unique_id(project, when)
        files_dir = os.path.join(self.snapshot_dir(project, sid), "files")
        os.makedirs(files_dir, exist_ok=True)

        captured = []
        for name in files:
            src = os.path.join(project_path, name)
            if not os.path.isfile(src):
                continue
            try:
                shutil.copy2(src, os.path.join(files_dir, name))
                captured.append(name)
            except OSError as exc:
                print("Snapshot: could not copy %s: %s" % (name, exc))

        meta = {
            "id": sid,
            "label": label or self._default_label(kind),
            "kind": kind,
            "created": when.isoformat(timespec="seconds"),
            "project": project,
            "project_path": project_path,
            "files": captured,
        }
        with open(self._manifest_path(project, sid), "w") as fh:
            json.dump(meta, fh, indent=2)
        return sid, len(captured)

    @staticmethod
    def _default_label(kind):
        return {
            "full": "Full backup",
            "single": "File snapshot",
            "partial": "Partial snapshot",
            "auto": "Before restore",
        }.get(kind, "Snapshot")

    # ------------------------------------------------------------ restore
    def restore(self, project, sid, files=None, dest_dir=None, safety=True):
        """Copy snapshot files back into the live project.

        ``files`` None restores the whole snapshot; otherwise the given
        basenames. Unless ``safety`` is False, the current state of the
        affected files is captured first (kind ``auto``) so the restore is
        itself undoable. Snapshots are never consumed by a restore.
        Returns the list of restored basenames.
        """
        snap = self.get_snapshot(project, sid)
        if snap is None:
            raise ValueError("snapshot not found: %s/%s" % (project, sid))

        dest = dest_dir or snap.project_path
        if not dest or not os.path.isdir(dest):
            raise FileNotFoundError(
                "no live project folder to restore into (%r)" % dest)

        targets = snap.files if files is None else list(files)

        if safety:
            present = [f for f in targets
                       if os.path.isfile(os.path.join(dest, f))]
            if present:
                self.create(project, dest, files=present,
                            label="Before restore", kind="auto")

        restored = []
        for name in targets:
            src = os.path.join(snap.files_dir, name)
            if not os.path.isfile(src):
                continue
            try:
                shutil.copy2(src, os.path.join(dest, name))
                restored.append(name)
            except OSError as exc:
                print("Restore: could not write %s: %s" % (name, exc))
        return restored

    # ------------------------------------------------------------ delete
    def delete_snapshot(self, project, sid):
        path = self.snapshot_dir(project, sid)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    def delete_project(self, project):
        path = self.project_dir(project)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------ migration
    def migrate(self, project):
        """One-time upgrade of legacy loose ``<file>(<ts>)`` copies.

        Files sharing a timestamp were written by the same backup, so they are
        regrouped into a single snapshot folder. Safe to call repeatedly; it
        no-ops once nothing loose remains.
        """
        pdir = self.project_dir(project)
        if not os.path.isdir(pdir):
            return
        loose = []
        for entry in os.listdir(pdir):
            full = os.path.join(pdir, entry)
            if not os.path.isfile(full):
                continue
            m = _LEGACY_RE.match(entry)
            if m:
                loose.append((entry, m.group(1), m.group(2)))
        if not loose:
            return

        resolved_path = self.resolve_project_path(project)
        groups = {}
        for entry, base, ts in loose:
            groups.setdefault(ts, []).append((entry, base))

        for ts, items in groups.items():
            try:
                when = datetime.strptime(ts, _LEGACY_TIME_FMT)
            except ValueError:
                when = datetime.now()
            sid = self._unique_id(project, when)
            files_dir = os.path.join(self.snapshot_dir(project, sid), "files")
            os.makedirs(files_dir, exist_ok=True)
            captured = []
            for entry, base in items:
                try:
                    shutil.move(os.path.join(pdir, entry),
                                os.path.join(files_dir, base))
                    captured.append(base)
                except OSError as exc:
                    print("Migrate: could not move %s: %s" % (entry, exc))
            meta = {
                "id": sid,
                "label": "Imported",
                "kind": "full" if len(captured) > 1 else "single",
                "created": when.isoformat(timespec="seconds"),
                "project": project,
                "project_path": resolved_path,
                "files": captured,
            }
            with open(self._manifest_path(project, sid), "w") as fh:
                json.dump(meta, fh, indent=2)

    # ------------------------------------------------------------ path lookup
    def resolve_project_path(self, project):
        """Best-effort live folder for ``project`` (a basename).

        Snapshots store ``project_path`` so any project can be restored, but
        legacy/imported ones lack it. Recover it from the workspace's
        ``.projectExplorer.txt`` registry or the last-opened project record.
        Returns an existing absolute path or None.
        """
        for path in self._known_project_paths():
            if os.path.basename(os.path.normpath(path)) == project:
                if os.path.isdir(path):
                    return path
        return None

    def _known_project_paths(self):
        paths = []
        # last_project.json -> {"ProjectName": "/abs/path", ...}
        try:
            with open(app_paths.esim_config_path("last_project.json")) as fh:
                data = json.load(fh)
            if data.get("ProjectName"):
                paths.append(data["ProjectName"])
        except (OSError, ValueError):
            pass

        # workspace registry: keys are absolute project paths
        try:
            _check, workspace = app_paths.read_workspace()
            reg = os.path.join(workspace, ".projectExplorer.txt")
            with open(reg) as fh:
                paths.extend(json.load(fh).keys())
        except (OSError, ValueError, IndexError):
            pass
        return paths
