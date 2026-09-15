"""
Unit tests for projManagement.projectPaths.previous_values_path.

These pin the behaviour that makes the kicadtoNgspice "remembered values" cache
safe to relocate out of the (shareable) project folder and into the user's
~/.esim area:

    * the cache lives under ~/.esim/prevvalues/, never in the project;
    * it is keyed by the project's *canonical* identity, so the same project
      always maps to the same file and two same-named projects in different
      folders never collide;
    * a legacy in-project <stem>_Previous_Values.xml is lazily, non-
      destructively migrated the first time the new path is requested.

HOME is redirected to a tmp dir in every test so the real ~/.esim is untouched.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))          # .../src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from projManagement.projectPaths import previous_values_path  # noqa: E402


def _redirect_home(monkeypatch, home):
    """Point ~ at `home` on every platform expanduser cares about."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))        # Windows
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)


def _mkproj(root, folder, stem):
    """Create <root>/<folder>/ and return the project's .cir path inside it."""
    proj_dir = os.path.join(str(root), folder)
    os.makedirs(proj_dir, exist_ok=True)
    return os.path.join(proj_dir, stem + ".cir")


def test_cache_lives_under_esim_not_in_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _redirect_home(monkeypatch, home)
    cir = _mkproj(tmp_path / "ws", "projA", "MACProject")

    path = previous_values_path(cir)

    expected_dir = os.path.join(str(home), ".esim", "prevvalues")
    assert os.path.dirname(path) == expected_dir
    assert path.endswith("_Previous_Values.xml")
    # Never written next to the schematic.
    assert not os.path.exists(
        os.path.join(os.path.dirname(cir), "MACProject_Previous_Values.xml"))
    # The directory is created eagerly so callers can write straight away.
    assert os.path.isdir(expected_dir)


def test_same_stem_different_folder_does_not_collide(tmp_path, monkeypatch):
    _redirect_home(monkeypatch, tmp_path / "home")
    a = _mkproj(tmp_path / "ws", "projA", "MACProject")
    b = _mkproj(tmp_path / "ws", "projB", "MACProject")

    assert previous_values_path(a) != previous_values_path(b)


def test_same_project_spelled_differently_is_stable(tmp_path, monkeypatch):
    _redirect_home(monkeypatch, tmp_path / "home")
    cir = _mkproj(tmp_path / "ws", "projA", "MACProject")

    # '<dir>/MACProject.cir' and '<dir>/../projA/MACProject.cir' are the same
    # project; canonical keying must collapse them to one cache file.
    weird = os.path.join(
        os.path.dirname(cir), "..", "projA", "MACProject.cir")
    assert previous_values_path(cir) == previous_values_path(weird)


def test_different_stem_same_folder_does_not_collide(tmp_path, monkeypatch):
    _redirect_home(monkeypatch, tmp_path / "home")
    proj_dir = tmp_path / "ws" / "projA"
    os.makedirs(proj_dir, exist_ok=True)
    a = os.path.join(str(proj_dir), "Amp.cir")
    b = os.path.join(str(proj_dir), "Filter.cir")

    assert previous_values_path(a) != previous_values_path(b)


def test_lazy_migration_copies_legacy_in_project_file(tmp_path, monkeypatch):
    _redirect_home(monkeypatch, tmp_path / "home")
    cir = _mkproj(tmp_path / "ws", "projA", "MACProject")
    legacy = os.path.join(
        os.path.dirname(cir), "MACProject_Previous_Values.xml")
    with open(legacy, "w") as fh:
        fh.write("<KicadtoNgspice><model>remembered</model></KicadtoNgspice>")

    path = previous_values_path(cir)

    assert os.path.exists(path), "legacy values should be migrated forward"
    with open(path) as fh:
        assert "remembered" in fh.read()
    # Migration is non-destructive: the legacy file stays put.
    assert os.path.exists(legacy)


def test_no_legacy_means_no_file_until_written(tmp_path, monkeypatch):
    _redirect_home(monkeypatch, tmp_path / "home")
    cir = _mkproj(tmp_path / "ws", "projA", "MACProject")

    path = previous_values_path(cir)

    # Path is resolved (dir exists) but nothing is fabricated to read.
    assert not os.path.exists(path)


def test_migration_runs_once_and_does_not_clobber_new(tmp_path, monkeypatch):
    _redirect_home(monkeypatch, tmp_path / "home")
    cir = _mkproj(tmp_path / "ws", "projA", "MACProject")
    legacy = os.path.join(
        os.path.dirname(cir), "MACProject_Previous_Values.xml")
    with open(legacy, "w") as fh:
        fh.write("<old/>")

    path = previous_values_path(cir)            # migrates <old/>
    with open(path, "w") as fh:                 # user converts, cache updates
        fh.write("<new/>")

    # A second call must NOT re-migrate the legacy file over the fresh cache.
    path2 = previous_values_path(cir)

    assert path == path2
    with open(path2) as fh:
        assert fh.read() == "<new/>"
