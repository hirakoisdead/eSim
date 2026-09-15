"""Neither Verilog backend's teardown may touch the other's build.

The NgVeri (Verilator) and d_cosim (Icarus) backends used to build into ONE
directory per model name, ``<DIGITAL_MODEL>/Ngveri/<model>/``. Removing a
d_cosim model therefore rmtree'd the Verilator backend's ``ifspec.ifs`` and
``cfunc.mod`` for a model of the same name -- while leaving its compiled ``.o``
in the release tree, so ngspice kept answering for a model whose sources were
gone. The reverse removal destroyed the d_cosim vvp just as thoroughly.

Guarding that shared directory can never be airtight, because on Windows the
filesystem compares names case-insensitively while every guard in Python
compares them exactly: the two disagree, and the disagreement is what deletes
the wrong tree. So the backends were given separate roots -- legacy
``Ngveri/`` untouched, d_cosim in a sibling ``NgVeriCosim/`` -- and these tests
hold that line.

Everything here is filesystem-only and runs identically on Windows and Linux.
The case-sensitivity questions are asked of the *helpers* (which must give the
same answer on both) rather than of the filesystem (which cannot).
"""
import os
import shutil

import pytest
from PyQt6 import QtWidgets

import maker.CosimConfig as CosimConfig
import maker.NgVeri as ngveri_mod
from maker.model_teardown import (_actual_subdir_name, _dir_has_name,
                                  _resolve_backend, discover_ngveri_models)


class _Log:
    """Swallows the teardown narration; these tests assert on the disk."""

    def __getattr__(self, _name):
        return lambda *a, **kw: None


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    return path


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    """A NgVeri widget wired to a throwaway model tree.

    Built with __new__ + QWidget.__init__ because the real constructor needs a
    configured NGHDL install; only the attributes the teardown reads are set.
    The KiCad symbol/XML surgery is stubbed out -- it is covered in
    test_nghdl_remove.py and would otherwise reach the user's real ~/.esim.
    """
    widget = ngveri_mod.NgVeri.__new__(ngveri_mod.NgVeri)
    QtWidgets.QWidget.__init__(widget)

    root = tmp_path / "lib"
    digital = root / "Ngveri"
    digital.mkdir(parents=True)
    (root / "NgVeriCosim").mkdir()
    release = tmp_path / "release"
    (release / "src" / "xspice" / "icm" / "Ngveri").mkdir(parents=True)
    xml = tmp_path / "xml"
    (xml / "Ngveri").mkdir(parents=True)
    (xml / "NgVeriCosim").mkdir()

    monkeypatch.setattr(CosimConfig, "digital_model_root", lambda: str(root))

    widget.digital_home = str(digital)
    widget.release_dir = str(release)
    widget._xml_loc = str(xml)
    widget.src_home = ""
    widget.fname = ""
    widget.filecount = 0
    widget.entry_var = {0: QtWidgets.QTextEdit()}

    def _init(self, modelname, modelpath="", *args, **kwargs):
        self.modelname = os.path.splitext(str(modelname))[0]
        self.xml_loc = str(xml)

    def _delete_ngveri(self):
        try:
            os.remove(os.path.join(self.xml_loc, "Ngveri",
                                   self.modelname + ".xml"))
        except FileNotFoundError:
            pass

    def _delete_cosim(self):
        try:
            os.remove(os.path.join(self.xml_loc, "NgVeriCosim",
                                   self.modelname + ".xml"))
        except FileNotFoundError:
            pass

    monkeypatch.setattr(ngveri_mod.createkicad.AutoSchematic, "init", _init)
    monkeypatch.setattr(ngveri_mod.createkicad.AutoSchematic,
                        "deleteKicadSymbol", _delete_ngveri)
    monkeypatch.setattr(ngveri_mod.createkicadCosim.CosimSchematic,
                        "init", _init)
    monkeypatch.setattr(ngveri_mod.createkicadCosim.CosimSchematic,
                        "deleteKicadSymbol", _delete_cosim)

    widget._paths = (str(root), str(digital), str(release), str(xml))
    return widget


