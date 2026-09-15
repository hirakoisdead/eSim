DEFAULT_WINDOW_WIDTH = 1400
DEFAULT_WINDOW_HEIGHT = 800
DEFAULT_DPI = 100
DEFAULT_FIGURE_SIZE = (10, 8)
DEFAULT_LINE_THICKNESS = 1.5
DEFAULT_VERTICAL_SPACING = 1.2
DEFAULT_ZOOM_FACTOR = 0.9
CURSOR_ALPHA = 0.7
THRESHOLD_ALPHA = 0.5
LEGEND_FONT_SIZE = 9
DEFAULT_EXPORT_DPI = 300

# pane scrolls vertically once MIN_STACKED_PANE_HEIGHT_PX * N exceeds viewport
MIN_STACKED_PANE_HEIGHT_PX = 120
DIVIDER_HIT_TOLERANCE_PX = 6

# Largest inter-pane gap the incremental stacked path may carry over from the
# previous layout, as a fraction of the pane height it would produce. The gap
# is sampled once and reused verbatim for the new (larger) pane count, so
# without a ceiling a gap solved when 2 panes were stacked keeps its absolute
# size while the panes it separates shrink — whitespace grows to dominate the
# figure. A constrained_layout solve lands near 0.35; exceeding this hands the
# placement back to the solver for one draw.
MAX_STACKED_GAP_RATIO = 0.5

# stacked view uses a wider debounce to coalesce a rapid-toggle burst into one rebuild
REFRESH_DEBOUNCE_MS = 80
STACKED_REFRESH_DEBOUNCE_MS = 160

# draw-time decimation: lines longer than DECIMATION_MIN_POINTS are drawn as a
# per-bin min/max envelope (~4 * DECIMATION_BINS points) and re-decimated from
# the raw arrays on zoom, so deep zoom-in never loses samples
DECIMATION_MIN_POINTS = 8000
DECIMATION_BINS = 2000
# debounce for zoom/pan-triggered re-decimation of on-screen lines
REDECIMATE_DEBOUNCE_MS = 150

VIBRANT_COLOR_PALETTE = [
    '#E53935',
    '#1E88E5',
    '#43A047',
    '#FB8C00',
    '#8E24AA',
    '#00ACC1',
    '#D81B60',
    '#6D4C41',
    '#FDD835',
    '#039BE5',
    '#C0CA33',
    '#37474F'
]

TIME_UNIT_THRESHOLD_PS = 1e-9
TIME_UNIT_THRESHOLD_NS = 1e-6
TIME_UNIT_THRESHOLD_US = 1e-3
TIME_UNIT_THRESHOLD_MS = 1

FREQ_UNIT_THRESHOLD_KHZ = 1e3
FREQ_UNIT_THRESHOLD_MHZ = 1e6
FREQ_UNIT_THRESHOLD_GHZ = 1e9

LINE_STYLES = [
    ('-', "Solid"),
    ('--', "Dashed"),
    (':', "Dotted"),
    ('steps-post', "Step (Post)")
]

THICKNESS_OPTIONS = [
    (1.0, "1 px"),
    (1.5, "1.5 px"),
    (2.0, "2 px"),
    (3.0, "3 px")
]
