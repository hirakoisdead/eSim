"""Preference writes merge (no key loss) and are atomic.

Appconfig.save_preferences used to rewrite preferences.json with only its four
theme keys, silently dropping zoom_level / enable_motion / any future key.
It now merges into the existing file and writes through paths.write_json_atomic
(tmp + os.replace), so a crash mid-write can't corrupt the file.
"""
import json
import os

from configuration import paths


def test_write_json_atomic_roundtrips(tmp_path):
    target = os.path.join(str(tmp_path), "cfg.json")
    paths.write_json_atomic(target, {"a": 1, "b": [2, 3]})
    with open(target) as f:
        assert json.load(f) == {"a": 1, "b": [2, 3]}


def test_write_json_atomic_leaves_no_tmp_file(tmp_path):
    target = os.path.join(str(tmp_path), "cfg.json")
    paths.write_json_atomic(target, {"x": 1})
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.startswith(".tmp-")]
    assert leftovers == []


def test_save_preferences_preserves_other_keys(tmp_path, monkeypatch):
    cfg = os.path.join(str(tmp_path), "preferences.json")
    # Pre-existing file carries keys save_preferences does not know about.
    with open(cfg, "w") as f:
        json.dump({"zoom_level": 150, "enable_motion": False,
                   "theme_mode": "System"}, f)

    monkeypatch.setattr(paths, "esim_config_path", lambda *p: cfg)

    from configuration.Appconfig import Appconfig
    Appconfig().save_preferences("Dark", "default")

    with open(cfg) as f:
        saved = json.load(f)
    # Theme key updated...
    assert saved["theme_mode"] == "Dark"
    # ...and the unrelated keys survived (the data-loss bug).
    assert saved["zoom_level"] == 150
    assert saved["enable_motion"] is False
