import pytest

from deskwidget_core import config


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    yield


def test_load_settings_returns_defaults_when_file_missing():
    settings = config.load_settings()

    assert settings == config.DEFAULT_SETTINGS


def test_load_settings_returns_defaults_when_file_corrupt():
    config.SETTINGS_PATH.write_text("not json", encoding="utf-8")

    assert config.load_settings() == config.DEFAULT_SETTINGS


def test_save_and_load_round_trip():
    settings = dict(config.DEFAULT_SETTINGS)
    settings["lang"] = "en"
    settings["dark_mode"] = False
    settings["width"] = 900

    config.save_settings(settings)
    loaded = config.load_settings()

    assert loaded["lang"] == "en"
    assert loaded["dark_mode"] is False
    assert loaded["width"] == 900


def test_load_settings_ignores_unknown_keys():
    config.SETTINGS_PATH.write_text('{"lang": "en", "bogus_key": "x"}', encoding="utf-8")

    settings = config.load_settings()

    assert "bogus_key" not in settings
    assert settings["lang"] == "en"


@pytest.mark.parametrize("bad_value", ['"not-a-number"', "null", "[1, 2]"])
def test_load_settings_coerces_bad_numeric_fields_to_default(bad_value):
    config.SETTINGS_PATH.write_text(f'{{"x": {bad_value}}}', encoding="utf-8")

    settings = config.load_settings()

    assert settings["x"] == config.DEFAULT_SETTINGS["x"]


def test_load_settings_clamps_width_and_height_to_bounds():
    config.SETTINGS_PATH.write_text(
        f'{{"width": {config.MAX_WIDTH + 500}, "height": {config.MIN_HEIGHT - 500}}}',
        encoding="utf-8",
    )

    settings = config.load_settings()

    assert settings["width"] == config.MAX_WIDTH
    assert settings["height"] == config.MIN_HEIGHT


def test_load_settings_clamps_background_alpha():
    config.SETTINGS_PATH.write_text('{"background_alpha": 5.0}', encoding="utf-8")

    settings = config.load_settings()

    assert settings["background_alpha"] == pytest.approx(1.0 - config.MIN_BACKGROUND_DARKNESS)


def test_load_settings_clamps_text_scale():
    config.SETTINGS_PATH.write_text('{"text_scale": 99}', encoding="utf-8")

    assert config.load_settings()["text_scale"] == config.TEXT_SCALE_MAX


def test_load_settings_rejects_unknown_language():
    config.SETTINGS_PATH.write_text('{"lang": "fr"}', encoding="utf-8")

    assert config.load_settings()["lang"] == "ja"


def test_load_settings_coerces_string_true_topmost_to_default():
    # _coerce_bool must not let bool("false") == True slip through for a
    # hand-edited settings.json.
    config.SETTINGS_PATH.write_text('{"topmost": "false"}', encoding="utf-8")

    assert config.load_settings()["topmost"] == config.DEFAULT_SETTINGS["topmost"]


def test_load_settings_accepts_real_boolean():
    config.SETTINGS_PATH.write_text('{"topmost": true}', encoding="utf-8")

    assert config.load_settings()["topmost"] is True


def test_load_settings_clamps_theme_index_out_of_range():
    from deskwidget_core.theme import THEME_PALETTE

    config.SETTINGS_PATH.write_text('{"theme_index": 9999}', encoding="utf-8")

    assert config.load_settings()["theme_index"] == len(THEME_PALETTE) - 1


def test_load_settings_filters_non_string_enabled_productions():
    config.SETTINGS_PATH.write_text('{"enabled_productions": ["hololive", 1, null, "nijisanji"]}', encoding="utf-8")

    assert config.load_settings()["enabled_productions"] == ["hololive", "nijisanji"]


def test_load_settings_enabled_productions_defaults_to_empty_when_not_a_list():
    config.SETTINGS_PATH.write_text('{"enabled_productions": "hololive"}', encoding="utf-8")

    assert config.load_settings()["enabled_productions"] == []


def test_load_settings_clamps_column_scale_to_bounds():
    config.SETTINGS_PATH.write_text(
        f'{{"column_scale": {config.COLUMN_SCALE_MAX + 5}}}', encoding="utf-8")

    assert config.load_settings()["column_scale"] == config.COLUMN_SCALE_MAX

    config.SETTINGS_PATH.write_text(
        f'{{"column_scale": {config.COLUMN_SCALE_MIN - 5}}}', encoding="utf-8")

    assert config.load_settings()["column_scale"] == config.COLUMN_SCALE_MIN


def test_load_settings_clamps_name_scale_to_bounds():
    config.SETTINGS_PATH.write_text(
        f'{{"name_scale": {config.NAME_SCALE_MAX + 5}}}', encoding="utf-8")

    assert config.load_settings()["name_scale"] == config.NAME_SCALE_MAX

    config.SETTINGS_PATH.write_text(
        f'{{"name_scale": {config.NAME_SCALE_MIN - 5}}}', encoding="utf-8")

    assert config.load_settings()["name_scale"] == config.NAME_SCALE_MIN


def test_settings_file_predating_the_width_sliders_gets_the_neutral_defaults():
    # 1.0 is the value that reproduces the fixed column pitch (column_scale)
    # and the fixed name/title split (name_scale) the app had before those
    # two sliders existed, so upgrading must not move anything on an existing
    # user's panel.
    config.SETTINGS_PATH.write_text('{"lang": "en"}', encoding="utf-8")

    assert config.load_settings()["column_scale"] == 1.0
    assert config.load_settings()["name_scale"] == 1.0
