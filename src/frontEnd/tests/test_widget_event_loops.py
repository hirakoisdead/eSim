"""Every eSim widget must survive being shown and re-themed.

A Qt event handler that mutates its own widget can re-raise the very event
it is handling -- ``changeEvent`` calling ``setStyleSheet`` is the classic
pair, because Qt answers the restyle with a fresh ``PaletteChange``.  The
recursion is synchronous, so it never returns to the event loop: it eats
the C stack and the process dies outright.  No Python traceback, no
``sys.excepthook`` (that only sees Python exceptions), no error dialog --
eSim simply vanishes.  That is exactly how double-clicking a .cir in the
project explorer used to kill the app: EditorWindow._apply_chrome_theme()
restyled the window from inside changeEvent(), and the loop only armed
itself once the window was *shown* (Qt polishes on show).

So the regression net has to (a) actually show each widget and (b) drive a
real theme switch over it.  Detection is by stack DEPTH, not event count:
a legit theme apply delivers plenty of palette events, but always shallow
(observed max ~17 frames), while a feedback loop nests them without bound.
Past the limit the filter swallows the event, which unwinds the recursion
and turns a would-be hard crash into a normal test failure.

``test_detector_catches_a_known_loop`` re-creates the pre-fix EditorWindow
so the detector itself stays honest: if that stops failing, this whole file
has quietly become a no-op.
"""
import importlib
import inspect
import os
import pkgutil
import sys

import pytest
from PyQt6 import QtCore, QtWidgets

#: Python frames below which every honest event delivery sits. The pre-fix
#: EditorWindow loop trips this within a single theme apply.
DEPTH_LIMIT = 60

#: Self-retriggering events: each one is raised by a setter a handler for
#: that same event is tempted to call.
WATCHED = {
    QtCore.QEvent.Type.PaletteChange,
    QtCore.QEvent.Type.StyleChange,
    QtCore.QEvent.Type.FontChange,
    QtCore.QEvent.Type.Resize,
    QtCore.QEvent.Type.LayoutRequest,
    QtCore.QEvent.Type.Polish,
}

PACKAGES = ["frontEnd", "codeEditor", "maker", "ngspiceSimulation",
            "browser", "configuration", "projManagement", "kicadtoNgspice"]

#: Widgets that shell out to the real toolchain (ngspice, KiCad, a terminal)
#: on construction. Showing them is an integration test, not this one.
NO_CONSTRUCT = {
    "frontEnd.TerminalUi.TerminalUi",
    "ngspiceSimulation.NgspiceWidget.NgspiceWidget",
}

#: Widgets that take constructor arguments. Without these they would be
#: skipped -- and CodeEditor, FlowNavigator and plotWindow all carry their own
#: changeEvent handler, i.e. they are precisely the shape this file exists to
#: police. `tmp` is a throwaway directory holding a sample netlist.
FACTORIES = {
    "codeEditor.CodeEditor.CodeEditor":
        lambda cls, tmp: cls(_sample_netlist(tmp)),
    "codeEditor.PlainEditor.PlainEditor":
        lambda cls, tmp: cls(_sample_netlist(tmp)),
    "maker.FlowNavigator.FlowNavigator": lambda cls, tmp: cls(0),
    "frontEnd.DockArea.WaveformDock": lambda cls, tmp: cls("Waveform"),
    "browser.Welcome.SectionHeader": lambda cls, tmp: cls("Section"),
    "browser.Welcome.ToolCard":
        lambda cls, tmp: cls("Name", "", "Description", "attr", lambda: None),
    "ngspiceSimulation.plot_window.plotWindow":
        lambda cls, tmp: cls(str(tmp), "sample"),
}


def _sample_netlist(tmp):
    path = os.path.join(str(tmp), "sample.cir")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("* sample\nV1 1 0 DC 5\nR1 1 0 1k\n.end\n")
    return path


def _stack_depth(cap=400):
    depth, frame = 0, sys._getframe()
    while frame is not None and depth < cap:
        depth += 1
        frame = frame.f_back
    return depth


