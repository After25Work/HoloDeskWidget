"""LayeredWidget.toggle_production_selection()'s core invariants: toggling a
real production on/off, refusing to drop the last selected one, and the
"All" shortcut's select-all/collapse-to-first-when-already-full behavior.
Driven through
a stub that assigns the real unbound method directly (toggle_production_selection
lives on LayeredWidget itself, not on one of its mixins, so there's no mixin
class to subclass the way FakeGrid/FakeMenu/FakeRefresh do elsewhere in this
test suite) rather than a live Tk widget -- everything else it touches is
stubbed the same lightweight way those other fakes already use.
"""
from deskwidget_core.talents import ALL_PRODUCTION_ID
from deskwidget_core.widget import LayeredWidget


class FakeSelection:
    toggle_production_selection = LayeredWidget.toggle_production_selection
    _valid_production_ids = LayeredWidget._valid_production_ids

    def __init__(self, production_ids, enabled, selected, has_multiple=True):
        self.productions = [{"id": pid} for pid in production_ids]
        self._productions_by_id = {p["id"]: p for p in self.productions}
        self.enabled_productions = set(enabled)
        self.selected_productions = set(selected)
        self.production_data = {}
        self.focus_index = None
        self.live_only = False
        self._has_multiple = has_multiple
        self.render_calls = 0
        self.refresh_calls = 0

    def _visible_productions(self):
        return [p for p in self.productions if p["id"] in self.enabled_productions]

    def _production_slot(self, prod_id):
        return self.production_data.setdefault(prod_id, {"targets": []})

    def has_multiple_productions(self):
        return self._has_multiple

    def _focus_is_on_a_tab(self):
        return False

    def fit_height(self):
        pass

    def request_render(self):
        self.render_calls += 1

    def refresh(self):
        self.refresh_calls += 1


def test_toggling_an_unselected_production_adds_it_and_creates_its_slot():
    widget = FakeSelection(["a", "b"], enabled=["a", "b"], selected=["a"])

    widget.toggle_production_selection("b")

    assert widget.selected_productions == {"a", "b"}
    assert "b" in widget.production_data
    assert widget.refresh_calls == 1


def test_toggling_off_one_of_several_selected_just_removes_it():
    widget = FakeSelection(["a", "b"], enabled=["a", "b"], selected=["a", "b"])

    widget.toggle_production_selection("b")

    assert widget.selected_productions == {"a"}


def test_toggling_off_the_only_selected_production_is_refused():
    widget = FakeSelection(["a", "b"], enabled=["a", "b"], selected=["a"])

    widget.toggle_production_selection("a")

    assert widget.selected_productions == {"a"}
    assert widget.refresh_calls == 0


def test_all_shortcut_selects_every_visible_production():
    widget = FakeSelection(["a", "b", "c"], enabled=["a", "b", "c"], selected=["a"])

    widget.toggle_production_selection(ALL_PRODUCTION_ID)

    assert widget.selected_productions == {"a", "b", "c"}
    assert set(widget.production_data) == {"a", "b", "c"}


def test_all_shortcut_collapses_to_first_visible_when_already_fully_selected():
    widget = FakeSelection(["a", "b", "c"], enabled=["a", "b", "c"], selected=["a", "b", "c"])

    widget.toggle_production_selection(ALL_PRODUCTION_ID)

    assert widget.selected_productions == {"a"}
    assert widget.refresh_calls == 1


def test_toggling_an_unknown_production_id_is_a_no_op():
    widget = FakeSelection(["a", "b"], enabled=["a", "b"], selected=["a"])

    widget.toggle_production_selection("nonexistent")

    assert widget.selected_productions == {"a"}
    assert widget.refresh_calls == 0


def test_all_shortcut_is_rejected_on_a_single_production_build():
    # Mirrors the old switch_production()'s guard: ALL_PRODUCTION_ID is only
    # a valid target when has_multiple_productions() (see
    # _valid_production_ids()) -- a single-production build has no "All" tab
    # to click, so a stale/hand-edited settings.json shouldn't be able to
    # select it either.
    widget = FakeSelection(["a"], enabled=["a"], selected=["a"], has_multiple=False)

    widget.toggle_production_selection(ALL_PRODUCTION_ID)

    assert widget.selected_productions == {"a"}
    assert widget.refresh_calls == 0
