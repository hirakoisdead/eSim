"""The NgVeri tab's model removal must run OFF the GUI thread.

Removing a model deletes whole build trees, rewrites the shared KiCad symbol
library and -- the expensive part -- reruns `make` + `make install` on the
ngspice code model. All of that used to happen inline in the button's slot, so
eSim froze ("not responding") for the whole teardown with no progress shown.

These tests drive the real widget headlessly: they assert the GUI event loop
keeps spinning while a slow teardown runs, that the progress bar and buttons
follow the job, and that the files really are gone at the end. The listing side
(which leftovers are offered at all) is covered in test_nghdl_remove.py.
"""
import os

import pytest
from PyQt6 import QtCore, QtWidgets

import maker.NgVeri as ngveri_mod
import maker.kicad_symlib as ksym


def _block(name):
    return f'(symbol "{name}" (pin_names (offset 0)) (property "Ref" "U"))'


class _FakeDialog:
    """Stand-in for RemoveItemsDialog: accepts and returns fixed names."""
    picked = []

    def __init__(self, *a, **kw):
        pass

    def exec(self):
        return 1

    def selected_items(self):
        return list(self.picked)


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    """A NgVeri widget wired to a throwaway model tree.

    Built with __new__ + QWidget.__init__ because the real constructor needs a
    configured NGHDL install; every attribute the removal path touches is set
    here explicitly.
    """
    w = ngveri_mod.NgVeri.__new__(ngveri_mod.NgVeri)
    QtWidgets.QWidget.__init__(w)

    digital = tmp_path / "icm" / "Ngveri"
    digital.mkdir(parents=True)
    release = tmp_path / "release"
    (release / "src" / "xspice" / "icm" / "Ngveri").mkdir(parents=True)
    xml = tmp_path / "xml"
    (xml / "Ngveri").mkdir(parents=True)
    (xml / "NgVeriCosim").mkdir()

    w.digital_home = str(digital)
    w.release_dir = str(release)
    w._xml_loc = str(xml)
    w.src_home = ""
    w.fname = ""
    w.filecount = 0
    w.count = 0
    w._remove_logs = None
    w._remove_log = None
    w._remove_job = None
    w._remove_model = None

    # The console + the progress widgets the removal drives.
    w.entry_var = {0: QtWidgets.QTextEdit()}
    w.buildStatus = QtWidgets.QLabel()
    w.buildBar = QtWidgets.QProgressBar()
    w.buildBar.setRange(0, 0)
    w.removeModelsBtn = QtWidgets.QPushButton()
    w.removeLintOffBtn = QtWidgets.QPushButton()
    w.addverilogbutton = QtWidgets.QPushButton()
    w.addcosimbutton = QtWidgets.QPushButton()

    # Symbol libraries live in a temp dir, never the real ~/.esim -- including
    # the ones the teardown reaches through createkicad, which would otherwise
    # resolve the user's own library from Appconfig.
    ngveri_sym = str(tmp_path / "eSim_Ngveri.kicad_sym")
    cosim_sym = str(tmp_path / "eSim_NgVeriCosim.kicad_sym")
    monkeypatch.setattr(w, "_sym_paths", lambda: (ngveri_sym, cosim_sym))
    monkeypatch.setattr(ngveri_mod, "RemoveItemsDialog", _FakeDialog)

    def _init(self, modelname, modelpath=""):
        self.modelname = os.path.splitext(modelname)[0]
        self.xml_loc = str(xml)
        self.kicad_ngveri_sym = ngveri_sym

    def _delete(self):
        parts = ksym._read_parts(self.kicad_ngveri_sym)
        parts.pop(self.modelname, None)
        ksym._write_lib(self.kicad_ngveri_sym, parts)
        try:
            os.remove(os.path.join(self.xml_loc, "Ngveri",
                                   self.modelname + ".xml"))
        except FileNotFoundError:
            pass

    monkeypatch.setattr(ngveri_mod.createkicad.AutoSchematic, "init", _init)
    monkeypatch.setattr(ngveri_mod.createkicad.AutoSchematic,
                        "deleteKicadSymbol", _delete)

    w._paths = (ngveri_sym, cosim_sym, str(digital), str(release), str(xml))
    return w


def _pump(qapp, predicate, timeout_ms=15000):
    """Spin the event loop until predicate() or the timeout. Returns the number
    of loop turns -- a nonzero count is the proof the GUI stayed responsive."""
    turns = 0
    deadline = QtCore.QElapsedTimer()
    deadline.start()
    while not predicate() and deadline.elapsed() < timeout_ms:
        qapp.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
        turns += 1
    return turns


def _idle(w):
    return w._remove_job is None


