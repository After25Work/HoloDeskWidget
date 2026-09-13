"""LayeredWidget._load_settings()'s selected_productions resolution: the
saved-list path, and the fallback chain consulted when nothing was saved yet
(a legacy "__all__" value, a legacy single production id that's still
enabled, one that's since been disabled, and no legacy value at all).
config.load_legacy_active_production()'s own JSON parsing is already covered
in tests/test_config.py; this covers the widget-side branching that consumes
it. Driven through a stub that assigns the real unbound _load_settings method
directly (mirrors tests/test_widget_selection.py's FakeSelection), with
config.SETTINGS_PATH redirected to a temp file the same way
tests/test_config.py does.
"""
import pytest

from deskwidget_core import config
from deskwidget_core.talents import ALL_PRODUCTION_ID
from deskwidget_core.widget import LayeredWidget


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    yield


class FakeWidget:
    _load_settings = LayeredWidget._load_settings
    _valid_production_ids = LayeredWidget._valid_production_ids

    def __init__(self, production_ids, has_multiple=True):
        self.productions = [{"id": pid} for pid in production_ids]
        self._productions_by_id = {p["id"]: p for p in self.productions}
        self._has_multiple = has_multiple

    def has_multiple_productions(self):
        return self._has_multiple


def test_saved_selected_productions_list_is_used_when_present():
    config.save_settings({**config.DEFAULT_SETTINGS, "selected_productions": ["b"]})

    widget = FakeWidget(["a", "b", "c"])
    widget._load_settings()

    assert widget.selected_productions == {"b"}


def test_saved_selected_productions_filters_out_ids_no_longer_enabled():
    config.save_settings({**config.DEFAULT_SETTINGS,
                           "selected_productions": ["b"],
                           "enabled_productions": ["a", "c"]})

    widget = FakeWidget(["a", "b", "c"])
    widget._load_settings()

    assert widget.selected_productions == {"a"}


def test_legacy_all_production_id_selects_every_enabled_production():
    config.SETTINGS_PATH.write_text(
        '{"active_production": "%s"}' % ALL_PRODUCTION_ID, encoding="utf-8")

    widget = FakeWidget(["a", "b", "c"])
    widget._load_settings()

    assert widget.selected_productions == {"a", "b", "c"}


def test_legacy_single_production_id_is_carried_over():
    config.SETTINGS_PATH.write_text('{"active_production": "b"}', encoding="utf-8")

    widget = FakeWidget(["a", "b", "c"])
    widget._load_settings()

    assert widget.selected_productions == {"b"}


def test_legacy_production_id_that_is_now_disabled_falls_back_to_first_enabled():
    config.SETTINGS_PATH.write_text(
        '{"active_production": "b", "enabled_productions": ["a", "c"]}', encoding="utf-8")

    widget = FakeWidget(["a", "b", "c"])
    widget._load_settings()

    assert widget.selected_productions == {"a"}


def test_no_saved_selection_and_no_legacy_value_falls_back_to_first_enabled():
    widget = FakeWidget(["a", "b", "c"])
    widget._load_settings()

    assert widget.selected_productions == {"a"}
