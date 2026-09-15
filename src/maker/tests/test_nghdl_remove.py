"""Tests for the NGHDL (GHDL) model-removal core.

The teardown logic lives in model_teardown as pure, dependency-free functions
(the GUI callers drag in Qt + hdlparse, so they are not importable in a bare
test env). These tests pin the irreversible bits -- modpath line strip, ghost
prune, backend resolution, the blank/`..` rmtree guard -- plus an end-to-end
add->remove->add->remove cycle that composes those helpers with the shared
kicad_symlib symbol writer exactly as the NGHDL app's _remove_nghdl_models
does. The model_teardown module is byte-identical between src/maker and
nghdl/src (drift-guarded below), so this one suite covers both copies.

All pure file ops: no GHDL, ngspice, Qt, or NGHDL install required.
"""
import filecmp
import os
import shutil

import pytest

import maker.model_teardown as mt
import maker.kicad_symlib as ksym


def _block(name):
    return f'(symbol "{name}" (pin_names (offset 0)) (property "Ref" "U"))'


# ── _strip_modpath_line ─────────────────────────────────────────────────────

def _write_modpath(path, names):
    with open(path, "w") as f:
        for n in names:
            f.write(n + "\n")


def _read_modpath(path):
    with open(path) as f:
        return [ln.strip() for ln in f if ln.strip()]


def test_strip_removes_exact_line_only(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["and2", "and2_gate", "mux"])
    assert mt._strip_modpath_line(mp, "and2") is True
    assert _read_modpath(mp) == ["and2_gate", "mux"]   # prefix sibling kept


def test_strip_is_idempotent(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["mux"])
    assert mt._strip_modpath_line(mp, "mux") is True
    assert mt._strip_modpath_line(mp, "mux") is False  # already gone
    assert _read_modpath(mp) == []


def test_strip_blank_name_is_noop(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["mux"])
    assert mt._strip_modpath_line(mp, "   ") is False
    assert mt._strip_modpath_line(mp, "") is False
    assert _read_modpath(mp) == ["mux"]


def test_strip_absent_file_is_noop(tmp_path):
    assert mt._strip_modpath_line(str(tmp_path / "nope.lst"), "mux") is False


# ── _append_modpath_line ────────────────────────────────────────────────────

def test_append_adds_new_name(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["and2", "mux"])
    assert mt._append_modpath_line(mp, "xor2") is True
    assert _read_modpath(mp) == ["and2", "mux", "xor2"]


def test_append_is_idempotent(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["mux"])
    assert mt._append_modpath_line(mp, "mux") is False   # already listed
    assert _read_modpath(mp) == ["mux"]


def test_append_repairs_missing_trailing_newline(tmp_path):
    # A last line without "\n" must not glue to the new
    # name ("muxxor2"); the new entry has to start on its own line.
    mp = str(tmp_path / "modpath.lst")
    with open(mp, "w") as f:
        f.write("and2\nmux")           # no trailing newline
    assert mt._append_modpath_line(mp, "xor2") is True
    assert _read_modpath(mp) == ["and2", "mux", "xor2"]


def test_append_blank_name_is_noop(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["mux"])
    assert mt._append_modpath_line(mp, "   ") is False
    assert mt._append_modpath_line(mp, "") is False
    assert _read_modpath(mp) == ["mux"]


