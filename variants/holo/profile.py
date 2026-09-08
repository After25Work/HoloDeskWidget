from pathlib import Path

from deskwidget_core.layout import button_row_delta

from .version import __version__

# Consumed by deskwidget_core.appconfig.configure() -- see start_widget_holo.py.
# "variant_root" anchors settings.json/productions/clock_zones.json/the log
# file when running from source (see deskwidget_core/paths.py); a frozen
# build ignores it and anchors to the exe's own directory instead.
# 568 was the min_width before the minimize-to-tray button existed (the
# result of widening 440 -> 480 -> 524 -> 568 as each earlier top button --
# the live-only filter, the fullscreen toggle -- was added); button_row_delta()
# adds exactly the room the "tray" button needs so it never overlaps the
# "LIVE STATUS" title text at minimum width, tied to TOP_BUTTON_WIDTHS/
# BUTTON_GAP instead of a hand-picked (and easy to forget in the other
# variant's profile.py) absolute number.
_MIN_WIDTH_BEFORE_TRAY_BUTTON = 568

PROFILE = {
    "app_name": "HoloDeskWidget",
    "version": __version__,
    "default_accent": (39, 199, 255),
    "variant_root": Path(__file__).resolve().parent,
    "title": {"ja": "ホロライブ", "en": "hololive"},
    # button_row_delta("productions") is reserved even though productions/
    # index.json currently has a single entry (so widget.has_multiple_
    # productions() is False and the button doesn't show today): whether it
    # shows is decided at runtime from that JSON's entry count, not anything
    # this static profile can rule out, so a second production added later
    # (a pure data change) must not be able to make the button overlap the
    # title text -- see VT's own profile.py, which bakes in the same room.
    "min_width": (_MIN_WIDTH_BEFORE_TRAY_BUTTON + button_row_delta("tray")
                  + button_row_delta("productions")),
}