def _build_ngveri(tab, name, modpath_line=True):
    """Everything a completed legacy NgVeri build leaves behind."""
    root, digital, release, xml = tab._paths
    _write(os.path.join(digital, name, "ifspec.ifs"))
    _write(os.path.join(digital, name, "cfunc.mod"))
    _write(os.path.join(digital, name, name + ".v"))
    # cmpp's generated C plus the object it compiles to, which is what the
    # release tree really holds and what keeps the model linked into ngspice.
    _write(os.path.join(release, "src", "xspice", "icm", "Ngveri",
                        name, "cfunc.c"))
    _write(os.path.join(release, "src", "xspice", "icm", "Ngveri",
                        name, "cfunc.o"))
    _write(os.path.join(xml, "Ngveri", name + ".xml"), "<x/>")
    _write(os.path.join(digital, "modpath.lst"),
           (name + "\n") if modpath_line else "")


def _build_cosim(tab, name):
    """Everything a completed d_cosim build leaves behind."""
    root, digital, release, xml = tab._paths
    vvp = CosimConfig.cosim_vvp_target(name)
    _write(vvp, "vvp")
    _write(os.path.join(os.path.dirname(vvp), "connection_info.txt"),
           "clk input 1\n")
    _write(os.path.join(xml, "NgVeriCosim", name + ".xml"), "<x/>")
    return vvp


def _ngveri_intact(tab, name):
    root, digital, release, xml = tab._paths
    return {
        "ifspec": os.path.isfile(os.path.join(digital, name, "ifspec.ifs")),
        "cfunc": os.path.isfile(os.path.join(digital, name, "cfunc.mod")),
        "release": os.path.isfile(os.path.join(
            release, "src", "xspice", "icm", "Ngveri", name, "cfunc.o")),
        "xml": os.path.isfile(os.path.join(xml, "Ngveri", name + ".xml")),
        "modpath": open(os.path.join(digital, "modpath.lst")).read().split(),
    }


# --------------------------------------------------------------------------- #
#  The two teardowns are isolated from each other
# --------------------------------------------------------------------------- #
def test_removing_a_cosim_model_leaves_the_ngveri_build_untouched(tab):
    """The original bug: a d_cosim teardown deleted the Verilator sources."""
    _build_ngveri(tab, "counter")
    vvp = _build_cosim(tab, "counter")

    tab._remove_cosim_model("counter", log=_Log())

    assert not os.path.exists(vvp)
    assert _ngveri_intact(tab, "counter") == {
        "ifspec": True, "cfunc": True, "release": True, "xml": True,
        "modpath": ["counter"],
    }


def test_removing_an_ngveri_model_leaves_the_cosim_build_untouched(tab):
    """The mirror image: the legacy teardown must not eat the vvp."""
    _build_ngveri(tab, "counter")
    vvp = _build_cosim(tab, "counter")
    _, digital, _, xml = tab._paths

    tab._remove_ngveri_model("counter", rebuild=False, log=_Log())

    assert os.path.isfile(vvp)
    assert os.path.isfile(os.path.join(xml, "NgVeriCosim", "counter.xml"))
    assert not os.path.exists(os.path.join(digital, "counter"))


def test_the_two_build_roots_are_siblings_not_nested(tab):
    """A d_cosim tree INSIDE Ngveri/ would put it back in rmtree's path."""
    cosim_root = os.path.abspath(CosimConfig.cosim_build_root())
    legacy_root = os.path.abspath(tab.digital_home)
    assert os.path.dirname(cosim_root) == os.path.dirname(legacy_root)
    assert os.path.commonpath([cosim_root, legacy_root]) != legacy_root