def test_append_creates_missing_file(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    assert mt._append_modpath_line(mp, "mux") is True
    assert _read_modpath(mp) == ["mux"]


# ── _prune_modpath ──────────────────────────────────────────────────────────

def _make_model_dir(base, name, with_marker=True):
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    if with_marker:
        open(os.path.join(d, "ifspec.ifs"), "w").close()


def test_prune_drops_ghost_and_duplicate(tmp_path):
    base = str(tmp_path)
    mp = os.path.join(base, "modpath.lst")
    _make_model_dir(base, "live")
    _make_model_dir(base, "halfbuilt", with_marker=False)  # ghost: no ifspec
    _write_modpath(mp, ["live", "halfbuilt", "live", "gone"])
    dropped = mt._prune_modpath(mp, base)
    assert sorted(dropped) == ["gone", "halfbuilt", "live"]  # dup live + ghosts
    assert _read_modpath(mp) == ["live"]


def test_prune_noop_when_all_valid(tmp_path):
    base = str(tmp_path)
    mp = os.path.join(base, "modpath.lst")
    _make_model_dir(base, "a")
    _make_model_dir(base, "b")
    _write_modpath(mp, ["a", "b"])
    assert mt._prune_modpath(mp, base) == []
    assert _read_modpath(mp) == ["a", "b"]


# ── _resolve_backend ────────────────────────────────────────────────────────

def _touch_xml(xml_loc, sub, name):
    d = os.path.join(xml_loc, sub)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, name + ".xml"), "w").close()


def test_resolve_backend_precedence(tmp_path):
    xml = str(tmp_path)
    assert mt._resolve_backend(xml, "ghost") == "ngveri"     # nothing on disk
    _touch_xml(xml, "Nghdl", "vhd")
    assert mt._resolve_backend(xml, "vhd") == "nghdl"
    _touch_xml(xml, "NgVeriCosim", "ic")
    assert mt._resolve_backend(xml, "ic") == "cosim"
    # cosim wins over nghdl if both ever exist for one name
    _touch_xml(xml, "Nghdl", "both")
    _touch_xml(xml, "NgVeriCosim", "both")
    assert mt._resolve_backend(xml, "both") == "cosim"


def test_resolve_backend_empty_loc_is_ngveri():
    assert mt._resolve_backend("", "anything") == "ngveri"


def test_resolve_backend_falls_back_to_symbol_libs(tmp_path):
    # A model built by an older eSim (or half-removed by one) can own a KiCad
    # symbol with no param XML beside it. Resolving such a leftover as "ngveri"
    # runs the wrong dismantler and the symbol stays in KiCad forever.
    xml = str(tmp_path / "xml")
    cosim_sym = str(tmp_path / "eSim_NgVeriCosim.kicad_sym")
    nghdl_sym = str(tmp_path / "eSim_Nghdl.kicad_sym")
    ksym._write_lib(cosim_sym, {"orphan_ic": _block("orphan_ic")})
    ksym._write_lib(nghdl_sym, {"orphan_vhd": _block("orphan_vhd")})

    assert mt._resolve_backend(xml, "orphan_ic", cosim_sym=cosim_sym) == "cosim"
    assert mt._resolve_backend(xml, "orphan_vhd",
                               nghdl_sym=nghdl_sym) == "nghdl"
    # unknown name -> still legacy ngveri; XML still outranks the symbol libs
    assert mt._resolve_backend(xml, "nobody", cosim_sym=cosim_sym) == "ngveri"
    _touch_xml(xml, "Nghdl", "both")
    assert mt._resolve_backend(xml, "both", cosim_sym=cosim_sym) == "nghdl"


# ── discovery: every on-disk trace, not just modpath.lst ────────────────────
# The remove dialogs used to list modpath.lst (+ NgVeriCosim XMLs) only, so a
# model left behind by an older version -- symbol only, XML only, build dir
# only -- could never be removed from the GUI while KiCad kept showing it.

def _sym(path, *names):
    ksym._write_lib(path, {n: _block(n) for n in names})
    return path


def _ngveri_env(tmp_path):
    digital = tmp_path / "icm" / "Ngveri"
    release = tmp_path / "release"
    xml = tmp_path / "xml"
    (digital).mkdir(parents=True)
    (release / "src" / "xspice" / "icm" / "Ngveri").mkdir(parents=True)
    (release / "src" / "xspice" / "icm" / "ghdl").mkdir(parents=True)
    xml.mkdir()
    return str(digital), str(release), str(xml)


