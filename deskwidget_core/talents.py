from .paths import ROOT, load_json

PRODUCTIONS_DIR = ROOT / "productions"
PRODUCTIONS_INDEX = PRODUCTIONS_DIR / "index.json"

# Pseudo production id/tab that aggregates every real production's talents
# into one list (see LayeredWidget._tab_productions() and the ALL_PRODUCTION_ID
# branches in widget.py) instead of picking a single production to view.
ALL_PRODUCTION_ID = "__all__"
ALL_PRODUCTION = {"id": ALL_PRODUCTION_ID, "name": {"ja": "すべて", "en": "All"}}

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
    productions = [
        entry for entry in (data if isinstance(data, list) else [])
        if isinstance(entry, dict) and entry.get("id") and entry.get("file")
        # A real production using the "All" tab's pseudo-id would silently
        # collide with ALL_PRODUCTION_ID in every ALL_PRODUCTION_ID branch
        # across widget.py/menus.py/refresh.py.
        and entry["id"] != ALL_PRODUCTION_ID
    ]
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
