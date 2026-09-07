BUTTON_ROW_TOP = 40
BUTTON_ROW_HEIGHT = 32
BUTTON_GAP = 12
BUTTON_RIGHT_MARGIN = 40

# Top-right button row, ordered from the window's right edge inward. Each
# button's rect is derived from the widths of everything to its right, so
# adding, removing, or resizing a button here can never silently overlap its
# neighbors the way independently hand-picked `width - N` offsets did —
# that pattern is what caused the resize-grip overlap fixed in commit
# eead505 and is why MIN_WIDTH had to be widened to 480 (see the comment on
# it in config.py) when the live-only filter button was added.
TOP_BUTTON_WIDTHS = {
    "close": 32,
    "fullscreen": 32,
    "tray": 32,
    "pin": 60,  # wider than the rest to fit "最前面"/"TopMost"
    "lang": 32,
    "color": 32,
    "font": 32,
    "mode": 32,
    "productions": 32,
    "filter": 32,
}
# "productions" sits right before "filter" here so it lands immediately to
# filter's right on screen -- this list is walked right-to-left (see
# top_button_rects() below), so the LAST key ends up leftmost. Likewise
# "font" sits right after "color" so the two appearance pickers stay
# adjacent on screen. "tray" sits right after "fullscreen" so the row reads
# close/fullscreen/minimize-to-tray left-to-right, the same
# close-maximize-minimize grouping as a normal window's own title-bar
# buttons. A variant with only one production (see
# GridMixin.top_button_rects()) drops "productions" from the order it
# actually passes in, which shifts every button to its left back in to fill
# the gap instead of leaving one.
TOP_BUTTON_ORDER = ["close", "fullscreen", "tray", "pin", "lang", "color", "font", "mode", "productions", "filter"]


def top_button_rects(width, order=TOP_BUTTON_ORDER):
    rects = {}
    cursor = width - BUTTON_RIGHT_MARGIN
    for key in order:
        btn_width = TOP_BUTTON_WIDTHS[key]
        left = cursor - btn_width
        rects[key] = (left, BUTTON_ROW_TOP, cursor, BUTTON_ROW_TOP + BUTTON_ROW_HEIGHT)
        cursor = left - BUTTON_GAP
    return rects


# Production tab strip: sits below the title/subtitle, above the status bar.
# Column count grows with the window (same reflow philosophy as the talent
# grid in widget.py's build_grid_layout) rather than staying fixed, so it
# collapses to one row once the window is wide enough for every production
# and wraps to more rows on a narrow window instead of squeezing labels
# unreadably thin.
TABS_TOP = 76
TABS_MARGIN = 40
TABS_TARGET_WIDTH = 108
TABS_GAP = 6
TAB_ROW_HEIGHT = 28


def production_tab_rects(width, count):
    # Returns (list of (x, y, w, h) in production order, total strip height).
    # count == 0 happens whenever the current variant/manifest has at most one
    # production (see GridMixin.production_tabs()), in addition to the
    # degenerate-data case load_productions() itself already guards against;
    # handled here rather than left to divmod(i, 0) below either way.
    if count <= 0:
        return [], 0
    available = width - TABS_MARGIN - 40
    cols = max(1, min(count, int((available + TABS_GAP) // (TABS_TARGET_WIDTH + TABS_GAP))))
    tab_width = (available - (cols - 1) * TABS_GAP) / cols
    rows = -(-count // cols)  # ceil division
    rects = []
    for index in range(count):
        row, col = divmod(index, cols)
        x = TABS_MARGIN + col * (tab_width + TABS_GAP)
        y = TABS_TOP + row * (TAB_ROW_HEIGHT + TABS_GAP)
        rects.append((x, y, tab_width, TAB_ROW_HEIGHT))
    total_height = rows * TAB_ROW_HEIGHT + (rows - 1) * TABS_GAP
    return rects, total_height
