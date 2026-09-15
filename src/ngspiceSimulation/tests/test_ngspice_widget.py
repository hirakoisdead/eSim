"""Unit tests for the pure helpers on NgspiceWidget.

These avoid constructing the widget (which would launch ngspice); they exercise
the rawfile-path derivation and terminal resolution in isolation.
"""
import shutil

from ngspiceSimulation.NgspiceWidget import NgspiceWidget


# ── _raw_path ─────────────────────────────────────────────────────────────

def test_raw_path_strips_cir_out():
    assert NgspiceWidget._raw_path("/p/foo.cir.out") == "/p/foo.raw"


def test_raw_path_other_suffix_swaps_extension():
    assert NgspiceWidget._raw_path("/p/foo.cir") == "/p/foo.raw"


def test_raw_path_never_equals_netlist():
    # The old str.replace('.cir.out', '.raw') was a no-op here and let ngspice
    # overwrite the netlist via '-r'. The derived path must always differ.
    for netlist in ("/p/foo", "/p/foo.txt", "/p/bar.cir.out"):
        assert NgspiceWidget._raw_path(netlist) != netlist


# ── _resolve_terminal ─────────────────────────────────────────────────────

def test_resolve_terminal_prefers_first_available(monkeypatch):
    # xterm present -> chosen with its -hold template, before the fallbacks.
    monkeypatch.setattr(shutil, "which",
                        lambda name: "/usr/bin/xterm" if name == "xterm" else None)
    path, template = NgspiceWidget._resolve_terminal()
    assert path == "/usr/bin/xterm"
    assert template[:2] == ["-hold", "-e"]


def test_resolve_terminal_falls_back_when_no_xterm(monkeypatch):
    # No xterm, but gnome-terminal exists -> fallback with its -- template.
    def which(name):
        return "/usr/bin/gnome-terminal" if name == "gnome-terminal" else None
    monkeypatch.setattr(shutil, "which", which)
    path, template = NgspiceWidget._resolve_terminal()
    assert path == "/usr/bin/gnome-terminal"
    assert template[0] == "--"


def test_resolve_terminal_none_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert NgspiceWidget._resolve_terminal() is None
