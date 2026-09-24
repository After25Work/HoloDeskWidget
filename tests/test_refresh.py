"""RefreshMixin.refresh_complete()'s staleness check: a refresh started for
one selection must not clobber last_updated/reschedule the periodic timer if
the user changed the selection while it was still in flight -- it should
instead kick an immediate refresh for whatever's selected now. Driven
through a stub (mirrors tests/test_menus.py's FakeMenu) rather than a real
widget, since refresh_worker()/check_one() do real threading and network
I/O that this repo has never unit-tested and this task isn't changing."""
from deskwidget_core.refresh import REFRESH_INTERVAL_MS, TRAY_REFRESH_INTERVAL_MS, RefreshMixin


class FakeRefresh(RefreshMixin):
    def __init__(self, selected, viewable=True):
        self.selected_productions = set(selected)
        self.refresh_in_progress = True
        self.tray = None
        self.last_updated = None
        self.render_calls = 0
        self.refresh_calls = 0
        self.rescheduled = []
        self._refresh_timer_id = None
        self._viewable = viewable

    def render(self):
        self.render_calls += 1

    def refresh(self):
        self.refresh_calls += 1

    class _Root:
        def __init__(self, outer):
            self._outer = outer

        def after(self, delay_ms, callback):
            self._outer.rescheduled.append((delay_ms, callback))
            return len(self._outer.rescheduled)

        def winfo_viewable(self):
            return self._outer._viewable

    @property
    def root(self):
        return self._Root(self)


def test_refresh_complete_with_still_current_selection_updates_and_reschedules():
    widget = FakeRefresh(selected=["a", "b"])

    widget.refresh_complete(frozenset({"a", "b"}))

    assert widget.refresh_in_progress is False
    assert widget.last_updated is not None
    assert widget.render_calls == 1
    assert widget.refresh_calls == 0
    assert widget.rescheduled == [(REFRESH_INTERVAL_MS, widget.refresh)]
    assert widget._refresh_timer_id == 1


def test_refresh_complete_while_withdrawn_to_tray_reschedules_at_the_slower_interval():
    widget = FakeRefresh(selected=["a", "b"], viewable=False)

    widget.refresh_complete(frozenset({"a", "b"}))

    assert widget.rescheduled == [(TRAY_REFRESH_INTERVAL_MS, widget.refresh)]


def test_refresh_complete_with_stale_selection_kicks_an_immediate_refresh():
    widget = FakeRefresh(selected=["a"])  # selection changed after the refresh started

    widget.refresh_complete(frozenset({"a", "b"}))

    assert widget.refresh_in_progress is False
    assert widget.last_updated is None
    assert widget.render_calls == 0
    assert widget.refresh_calls == 1
    assert widget.rescheduled == []
