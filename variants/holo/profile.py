from pathlib import Path

from .version import __version__

# Consumed by deskwidget_core.appconfig.configure() -- see start_widget_holo.py.
# "variant_root" anchors settings.json/productions/clock_zones.json/the log
# file when running from source (see deskwidget_core/paths.py); a frozen
# build ignores it and anchors to the exe's own directory instead.
PROFILE = {
    "app_name": "HoloDeskWidget",
    "version": __version__,
    "default_accent": (39, 199, 255),
    "variant_root": Path(__file__).resolve().parent,
    "title": {"ja": "ホロライブ", "en": "hololive"},
    # 568 (not 524) so the extra font-picker button in the top row never
    # overlaps the "LIVE STATUS" title text at minimum width, the same
    # reasoning that widened this from 440 to 480 to 524 as each earlier top
    # button (the live-only filter, the fullscreen toggle) was added.
    "min_width": 568,
}
