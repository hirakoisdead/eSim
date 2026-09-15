# ngspiceSimulation/_palette.py
"""Theme-aware color palette shared by every plotting widget.

The plotting surface has three independent color sources:

  1. The active light/dark theme (chosen by the user in preferences.json).
  2. The user-selected accent color (also in preferences.json).
  3. The trace color table (``constants.VIBRANT_COLOR_PALETTE``) which is data,
     not chrome, and stays the same across themes so existing user configs
     keep the colors they expect.

This module exposes ``current_palette()`` — a dict of named tokens — that the
plotting widgets read at construction time to build their stylesheets and to
feed matplotlib's ``rcParams``. The palette is a flat string-only dict so the
plotting stylesheet f-string can interpolate it directly without converting to
``QColor`` first.

The module never imports from frontEnd/ — it's a leaf helper, so the
backend plotting tree stays importable in headless tests.
"""
from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets


# Fallback defaults if the runtime can't reach the live QApplication.
_LIGHT_DEFAULTS: Dict[str, Any] = {
    "is_dark": False,
    # Surfaces
    "bg":            "#FFFFFF",
    "surface":       "#FAFBFC",
    "panel":         "#FFFFFF",
    "panel_alt":     "#F3F4F6",
    # Borders / dividers
    "border":        "#E5E7EB",
    "border_strong": "#D1D5DB",
    "divider":       "#E5E7EB",
    "spine_separator": "#BDBDBD",
    # Text
    "text":          "#1F2937",
    "text_muted":    "#6B7280",
    "text_subtle":   "#9CA3AF",
    # Brand
    "primary":       "#165982",
    "primary_hover": "#1E88E5",
    "primary_pressed": "#0E4D7A",
    # Overlays
    "hover_overlay":   "rgba(0,0,0,0.04)",
    "pressed_overlay": "rgba(0,0,0,0.07)",
    "selection_bg":    "#E3F2FD",
    "selection_text":  "#1F2937",
    # Plotting axes/legend/grid
    "axes_face":     "#FFFFFF",
    "axes_edge":     "#E5E7EB",
    "label_color":   "#1F2937",
    "tick_color":    "#6B7280",
    "grid_color":    "#E5E7EB",
    "legend_face":   "#FFFFFF",
    "legend_edge":   "#E0E0E0",
    "stats_text":    "#444444",
    "info_text":     "#757575",
    # Cursor UI
    "cursor1":       "#e53935",
    "cursor2":       "#1976d2",
    "cursor_delta":  "#e65100",
    "cursor_chrome": "#999999",   # "@" / undefined-state labels
    "cursor_dim":    "#555555",   # dimmed trace names in rows
    "cursor_disabled": "#AAAAAA", # "not set" / "—" placeholders
}

_DARK_DEFAULTS: Dict[str, Any] = {
    "is_dark": True,
    # Surfaces
    "bg":            "#0B1220",
    "surface":       "#111827",
    "panel":         "#1F2937",
    "panel_alt":     "#374151",
    # Borders / dividers
    "border":        "#1F2937",
    "border_strong": "#3B4A5F",
    "divider":       "#2C3A4F",
    "spine_separator": "#475569",
    # Text
    "text":          "#F1F5F9",
    "text_muted":    "#94A3B8",
    "text_subtle":   "#64748B",
    # Brand (replaced by accent color when user has set one)
    "primary":       "#3B82F6",
    "primary_hover": "#60A5FA",
    "primary_pressed": "#1D4ED8",
    # Overlays
    "hover_overlay":   "rgba(255,255,255,0.06)",
    "pressed_overlay": "rgba(255,255,255,0.10)",
    "selection_bg":    "rgba(59,130,246,0.18)",
    "selection_text":  "#F1F5F9",
    # Plotting axes/legend/grid
    "axes_face":     "#0B1220",
    "axes_edge":     "#1F2937",
    "label_color":   "#F1F5F9",
    "tick_color":    "#94A3B8",
    "grid_color":    "#1F2937",
    "legend_face":   "#111827",
    "legend_edge":   "#2C3A4F",
    "stats_text":    "#CBD5E1",
    "info_text":     "#94A3B8",
    # Cursor UI — brighter variants for dark mode contrast.
    "cursor1":       "#ef5350",
    "cursor2":       "#42a5f5",
    "cursor_delta":  "#ffb74d",
    "cursor_chrome": "#94A3B8",
    "cursor_dim":    "#94A3B8",
    "cursor_disabled": "#64748B",
}


