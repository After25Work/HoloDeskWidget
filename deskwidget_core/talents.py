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
# tab bar and no talents at all.
_FALLBACK_PRODUCTION = {
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
    return productions or [_FALLBACK_PRODUCTION]


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
