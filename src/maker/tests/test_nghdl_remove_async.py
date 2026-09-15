"""The NGHDL tab's "Uninstall Models" must run OFF the GUI thread, and must
offer every leftover model -- not just the ones in ghdl/modpath.lst.

Same two defects as the NgVeri side (see test_ngveri_remove_async.py): the
teardown froze the window while it deleted build trees and rewrote the symbol
library, and models built by an older NGHDL were invisible to the dialog while
KiCad kept showing their eSim_Nghdl symbols.
"""
import os
import sys

import pytest
from PyQt6 import QtCore, QtWidgets

_NGHDL_SRC = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "nghdl", "src"))
if _NGHDL_SRC not in sys.path:
    sys.path.insert(0, _NGHDL_SRC)

ngspice_ghdl = pytest.importorskip("ngspice_ghdl")

import kicad_symlib as ksym                                    # noqa: E402


def _block(name):
    return f'(symbol "{name}" (pin_names (offset 0)) (property "Ref" "U"))'


class _FakeDialog:
    picked = []

    def __init__(self, *a, **kw):
        pass

    def exec(self):
        return 1

    def selected_items(self):
        return list(self.picked)


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    """A Mainwindow wired to a throwaway ghdl tree (no NGHDL install needed)."""
    w = ngspice_ghdl.Mainwindow.__new__(ngspice_ghdl.Mainwindow)
    QtWidgets.QWidget.__init__(w)
    w.embedded = True
    w._home_cwd = os.getcwd()
    w.file_list = []
    w.filename = ''
    w.errorFlag = False
    w._removejob = None

    ghdl = tmp_path / "icm" / "ghdl"
    ghdl.mkdir(parents=True)
    release = tmp_path / "release"
    (release / "src" / "xspice" / "icm" / "ghdl").mkdir(parents=True)
    xml = tmp_path / "xml"
    (xml / "Nghdl").mkdir(parents=True)
    sym = str(tmp_path / "eSim_Nghdl.kicad_sym")

    w.nghdl_home = str(tmp_path)
    w.release_dir = str(release)
    w.src_home = ""
    w.licensefile = ""
    w.initUI()

    monkeypatch.setattr(w, "_ghdl_home", lambda: str(ghdl))
    # Symbol lib + param XML must never resolve to the real ~/.esim tree.
    monkeypatch.setattr(ngspice_ghdl.model_teardown, "_nghdl_sym_path",
                        lambda src_home: sym)
    # Listing now refreshes the KiCad sym-lib-table (so a removed symbol really
    # leaves the picker on an upgraded install). Sandbox the config root: a
    # test must never rewrite the developer's real KiCad profile.
    monkeypatch.setattr(ksym, "_kicad_config_dir",
                        lambda: str(tmp_path / "kicad-config"))
    monkeypatch.setattr(ngspice_ghdl.Appconfig, "xml_loc", str(xml))
    monkeypatch.setattr(ngspice_ghdl, "RemoveItemsDialog", _FakeDialog)

    w._paths = (sym, str(ghdl), str(release), str(xml))
    return w


def _pump(qapp, predicate, timeout_ms=15000):
    turns = 0
    clock = QtCore.QElapsedTimer()
    clock.start()
    while not predicate() and clock.elapsed() < timeout_ms:
        qapp.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
        turns += 1
    return turns


def test_lists_symbol_only_leftovers(win):
    # The reported bug: eSim_Ngveri/eSim_Nghdl full of models the remove dialog
    # never offered, because only modpath.lst was consulted.
    sym, ghdl, release, xml = win._paths
    ksym._write_lib(sym, {"bin_to_gray": _block("bin_to_gray"),
                          "nand_gate": _block("nand_gate")})
    with open(os.path.join(ghdl, "modpath.lst"), "w") as f:
        f.write("nand_gate\n")
    assert win._list_nghdl_models() == ["bin_to_gray", "nand_gate"]


def test_uninstall_runs_off_the_gui_thread(win, qapp, monkeypatch):
    sym, ghdl, release, xml = win._paths
    ksym._write_lib(sym, {"slowvhd": _block("slowvhd")})
    os.makedirs(os.path.join(ghdl, "slowvhd"))
    open(os.path.join(ghdl, "slowvhd", "ifspec.ifs"), "w").close()
    open(os.path.join(xml, "Nghdl", "slowvhd.xml"), "w").close()
    with open(os.path.join(ghdl, "modpath.lst"), "w") as f:
        f.write("slowvhd\n")

    gui_thread = QtCore.QThread.currentThread()
    seen = {}
    real_strip = ngspice_ghdl.model_teardown._strip_modpath_line

    def slow_strip(path, name):
        seen["thread"] = QtCore.QThread.currentThread()
        QtCore.QThread.msleep(500)
        return real_strip(path, name)

    monkeypatch.setattr(ngspice_ghdl.model_teardown, "_strip_modpath_line",
                        slow_strip)
    # The ghdl.cm rebuild is a QProcess chain; stub it out and just close the
    # progress row as the real chain's terminal step does.
    monkeypatch.setattr(win, "_rebuild_ghdl_cm", win._end_removal_ui)
    _FakeDialog.picked = ["slowvhd"]

    win.openRemoveModels()
    assert win._removejob is not None
    assert not win.removemodelbtn.isEnabled()
    # isVisible() is False for a never-shown parent; isHidden() is the
    # widget's own state, which is what the code toggles.
    assert not win.progressBar.isHidden()

    turns = _pump(qapp, lambda: win._removejob is None
                  and win.removemodelbtn.isEnabled())
    assert turns > 5, f"event loop only turned {turns} times"
    assert seen["thread"] is not gui_thread

    assert ksym._read_parts(sym) == {}
    assert not os.path.exists(os.path.join(ghdl, "slowvhd"))
    assert not os.path.exists(os.path.join(xml, "Nghdl", "slowvhd.xml"))
    with open(os.path.join(ghdl, "modpath.lst")) as f:
        assert "slowvhd" not in f.read()
    assert win.progressBar.isHidden()
    assert win.uploadbtn.isEnabled()


def test_worker_failure_restores_controls(win, qapp, monkeypatch):
    sym = win._paths[0]
    ksym._write_lib(sym, {"boom": _block("boom")})
    monkeypatch.setattr(win, "_remove_nghdl_models",
                        lambda names: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical",
                        staticmethod(lambda *a, **kw: None))
    _FakeDialog.picked = ["boom"]

    win.openRemoveModels()
    _pump(qapp, lambda: win._removejob is None and win.uploadbtn.isEnabled())
    assert win.removemodelbtn.isEnabled()
    assert win.progressBar.isHidden()