# --------------------------------------------------------------------------- #
#  No half-removals
# --------------------------------------------------------------------------- #
def test_ngveri_teardown_removes_the_release_dir_too(tab):
    """Deleting only the sources leaves the compiled .o linked into ngspice --
    the model looks removed and keeps answering."""
    _build_ngveri(tab, "counter")

    tab._remove_ngveri_model("counter", rebuild=False, log=_Log())

    state = _ngveri_intact(tab, "counter")
    assert state["ifspec"] is False
    assert state["release"] is False
    assert state["xml"] is False
    assert state["modpath"] == []


def test_cosim_teardown_removes_the_whole_model_dir(tab):
    """Sources and connection_info go with the vvp: a leftover dir is listed
    again on the next open, so removal would look broken."""
    vvp = _build_cosim(tab, "counter")
    _, _, _, xml = tab._paths

    tab._remove_cosim_model("counter", log=_Log())

    assert not os.path.exists(os.path.dirname(vvp))
    assert not os.path.isfile(os.path.join(xml, "NgVeriCosim", "counter.xml"))


# --------------------------------------------------------------------------- #
#  Models built BEFORE the split, whose vvp sits in the legacy dir
# --------------------------------------------------------------------------- #
def test_a_presplit_vvp_is_removed_but_never_its_directory(tab):
    """The old shared location may be a legacy build dir, so only the FILE may
    go."""
    _build_ngveri(tab, "counter")
    stale = CosimConfig.legacy_cosim_vvp_path("counter")
    _write(stale, "vvp")
    _write(os.path.join(tab._xml_loc, "NgVeriCosim", "counter.xml"), "<x/>")

    tab._remove_cosim_model("counter", log=_Log())

    assert not os.path.exists(stale)
    assert _ngveri_intact(tab, "counter")["ifspec"] is True


def test_an_ngveri_teardown_rescues_a_live_models_presplit_vvp(tab):
    """Removing the NgVeri model must not destroy a d_cosim model that is still
    in KiCad -- its only artifact happens to live in the doomed directory."""
    _build_ngveri(tab, "counter")
    stale = CosimConfig.legacy_cosim_vvp_path("counter")
    _write(stale, "vvp")
    _write(os.path.join(tab._xml_loc, "NgVeriCosim", "counter.xml"), "<x/>")

    tab._remove_ngveri_model("counter", rebuild=False, log=_Log())

    assert not os.path.exists(stale)
    assert os.path.isfile(CosimConfig.cosim_vvp_target("counter"))


def test_a_presplit_vvp_of_a_removed_cosim_model_is_not_resurrected(tab):
    """No NgVeriCosim param XML == no live d_cosim model, so there is nothing
    to rescue and the stale file goes with its directory."""
    _build_ngveri(tab, "counter")
    stale = _write(CosimConfig.legacy_cosim_vvp_path("counter"), "vvp")

    tab._remove_ngveri_model("counter", rebuild=False, log=_Log())

    assert not os.path.exists(stale)
    assert not os.path.exists(CosimConfig.cosim_vvp_target("counter"))


def test_the_reader_finds_a_presplit_vvp_but_prefers_the_new_one(tab):
    """Pre-split models keep simulating; a rebuilt one wins."""
    legacy = _write(CosimConfig.legacy_cosim_vvp_path("counter"), "old")
    assert CosimConfig.cosim_vvp_path("counter") == legacy

    target = _write(CosimConfig.cosim_vvp_target("counter"), "new")
    assert CosimConfig.cosim_vvp_path("counter") == target


# --------------------------------------------------------------------------- #
#  The switch guard, which decides whether coexistence is created at all
# --------------------------------------------------------------------------- #
def test_switch_guard_sees_an_ngveri_model_with_no_modpath_line(tab):
    """modpath.lst is not proof of existence: a ghost line is pruned while the
    files stay, and an interrupted teardown leaves the same state. Checking the
    line alone let a d_cosim build start silently on top of a live model."""
    _build_ngveri(tab, "counter", modpath_line=False)
    assert tab._legacy_registered("counter") is True


