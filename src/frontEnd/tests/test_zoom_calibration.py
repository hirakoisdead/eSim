"""First-run zoom is calibrated to the screen, then owned by the user.

A single shipped default cannot serve every machine: Qt divides the OS scale
factor out before layout, so a 1920x1080 panel at 150% Windows scaling has a
1280x720 *logical* workspace while a 2880x1800 panel at 175% has 1646x1029.
eSim's chrome costs a fixed number of logical pixels, so the same build reads
as "great at 60%" on the first machine and "great at 90%" on the second. These
pin that calibrate_default_zoom() lands on the hand-tuned value for the screen
we measured, and that ensure_zoom_calibrated() never overwrites a user's own
choice.
"""
import json
import os
import sys

import pytest

from PyQt6 import QtCore

from configuration import paths

_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)


class _FakeScreen:
    def __init__(self, width, height):
        self._rect = QtCore.QRect(0, 0, width, height)

    def availableGeometry(self):
        return self._rect


@pytest.mark.parametrize("logical,expected,why", [
    # The calibration anchor: measured on the dev machine (2880x1800 @175%),
    # hand-tuned to 90%.
    ((1646, 1029), 90, "2880x1800 @175%"),
    ((1920, 1080), 90, "1080p @100%"),
    ((1536, 864), 80, "1080p @125%"),
    ((1280, 720), 60, "1080p @150%"),
    ((1366, 768), 70, "common budget laptop @100%"),
    ((1600, 900), 80, "1600x900 @100%"),
    ((1920, 1200), 100, "1920x1200 @100%"),
    ((2560, 1440), 130, "1440p @100%"),
    ((1280, 1024), 70, "narrow 5:4 -- the width term binds, not height"),
])
def test_calibration_matches_the_screen(qapp, logical, expected, why):
    from frontEnd.theme_utils import calibrate_default_zoom
    assert calibrate_default_zoom(_FakeScreen(*logical)) == expected, why


@pytest.mark.parametrize("logical", [(3840, 2160), (5120, 2880)])
def test_calibration_is_clamped_at_the_top(qapp, logical):
    """A 4K panel at 100% OS scaling is a deliberate 'I like small UI' choice;
    don't override it with a 200% zoom."""
    from frontEnd.theme_utils import calibrate_default_zoom
    assert calibrate_default_zoom(_FakeScreen(*logical)) == 150


@pytest.mark.parametrize("logical", [(1024, 600), (800, 600)])
def test_calibration_is_clamped_at_the_bottom(qapp, logical):
    from frontEnd.theme_utils import calibrate_default_zoom
    assert calibrate_default_zoom(_FakeScreen(*logical)) == 60


def test_calibration_lands_on_the_ten_percent_grid(qapp):
    """The value must be one the -/+ buttons could have produced themselves."""
    from frontEnd.theme_utils import calibrate_default_zoom
    for h in range(600, 2200, 17):
        z = calibrate_default_zoom(_FakeScreen(round(h * 16 / 9), h))
        assert z % 10 == 0
        assert 60 <= z <= 150


def test_calibration_survives_a_degenerate_screen(qapp):
    from frontEnd.theme_utils import calibrate_default_zoom
    assert calibrate_default_zoom(_FakeScreen(0, 0)) == 100
    assert calibrate_default_zoom(None) in range(50, 301)  # real primaryScreen


def _point_prefs_at(monkeypatch, tmp_path):
    cfg = os.path.join(str(tmp_path), "preferences.json")
    monkeypatch.setattr(paths, "esim_config_path", lambda *p: cfg)
    return cfg


def test_first_run_writes_a_calibrated_zoom(qapp, tmp_path, monkeypatch):
    cfg = _point_prefs_at(monkeypatch, tmp_path)
    from frontEnd.theme_utils import ensure_zoom_calibrated
    assert ensure_zoom_calibrated(_FakeScreen(1280, 720)) == 60
    with open(cfg) as f:
        assert json.load(f)["zoom_level"] == 60


def test_a_users_own_zoom_is_never_overwritten(qapp, tmp_path, monkeypatch):
    """The whole point: tweak it once, and every later launch keeps it --
    including on a machine whose screen would calibrate to something else."""
    cfg = _point_prefs_at(monkeypatch, tmp_path)
    with open(cfg, "w") as f:
        json.dump({"zoom_level": 130, "theme_mode": "Dark"}, f)

    from frontEnd.theme_utils import ensure_zoom_calibrated
    assert ensure_zoom_calibrated(_FakeScreen(1280, 720)) == 130
    with open(cfg) as f:
        saved = json.load(f)
    assert saved["zoom_level"] == 130
    assert saved["theme_mode"] == "Dark"


def test_calibration_preserves_unrelated_preferences(qapp, tmp_path,
                                                     monkeypatch):
    cfg = _point_prefs_at(monkeypatch, tmp_path)
    with open(cfg, "w") as f:
        json.dump({"theme_mode": "Dark", "accent_color": "#FF0000",
                   "enable_motion": False}, f)

    from frontEnd.theme_utils import ensure_zoom_calibrated
    ensure_zoom_calibrated(_FakeScreen(1920, 1080))
    with open(cfg) as f:
        saved = json.load(f)
    assert saved["zoom_level"] == 90
    assert saved["theme_mode"] == "Dark"
    assert saved["accent_color"] == "#FF0000"
    assert saved["enable_motion"] is False


@pytest.mark.parametrize("junk", ["120", None, 0, 9999, True])
def test_a_corrupt_zoom_value_recalibrates(qapp, tmp_path, monkeypatch, junk):
    """Hand-edited or out-of-range values must not survive into the metrics."""
    cfg = _point_prefs_at(monkeypatch, tmp_path)
    with open(cfg, "w") as f:
        json.dump({"zoom_level": junk}, f)

    from frontEnd.theme_utils import ensure_zoom_calibrated
    assert ensure_zoom_calibrated(_FakeScreen(1280, 720)) == 60


def test_an_unwritable_config_dir_does_not_block_startup(qapp, monkeypatch):
    from frontEnd import theme_utils

    def boom(*_a, **_k):
        raise OSError("read-only config dir")

    monkeypatch.setattr(paths, "esim_config_path",
                        lambda *p: os.path.join(os.sep, "nope", "prefs.json"))
    monkeypatch.setattr(paths, "write_json_atomic", boom)
    # Still returns a usable zoom for this session; recomputes next launch.
    assert theme_utils.ensure_zoom_calibrated(_FakeScreen(1280, 720)) == 60