def test_discover_ngveri_unions_every_trace(tmp_path):
    digital, release, xml = _ngveri_env(tmp_path)
    _write_modpath(os.path.join(digital, "modpath.lst"), ["only_modpath"])
    _make_model_dir(digital, "only_srcdir")
    _make_model_dir(os.path.join(release, "src", "xspice", "icm", "Ngveri"),
                    "only_reldir")
    _touch_xml(xml, "Ngveri", "only_xml")
    ngveri_sym = _sym(str(tmp_path / "eSim_Ngveri.kicad_sym"), "only_symbol")
    _touch_xml(xml, "NgVeriCosim", "cosim_xml")
    cosim_sym = _sym(str(tmp_path / "eSim_NgVeriCosim.kicad_sym"),
                     "cosim_symbol")

    badges = mt.discover_ngveri_models(digital, release, xml,
                                       ngveri_sym=ngveri_sym,
                                       cosim_sym=cosim_sym)
    assert sorted(badges) == sorted([
        "only_modpath", "only_srcdir", "only_reldir", "only_xml",
        "only_symbol", "cosim_xml", "cosim_symbol"])
    # The badge must agree with the dismantler _resolve_backend picks.
    assert badges["cosim_symbol"] == "d_cosim"
    assert badges["cosim_xml"] == "d_cosim"
    assert badges["only_symbol"] == "NgVeri"


def test_discover_skips_non_model_dirs(tmp_path):
    # verilated.d / scratch folders share the icm tree with real model dirs;
    # offering them as removable "models" would be nonsense.
    digital, release, xml = _ngveri_env(tmp_path)
    os.makedirs(os.path.join(digital, "verilated.d"))
    assert mt.discover_ngveri_models(digital, release, xml) == {}


def test_discover_cosim_vvp_dir_counts_as_a_model(tmp_path):
    # A d_cosim build dir holds the compiled vvp named exactly like the dir,
    # and none of the cmpp markers.
    digital, release, xml = _ngveri_env(tmp_path)
    os.makedirs(os.path.join(digital, "icmodel"))
    open(os.path.join(digital, "icmodel", "icmodel"), "w").close()
    assert list(mt.discover_ngveri_models(digital, release, xml)) == ["icmodel"]


def test_discover_nghdl_unions_every_trace(tmp_path):
    ghdl = tmp_path / "icm" / "ghdl"
    release = tmp_path / "release"
    xml = tmp_path / "xml"
    ghdl.mkdir(parents=True)
    (release / "src" / "xspice" / "icm" / "ghdl").mkdir(parents=True)
    xml.mkdir()
    _write_modpath(str(ghdl / "modpath.lst"), ["live"])
    _make_model_dir(str(ghdl), "live")
    _make_model_dir(str(ghdl), "halfremoved")
    _make_model_dir(str(release / "src" / "xspice" / "icm" / "ghdl"), "relonly")
    _touch_xml(str(xml), "Nghdl", "xmlonly")
    sym = _sym(str(tmp_path / "eSim_Nghdl.kicad_sym"), "symonly")

    assert mt.discover_nghdl_models(str(ghdl), str(release), str(xml),
                                    nghdl_sym=sym) == [
        "halfremoved", "live", "relonly", "symonly", "xmlonly"]


def test_discover_tolerates_missing_everything(tmp_path):
    # A listing must never be the thing that raises.
    missing = str(tmp_path / "nope")
    assert mt.discover_ngveri_models(missing, "", "", None, None) == {}
    assert mt.discover_nghdl_models(missing, "", "", None) == []
    assert mt._lib_part_names(str(tmp_path / "gone.kicad_sym")) == []
    assert mt._lib_part_names("") == []


# ── _safe_model_subdir guard (rmtree-all protection) ────────────────────────

def test_safe_model_subdir_rejects_dangerous_names(tmp_path):
    base = str(tmp_path)
    for bad in ("", "   ", ".", "..", "a/b", "a" + os.sep + "b"):
        assert mt._safe_model_subdir(base, bad) is None, bad


def test_safe_model_subdir_accepts_plain_name(tmp_path):
    base = str(tmp_path)
    got = mt._safe_model_subdir(base, "mux")
    assert got == os.path.join(os.path.abspath(base), "mux")


