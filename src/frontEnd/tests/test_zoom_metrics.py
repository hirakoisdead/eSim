"""Sizes set from Python have to move when the zoom pill does.

``zoom_px`` is evaluated once, when the widget is built. A panel constructed at
90% therefore keeps its 90% widths if the user then dials to 150% -- the QSS
metrics around it grow, its own do not, and the labels inside its buttons run
out of the boxes drawn around them. Long-lived surfaces register a hook so they
are re-measured on the settled zoom change; these pin that contract, including
that a dead widget can never keep the registry (or a later zoom change) alive.
"""
import gc
import os
import sys

from PyQt6 import QtWidgets

_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _FRONTEND not in sys.path:
    sys.path.insert(0, _FRONTEND)

from frontEnd import theme_utils as tu          # noqa: E402


def _fresh_registry(monkeypatch):
    hooks = []
    monkeypatch.setattr(tu, "_ZOOM_HOOKS", hooks)
    return hooks


def test_the_hook_runs_immediately(qapp, monkeypatch):
    """Registering is also the initial measurement -- callers should not have
    to set the size once and register the same lambda a second time."""
    _fresh_registry(monkeypatch)
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", 150)
    box = QtWidgets.QWidget()
    seen = []
    tu.on_zoom_changed(box, lambda z: seen.append(z))
    assert seen == [150]
    box.deleteLater()


def test_the_hook_runs_again_on_a_zoom_change(qapp, monkeypatch):
    _fresh_registry(monkeypatch)
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", 100)
    box = QtWidgets.QWidget()
    seen = []
    tu.on_zoom_changed(box, lambda z: seen.append(z))
    tu.reapply_zoom_metrics(150)
    tu.reapply_zoom_metrics(60)
    assert seen == [100, 150, 60]
    box.deleteLater()


def test_it_actually_resizes_the_widget(qapp, monkeypatch):
    _fresh_registry(monkeypatch)
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", 100)
    box = QtWidgets.QWidget()
    tu.on_zoom_changed(box, lambda z, w=box: w.setFixedWidth(tu.zoom_px(210, z)))
    assert box.width() == 210
    tu.reapply_zoom_metrics(150)
    assert box.width() == 315
    tu.reapply_zoom_metrics(60)
    assert box.width() == 126
    box.deleteLater()


def test_a_collected_widget_drops_its_hook(qapp, monkeypatch):
    hooks = _fresh_registry(monkeypatch)
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", 100)
    seen = []

    def register():
        box = QtWidgets.QWidget()
        tu.on_zoom_changed(box, lambda z: seen.append(z))

    register()
    gc.collect()
    tu.reapply_zoom_metrics(150)
    assert hooks == []
    assert seen == [100]


def test_a_deleted_cpp_widget_drops_its_hook(qapp, monkeypatch):
    """sip keeps the Python wrapper alive after the C++ side is gone; touching
    it raises RuntimeError. The registry must shed the hook, not propagate."""
    hooks = _fresh_registry(monkeypatch)
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", 100)
    box = QtWidgets.QWidget()
    tu.on_zoom_changed(box, lambda z, w=box: w.setFixedWidth(tu.zoom_px(10, z)))
    assert len(hooks) == 1

    from PyQt6 import sip
    # Free the C++ object while the lambda still holds the Python wrapper --
    # exactly the state a closed dock leaves behind.
    sip.delete(box)
    tu.reapply_zoom_metrics(150)     # must not raise
    assert hooks == []


def test_a_raising_hook_does_not_stop_the_others(qapp, monkeypatch):
    _fresh_registry(monkeypatch)
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", 100)
    a, b = QtWidgets.QWidget(), QtWidgets.QWidget()
    seen = []

    def boom(_z):
        raise ValueError("badly written hook")

    tu.on_zoom_changed(a, boom)
    tu.on_zoom_changed(b, lambda z: seen.append(z))
    tu.reapply_zoom_metrics(150)
    assert seen == [100, 150]
    a.deleteLater()
    b.deleteLater()


def test_current_zoom_falls_back_to_the_stored_preference(qapp, monkeypatch,
                                                          tmp_path):
    """Widget code can build before the first apply_theme (startup, tests);
    it must still get the user's zoom, not a hard-coded 100."""
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", None)
    monkeypatch.setattr(tu, "get_preferences", lambda *a, **k: {
        "zoom_level": 130})
    assert tu.current_zoom() == 130


def test_a_corrupt_stored_zoom_does_not_reach_the_metrics(qapp, monkeypatch):
    monkeypatch.setattr(tu, "_CURRENT_ZOOM", None)
    for junk in ("120", None, 0, 9999, 49, 301):
        def _prefs(*_a, _j=junk, **_k):
            return {"zoom_level": _j}
        monkeypatch.setattr(tu, "get_preferences", _prefs)
        assert tu.current_zoom() == 100
