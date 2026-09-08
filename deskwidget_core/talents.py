from pathlib import Path

from .paths import ROOT, load_json

PRODUCTIONS_DIR = ROOT / "productions"
PRODUCTIONS_INDEX = PRODUCTIONS_DIR / "index.json"

# Pseudo production id/tab that aggregates every real production's talents
# into one list (see LayeredWidget._tab_productions() and the ALL_PRODUCTION_ID
# branches in widget.py) instead of picking a single production to view.
ALL_PRODUCTION_ID = "__all__"
ALL_PRODUCTION = {"id": ALL_PRODUCTION_ID, "name": {"ja": "すべて", "en": "All"}}

# Seed value widget.py's _production_slot() gives every talent's state at the
# start of each app session -- never a real observed live/offline/error
# result. Shared here (rather than each side hardcoding the string "unknown")
# so refresh.py's _log_state_transition() can recognize "never checked this
# session yet" without the two call sites silently drifting apart.
UNOBSERVED_STATE = "unknown"

# Used only if productions/index.json is missing/corrupt/empty, so the
# widget always has at least one production to show instead of an empty
# tab bar and no talents at all. This module is shared by every variant, so
# the fallback isn't hardcoded to a single production: it prefers
# hololive.json (what every variant ships today) but falls through to
# whichever talent-list file this variant's own productions/ directory
# actually has, so a future variant that ships without one still gets a
# fallback instead of a hardcoded id/file it may not have.
def _fallback_production():
    try:
        files = sorted(path.name for path in PRODUCTIONS_DIR.glob("*.json")
                        if path.name != "index.json")
    except OSError:
        files = []
    if "hololive.json" in files:
        return {
            "id": "hololive",
            "name": {"ja": "ホロライブ", "en": "hololive"},
            "file": "hololive.json",
            "auto_resolve": "hololivepro",
        }
    if files:
        filename = files[0]
        stem = Path(filename).stem
        return {"id": stem, "name": {"ja": stem, "en": stem}, "file": filename}
    # No production file at all -- still returns something rather than None,
    # so load_productions() always has one entry; load_targets() on it will
    # just come back empty since load_json() treats the missing file as a
    # missing-default case too.
    return {
        "id": "hololive",
        "name": {"ja": "ホロライブ", "en": "hololive"},
        "file": "hololive.json",
        "auto_resolve": "hololivepro",
    }


def load_productions():
    data = load_json(PRODUCTIONS_INDEX, [])
    productions = []
    seen_ids = set()
    for entry in (data if isinstance(data, list) else []):
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("file"):
            continue
        # A real production using the "All" tab's pseudo-id would silently
        # collide with ALL_PRODUCTION_ID in every ALL_PRODUCTION_ID branch
        # across widget.py/menus.py/refresh.py.
        if entry["id"] == ALL_PRODUCTION_ID:
            continue
        # index.json is user-editable -- a hand-added duplicate id would
        # otherwise double every refresh/log entry for it (widget.py's
        # id-keyed lookups collapse to one, but self.productions itself
        # stayed a list of two), so only the first entry for a given id wins.
        if entry["id"] in seen_ids:
            continue
        seen_ids.add(entry["id"])
        productions.append(entry)
    return productions or [_fallback_production()]


def production_display_name(production, lang):
    name = production.get("name") or {}
    return name.get(lang) or name.get("ja") or production["id"]


def load_talents_raw(filename):
    return load_json(PRODUCTIONS_DIR / filename, [])


def load_targets(production):
    raw = load_talents_raw(production["file"])
    return [
        (talent["name"], talent["slug"],
         talent.get("channel_url", f"https://www.youtube.com/@{talent['slug']}"),
         talent["unit"])
        for talent in (raw if isinstance(raw, list) else [])
        if isinstance(talent, dict) and "name" in talent and "slug" in talent and "unit" in talent
    ]
