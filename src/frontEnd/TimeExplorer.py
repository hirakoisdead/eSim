"""Project Snapshots panel — the view over :mod:`frontEnd.SnapshotStore`.

A snapshot is a point-in-time copy of a project's files so the user can
experiment and roll back. The panel is a *global manager*: every project that
has history shows as a top-level node, each snapshot under it, and each file
under the snapshot (with a checkbox for partial restore).

  Project ▸ Snapshot ▸ file ☐

Scope rules that keep behaviour unambiguous:
  * **Quick Backup** always targets the *active* project (named in the header),
    so there is never a question of which project gets backed up.
  * **Restore** writes into the project folder recorded in the snapshot, so any
    project shown here can be rolled back, not only the active one.
  * Restore never consumes a snapshot, and it takes an automatic
    *Before restore* safety snapshot first, so a restore is itself undoable.

The look follows the Aurora design: header (title + icon refresh), an
alternating-row tree, and a primary/secondary/danger action bar.
"""

import os

from PyQt6 import QtCore, QtWidgets

from configuration import Dialogs
from configuration.Appconfig import Appconfig
from frontEnd.SnapshotStore import SnapshotStore


# Roles stashed on each tree item so the action bar knows what is selected.
_ROLE = QtCore.Qt.ItemDataRole.UserRole
_KIND_LABEL = {
    "full": "Full",
    "single": "File",
    "partial": "Partial",
    "auto": "Auto",
    "imported": "Imported",
}


