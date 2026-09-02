import functools
import os
from pathlib import Path

from PIL import ImageFont

_FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

# Yu Gothic is the primary UI font, but some Windows installs (e.g. without
# East Asian language support added) don't have it. Meiryo and MS Gothic are
# older, more broadly-preinstalled CJK fonts tried next so Japanese text
# still renders; both ship as single .ttc files with no separate bold/regular
# weight, so they're reused for both bold=True/False.
_FONT_CANDIDATES = {
    True: ("YuGothM.ttc", "meiryob.ttc", "msgothic.ttc"),
    False: ("YuGothR.ttc", "meiryo.ttc", "msgothic.ttc"),
}


@functools.lru_cache(maxsize=None)
def _font_path(bold):
    # Resolved once per bold value (there are only two) instead of inside
    # font(): font() is cached per (size, bold), and the UI's label auto-fit
    # search calls it with many distinct sizes, so without this a missing
    # Yu Gothic/Meiryo would have its candidate files re-probed via failed
    # ImageFont.truetype() OSErrors on every new size instead of just once.
    for filename in _FONT_CANDIDATES[bold]:
        path = _FONTS_DIR / filename
        if path.exists():
            return path
    return None


@functools.lru_cache(maxsize=None)
def font(size, bold=True):
    path = _font_path(bold)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    # None of the known CJK-capable fonts are present. Fall back to Pillow's
    # built-in font rather than letting the OSError propagate and crash
    # startup — Japanese glyphs won't render, but a degraded UI beats a
    # hard failure the caller (widget.py draws through this everywhere) has
    # no way to work around.
    return ImageFont.load_default(size=size)


@functools.lru_cache(maxsize=None)
def emoji_font(size):
    # Yu Gothic has no emoji glyphs, so emoji in live titles need Segoe UI
    # Emoji instead. It's a color bitmap font with fixed strike sizes;
    # FreeType scales to the nearest one and Pillow renders it via
    # ImageDraw.text(..., embedded_color=True).
    try:
        return ImageFont.truetype(str(_FONTS_DIR / "seguiemj.ttf"), size)
    except OSError:
        return None
