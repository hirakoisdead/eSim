"""Appconfig is a plain class whose disk state is loaded by
explicit classmethods, not at import time.

These lock the two properties the refactor bought us:
  1. Importing/instantiating Appconfig performs no file I/O and never raises.
  2. The load_* classmethods seed the shared class-level state, preserving the
     dict identities callers cache.
"""

import json
import os

from configuration.Appconfig import Appconfig


def test_appconfig_is_not_a_qwidget():
    # Dropping the QWidget base is the whole point: no parentless invisible
    # widgets leaked per instantiation. A plain object() has no Qt bases.
    assert not any(
        base.__name__ == "QWidget" for base in Appconfig.__mro__)


def test_instantiation_is_cheap_and_side_effect_free(tmp_path, monkeypatch):
    # Even with HOME pointed at an empty dir (no workspace.txt, no config.ini),
    # constructing Appconfig must not touch disk or raise.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    obj = Appconfig()
    assert obj._APPLICATION == "eSim"


def test_load_workspace_seeds_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    ws = str(tmp_path / "my workspace")
    # write workspace.txt via the same helper the app uses
    from configuration import paths
    paths.write_workspace(1, ws)

    dict_identity = Appconfig.dictPath
    Appconfig.load_workspace()

    assert Appconfig.home == ws
    assert Appconfig.default_workspace["workspace"] == ws
    assert Appconfig.dictPath["path"] == os.path.join(
        ws, ".projectExplorer.txt")
    # identity preserved (mutated in place), not rebound
    assert Appconfig.dictPath is dict_identity


def test_load_project_explorer_updates_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from configuration import paths
    ws = str(tmp_path)
    paths.write_workspace(1, ws)
    Appconfig.load_workspace()

    registry = {"/proj/a": ["a.proj"], "/proj/b": ["b.proj"]}
    with open(Appconfig.dictPath["path"], "w") as fh:
        json.dump(registry, fh)

    pe_identity = Appconfig.project_explorer
    Appconfig.load_project_explorer()

    assert Appconfig.project_explorer == registry
    # identity preserved so cached references stay in sync
    assert Appconfig.project_explorer is pe_identity


def test_load_project_explorer_tolerates_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    Appconfig.dictPath["path"] = str(tmp_path / "does-not-exist.txt")
    Appconfig.load_project_explorer()
    assert Appconfig.project_explorer == {}
