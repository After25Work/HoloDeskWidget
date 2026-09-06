# Branding/identity knobs that differ per variant (see variants/holo/profile.py
# and variants/vt/profile.py). The entry script calls configure() with its
# variant's PROFILE before importing anything else from deskwidget_core, so
# every other module in this package can read these at import time exactly
# like it would a plain constant -- see paths.py's WINDOW_TITLE/ROOT and
# theme.py's DEFAULT_ACCENT for the two call sites that matter most.
_profile = {
    "app_name": "DeskWidget",
    "version": "0.0.0",
    "default_accent": (39, 199, 255),
    "variant_root": None,
    # Shown as the two-line brand header when this variant has exactly one
    # production loaded (see widget.py's has_multiple_productions() and
    # rendering.py's render()) -- unused (but still required to be present)
    # once a variant ships more than one production, where the header
    # switches to a compact single line reading app_name() instead.
    "title": {"ja": "DeskWidget", "en": "DeskWidget"},
    # Minimum/initial window width, wide enough that the top-right button row
    # never overlaps the title text -- see the note on TOP_BUTTON_WIDTHS in
    # layout.py. Differs per variant only because a variant with more than one
    # production always shows one extra button (the productions picker) that
    # a single-production variant never draws.
    "min_width": 568,
}


def configure(profile):
    _profile.update(profile)


def app_name():
    return _profile["app_name"]


def version():
    return _profile["version"]


def default_accent():
    return _profile["default_accent"]


def variant_root():
    return _profile["variant_root"]


def title(lang):
    return _profile["title"].get(lang) or _profile["title"]["ja"]


def min_width():
    return _profile["min_width"]