class LoopDetector(QtCore.QObject):
    """Flags event deliveries that arrive impossibly deep in the stack."""

    def __init__(self):
        super().__init__()
        self.offenders = {}

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype in WATCHED:
            depth = _stack_depth()
            if depth > DEPTH_LIMIT:
                key = "%s.%s" % (type(obj).__name__, etype.name)
                self.offenders[key] = max(self.offenders.get(key, 0), depth)
                # Swallow it: this unwinds the recursion, so the test reports
                # a failure instead of taking the whole pytest run down with a
                # C-stack overflow.
                return True
        return False


def _widget_classes():
    """Every QWidget subclass eSim defines, that we can build with no args."""
    src = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", ".."))
    found = []
    for pkg in PACKAGES:
        pkg_dir = os.path.join(src, pkg)
        if not os.path.isdir(pkg_dir):
            continue
        for mod in pkgutil.iter_modules([pkg_dir]):
            if mod.name in ("tests", "conftest"):
                continue
            full = "%s.%s" % (pkg, mod.name)
            try:
                module = importlib.import_module(full)
            except Exception:
                continue          # optional deps / heavy imports: not our job
            for name, obj in vars(module).items():
                label = "%s.%s" % (full, name)
                if (inspect.isclass(obj)
                        and issubclass(obj, QtWidgets.QWidget)
                        and obj.__module__ == full
                        and label not in NO_CONSTRUCT):
                    found.append(pytest.param(obj, id=label))
    return found


@pytest.fixture
def detector(qapp, monkeypatch):
    # A modal dialog raised during construction would hang a headless run.
    monkeypatch.setattr(QtWidgets.QDialog, "exec", lambda *a, **k: 0)
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda *a, **k: 0)
    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QtWidgets.QMessageBox, name,
                            staticmethod(lambda *a, **k: 0))
    det = LoopDetector()          # keep the ref: a GC'd filter filters nothing
    qapp.installEventFilter(det)
    yield det
    qapp.removeEventFilter(det)


def _apply_theme(qapp, monkeypatch, mode):
    from frontEnd import theme_utils
    prefs = dict(theme_utils.get_preferences())
    prefs["theme_mode"] = mode
    monkeypatch.setattr(theme_utils, "get_preferences", lambda: prefs)
    theme_utils.apply_theme(qapp)
    qapp.processEvents()


def _exercise(widget, qapp, monkeypatch):
    """Show it, flip the theme both ways, resize it, close it."""
    widget.show()
    qapp.processEvents()
    for mode in ("Dark", "Light"):
        _apply_theme(qapp, monkeypatch, mode)
    widget.resize(720, 520)
    qapp.processEvents()
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("cls", _widget_classes())
def test_widget_shows_and_rethemes_without_event_loop(cls, qapp, detector,
                                                      monkeypatch, tmp_path):
    label = "%s.%s" % (cls.__module__, cls.__name__)
    factory = FACTORIES.get(label)
    try:
        widget = factory(cls, tmp_path) if factory else cls()
    except TypeError:
        pytest.skip("needs constructor arguments; add one to FACTORIES")
    _exercise(widget, qapp, monkeypatch)
    assert not detector.offenders, (
        "%s re-raises the event it handles -- runaway recursion, which is a "
        "C-stack overflow (hard crash) in a real session, not an exception. "
        "Deepest deliveries: %s" % (cls.__name__, detector.offenders))


def test_detector_catches_a_known_loop(qapp, detector, monkeypatch):
    """Guard the guard: rebuild the pre-fix EditorWindow and require a catch.

    Without this, a detector that silently stopped working would leave every
    other test in this file passing for the wrong reason.
    """
    from codeEditor import EditorWindow, theme

    class PreFixEditorWindow(EditorWindow.EditorWindow):
        def _apply_chrome_theme(self):        # no guard, no cached sheet
            self.setStyleSheet(
                EditorWindow.STYLE_DARK if theme.is_dark_theme()
                else EditorWindow.STYLE_LIGHT)

        def changeEvent(self, event):
            if event.type() == QtCore.QEvent.Type.PaletteChange:
                self._apply_chrome_theme()
            QtWidgets.QMainWindow.changeEvent(self, event)

    _exercise(PreFixEditorWindow(), qapp, monkeypatch)
    assert detector.offenders, (
        "the loop detector failed to catch a known-bad widget; the rest of "
        "this file is not protecting anything")
