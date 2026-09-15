"""Behavioral tests for DesignBus -- the single source of truth shared by the
Author / Verify / Convert stages.

These pin the contract the Flow Navigator relies on: in-app sync is in memory,
disk is persistence only (explicit Save + a lazy ``materialize`` before
Convert), and the external-edit watch is echo-proof -- it ignores any disk
event whose bytes match what we last wrote, so our own writes never nag.
"""
import hashlib
import os

import pytest

pytest.importorskip("watchdog")     # declared dep; skip cleanly if absent

from maker.DesignBus import DesignBus     # noqa: E402
from maker import Maker                    # noqa: E402


def _h(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def bus(qapp):
    b = DesignBus(0)
    yield b
    b.close()


# --- in-memory model (no disk) ------------------------------------------

def test_content_round_trip_in_memory(bus):
    seen = []
    bus.contentChanged.connect(seen.append)
    bus.set_content("module a; endmodule")
    assert bus.get_content() == "module a; endmodule"
    assert seen == ["module a; endmodule"]


def test_set_same_content_is_noop(bus):
    bus.set_content("x")
    seen = []
    bus.contentChanged.connect(seen.append)
    bus.set_content("x")            # identical -> must not re-emit / loop
    assert seen == []


def test_set_content_does_not_touch_disk(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_path(str(f))
    bus.set_content("module a; endmodule")
    assert not f.exists()           # in-memory only; persistence is explicit


def test_is_dirty_tracks_unpersisted_content(bus):
    assert not bus.is_dirty()       # empty, never persisted
    bus.set_content("x")
    assert bus.is_dirty()           # has content, no disk copy yet


# --- disk I/O (the only place that reads/writes the design file) ---------

def test_save_to_disk_writes_and_records_hash(bus, tmp_path):
    f = tmp_path / "sub" / "d.v"    # nested -> exercises makedirs
    bus.set_content("module a; endmodule")
    out = bus.save_to_disk(str(f))
    assert out == str(f)
    assert f.read_text() == "module a; endmodule"
    assert bus._saved_hash == _h("module a; endmodule")
    assert not bus.is_dirty()


def test_load_from_disk_sets_content_path_hash(bus, tmp_path):
    f = tmp_path / "d.v"
    f.write_text("module loaded; endmodule")
    seen = []
    bus.contentChanged.connect(seen.append)
    out = bus.load_from_disk(str(f))
    assert out == str(f)
    assert bus.get_content() == "module loaded; endmodule"
    assert bus.path == str(f)
    assert bus._saved_hash == _h("module loaded; endmodule")
    assert seen == ["module loaded; endmodule"]
    assert not bus.is_dirty()


def test_load_missing_file_is_safe(bus, tmp_path):
    assert bus.load_from_disk(str(tmp_path / "nope.v")) == ""
    assert bus.get_content() == ""


# --- materialize (lazy write right before Convert) ----------------------

def test_materialize_writes_when_dirty(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_path(str(f))
    bus.set_content("module a; endmodule")
    assert bus.is_dirty()
    assert bus.materialize() == str(f)
    assert f.read_text() == "module a; endmodule"


def test_materialize_noop_when_fresh(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_content("module a; endmodule")
    bus.save_to_disk(str(f))
    mtime = f.stat().st_mtime_ns
    assert bus.materialize() == str(f)   # already in sync -> no rewrite
    assert f.stat().st_mtime_ns == mtime


def test_materialize_gives_a_pathless_design_a_home(bus):
    """A design authored in eSim and never saved must still reach Convert.

    It used to return "" here -- no path, so nothing written, so Convert
    reported "No Verilog File Chosen" and the design could not be built at all
    without first writing a correctly-named .v in some other editor. Now the
    autosave files it under its own module name and materialize hands back
    that path."""
    bus.set_content("module a; endmodule")
    home = bus.materialize()
    assert home.endswith(os.path.join("VerilogLibrary", "a", "a.v"))
    assert os.path.isfile(home)


def test_materialize_still_returns_empty_for_an_unnameable_design(bus):
    """Nothing to name it after -> nothing written, and no crash. The design
    stays in memory; Convert's parse failure is the error that helps."""
    bus.set_content("// just a comment, no module here\n")
    assert bus.materialize() == ""


# --- external-edit watch: echo-proof ------------------------------------

def test_disk_event_matching_our_write_is_ignored(bus, tmp_path):
    """An event whose bytes equal what we last wrote is our own echo."""
    f = tmp_path / "d.v"
    bus.set_content("module a; endmodule")
    bus.save_to_disk(str(f))        # records _saved_hash for these bytes
    fired = []
    bus.externalChange.connect(fired.append)
    bus._on_disk_event()            # file on disk still == last write
    assert fired == []


def test_disk_event_with_outside_edit_fires(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_content("module a; endmodule")
    bus.save_to_disk(str(f))
    f.write_text("module a; /* edited in vim */ endmodule")  # outside edit
    fired = []
    bus.externalChange.connect(fired.append)
    bus._on_disk_event()
    assert fired == [str(f)]


def test_save_starts_an_observer(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_content("x")
    bus.save_to_disk(str(f))
    assert bus._observer is not None
    assert bus._watch_file == str(f)


# --- legacy slot mirror (NgVeri / ModelGeneration read it as a path) -----

def test_save_mirrors_slot_to_path(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_content("module a; endmodule")
    bus.save_to_disk(str(f))
    assert Maker.verilogFile[0] == str(f)


def test_set_path_mirrors_without_writing(bus, tmp_path):
    f = tmp_path / "d.v"
    bus.set_path(str(f))
    assert Maker.verilogFile[0] == str(f)
    assert not f.exists()