def test_switch_guard_sees_an_ngveri_model_left_only_in_the_release_tree(tab):
    _, digital, release, _ = tab._paths
    _write(os.path.join(release, "src", "xspice", "icm", "Ngveri",
                        "counter", "cfunc.c"))
    _write(os.path.join(release, "src", "xspice", "icm", "Ngveri",
                        "counter", "cfunc.o"))
    _write(os.path.join(digital, "modpath.lst"), "")
    assert tab._legacy_registered("counter") is True


def test_switch_guard_ignores_a_name_no_backend_owns(tab):
    _write(os.path.join(tab.digital_home, "modpath.lst"), "")
    assert tab._legacy_registered("counter") is False
    assert tab._cosim_registered("counter") is False


def test_switch_guard_matches_a_modpath_line_of_a_different_case(tab):
    """On Windows "Counter" and "counter" are one directory, so a guard that
    compares exactly answers False about a tree rmtree would happily delete."""
    _write(os.path.join(tab.digital_home, "modpath.lst"), "Counter\n")
    assert tab._legacy_registered("counter") is True


def test_switch_guard_sees_a_cosim_model_with_only_a_build_dir(tab):
    """A d_cosim build that died before writing its XML still owns the name."""
    _write(os.path.join(CosimConfig.cosim_build_dir("counter"),
                        "connection_info.txt"), "clk input 1\n")
    assert tab._cosim_registered("counter") is True


# --------------------------------------------------------------------------- #
#  Identity: one name resolves to one backend, the same way on every OS
# --------------------------------------------------------------------------- #
def test_resolve_backend_is_not_fooled_by_a_differently_cased_xml(tmp_path):
    """os.path.isfile answers True for "counter.xml" when asked about
    "Counter.xml" on Windows, which handed a row badged NgVeri to the d_cosim
    dismantler. Listing the directory answers the same on both platforms."""
    xml = tmp_path / "xml"
    (xml / "NgVeriCosim").mkdir(parents=True)
    (xml / "Nghdl").mkdir()
    _write(str(xml / "NgVeriCosim" / "counter.xml"), "<x/>")

    assert _resolve_backend(str(xml), "counter") == "cosim"
    assert _resolve_backend(str(xml), "Counter") == "ngveri"
    assert _dir_has_name(str(xml / "NgVeriCosim"), "Counter.xml") is False


def test_cosim_model_id_is_the_one_canonical_name():
    assert CosimConfig.cosim_model_id("  Counter ") == "counter"
    assert CosimConfig.cosim_model_id("") == ""
    assert CosimConfig.cosim_model_id(None) == ""


def test_teardown_deletes_by_the_directory_case_that_is_on_disk(tab):
    """The name reaching the teardown comes from a modpath line or a symbol
    block, which need not match the directory's case. rmtree on the wrong case
    is a silent no-op on Linux and the model reappears in the next listing."""
    _, digital, _, _ = tab._paths
    _write(os.path.join(digital, "Counter", "ifspec.ifs"))
    assert _actual_subdir_name(digital, "counter") == "Counter"

    tab._remove_ngveri_model("counter", rebuild=False, log=_Log())
    assert not os.path.exists(os.path.join(digital, "Counter"))


def test_an_exact_match_wins_over_a_case_folded_one(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "counter").mkdir()
    try:
        (base / "Counter").mkdir()
    except OSError:                     # case-insensitive filesystem: one dir
        assert _actual_subdir_name(str(base), "counter") == "counter"
        return
    assert _actual_subdir_name(str(base), "counter") == "counter"
    assert _actual_subdir_name(str(base), "Counter") == "Counter"
    # Ambiguous fold with no exact match -> refuse rather than guess.
    assert _actual_subdir_name(str(base), "COUNTER") is None


