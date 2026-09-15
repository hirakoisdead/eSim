"""Regression tests for projectPaths.save_project_explorer.

The project registry was written with a plain open('w')+json.dump, which
truncates the target the instant it starts -- a crash mid-write left a
truncated file that Appconfig reads as {}, losing the whole project tree.
The helper writes a temp file and os.replace()s it in atomically.
"""
import json
import os

from projManagement.projectPaths import save_project_explorer


def test_writes_readable_json(tmp_path):
    target = tmp_path / ".projectExplorer.txt"
    data = {"/home/u/projA": ["a.proj"], "/home/u/projB": ["b.proj"]}
    save_project_explorer(str(target), data)
    with open(target) as fh:
        assert json.load(fh) == data


def test_overwrite_is_atomic_no_tmp_left(tmp_path):
    target = tmp_path / ".projectExplorer.txt"
    save_project_explorer(str(target), {"one": [1]})
    save_project_explorer(str(target), {"two": [2]})
    with open(target) as fh:
        assert json.load(fh) == {"two": [2]}
    # No leftover *.json.tmp scratch files.
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []


def test_creates_missing_parent_dir(tmp_path):
    target = tmp_path / "nested" / "dir" / ".projectExplorer.txt"
    save_project_explorer(str(target), {"x": []})
    assert target.exists()


def test_failure_leaves_original_intact(tmp_path, monkeypatch):
    target = tmp_path / ".projectExplorer.txt"
    save_project_explorer(str(target), {"good": [1]})

    # Force the replace step to fail after the temp file is written.
    def boom(src, dst):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(os, "replace", boom)
    try:
        save_project_explorer(str(target), {"bad": [2]})
    except OSError:
        pass
    # Original content survives; no temp scratch left behind.
    with open(target) as fh:
        assert json.load(fh) == {"good": [1]}
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []
