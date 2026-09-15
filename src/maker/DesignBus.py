# =========================================================================
#             FILE: DesignBus.py
#
#      DESCRIPTION: Single source of truth for one HDL design in the Flow
#                   Navigator (Author -> Verify -> Convert). The three stages
#                   are *views* on one design, not three editors that sync
#                   through disk. The design lives here, in memory; disk is
#                   only persistence.
#
#                   Why this exists: the stages used to hand the design around
#                   by writing a .v to disk and reading it back, so a watchdog
#                   was needed to notice the change -- and it could not tell our
#                   own write from an outside one, so it nagged on every tab
#                   switch. With one in-memory owner, in-app navigation never
#                   touches disk, and the watch fires only on genuine external
#                   edits (e.g. the file opened in another editor).
#
#                   Disk writes still happen, but only on purpose: an explicit
#                   Save, a lazy materialize right before Convert (whose
#                   toolchain reads a real file path), and a debounced autosave
#                   into the Verilog library. They are echo-proof: the sha256 of
#                   the bytes we last wrote is remembered, so the watch ignores
#                   any disk event whose content matches it.
#
#                   The autosave is what gives a design authored in eSim a file
#                   at all. Without it the editor could produce a design that
#                   existed only in memory: Save had nothing to name a file
#                   after, materialize had no path to write, and Convert
#                   reported "No Verilog File Chosen" for a design plainly on
#                   screen. It writes under the design's own top module name,
#                   and re-derives that name whenever the module changes -- so
#                   replacing the design replaces its home instead of leaving it
#                   filed under the first name it ever had.
#
#                   Two things it must never do, both tested: overwrite a file
#                   the user opened from their own project (eSim copies that
#                   into the library and mirrors back only on an explicit Save),
#                   and overrule a home the user chose with Save As.
#
#  ORGANIZATION: eSim Team at FOSSEE, IIT Bombay
# =========================================================================
import hashlib
import os

try:
    import watchdog.events
    import watchdog.observers
    _HAS_WATCHDOG = True
except ImportError:
    # watchdog is an OPTIONAL dependency. Without it the whole in-app design
    # flow still works: Author -> Verify -> Convert navigation, explicit Save,
    # and the lazy materialize before Convert never need it -- only the passive
    # external-edit watch does. Importing maker.makerchip (-> DesignBus) must
    # never brick Model Creation just because watchdog is missing or fails to
    # load, mirroring the graceful QScintilla fallback in
    # codeEditor.EditorWindow.
    watchdog = None
    _HAS_WATCHDOG = False
from PyQt6 import QtCore
from PyQt6.QtCore import pyqtSignal

from . import verilog_library

#: Quiet period after the last edit before the design is written to the
#: library. Long enough that typing does not thrash the disk, short enough that
#: a design is on disk before the user has finished reading what they pasted.
AUTOSAVE_MS = 1500


def _hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


if _HAS_WATCHDOG:
    class _DiskWatchHandler(watchdog.events.PatternMatchingEventHandler):
        """Reports modifications of one watched file back to its DesignBus.

        Scoped to the file's *directory* (not the file) because many editors
        save atomically -- write a temp file, then rename it over the target --
        which a file-level watch misses. The pattern keeps only events for our
        file.
        """

        def __init__(self, bus, filepath):
            super().__init__(
                patterns=[filepath],
                ignore_directories=True,
                case_sensitive=True)
            self._bus = bus

        def on_modified(self, event):
            self._bus._on_disk_event()

        def on_created(self, event):
            self._bus._on_disk_event()

        def on_moved(self, event):
            # Atomic-save rename landing on our file.
            self._bus._on_disk_event()
else:
    # No base class to subclass when watchdog is absent; _start_watch bails
    # out before this is ever referenced.
    _DiskWatchHandler = None