def test_nghdl_sym_path_posix(tmp_path, monkeypatch):
    # HOME redirected so we never create/touch the real ~/.esim.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path), 1))
    p = mt._nghdl_sym_path("")
    assert p.endswith("eSim_Nghdl.kicad_sym")
    assert os.path.join(".esim", "kicad_symbols") in p


# ── end-to-end: add -> remove -> add -> remove stays clean ──────────────────

def _add(env, name):
    """Replicate what an NGHDL upload leaves on disk."""
    sym, xml_dir, mp, ghdl, rel = env
    # modpath line (idempotent, like addingModelInModpath)
    existing = _read_modpath(mp) if os.path.exists(mp) else []
    if name not in existing:
        with open(mp, "a") as f:
            f.write(name + "\n")
    # param XML
    os.makedirs(xml_dir, exist_ok=True)
    open(os.path.join(xml_dir, name + ".xml"), "w").close()
    # symbol block
    parts = ksym._read_parts(sym)
    parts[name] = _block(name)
    ksym._write_lib(sym, parts)
    # source + release dirs with the cmpp marker
    _make_model_dir(ghdl, name)
    _make_model_dir(rel, name)


def _remove(env, name):
    """Replicate the NGHDL app's _remove_nghdl_models using the same helpers."""
    sym, xml_dir, mp, ghdl, rel = env
    mt._strip_modpath_line(mp, name)
    parts = ksym._read_parts(sym)
    if parts.pop(name, None) is not None:
        ksym._write_lib(sym, parts)
    try:
        os.remove(os.path.join(xml_dir, name + ".xml"))
    except FileNotFoundError:
        pass
    for base in (ghdl, rel):
        d = mt._safe_model_subdir(base, name)
        if d:
            shutil.rmtree(d, ignore_errors=True)


def _present(env, name):
    sym, xml_dir, mp, ghdl, rel = env
    return {
        "modpath": name in (_read_modpath(mp) if os.path.exists(mp) else []),
        "xml": os.path.exists(os.path.join(xml_dir, name + ".xml")),
        "symbol": name in ksym._read_parts(sym),
        "src": os.path.isdir(os.path.join(ghdl, name)),
        "rel": os.path.isdir(os.path.join(rel, name)),
    }


def test_add_remove_cycle_is_clean(tmp_path):
    env = (
        str(tmp_path / "eSim_Nghdl.kicad_sym"),
        str(tmp_path / "Nghdl"),
        str(tmp_path / "ghdl" / "modpath.lst"),
        str(tmp_path / "ghdl"),
        str(tmp_path / "release"),
    )
    os.makedirs(os.path.dirname(env[2]), exist_ok=True)
    # A second model that must survive every cycle untouched.
    _add(env, "keeper")

    for _ in range(25):
        _add(env, "churn")
        assert all(_present(env, "churn").values())
        _remove(env, "churn")
        assert not any(_present(env, "churn").values())
        # idempotent second remove
        _remove(env, "churn")
        assert not any(_present(env, "churn").values())
        # bystander intact throughout
        assert all(_present(env, "keeper").values())


# ── _ensure_modpath: fresh-tree create-if-missing ───────────────────────────
# The digital-model root is built lazily (the remove dialog or a build makes
# it), so a first-ever convert on a fresh install used to die reading a
# modpath.lst whose directory did not exist yet -- surfacing as a generic
# "Error in Ngspice code model generation" that named nothing.

def test_ensure_modpath_creates_parent_and_file(tmp_path):
    mp = str(tmp_path / "DigitalModelLibrary" / "Ngveri" / "modpath.lst")
    assert mt._ensure_modpath(mp) == mp
    assert os.path.isfile(mp)
    assert open(mp).read() == ""


def test_ensure_modpath_does_not_truncate_existing(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["mux", "and2"])
    mt._ensure_modpath(mp)
    assert _read_modpath(mp) == ["mux", "and2"]     # 'a', never 'w'


