import json

from .paths import SETTINGS_PATH, log_error
from .strings import STRINGS
from .theme import THEME_PALETTE

# Resizing reflows the layout (more grid columns, wider sliders) rather than
# zooming a fixed canvas. DEFAULT_* is the initial window size; fonts and row
# heights stay constant, only positions/counts adapt to the current size.
DEFAULT_WIDTH, DEFAULT_HEIGHT = 480, 996
# 480 (not 440) so the extra live-only-filter button in the top row never
# overlaps the "LIVE STATUS" title text at minimum width.
MIN_WIDTH, MIN_HEIGHT = 480, 450
MAX_WIDTH, MAX_HEIGHT = 1400, 1600
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
    "dark_mode": True,
    "live_only": False,
    "text_scale": 1.0,
}


def _coerce(value, default, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def load_settings():
    # Kept in its own file (not talents.json) so user preferences survive a
    # talents.json refresh/replace, and vice versa. Falls back to defaults
    # whole-cloth on a missing/corrupt file rather than partially applying it.
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
    settings["topmost"] = bool(settings["topmost"])
    settings["theme_index"] = max(0, min(len(THEME_PALETTE) - 1,
        _coerce(settings["theme_index"], DEFAULT_SETTINGS["theme_index"], int)))
    settings["dark_mode"] = bool(settings["dark_mode"])
    settings["live_only"] = bool(settings["live_only"])
    settings["text_scale"] = max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX,
        _coerce(settings["text_scale"], DEFAULT_SETTINGS["text_scale"], float)))
    return settings


def save_settings(settings):
    try:
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as error:
        log_error("save_settings", error)