# --------------------------------------------------------------------------- #
#  Blank / hostile names must never reach rmtree
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["", "   ", ".", "..", "a/b", "a\\b"])
def test_a_blank_or_traversing_name_deletes_nothing(tab, name):
    """os.path.join(base, "") collapses to the base directory: one unguarded
    blank name would rmtree every model at once."""
    _build_ngveri(tab, "counter")
    _build_cosim(tab, "counter")
    before = sorted(os.listdir(tab.digital_home)), \
        sorted(os.listdir(CosimConfig.cosim_build_root()))

    tab._remove_cosim_model(name, log=_Log())
    tab._remove_ngveri_model(name, rebuild=False, log=_Log())

    assert (sorted(os.listdir(tab.digital_home)),
            sorted(os.listdir(CosimConfig.cosim_build_root()))) == before


# --------------------------------------------------------------------------- #
#  Discovery: every leftover is listed, and each under the right backend
# --------------------------------------------------------------------------- #
def test_discovery_lists_a_failed_cosim_build(tab):
    """A d_cosim build that produced sources but no vvp is still a leftover the
    user has to be able to delete."""
    _write(os.path.join(CosimConfig.cosim_build_dir("counter"),
                        "connection_info.txt"), "clk input 1\n")
    badges = discover_ngveri_models(
        tab.digital_home, tab.release_dir, tab._xml_loc,
        cosim_home=CosimConfig.cosim_build_root())
    assert badges == {"counter": "d_cosim"}


def test_discovery_attributes_each_build_dir_to_the_tree_it_sits_in(tab):
    """Distinct names, so nothing can be hidden by badge precedence."""
    _build_ngveri(tab, "adder")
    _build_cosim(tab, "toggle")
    badges = discover_ngveri_models(
        tab.digital_home, tab.release_dir, tab._xml_loc,
        cosim_home=CosimConfig.cosim_build_root())
    assert badges == {"adder": "NgVeri", "toggle": "d_cosim"}


def test_a_removed_model_disappears_from_the_listing(tab):
    """The end-to-end promise: remove one of two models and exactly the other
    is left, with no trace of the first anywhere on disk."""
    _build_ngveri(tab, "adder")
    _build_cosim(tab, "toggle")

    tab._remove_cosim_model("toggle", log=_Log())

    badges = discover_ngveri_models(
        tab.digital_home, tab.release_dir, tab._xml_loc,
        cosim_home=CosimConfig.cosim_build_root())
    assert badges == {"adder": "NgVeri"}
    assert _ngveri_intact(tab, "adder")["release"] is True

    tab._remove_ngveri_model("adder", rebuild=False, log=_Log())

    badges = discover_ngveri_models(
        tab.digital_home, tab.release_dir, tab._xml_loc,
        cosim_home=CosimConfig.cosim_build_root())
    assert badges == {}
    assert os.listdir(tab.digital_home) == ["modpath.lst"]
    assert os.listdir(CosimConfig.cosim_build_root()) == []
    assert os.listdir(os.path.join(tab.release_dir, "src", "xspice", "icm",
                                   "Ngveri")) == []


def test_removal_is_idempotent(tab):
    """A second removal of the same name must be a clean no-op, not a crash --
    the dialog can list a name whose files a previous run already took."""
    _build_ngveri(tab, "counter")
    _build_cosim(tab, "toggle")
    for _ in range(2):
        tab._remove_ngveri_model("counter", rebuild=False, log=_Log())
        tab._remove_cosim_model("toggle", log=_Log())
    assert os.listdir(CosimConfig.cosim_build_root()) == []


def test_teardown_survives_a_model_dir_that_is_not_a_directory(tab):
    """Half-created state: a plain file where the build dir should be."""
    _write(os.path.join(tab.digital_home, "counter"), "not a dir")
    shutil.rmtree(CosimConfig.cosim_build_root(), ignore_errors=True)

    tab._remove_ngveri_model("counter", rebuild=False, log=_Log())
    tab._remove_cosim_model("counter", log=_Log())