class TimeExplorer(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(TimeExplorer, self).__init__(parent)
        self.store = SnapshotStore()
        # Active project basename, kept for back-compat with callers that read
        # ``current_project`` (Application.load_snapshots passes a basename).
        self.current_project = {"ProjectName": None}

        # ---- Header bar (title + icon-only refresh) ----
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(8, 8, 8, 0)
        header.setSpacing(6)

        self.title_label = QtWidgets.QLabel('Project Snapshots')
        self.title_label.setProperty('cssClass', 'title')
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.refresh_btn = QtWidgets.QPushButton()
        try:
            from frontEnd.icon_paths import refresh_icon
            self.refresh_btn.setIcon(refresh_icon())
        except Exception:
            self.refresh_btn.setText('Refresh')
        self.refresh_btn.setProperty('cssClass', 'icon')
        self.refresh_btn.setToolTip('Refresh snapshot list')
        self.refresh_btn.clicked.connect(self.reload)
        header.addWidget(self.refresh_btn)

        # Muted caption: removes the "which project does Quick Backup hit?"
        # ambiguity by naming the target up front.
        self.scope_label = QtWidgets.QLabel()
        self.scope_label.setProperty('cssClass', 'muted')
        self.scope_label.setWordWrap(True)

        # ---- Tree: project > snapshot > file ----
        self.treewidget = QtWidgets.QTreeWidget()
        self.treewidget.setHeaderLabels(['Snapshot', 'Type', 'Created'])
        self.treewidget.setColumnWidth(0, 220)
        self.treewidget.setColumnWidth(1, 70)
        self.treewidget.setAlternatingRowColors(True)
        self.treewidget.setUniformRowHeights(True)
        self.treewidget.itemDoubleClicked.connect(self._on_double_click)
        self.treewidget.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.treewidget.customContextMenuRequested.connect(self._open_menu)

        # ---- Action bar ----
        actions = QtWidgets.QHBoxLayout()
        actions.setContentsMargins(8, 8, 8, 8)
        actions.setSpacing(6)

        self.backup_btn = QtWidgets.QPushButton('Quick Backup')
        # Aurora's only filled-primary class; pairs with restore=secondary /
        # delete=danger.
        self.backup_btn.setProperty('cssClass', 'verifierPrimary')
        self.backup_btn.setToolTip('Back up every file in the active project')
        self.backup_btn.clicked.connect(self.quick_backup)

        # Kept under the historical attribute names so any external reference
        # keeps working.
        self.restore = QtWidgets.QPushButton('Restore')
        self.restore.setProperty('cssClass', 'secondary')
        self.restore.setToolTip(
            'Restore the selected snapshot, or only its ticked files')
        self.restore.clicked.connect(self.restore_snapshots)

        self.clear = QtWidgets.QPushButton('Delete')
        self.clear.setProperty('cssClass', 'danger')
        self.clear.setToolTip('Delete the selected snapshot or project history')
        self.clear.clicked.connect(self.clear_snapshots)

        actions.addWidget(self.backup_btn)
        actions.addStretch(1)
        actions.addWidget(self.restore)
        actions.addWidget(self.clear)

        # ---- Compose ----
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.scope_label)
        layout.addWidget(self.treewidget)
        layout.addLayout(actions)

        # Floor that keeps button labels from clipping when the panel/dock is
        # dragged small.
        from frontEnd.theme_utils import zoom_px
        self.setMinimumWidth(zoom_px(300))
        self.setMinimumHeight(zoom_px(360))

    def changeEvent(self, event):
        """Re-tint the refresh icon on a live light/dark toggle.

        refresh_icon() bakes the theme's text color into the SVG once, at
        construction (icon_paths._svg_icon), and nothing re-tints it on a
        PaletteChange — so after a toggle the glyph keeps the old theme's color
        (dark on dark / light on light) and effectively vanishes. This mirrors
        the ProjectExplorer.changeEvent icon-refresh convention.
        """
        super().changeEvent(event)
        # Deferred by a tick: rasterising the SVG inside the handler re-enters
        # the polish that delivered the event (theme_utils.defer_restyle).
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            from frontEnd.theme_utils import defer_restyle
            defer_restyle(self, self._retint_refresh_icon)

    def _retint_refresh_icon(self):
        """Deferred body of the PaletteChange branch of changeEvent."""
        try:
            from frontEnd.icon_paths import refresh_icon
            self.refresh_btn.setIcon(refresh_icon())
        except Exception:
            pass

    # ------------------------------------------------------------ helpers
    def _active(self):
        """(name, path) of the live project, or (None, None)."""
        try:
            path = Appconfig().current_project.get("ProjectName")
        except Exception:
            path = None
        if path and os.path.isdir(path):
            return os.path.basename(os.path.normpath(path)), path
        return None, None

    def _item_info(self, item):
        return item.data(0, _ROLE) if item is not None else None

    def _iter_items(self):
        it = QtWidgets.QTreeWidgetItemIterator(self.treewidget)
        while it.value():
            yield it.value()
            it += 1

    def _checked_files(self):
        """Ticked file items grouped by (project, sid) -> [basenames]."""
        groups = {}
        for item in self._iter_items():
            info = self._item_info(item)
            if not info or info.get("kind") != "file":
                continue
            if item.checkState(0) == QtCore.Qt.CheckState.Checked:
                key = (info["project"], info["sid"])
                groups.setdefault(key, []).append(info["name"])
        return groups

    # ------------------------------------------------------------ rendering
    def reload(self):
        """Rebuild the whole tree from disk."""
        self.treewidget.clear()
        active_name, active_path = self._active()

        if active_name:
            self.scope_label.setText(
                "Quick Backup will back up the active project: "
                "“%s”." % active_name)
        else:
            self.scope_label.setText(
                "No active project — open one to use Quick Backup.")

        for project in self.store.list_projects():
            proj_item = QtWidgets.QTreeWidgetItem([project, "", ""])
            proj_item.setData(0, _ROLE, {"kind": "project", "project": project})
            if project == active_name:
                font = proj_item.font(0)
                font.setBold(True)
                proj_item.setFont(0, font)
                proj_item.setText(0, "%s  • active" % project)
            self.treewidget.addTopLevelItem(proj_item)

            for snap in self.store.list_snapshots(project):
                snap_item = QtWidgets.QTreeWidgetItem([
                    snap.label,
                    _KIND_LABEL.get(snap.kind, snap.kind.title()),
                    snap.created_display,
                ])
                snap_item.setData(0, _ROLE, {
                    "kind": "snapshot", "project": project, "sid": snap.id})
                snap_item.setToolTip(
                    0, "%d file(s)" % len(snap.files))
                proj_item.addChild(snap_item)

                for name in snap.files:
                    file_item = QtWidgets.QTreeWidgetItem([name, "", ""])
                    file_item.setFlags(
                        file_item.flags()
                        | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    file_item.setCheckState(
                        0, QtCore.Qt.CheckState.Unchecked)
                    file_item.setData(0, _ROLE, {
                        "kind": "file", "project": project,
                        "sid": snap.id, "name": name})
                    snap_item.addChild(file_item)

            if project == active_name:
                proj_item.setExpanded(True)

    # Back-compat shims --------------------------------------------------
    def load_snapshots(self, project_name):
        """Set the active project (by basename) and rebuild the tree."""
        self.current_project["ProjectName"] = project_name
        self.reload()

    def load_last_snapshots(self):
        """Startup hook: render whatever history exists on disk."""
        self.reload()

    def add_snapshot(self, file_name=None, timestamp=None):
        """Legacy entry point; snapshots now self-register, so just refresh."""
        self.reload()

    # ------------------------------------------------------------ commands
    def quick_backup(self):
        """Snapshot every file in the *active* project (unambiguous target)."""
        name, path = self._active()
        if not name:
            Dialogs.warning(
                self, "No Active Project",
                "Open a project first to back it up.")
            return
        try:
            sid, count = self.store.create(name, path, label="Quick Backup")
        except Exception as exc:
            Dialogs.warning(self, "Backup Failed", str(exc))
            return
        self.reload()
        Dialogs.information(
            self, "Quick Backup",
            "%d file(s) backed up for “%s”." % (count, name))

    def restore_snapshots(self):
        """Restore the whole selected snapshot, or only its ticked files."""
        checked = self._checked_files()
        if len(checked) > 1:
            Dialogs.warning(
                self, "Multiple Snapshots",
                "Tick files from a single snapshot at a time.")
            return

        if checked:
            (project, sid), files = next(iter(checked.items()))
            summary = "%d ticked file(s)" % len(files)
        else:
            info = self._item_info(self.treewidget.currentItem())
            if not info or info["kind"] == "project":
                Dialogs.warning(
                    self, "Nothing Selected",
                    "Select a snapshot, or tick files to restore.")
                return
            project, sid = info["project"], info["sid"]
            if info["kind"] == "file":
                files = [info["name"]]
                summary = info["name"]
            else:
                files = None  # whole snapshot
                summary = "the entire snapshot"

        if Dialogs.question(
                self, "Confirm Restore",
                "Restore %s into “%s”?\n\n"
                "Your current files are saved as a “Before restore” "
                "snapshot first." % (summary, project)) != Dialogs.Button.Yes:
            return

        try:
            restored = self.store.restore(project, sid, files=files)
        except FileNotFoundError:
            Dialogs.warning(
                self, "Project Folder Missing",
                "Could not find this project's folder on disk.\n"
                "Open the project once so eSim knows where to restore it.")
            return
        except Exception as exc:
            Dialogs.warning(self, "Restore Failed", str(exc))
            return

        self.reload()
        Dialogs.information(
            self, "Restored", "%d file(s) restored." % len(restored))

    def clear_snapshots(self):
        """Delete the selected snapshot, or a project's whole history."""
        info = self._item_info(self.treewidget.currentItem())
        if not info:
            Dialogs.warning(
                self, "Nothing Selected",
                "Select a snapshot or a project to delete.")
            return

        if info["kind"] == "project":
            project = info["project"]
            if Dialogs.question(
                    self, "Delete All Snapshots",
                    "Delete ALL snapshots for “%s”?\n"
                    "This cannot be undone." % project) != Dialogs.Button.Yes:
                return
            self.store.delete_project(project)
        else:
            project, sid = info["project"], info["sid"]
            if Dialogs.question(
                    self, "Delete Snapshot",
                    "Delete this snapshot?\nThis cannot be undone."
                    ) != Dialogs.Button.Yes:
                return
            self.store.delete_snapshot(project, sid)

        self.reload()

    # ------------------------------------------------------------ interaction
    def _on_double_click(self, item, _column):
        info = self._item_info(item)
        if info and info["kind"] in ("snapshot", "file"):
            self.restore_snapshots()

    def _open_menu(self, position):
        item = self.treewidget.itemAt(position)
        info = self._item_info(item)
        if not info:
            return
        # Align selection with the clicked node so the action handlers (which
        # read currentItem) act on what was right-clicked.
        self.treewidget.setCurrentItem(item)
        menu = QtWidgets.QMenu()

        if info["kind"] == "project":
            active_name, _ = self._active()
            backup = menu.addAction("Back up now")
            backup.setEnabled(info["project"] == active_name)
            if info["project"] != active_name:
                backup.setToolTip("Open this project to back it up")
            backup.triggered.connect(self.quick_backup)
            menu.addSeparator()
            menu.addAction(
                "Delete all snapshots", self.clear_snapshots)
        elif info["kind"] == "snapshot":
            menu.addAction("Restore this snapshot", self.restore_snapshots)
            menu.addAction("Delete snapshot", self.clear_snapshots)
        else:  # file
            menu.addAction("Restore this file", self.restore_snapshots)

        menu.exec(self.treewidget.viewport().mapToGlobal(position))