def test_ensure_modpath_is_idempotent(tmp_path):
    mp = str(tmp_path / "d" / "modpath.lst")
    mt._ensure_modpath(mp)
    mt._ensure_modpath(mp)
    assert os.path.isfile(mp)


# ── modpath.lst rewrites are atomic ─────────────────────────────────────────
# A crash mid-rewrite leaves a truncated list, and cmpp then aborts the WHOLE
# code-model build -- for every model, not just the one being removed.

def _atomic_leftovers(directory):
    return [n for n in os.listdir(directory) if n.startswith(".eSim_atomic_")]


def test_strip_leaves_no_temp_file(tmp_path):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["and2", "mux"])
    assert mt._strip_modpath_line(mp, "and2") is True
    assert _atomic_leftovers(str(tmp_path)) == []


def test_strip_failure_leaves_list_intact(tmp_path, monkeypatch):
    mp = str(tmp_path / "modpath.lst")
    _write_modpath(mp, ["and2", "mux"])
    before = open(mp).read()

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(ksym.os, "replace", boom)
    with pytest.raises(OSError):
        mt._strip_modpath_line(mp, "and2")

    assert open(mp).read() == before
    assert _atomic_leftovers(str(tmp_path)) == []


def test_prune_failure_leaves_list_intact(tmp_path, monkeypatch):
    base = str(tmp_path)
    mp = os.path.join(base, "modpath.lst")
    os.makedirs(os.path.join(base, "keeper"))
    open(os.path.join(base, "keeper", "ifspec.ifs"), "w").close()
    _write_modpath(mp, ["keeper", "ghost"])
    before = open(mp).read()

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(ksym.os, "replace", boom)
    with pytest.raises(OSError):
        mt._prune_modpath(mp, base)

    assert open(mp).read() == before     # ghost still listed, nothing lost
    assert _atomic_leftovers(base) == []


# ── drift guard: eSim canonical == NGHDL vendored copy ──────────────────────

def test_vendored_teardown_is_byte_identical():
    canonical = mt.__file__
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(canonical)))
    vendored = os.path.join(repo_root, "nghdl", "src", "model_teardown.py")
    assert os.path.exists(vendored), (
        "NGHDL vendored copy missing: " + vendored)
    assert filecmp.cmp(canonical, vendored, shallow=False), (
        "src/maker/model_teardown.py and nghdl/src/model_teardown.py have "
        "drifted; edit one and copy it verbatim to the other.")


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(mt.__file__)))


def test_vendored_remove_dialog_is_byte_identical():
    # The searchable remove-model picker is shared with the NGHDL standalone app
    # by vendoring (it cannot import eSim). Its dual-layout Dialogs import keeps
    # both copies truly identical, so a plain byte compare guards the drift.
    root = _repo_root()
    canonical = os.path.join(root, "src", "maker", "RemoveItemsDialog.py")
    vendored = os.path.join(root, "nghdl", "src", "RemoveItemsDialog.py")
    assert os.path.exists(vendored), (
        "NGHDL vendored copy missing: " + vendored)
    assert filecmp.cmp(canonical, vendored, shallow=False), (
        "src/maker/RemoveItemsDialog.py and nghdl/src/RemoveItemsDialog.py "
        "have drifted; edit one and copy it verbatim to the other.")


def test_vendored_dialogs_is_byte_identical():
    # RemoveItemsDialog needs Dialogs.warning; NGHDL has no configuration pkg,
    # so Dialogs.py (PyQt6-only) is vendored beside it for the flat-import path.
    root = _repo_root()
    canonical = os.path.join(root, "src", "configuration", "Dialogs.py")
    vendored = os.path.join(root, "nghdl", "src", "Dialogs.py")
    assert os.path.exists(vendored), (
        "NGHDL vendored copy missing: " + vendored)
    assert filecmp.cmp(canonical, vendored, shallow=False), (
        "src/configuration/Dialogs.py and nghdl/src/Dialogs.py have drifted; "
        "edit one and copy it verbatim to the other.")
