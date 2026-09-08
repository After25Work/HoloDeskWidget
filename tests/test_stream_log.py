import json

import pytest

from deskwidget_core import stream_log


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setattr(stream_log, "STREAM_LOG_PATH", tmp_path / "stream_history.jsonl")
    monkeypatch.setattr(stream_log, "_writes_since_trim", 0)
    yield


def test_record_and_load_round_trip():
    stream_log.record_event("hololive", "Talent A", "start", "Karaoke stream", "https://youtube.com/watch?v=abc")
    stream_log.record_event("hololive", "Talent A", "end")

    events = stream_log.load_events()

    assert len(events) == 2
    # Newest first.
    assert events[0]["event"] == "end"
    assert events[1]["event"] == "start"
    assert events[1]["title"] == "Karaoke stream"
    assert events[1]["url"] == "https://youtube.com/watch?v=abc"


def test_record_event_omits_absent_title_and_url():
    stream_log.record_event("hololive", "Talent A", "end")

    [event] = stream_log.load_events()

    assert "title" not in event
    assert "url" not in event


def test_load_events_respects_limit():
    for i in range(5):
        stream_log.record_event("hololive", f"Talent {i}", "start")

    assert len(stream_log.load_events(limit=2)) == 2
    assert len(stream_log.load_events()) == 5


def test_load_events_returns_empty_list_when_file_missing():
    assert stream_log.load_events() == []


def test_load_events_skips_unparseable_lines(tmp_path):
    stream_log.STREAM_LOG_PATH.write_text(
        json.dumps({"ts": 1, "production_id": "hololive", "name": "A", "event": "start"}) + "\n"
        "not valid json\n",
        encoding="utf-8",
    )

    events = stream_log.load_events()

    assert len(events) == 1
    assert events[0]["name"] == "A"


def test_trim_keeps_only_the_most_recent_entries(monkeypatch):
    monkeypatch.setattr(stream_log, "MAX_ENTRIES", 3)
    monkeypatch.setattr(stream_log, "_TRIM_CHECK_INTERVAL", 1)

    for i in range(5):
        stream_log.record_event("hololive", f"Talent {i}", "start")

    events = stream_log.load_events()

    assert len(events) == 3
    # Newest-first: the three most recently written talents survive the trim.
    assert [event["name"] for event in events] == ["Talent 4", "Talent 3", "Talent 2"]


def test_trim_leaves_file_untouched_when_under_the_cap(monkeypatch):
    monkeypatch.setattr(stream_log, "MAX_ENTRIES", 10)
    monkeypatch.setattr(stream_log, "_TRIM_CHECK_INTERVAL", 1)

    stream_log.record_event("hololive", "Talent A", "start")

    assert len(stream_log.load_events()) == 1