def test_removal_runs_off_the_gui_thread(tab, qapp, monkeypatch):
    ngveri_sym, cosim_sym, digital, release, xml = tab._paths
    # A legacy model with the full set of traces.
    ksym._write_lib(ngveri_sym, {"slowmodel": _block("slowmodel")})
    os.makedirs(os.path.join(digital, "slowmodel"))
    open(os.path.join(digital, "slowmodel", "ifspec.ifs"), "w").close()
    with open(os.path.join(digital, "modpath.lst"), "w") as f:
        f.write("slowmodel\n")

    gui_thread = QtCore.QThread.currentThread()
    seen = {}

    def slow_rebuild(model, log):
        # Stands in for make + make install: slow, and must NOT be on the GUI
        # thread (that is the freeze this whole change exists to kill).
        seen["thread"] = QtCore.QThread.currentThread()
        QtCore.QThread.msleep(600)
        return ""

    monkeypatch.setattr(tab, "_run_cm_rebuild", slow_rebuild)
    monkeypatch.setattr(ngveri_mod.ModelGeneration, "ModelGeneration",
                        lambda *a, **kw: _FakeModel())
    _FakeDialog.picked = ["slowmodel"]

    tab.open_remove_models()
    # The slot returned immediately with the job still running.
    assert tab._remove_job is not None
    assert not tab.buildBar.isHidden()
    assert tab.buildBar.maximum() == 1      # determinate: one model to remove
    assert not tab.removeModelsBtn.isEnabled()

    turns = _pump(qapp, lambda: _idle(tab))
    assert _idle(tab), "removal never finished"
    # Many event-loop turns during a 600 ms teardown == the GUI stayed alive.
    assert turns > 5, f"event loop only turned {turns} times"
    assert seen["thread"] is not gui_thread

    # Every trace of the model is gone...
    assert "slowmodel" not in ksym._read_parts(ngveri_sym)
    assert not os.path.exists(os.path.join(digital, "slowmodel"))
    with open(os.path.join(digital, "modpath.lst")) as f:
        assert "slowmodel" not in f.read()
    # ...the controls came back, and the bar is indeterminate again for builds.
    assert tab.removeModelsBtn.isEnabled()
    assert tab.addverilogbutton.isEnabled()
    assert tab.buildBar.isHidden()
    assert (tab.buildBar.minimum(), tab.buildBar.maximum()) == (0, 0)


class _FakeModel(QtCore.QObject):
    """Minimal ModelGeneration stand-in (only the parts the removal uses)."""
    phase = QtCore.pyqtSignal(str)

    def require_legacy_toolchain(self):
        return True

    def prune_modpathlst(self):
        return []


def test_symbol_only_cosim_orphan_is_torn_down_as_cosim(tab, qapp,
                                                        monkeypatch):
    # The reported bug: a d_cosim model left over from an older eSim owns a
    # symbol and nothing else. Resolved by XML alone it looks like a legacy
    # NgVeri model, the wrong dismantler runs, and the symbol survives in
    # KiCad's eSim_NgVeriCosim library forever.
    ngveri_sym, cosim_sym, digital, release, xml = tab._paths
    ksym._write_lib(cosim_sym, {"or_gate": _block("or_gate")})

    names, badges = tab._list_models()
    assert names == ["or_gate"] and badges["or_gate"] == "d_cosim"
    assert tab._model_backend("or_gate") == "cosim"

    removed = {}

    def fake_delete(self):
        parts = ksym._read_parts(cosim_sym)
        parts.pop(self.modelname, None)
        ksym._write_lib(cosim_sym, parts)
        removed["name"] = self.modelname

    monkeypatch.setattr(
        ngveri_mod.createkicadCosim.CosimSchematic, "init",
        lambda self, name, path="": setattr(self, "modelname", name))
    monkeypatch.setattr(
        ngveri_mod.createkicadCosim.CosimSchematic, "deleteKicadSymbol",
        fake_delete)
    monkeypatch.setattr(ngveri_mod.CosimConfig, "cosim_vvp_path",
                        lambda name: "")
    _FakeDialog.picked = ["or_gate"]

    tab.open_remove_models()
    _pump(qapp, lambda: _idle(tab))

    assert removed.get("name") == "or_gate"
    assert ksym._read_parts(cosim_sym) == {}
    assert tab._list_models()[0] == []          # nothing left to list


def test_second_removal_is_refused_while_one_runs(tab, qapp, monkeypatch):
    ngveri_sym = tab._paths[0]
    ksym._write_lib(ngveri_sym, {"m1": _block("m1")})
    monkeypatch.setattr(tab, "_run_cm_rebuild",
                        lambda model, log: (QtCore.QThread.msleep(400) or ""))
    monkeypatch.setattr(ngveri_mod.ModelGeneration, "ModelGeneration",
                        lambda *a, **kw: _FakeModel())
    asked = []
    monkeypatch.setattr(ngveri_mod.Dialogs, "information",
                        lambda *a, **kw: asked.append(a[2]))
    _FakeDialog.picked = ["m1"]

    tab.open_remove_models()
    tab.open_remove_models()            # while the first is still running
    assert any("already in progress" in str(m) for m in asked)
    _pump(qapp, lambda: _idle(tab))


def test_rebuild_skipped_without_toolchain(tab, qapp, monkeypatch):
    # Removing leftovers has to work on a machine that can no longer build
    # code models at all: the files go, the rebuild is only reported as
    # skipped, and no error dialog is raised.
    class _NoToolchain(_FakeModel):
        def require_legacy_toolchain(self):
            return False

    log = ngveri_mod.CosimLog(QtWidgets.QTextEdit())
    assert tab._run_cm_rebuild(_NoToolchain(), log) == ""
