import json

import pytest

from deskwidget_core import talents


@pytest.fixture(autouse=True)
def isolated_productions(tmp_path, monkeypatch):
    productions_dir = tmp_path / "productions"
    productions_dir.mkdir()
    monkeypatch.setattr(talents, "PRODUCTIONS_DIR", productions_dir)
    monkeypatch.setattr(talents, "PRODUCTIONS_INDEX", productions_dir / "index.json")
    yield


def _write_index(entries):
    talents.PRODUCTIONS_INDEX.write_text(json.dumps(entries), encoding="utf-8")


def test_load_productions_falls_back_when_index_missing():
    assert talents.load_productions() == [talents._FALLBACK_PRODUCTION]


def test_load_productions_falls_back_when_index_is_not_a_list():
    _write_index({"id": "hololive"})

    assert talents.load_productions() == [talents._FALLBACK_PRODUCTION]


def test_load_productions_falls_back_when_result_is_empty():
    _write_index([{"id": "x"}])  # missing required "file" key, dropped

    assert talents.load_productions() == [talents._FALLBACK_PRODUCTION]


def test_load_productions_drops_entries_missing_id_or_file():
    _write_index([
        {"id": "a", "file": "a.json"},
        {"id": "b"},
        {"file": "c.json"},
        "not-a-dict",
    ])

    result = talents.load_productions()

    assert [p["id"] for p in result] == ["a"]


def test_load_productions_rejects_all_pseudo_id():
    _write_index([{"id": talents.ALL_PRODUCTION_ID, "file": "x.json"}])

    assert talents.load_productions() == [talents._FALLBACK_PRODUCTION]


def test_load_productions_dedupes_by_id_keeping_first():
    _write_index([
        {"id": "hololive", "file": "first.json"},
        {"id": "hololive", "file": "second.json"},
    ])

    result = talents.load_productions()

    assert len(result) == 1
    assert result[0]["file"] == "first.json"


def test_production_display_name_prefers_requested_language():
    production = {"id": "hololive", "name": {"ja": "ホロライブ", "en": "hololive"}}

    assert talents.production_display_name(production, "en") == "hololive"
    assert talents.production_display_name(production, "ja") == "ホロライブ"


def test_production_display_name_falls_back_to_japanese_then_id():
    assert talents.production_display_name({"id": "x", "name": {"ja": "エックス"}}, "en") == "エックス"
    assert talents.production_display_name({"id": "x", "name": {}}, "en") == "x"
    assert talents.production_display_name({"id": "x"}, "en") == "x"


def test_load_targets_reads_and_normalizes_entries():
    (talents.PRODUCTIONS_DIR / "hololive.json").write_text(json.dumps([
        {"name": "Talent A", "slug": "talent-a", "unit": "Unit 1"},
        {"name": "Talent B", "slug": "talent-b", "unit": "Unit 1", "channel_url": "https://youtube.com/channel/UC123"},
    ]), encoding="utf-8")

    targets = talents.load_targets({"file": "hololive.json"})

    assert targets == [
        ("Talent A", "talent-a", "https://www.youtube.com/@talent-a", "Unit 1"),
        ("Talent B", "talent-b", "https://youtube.com/channel/UC123", "Unit 1"),
    ]


def test_load_targets_skips_entries_missing_required_fields():
    (talents.PRODUCTIONS_DIR / "hololive.json").write_text(json.dumps([
        {"name": "Talent A", "slug": "talent-a"},  # missing unit
        {"slug": "talent-b", "unit": "Unit 1"},  # missing name
        {"name": "Talent C", "slug": "talent-c", "unit": "Unit 1"},
    ]), encoding="utf-8")

    targets = talents.load_targets({"file": "hololive.json"})

    assert [t[0] for t in targets] == ["Talent C"]


def test_load_targets_returns_empty_list_when_file_missing():
    assert talents.load_targets({"file": "missing.json"}) == []
