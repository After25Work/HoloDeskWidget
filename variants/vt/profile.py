from pathlib import Path

from deskwidget_core.layout import button_row_delta

from .version import __version__

# Consumed by deskwidget_core.appconfig.configure() -- see start_widget_vt.py.
# "variant_root" anchors settings.json/productions/clock_zones.json/the log
# file when running from source (see deskwidget_core/paths.py); a frozen
# build ignores it and anchors to the exe's own directory instead.
# 612 was the min_width before the minimize-to-tray button existed (the
# result of widening 440 -> 480 -> 524 -> 568 -> 612 as each earlier top
# button -- the productions picker, the fullscreen toggle, the live-only
# filter -- was added); button_row_delta() adds exactly the room the "tray"
# button needs so it never overlaps the title text at minimum width, tied to
# TOP_BUTTON_WIDTHS/BUTTON_GAP instead of a hand-picked (and easy to forget
# in the other variant's profile.py) absolute number.
_MIN_WIDTH_BEFORE_TRAY_BUTTON = 612

PROFILE = {
    "app_name": "VTDeskWidget",
    "version": __version__,
    "default_accent": (0, 120, 212),
    "variant_root": Path(__file__).resolve().parent,
    # Not actually shown: with more than one production loaded, render()
    # always uses the compact single-line app_name() header instead (see the
    # note on "title" in deskwidget_core/appconfig.py). Kept populated anyway
    # so the profile still satisfies appconfig's contract.
    "title": {"ja": "VTDeskWidget", "en": "VTDeskWidget"},
    "min_width": _MIN_WIDTH_BEFORE_TRAY_BUTTON + button_row_delta("tray"),
}
