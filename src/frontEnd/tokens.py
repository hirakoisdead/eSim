"""Single source of truth for the eSim 'Aurora' design system.

Nothing else in the codebase should hard-code a brand hex string. Python
painters import THEME/accent helpers from here; ``theme_utils`` uses the
accent values to propagate a custom accent through the whole stylesheet
(including the rgba() glows that the old token-replace step missed).

No external dependencies — pure stdlib + values.
"""

# ── Per-theme palette ────────────────────────────────────────────────
DARK = {
    "bg":            "#05070F",
    "bg_raise":      "#0A1020",
    "surface":       "#0E1728",
    "surface_2":     "#121E33",
    "surface_3":     "#17243B",
    "stroke":        "#1D2B45",
    "text":          "#F4F8FF",
    "text_muted":    "#9FB1CC",
    "text_subtle":   "#5F728D",
    "text_invert":   "#03121C",
    "accent":        "#53D7FF",   # primary accent (cyan)
    "accent_hi":     "#8BEAFF",
    "accent_lo":     "#18A8D8",
    "accent_2":      "#9B7CFF",   # violet companion
    "accent_2_hi":   "#C4B5FD",
    "success":       "#42E6A4",
    "warning":       "#FACC15",
    "danger":        "#FB7185",
    "danger_lo":     "#E11D48",
    "sel_bg":        "#0E7490",
    "sel_fg":        "#FFFFFF",
    "shadow_rgb":    (0, 0, 0),
}

LIGHT = {
    "bg":            "#EEF3FA",
    "bg_raise":      "#F3F7FC",
    "surface":       "#FFFFFF",
    "surface_2":     "#F6F9FD",
    "surface_3":     "#FFFFFF",
    "stroke":        "#DCE6F1",
    "text":          "#142033",
    "text_muted":    "#5A6E89",
    "text_subtle":   "#9AAABE",
    "text_invert":   "#FFFFFF",
    "accent":        "#0077A8",
    "accent_hi":     "#00A4DC",
    "accent_lo":     "#005E86",
    "accent_2":      "#6D5DF6",
    "accent_2_hi":   "#8B7CF8",
    "success":       "#059669",
    "warning":       "#D97706",
    "danger":        "#E11D48",
    "danger_lo":     "#BE123C",
    "sel_bg":        "#0077A8",
    "sel_fg":        "#FFFFFF",
    # blue-grey tinted shadow so light-mode depth reads as soft ambient
    # occlusion instead of an invisible/muddy black.
    "shadow_rgb":    (27, 42, 65),
}

# The default accent's literal rgb, as authored in the .qss files. Used by
# theme_utils to find-and-recolor every rgba(...) glow when the user picks
# a custom accent.
DEFAULT_ACCENT_RGB = {
    "dark":  (83, 215, 255),    # #53D7FF
    "light": (0, 119, 168),     # #0077A8
}

# Shape & rhythm (theme-independent)
RADIUS = {"sm": 8, "md": 12, "lg": 16, "xl": 20, "pill": 999}
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
DUR = {"fast": 130, "base": 180, "slow": 240}  # ms


def theme(is_dark: bool) -> dict:
    return DARK if is_dark else LIGHT


def hex_to_rgb(hexv: str):
    hexv = hexv.lstrip("#")
    return int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16)
