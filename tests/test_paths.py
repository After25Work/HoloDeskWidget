from deskwidget_core.paths import load_json


def test_load_json_returns_default_when_file_missing(tmp_path):
    assert load_json(tmp_path / "missing.json", "fallback") == "fallback"


def test_load_json_returns_default_when_file_corrupt(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid", encoding="utf-8")

    assert load_json(path, []) == []


def test_load_json_returns_parsed_content_on_success(tmp_path):
    path = tmp_path / "good.json"
    path.write_text('{"a": 1}', encoding="utf-8")

    assert load_json(path, {}) == {"a": 1}
