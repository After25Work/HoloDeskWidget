import functools
import os
from pathlib import Path

from PIL import ImageFont


@functools.lru_cache(maxsize=None)
def font(size, bold=True):
    path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / (
        "YuGothM.ttc" if bold else "YuGothR.ttc"
    )
    return ImageFont.truetype(str(path), size)


@functools.lru_cache(maxsize=None)
def emoji_font(size):
    # Yu Gothic has no emoji glyphs, so emoji in live titles need Segoe UI
    # Emoji instead. It's a color bitmap font with fixed strike sizes;
    # FreeType scales to the nearest one and Pillow renders it via
    # ImageDraw.text(..., embedded_color=True).
    path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "seguiemj.ttf"
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return None
