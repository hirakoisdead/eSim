import shlex
from PyQt6 import QtWidgets, QtCore
from configuration.Appconfig import Appconfig
from configuration import paths
from configuration import Dialogs
from projManagement.Worker import WorkerThread
from subcircuit.subPaths import (resolve_subcircuit, schematic_path,
                                 list_stems)


# This class is called when User clicks on Edit Subcircuit Button.
class openSub(QtWidgets.QWidget):
    """
    It opens the existing subcircuit projects that are present in
    Subcircuit directory.
    """

    def __init__(self):
        super(openSub, self).__init__()
        self.obj_appconfig = Appconfig()

    def body(self, editfile=None, stem=None):
        """
        Open a subcircuit for editing in eeschema.

        @params
            :editfile   => the subcircuit folder. Asked for interactively when
                           omitted, which is what the Edit button does.
            :stem        => the subcircuit inside that folder. Resolved (and,
                           only when genuinely ambiguous, asked for) when
                           omitted.

        Both parameters exist so a richer picker can hand over a folder AND the
        subcircuit chosen inside it without going through the folder dialog
        again -- and, crucially, so the choice is recorded as the active
        selection rather than re-derived later by Convert.
        """
        if editfile is None:
            editfile, stem = self._pick()

        if not editfile:
            return None

        self.editfile = editfile

        if stem is None:
            stem, status = resolve_subcircuit(editfile)
            # Only a genuinely ambiguous folder gets a prompt: several .sub
            # files with nothing to prefer among them. A folder whose name
            # matches one of its .sub files, or that carries its own netlist,
            # resolves silently the way it always did -- the prompt exists to
            # replace a lookup for a file called "None", not to interrogate
            # every subcircuit that happens to bundle a nested model.
            if stem is None and status == 'ambiguous':
                stem = self._chooseSubcircuit(list_stems(editfile))
                if stem is None:
                    self.obj_appconfig.print_info('No subcircuit opened')
                    return None

        if stem is None:
            Dialogs.critical(
                self, "Error Message",
                "Could not work out which subcircuit this folder holds.\n\n"
                + str(editfile))
            return None

        # Record folder AND stem together: this is the selection Convert acts
        # on, so the subcircuit the user opened is the one that gets rebuilt.
        self.obj_appconfig.set_current_subcircuit(editfile, stem)
        self.schname = stem

        schematic = schematic_path(editfile, stem)
        self.cmd = "eeschema " + shlex.quote(schematic)
        self.obj_workThread = WorkerThread(self.cmd)
        self.obj_workThread.start()
        self.obj_appconfig.print_info('Editing subcircuit ' + str(stem))
        return stem

    def _pick(self):
        """Ask which subcircuit to open. Returns ``(folder, stem)``.

        The library picker comes first because it can answer the question the
        folder dialog cannot: which subcircuit a folder actually holds, whether
        it has been converted yet, and how many ports it ended up with. Its
        Browse button drops through to the original folder dialog, so a
        subcircuit kept outside the library is reached exactly as before.
        """
        from subcircuit.subPicker import SubcircuitPicker

        picker = SubcircuitPicker(
            paths.library_path("SubcircuitLibrary"),
            Dialogs.resolve_parent(self))
        try:
            if picker.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return None, None
            if not picker.browse:
                return picker.chosen or (None, None)
        finally:
            picker.deleteLater()

        return self._browseForFolder(), None

    def _browseForFolder(self):
        """The folder dialog Edit has always used, unchanged."""
        return QtCore.QDir.toNativeSeparators(
            QtWidgets.QFileDialog.getExistingDirectory(
                self, "Open File", paths.library_path("SubcircuitLibrary")
            )
        )

    def _chooseSubcircuit(self, stems):
        """
        When a folder contains more than one .sub, ask the user which
        subcircuit to edit. Returns the chosen stem, or None if cancelled.
        """
        if not stems:
            return None
        choice, ok = QtWidgets.QInputDialog.getItem(
            Dialogs.resolve_parent(self), "Select Subcircuit",
            "This folder contains multiple eSim subcircuits.\n"
            "Choose one to edit:",
            stems, 0, False
        )
        if ok and choice:
            return str(choice)
        return None
