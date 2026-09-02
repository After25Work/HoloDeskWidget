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
    "pin": 60,  # wider than the rest to fit "最前面"/"TopMost"
    "lang": 32,
    "color": 32,
    "mode": 32,
    "filter": 32,
}
TOP_BUTTON_ORDER = ["close", "pin", "lang", "color", "mode", "filter"]


def top_button_rects(width):
    rects = {}
    cursor = width - BUTTON_RIGHT_MARGIN
    for key in TOP_BUTTON_ORDER:
        btn_width = TOP_BUTTON_WIDTHS[key]
        left = cursor - btn_width
        rects[key] = (left, BUTTON_ROW_TOP, cursor, BUTTON_ROW_TOP + BUTTON_ROW_HEIGHT)
        cursor = left - BUTTON_GAP
    return rects
