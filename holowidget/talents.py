import json

from .paths import ROOT


def load_talents_raw():
    return json.loads((ROOT / "talents.json").read_text(encoding="utf-8"))


def load_targets():
    return [
        (talent["name"], talent["slug"],
         talent.get("channel_url", f"https://www.youtube.com/@{talent['slug']}"),
         talent["unit"])
        for talent in load_talents_raw()
    ]
