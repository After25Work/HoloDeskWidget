from pathlib import Path

from .version import __version__

# Consumed by deskwidget_core.appconfig.configure() -- see start_widget_vt.py.
# "variant_root" anchors settings.json/productions/clock_zones.json/the log
# file when running from source (see deskwidget_core/paths.py); a frozen
# build ignores it and anchors to the exe's own directory instead.
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
    # 656 (not 612) so the extra minimize-to-tray button in the top row
    # never overlaps the title text at minimum width, the same reasoning
    # that widened this from 440 to 480 to 524 to 568 to 612 as each earlier
    # top button (the productions picker, the fullscreen toggle, the
    # live-only filter) was added.
    "min_width": 656,
}
