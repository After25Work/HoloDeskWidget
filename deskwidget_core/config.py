import json

from . import appconfig
from .fonts import DEFAULT_FONT_FAMILY
from .paths import SETTINGS_PATH, log_error
from .strings import STRINGS
from .theme import THEME_PALETTE

# Resizing reflows the layout (more grid columns, wider sliders) rather than
# zooming a fixed canvas. DEFAULT_* is the initial window size; fonts and row
# heights stay constant, only positions/counts adapt to the current size.
# MIN_WIDTH (see appconfig.min_width()) is a per-variant value: it only needs
# to be wide enough for the top-right button row this variant actually draws,
# which is one button narrower for a variant with a single production (no
# productions picker) than one with several -- see layout.py's
# TOP_BUTTON_WIDTHS/TOP_BUTTON_ORDER.
DEFAULT_WIDTH, DEFAULT_HEIGHT = appconfig.min_width(), 996
MIN_WIDTH, MIN_HEIGHT = appconfig.min_width(), 450
# Cap resizing at 4K (3840x2160) -- the fullscreen button lets a window grow
# to fill the whole screen, and this is the largest a real monitor is likely
# to be.
MAX_WIDTH, MAX_HEIGHT = 3840, 2160
WINDOW_ALPHA = 0.78
MIN_WINDOW_ALPHA = 0.05
MIN_BACKGROUND_DARKNESS = 0.3
TEXT_SCALE_MIN = 0.8
TEXT_SCALE_MAX = 1.0

DEFAULT_SETTINGS = {
    "x": 40,
    "y": 40,
    "width": DEFAULT_WIDTH,
    "height": DEFAULT_HEIGHT,
    "background_alpha": 0.0,
    "lang": "ja",
    # Off by default, matching how ordinary windows behave — a general app
    # isn't pinned above everything else until the user asks it to be (pin
    # button / right-click menu).
    "topmost": False,
    "theme_index": 0,
    "font_family": DEFAULT_FONT_FAMILY,
    "dark_mode": True,
    "live_only": False,
    "text_scale": 1.0,
    # Validated against the actually-loaded productions manifest in
    # widget.py (not here) since that's data talents.py owns, not a plain
    # window/UI preference like everything else in this file.
    "active_production": "hololive",
    # Which productions show as tabs. Empty here means "no preference saved
    # yet" -- widget.py treats that (and any list left with nothing valid
    # after being checked against the loaded manifest) as "show everything",
    # so a first run or a stale/edited list never hides every tab.
    "enabled_productions": [],
}


def _coerce(value, default, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def load_settings():
    # Kept in its own file (not alongside productions/) so user preferences
    # survive a talent-list refresh/replace, and vice versa. Falls back to
    # defaults whole-cloth on a missing/corrupt file rather than partially
    # applying it.
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        settings.update({key: data[key] for key in DEFAULT_SETTINGS if key in data})
    # Each field is type-coerced (not just merged) before use, since a
    # hand-edited settings.json can carry a value of the wrong type (e.g. a
    # string) that would otherwise raise inside min()/max() below.
    settings["x"] = _coerce(settings["x"], DEFAULT_SETTINGS["x"], int)
    settings["y"] = _coerce(settings["y"], DEFAULT_SETTINGS["y"], int)
    settings["width"] = max(MIN_WIDTH, min(MAX_WIDTH,
        _coerce(settings["width"], DEFAULT_SETTINGS["width"], int)))
    settings["height"] = max(MIN_HEIGHT, min(MAX_HEIGHT,
        _coerce(settings["height"], DEFAULT_SETTINGS["height"], int)))
    settings["background_alpha"] = max(0.0, min(1.0 - MIN_BACKGROUND_DARKNESS,
        _coerce(settings["background_alpha"], DEFAULT_SETTINGS["background_alpha"], float)))
    settings["lang"] = settings["lang"] if settings["lang"] in STRINGS else "ja"
    # isinstance, not bool(...): bool() coerces any truthy non-bool (e.g. a
    # hand-edited string "false") to True instead of falling back to the
    # default like every other coerced field here does.
    settings["topmost"] = (settings["topmost"] if isinstance(settings["topmost"], bool)
                            else DEFAULT_SETTINGS["topmost"])
    settings["theme_index"] = max(0, min(len(THEME_PALETTE) - 1,
        _coerce(settings["theme_index"], DEFAULT_SETTINGS["theme_index"], int)))
    # Not checked against list_installed_fonts() here: that's a full
    # Fonts-directory scan (every file loaded via Pillow/FreeType, plus a
    # GDI glyph-coverage probe per family -- can easily be 200+ fonts), and
    # running it this early would block startup before the window even
    # exists. font() already tolerates an unknown/uninstalled name
    # gracefully via its fallback chain, so an uninstalled saved name just
    # means the font-picker's "currently selected" row won't highlight
    # until a real family is picked -- not worth paying the scan's cost on
    # every launch to avoid.
    settings["font_family"] = _coerce(settings["font_family"], DEFAULT_SETTINGS["font_family"], str)
    settings["dark_mode"] = (settings["dark_mode"] if isinstance(settings["dark_mode"], bool)
                              else DEFAULT_SETTINGS["dark_mode"])
    settings["live_only"] = (settings["live_only"] if isinstance(settings["live_only"], bool)
                              else DEFAULT_SETTINGS["live_only"])
    settings["text_scale"] = max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX,
        _coerce(settings["text_scale"], DEFAULT_SETTINGS["text_scale"], float)))
    settings["active_production"] = _coerce(
        settings["active_production"], DEFAULT_SETTINGS["active_production"], str)
    raw_enabled = settings["enabled_productions"]
    settings["enabled_productions"] = (
        [entry for entry in raw_enabled if isinstance(entry, str)]
        if isinstance(raw_enabled, list) else [])
    return settings


def save_settings(settings):
    try:
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as error:
        log_error("save_settings", error)
