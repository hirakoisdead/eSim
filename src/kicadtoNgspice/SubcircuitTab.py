from PyQt6 import QtWidgets, QtCore
from configuration import paths
from configuration import Dialogs
from . import TrackWidget
from . import ModelGrouping
from .ModelGroupWidget import (ModelGroupWidget, InstanceRow,
                               finish_group_layout)
from projManagement import Validation
from projManagement import modelCache
from projManagement.projectPaths import stem_from_file, previous_values_path
import os
from xml.etree import ElementTree as ET


class SubcircuitTab(QtWidgets.QWidget):
    """
    Subcircuit tab of the KicadtoNgspice window.

    Subcircuit instances that reference the same subcircuit (e.g. several
    ``lm_741`` op-amps) are grouped into a single ModelGroupWidget: the user
    selects the subcircuit directory once and it fans out to every instance,
    with per-instance override still available. A directory is validated against
    each instance's port count before it is accepted.

    The per-instance QLineEdits stay registered in ``entry_var`` /
    ``subcircuit_dict_beg`` / ``subcircuit_dict_end`` with one field per
    instance, so the Convert step, the callConvert Previous_Values writer and
    tab reload are unchanged; grouping is a view/controller layer over the
    existing per-ref ``subcircuitTrack`` storage.
    """

    def __init__(self, schematicInfo, clarg1, track=None):
        kicadFile = clarg1
        # Stem of the .cir handed in -- the key prefix for subcircuitList.
        project_name = stem_from_file(kicadFile)

        self.root = []
        try:
            f = open(previous_values_path(kicadFile), 'r')
            tree = ET.parse(f)
            for child in tree.getroot():
                if child.tag == "subcircuit":
                    self.root = child
        except Exception:
            print("Subcircuit Previous values XML is Empty")

        QtWidgets.QWidget.__init__(self)

        # Shared per-conversion data bus, injected by the converter window; a
        # standalone construction falls back to its own instance.
        self.obj_trac = track if track is not None else \
            TrackWidget.TrackWidget()
        self.obj_validation = Validation.Validation()

        self.count = 1                 # entry_var index counter
        self.entry_var = {}
        self.subcircuit_dict_beg = {}
        self.subcircuit_dict_end = {}
        self.subDetail = {}            # entry index -> ref
        self.sub_ports = {}            # ref -> required port count
        # (model_name, ModelGroupWidget) per group, for model_cache hints.
        self._groups = []

        self.grid = QtWidgets.QGridLayout()
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setVerticalSpacing(8)
        self.setLayout(self.grid)

        components = ModelGrouping.parse_subcircuit_components(schematicInfo)
        groups = ModelGrouping.group_by_model(components)

        for (_kind, model), instances in groups.items():
            rows = []
            for comp in instances:
                ref = comp.ref
                words = comp.words
                beg = self.count

                self.subcircuit_dict_beg[ref] = beg
                self.subDetail[beg] = ref
                # Ports = tokens between the ref and the subcircuit name.
                self.sub_ports[ref] = len(words) - 2
                # Mirror the legacy registration Convert's count check reads.
                self.obj_trac.subcircuitList[project_name + ref] = words

                edit = QtWidgets.QLineEdit()
                self.entry_var[beg] = edit
                self.count += 1
                self.subcircuit_dict_end[ref] = self.count - 1

                self._restore_subcircuit(ref, beg)
                if edit.text():
                    self._resolve_subcircuit(ref, edit.text())

                rows.append(InstanceRow(
                    ref, edit, browse_fn=self._make_row_browse(ref)))

            title = "%s  (Subcircuit)" % model
            group = ModelGroupWidget(
                title, rows,
                resolve_fn=self._resolve_subcircuit,
                group_browse_fn=self._make_group_browse(instances))
            self._apply_cache_hint(model, group, rows)
            self.grid.addWidget(group)
            self._groups.append((model, group))

        finish_group_layout(self.grid)


    def _apply_cache_hint(self, model, group, rows):
        """Pre-fill a blank group default from the cross-project model_cache,
        but only a directory that exists (lookup guarantees it) AND validates
        for every instance's port count. A project's own restored values and any
        override always take precedence."""
        if group.group_path() or any(group.is_overridden(r.ref) for r in rows):
            return
        hint = modelCache.lookup(model)
        if not hint:
            return
        if all(self.obj_validation.validateSub(hint, self.sub_ports[r.ref])
               == "True" for r in rows):
            group.set_group_path(hint)

    def remembered_models(self):
        """{subcircuit_name: directory} for groups where every instance
        resolved to the same non-empty directory. Fed to modelCache after a
        successful convert."""
        out = {}
        for model, group in self._groups:
            vals = set(group.resolved().values())
            if len(vals) == 1:
                path = next(iter(vals))
                if path:
                    out[model] = path
        return out

    # -- tracking ------------------------------------------------------------

    def _resolve_subcircuit(self, ref, path):
        """Write one instance's directory into subcircuitTrack -- the same
        per-ref entry Convert reads. An empty path removes the entry, so an
        unassigned instance fails the "all subcircuits specified" check rather
        than emitting an empty include."""
        track = self.obj_trac.subcircuitTrack
        if path:
            track[ref] = path
        else:
            track.pop(ref, None)

    def _restore_subcircuit(self, ref, idx):
        """Refill an instance from self.root (Previous_Values.xml), dropping a
        directory that no longer exists on this machine (the leak guard). Match
        is by exact ref, fixing the legacy 2-character match that confused e.g.
        x1 with x10."""
        for child in self.root:
            if child.tag != ref:
                continue
            try:
                text = child[0].text or ""
            except IndexError:
                return
            if text and os.path.exists(text):
                self.entry_var[idx].setText(text)
            else:
                self.entry_var[idx].setText("")
            return

    # -- browse + validation -------------------------------------------------

    def _open_sub_dir(self):
        """Open the subcircuit directory picker; return the path or ''."""
        return str(QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getExistingDirectory(
                self, "Open Subcircuit",
                paths.library_path("SubcircuitLibrary"))))

    def _validate(self, path, ref):
        """True if `path` is a valid subcircuit dir with the right port count
        for `ref`; otherwise show the matching error and return False."""
        reply = self.obj_validation.validateSub(path, self.sub_ports[ref])
        if reply == "True":
            return True
        if reply == "PORT":
            self._error("Please select a Subcircuit with the correct number "
                        "of ports.")
        elif reply == "DIREC":
            self._error("Please select a valid Subcircuit directory "
                        "(containing a '.sub' file).")
        elif reply == "NOSUBCKT":
            self._error("The selected '.sub' file has no '.subckt' line "
                        "-- it is not a valid subcircuit.")
        return False

    def _make_group_browse(self, instances):
        """Group Browse: pick one directory and accept it only if it validates
        for every instance in the group (same subcircuit => same ports, but
        checked defensively)."""
        refs = [c.ref for c in instances]

        def browse():
            path = self._open_sub_dir()
            if not path:
                return ""
            for ref in refs:
                if not self._validate(path, ref):
                    return ""
            return path
        return browse

    def _make_row_browse(self, ref):
        """Per-instance Browse: pick and validate a directory for one ref."""
        def browse():
            path = self._open_sub_dir()
            if not path:
                return ""
            return path if self._validate(path, ref) else ""
        return browse

    def _error(self, message):
        Dialogs.critical(self, "Error Message", message)