class DesignBus(QtCore.QObject):
    """The one design shared by the Author / Verify / Convert stages.

    Hold the design text in ``content`` and let every stage render from / write
    to it. ``path`` is where it persists (empty until first materialize).
    ``_saved_hash`` is the sha256 of the bytes last exchanged with disk and is
    what makes the external-edit watch echo-proof.
    """

    #: content was replaced in memory (load / explicit set).
    contentChanged = pyqtSignal(str)
    #: the file on disk diverged from our content -- a real outside edit.
    externalChange = pyqtSignal(str)

    def __init__(self, filecount, parent=None):
        super().__init__(parent)
        self.filecount = filecount
        self._content = ""
        self._path = ""
        self._saved_hash = ""
        self._observer = None
        self._handler = None
        self._watch_file = None
        # Where this design was imported from, when it came from a file of the
        # user's own. eSim works on its library copy from then on and NEVER
        # writes here by itself; only an explicit Save mirrors back to it.
        self.origin_path = ""
        self._autosave_timer = None

    # ------------------------------------------------------------------ #
    #  In-memory model (no disk)
    # ------------------------------------------------------------------ #
    def get_content(self):
        return self._content

    def set_content(self, text):
        """Update the in-memory design. Idempotent: setting the same text is a
        no-op, so a view rendering exactly what it received cannot loop."""
        if text == self._content:
            return
        self._content = text
        self._arm_autosave()
        self.contentChanged.emit(text)

    # ------------------------------------------------------------------ #
    #  Autosave to the Verilog library
    #
    #  Every stage edits the design through set_content, so hanging the
    #  autosave off that one method gives Author, Verify and anything added
    #  later the same behaviour for free -- and keeps it out of
    #  collect_into_bus, which must stay pure in-memory (writing disk on a
    #  stage switch is what made the old watchdog nag on every tab change).
    # ------------------------------------------------------------------ #
    def _arm_autosave(self):
        """(Re)start the quiet-period timer after an edit."""
        if self._autosave_timer is None:
            # Built lazily: a DesignBus can be constructed in a test with no
            # event loop, where a timer would never fire anyway.
            self._autosave_timer = QtCore.QTimer(self)
            self._autosave_timer.setSingleShot(True)
            self._autosave_timer.timeout.connect(self.flush_autosave)
        self._autosave_timer.start(AUTOSAVE_MS)

    def _in_library(self, path):
        """True when ``path`` is a file eSim filed away itself."""
        if not path:
            return False
        root = os.path.normcase(os.path.abspath(verilog_library.library_root()))
        return os.path.normcase(os.path.abspath(path)).startswith(root)

    def flush_autosave(self):
        """Write the design to its home now, if it is ready to be written.

        Called on the quiet-period timer and at every milestone that wants the
        design on disk (entering Convert, leaving Verify, closing). Returns the
        path written, or "" when there was nothing worth writing -- an
        unparseable or half-typed design simply stays in memory until it makes
        sense, which is why this is safe to call on a keystroke.

        A design eSim filed itself is named after its top module and MOVES when
        that module changes: the folder is RENAMED where that is provably safe
        (verilog_library.rename_design), and otherwise the design is simply
        written to its new home and the old folder left alone -- an autosave
        must never be able to lose work. A home the user picked themselves,
        with Save As, is never second-guessed: autosave keeps writing exactly
        where they put it."""
        if self._autosave_timer is not None:
            self._autosave_timer.stop()
        if not verilog_library.is_saveable(self._content):
            return ""
        target = self._path
        if not target or self._in_library(target):
            module = verilog_library.top_module(self._content)
            target = verilog_library.design_path(module)
            if self._path and self._in_library(self._path) \
                    and target != self._path:
                moved = self._rename_previous_home(module)
                if moved:
                    target = moved
        if target == self._path and not self.is_dirty() \
                and os.path.isfile(target):
            return target                       # already on disk, unchanged
        return self.save_to_disk(target)

    def _rename_previous_home(self, module):
        """Move the design's folder to ``module`` when -- and only when -- the
        design was RENAMED rather than replaced. Returns the new design path,
        or "".

        A design is named after its top module, so renaming the module renames
        the design. Left alone, that filed one design under every name it ever
        had (nand / nandg / nand_gate, only the last of them real) and made the
        user work out which was which.

        Replacing the design is the case this must not touch: pasting design B
        over design A also changes the top module, and A has to stay exactly
        where it is. The two are told apart by content, not by guesswork --
        is_pure_rename asks whether the new text IS the old text with the
        module renamed. Anything less certain keeps the old folder, which is
        never destructive; it only leaves a folder behind.
        """
        previous = os.path.basename(
            os.path.dirname(os.path.abspath(self._path)))
        try:
            with open(self._path, encoding="utf-8", errors="replace") as fh:
                old_text = fh.read()
        except OSError:
            return ""
        if not verilog_library.is_pure_rename(old_text, self._content,
                                              previous, module):
            return ""
        return verilog_library.rename_design(previous, module)

    def start_new(self, text=""):
        """Begin a fresh design, keeping whatever is already on disk.

        The current design is flushed first, so starting a new one never
        discards the last edit of the old one, and then the bus is detached
        from its file: the new design earns its own home from its own module
        name at the next autosave, rather than inheriting the previous
        design's."""
        self.flush_autosave()
        self._stop_watch()
        self._path = ""
        self.origin_path = ""
        self._saved_hash = ""
        self._content = ""
        self._mirror_slot()
        self.set_content(text)
        if not text:
            self.contentChanged.emit("")
        return self._path

    @property
    def path(self):
        return self._path

    def set_path(self, path):
        """Assign where the design will persist, WITHOUT writing it yet (a Verify
        -authored design gets a home so Convert can later materialize it). The
        bytes are written on the next save / materialize, not here."""
        if path and path != self._path:
            self._path = path
            self._mirror_slot()

    def is_dirty(self):
        if not self._path:
            return bool(self._content)
        return _hash_bytes(self._content.encode("utf-8")) != self._saved_hash

    # ------------------------------------------------------------------ #
    #  Disk I/O  (the ONLY place that reads/writes the design file)
    # ------------------------------------------------------------------ #
    def load_from_disk(self, path, imported=False):
        """Read an existing .v as THE design (explicit Open / Reload).

        ``imported=True`` marks a file of the user's own, opened from wherever
        they keep it. eSim takes a copy into the library and works on THAT from
        then on, so nothing eSim does in the background can rewrite a file
        sitting in someone's project folder. The original is remembered as
        ``origin_path`` and is only ever written by an explicit Save."""
        if not path or not os.path.isfile(path):
            return ""
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return ""
        self._content = data.decode("utf-8", errors="replace")
        self._path = path
        self._saved_hash = _hash_bytes(data)
        if imported:
            self.origin_path = path
            # Place the library copy EXPLICITLY rather than via flush_autosave:
            # autosave deliberately keeps writing to whatever path is already
            # set (so it can never hijack a home the user chose with Save As),
            # and at this instant that path is still the user's own file --
            # which is the one file eSim must not write behind their back.
            copy = verilog_library.save_design(self._content)
            if copy:
                self._path = copy
                self._saved_hash = _hash_bytes(self._content.encode("utf-8"))
            # No parseable module: nothing to name a copy after. The design
            # stays pointed at the file it came from, and materialize() refuses
            # to rewrite it (Convert's parse error is the useful message).
        self._mirror_slot()
        self._start_watch()
        self.contentChanged.emit(self._content)
        return self._path

    def save_to_disk(self, path=None):
        """Persist the in-memory content. Sole writer of the design file."""
        target = path or self._path
        if not target:
            return ""
        data = self._content.encode("utf-8")
        # Record the hash BEFORE writing so the watch never echoes our own write,
        # even if its event fires before this call returns.
        self._saved_hash = _hash_bytes(data)
        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)
        except OSError:
            return ""
        self._path = target
        self._mirror_slot()
        self._start_watch()
        return target

    def materialize(self):
        """Ensure disk reflects the in-memory content, then return the path.
        Used right before Convert, which reads a real file. No-op when disk
        already matches what we hold."""
        # Settle the autosave first: that is what gives a design authored in
        # eSim a real file at all, which is what Convert could never get before
        # (no path -> nothing written -> "No Verilog File Chosen").
        home = self.flush_autosave()
        if home:
            return home
        if not self._path:
            return ""
        if self._path == self.origin_path:
            # An imported design eSim could not name yet (no parseable module).
            # Building from the file as it sits is right; rewriting the user's
            # own file behind their back is not. Convert will report the parse
            # failure itself, which is the error that actually helps.
            return self._path if os.path.isfile(self._path) else ""
        fresh = _hash_bytes(self._content.encode("utf-8")) == self._saved_hash
        if fresh and os.path.isfile(self._path):
            return self._path
        return self.save_to_disk()

    def mirror_to_origin(self):
        """Write the design back to the file it was imported from, if any.

        Only an explicit Save calls this. Autosave and materialize stay inside
        the library, so the file the user opened changes when -- and only when
        -- they ask for it to."""
        if not self.origin_path or self.origin_path == self._path:
            return ""
        try:
            with open(self.origin_path, "wb") as fh:
                fh.write(self._content.encode("utf-8"))
        except OSError:
            return ""
        return self.origin_path

    # ------------------------------------------------------------------ #
    #  Legacy compat: keep Maker.verilogFile[filecount] == path
    #
    #  NgVeri / ModelGeneration still read that slot as the design path. The
    #  slot is no longer shared *mutable* state edited from everywhere: this bus
    #  is its one writer, so the slot is just a derived mirror of ``path``.
    # ------------------------------------------------------------------ #
    def _mirror_slot(self):
        from . import Maker
        while len(Maker.verilogFile) <= self.filecount:
            Maker.verilogFile.append("")
        Maker.verilogFile[self.filecount] = self._path

    # ------------------------------------------------------------------ #
    #  External-edit watch (echo-proof, one observer per bus)
    # ------------------------------------------------------------------ #
    def _start_watch(self):
        if not _HAS_WATCHDOG:
            return          # watchdog absent: external-edit watch disabled
        if not self._path:
            return
        if self._observer is not None and self._watch_file == self._path:
            return                      # already watching the right file
        # _stop_watch, NOT close(): close() flushes the autosave, which writes
        # the file, which re-enters _start_watch.
        self._stop_watch()
        watch_dir = os.path.dirname(self._path) or "."
        if not os.path.isdir(watch_dir):
            return
        self._handler = _DiskWatchHandler(self, self._path)
        self._observer = watchdog.observers.Observer()
        self._observer.schedule(self._handler, path=watch_dir, recursive=False)
        self._observer.daemon = True
        self._watch_file = self._path
        self._observer.start()

    def _on_disk_event(self):
        """Runs in the watchdog thread. Compare the file to what WE last wrote:
        equal hash => our own write (echo) -> ignore; different => a real outside
        edit. ``externalChange`` is delivered queued to the GUI thread."""
        try:
            with open(self._path, "rb") as fh:
                data = fh.read()
        except OSError:
            return
        if _hash_bytes(data) == self._saved_hash:
            return
        self.externalChange.emit(self._path)

    def close(self):
        """Persist any pending edit, then stop the watch. Owner's teardown.

        The flush is what makes closing eSim mid-thought safe: the design is in
        memory until the quiet-period timer fires, and a close would otherwise
        beat the timer to it."""
        self.flush_autosave()
        self._stop_watch()

    def _stop_watch(self):
        """Tear the observer down without touching disk."""
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
        self._observer = None
        self._handler = None
        self._watch_file = None
