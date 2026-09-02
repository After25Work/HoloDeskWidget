import colorsys

KEY_COLOR = "#010001"
MIN_LABEL_SIZE = 11
DEFAULT_ACCENT = (39, 199, 255)
MONOCHROME_ACCENT = (255, 255, 255)

# Two full palettes (not just an inverted text/background pair) so the badge,
# neutral-button, outline, divider, and status colors are each hand-picked for
# contrast against their own theme rather than mechanically inverted.
THEMES = {
    "dark": {
        "panel": (18, 18, 26, 245),
        "text": (250, 250, 253, 255),
        "muted": (205, 207, 220, 255),
        "live": (255, 77, 103, 255),
        "error": (255, 157, 77, 255),
        "outline": (52, 55, 70, 255),
        "neutral_btn": (43, 46, 59),
        "status_bg": (36, 38, 49),
        "divider": (55, 58, 74),
        "label_stroke": (18, 18, 26),
    },
    "light": {
        "panel": (247, 247, 251, 245),
        "text": (10, 10, 14, 255),
        "muted": (45, 47, 60, 255),
        "live": (214, 33, 58, 255),
        "error": (196, 108, 20, 255),
        "outline": (214, 216, 226, 255),
        "neutral_btn": (226, 228, 236),
        "status_bg": (232, 233, 240),
        "divider": (210, 212, 222),
        "label_stroke": (255, 255, 255),
    },
}


def build_theme_palette(divisions=23):
    # "Default" (hololive purple) is first, top-left; "Monochrome" is second.
    # The rest is an evenly-spaced hue wheel, sized so the total is exactly
    # 25 — a clean 5x5 grid in the picker.
    palette = [("Default", DEFAULT_ACCENT), ("Monochrome", MONOCHROME_ACCENT)]
    for i in range(divisions):
        r, g, b = colorsys.hls_to_rgb(i / divisions, 0.55, 0.65)
        rgb = (round(r * 255), round(g * 255), round(b * 255))
        palette.append(("#{:02X}{:02X}{:02X}".format(*rgb), rgb))
    return palette


THEME_PALETTE = build_theme_palette()