def _read_pref(pref: str, default: str) -> str:
    """Read a single key from ``~/.esim/preferences.json``."""
    try:
        home = os.path.expanduser("~")
        path = os.path.join(home, ".esim", "preferences.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            v = data.get(pref)
            if v:
                return str(v)
    except Exception:
        pass
    return default


def _detect_is_dark(app: Optional[QtWidgets.QApplication]) -> bool:
    """Decide whether we're rendering in dark mode.

    Priority: explicit ``theme_mode`` pref → live palette lightness → system
    colorScheme(). The palette branch is what catches a user overriding the
    palette programmatically (e.g. by a toggle that calls setPalette).
    """
    mode = _read_pref("theme_mode", "System")
    if mode == "Dark":
        return True
    if mode == "Light":
        return False

    if app is not None:
        try:
            win = app.palette().color(QtGui.QPalette.ColorRole.Window)
            if win.isValid() and win.lightness() < 128:
                return True
        except Exception:
            pass
        try:
            # colorScheme() needs Qt >= 6.5; on Ubuntu 24.04 (Qt 6.4) the
            # palette-lightness branch above is the only system signal.
            hints = QtGui.QGuiApplication.styleHints()
            if hasattr(hints, "colorScheme"):
                return hints.colorScheme() == QtCore.Qt.ColorScheme.Dark
        except Exception:
            pass
        return False
    return False


def current_palette(app: Optional[QtWidgets.QApplication] = None) -> Dict[str, Any]:
    """Return the theme-aware color dict for the plotting module.

    Reads preferences.json for ``theme_mode``, ``accent_color``,
    ``secondary_accent_color`` and ``internal_bg_color``. If the live app
    already has a palette set (after ``apply_theme()`` runs), we honor that
    by deriving ``text``/``bg``/``surface`` from the active palette so the
    widgets line up with the rest of eSim.
    """
    app = app or QtWidgets.QApplication.instance()
    dark = _detect_is_dark(app)
    palette: Dict[str, Any] = dict(_DARK_DEFAULTS if dark else _LIGHT_DEFAULTS)

    # Honor the accent color the user picked, if any.
    accent_pref = _read_pref("accent_color", "default")
    if accent_pref and accent_pref != "default":
        palette["primary"] = accent_pref

    # Match surfaces with whatever apply_theme wired into the global palette,
    # so opening a plotting window mid-session aligns with the rest of eSim.
    if app is not None:
        try:
            q_pal = app.palette()
            palette["bg"]       = q_pal.color(QtGui.QPalette.ColorRole.Base).name().upper() \
                                  if dark else q_pal.color(QtGui.QPalette.ColorRole.Base).name()
            palette["panel"]    = q_pal.color(QtGui.QPalette.ColorRole.Base).name()
            palette["surface"]  = q_pal.color(QtGui.QPalette.ColorRole.Window).name()
            palette["text"]     = q_pal.color(QtGui.QPalette.ColorRole.Text).name()
            palette["text_muted"] = q_pal.color(QtGui.QPalette.ColorRole.PlaceholderText).name() \
                                    if hasattr(QtGui.QPalette.ColorRole, "PlaceholderText") else palette["text_muted"]
        except Exception:
            # Stay with the static defaults if the palette isn't ready yet.
            pass

    return palette


def matplotlib_rc_overrides(palette: Dict[str, Any]) -> Dict[str, Any]:
    """Translate the plotting palette to a matplotlib ``rcParams`` update dict.

    Returned dict can be splatted into ``plt.rcParams.update(...)``. Only the
    keys that affect the plotting surface are included; theme/blur/anim keys
    stay at matplotlib's defaults.
    """
    return {
        "figure.facecolor":      palette["bg"],
        "axes.facecolor":        palette["axes_face"],
        "axes.edgecolor":        palette["axes_edge"],
        "axes.labelcolor":       palette["label_color"],
        "xtick.color":           palette["tick_color"],
        "ytick.color":           palette["tick_color"],
        "text.color":            palette["label_color"],
        "grid.color":            palette["grid_color"],
        "legend.facecolor":      palette["legend_face"],
        "legend.edgecolor":      palette["legend_edge"],
        "legend.labelcolor":     palette["label_color"],
        "savefig.facecolor":     palette["bg"],
        "savefig.edgecolor":     palette["bg"],
    }
