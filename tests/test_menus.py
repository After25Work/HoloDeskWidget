"""MenuMixin's production enable/disable cascade: disabling a production
that's part of the current multi-select must also drop it from the
selection, falling back to "select everything still visible" if that would
otherwise empty the selection -- the same "never leave the merged view with
nothing selected" invariant the tab strip itself enforces. Driven through a
stub carrying only the handful of attributes this cascade reads, so no Tk
window is needed (mirrors the FakeGrid/FakeWidget pattern already used for
GridMixin in tests/test_grid_columns.py and tests/test_grid_layout.py)."""
from deskwidget_core.menus import MenuMixin


class FakeMenu(MenuMixin):
    def __init__(self, production_ids, enabled, selected):
        self.productions = [{"id": pid} for pid in production_ids]
        self.enabled_productions = set(enabled)
        self.selected_productions = set(selected)
        self.production_data = {}
        self.render_calls = 0

    def _visible_productions(self):
        return [p for p in self.productions if p["id"] in self.enabled_productions]

    def _production_slot(self, prod_id):
        return self.production_data.setdefault(prod_id, {"targets": []})

    def render(self):
        self.render_calls += 1


def test_disabling_a_production_outside_the_selection_leaves_selection_untouched():
    menu = FakeMenu(["a", "b", "c"], enabled=["a", "b", "c"], selected=["a"])

    assert menu.set_production_enabled("b", False) is True
    assert menu.selected_productions == {"a"}
    assert menu.enabled_productions == {"a", "c"}


def test_disabling_one_of_several_selected_productions_just_drops_it():
    menu = FakeMenu(["a", "b", "c"], enabled=["a", "b", "c"], selected=["a", "b"])

    menu.set_production_enabled("b", False)

    assert menu.selected_productions == {"a"}


def test_disabling_the_only_selected_production_falls_back_to_everything_visible():
    menu = FakeMenu(["a", "b", "c"], enabled=["a", "b", "c"], selected=["b"])

    menu.set_production_enabled("b", False)

    assert menu.selected_productions == {"a", "c"}
    # Both remaining visible productions get a slot pre-created, same as the
    # old switch_production(ALL_PRODUCTION_ID) fallback used to.
    assert set(menu.production_data) == {"a", "c"}


def test_disabling_the_last_visible_production_is_refused():
    menu = FakeMenu(["a"], enabled=["a"], selected=["a"])

    assert menu.set_production_enabled("a", False) is False
    assert menu.enabled_productions == {"a"}
    assert menu.selected_productions == {"a"}


def test_enabling_a_production_does_not_add_it_to_the_selection():
    menu = FakeMenu(["a", "b"], enabled=["a"], selected=["a"])

    menu.set_production_enabled("b", True)

    assert menu.enabled_productions == {"a", "b"}
    assert menu.selected_productions == {"a"}
