"""SearchMixin's filtering predicates -- the part of the title filter that is
pure logic, exercised without a Tk window (the entry widget itself needs a
real display, so only its state-side helpers are covered here)."""
import pytest

from deskwidget_core.search import SearchMixin


class FakeWidget(SearchMixin):
    """Just enough of LayeredWidget for the predicates: the live-only flag
    they combine with, plus the two hooks set_title_query() calls."""

    def __init__(self, live_only=False):
        self.live_only = live_only
        self.focus_index = 3
        self.render_requests = 0
        self.search_entry = None
        self.title_query = ""
        self._title_query_folded = ""

    def request_render(self):
        self.render_requests += 1


TITLES = {
    "A": "【歌枠】Karaoke Night",
    "B": "Minecraft 建築配信",
    "C": "ASMR 耳かき",
    "D": "",
}


def test_no_query_matches_every_row():
    widget = FakeWidget()

    assert all(widget.row_matches_title(title) for title in TITLES.values())
    assert widget.row_matches_title(None)


def test_query_matches_case_insensitively():
    widget = FakeWidget()
    widget.set_title_query("MINECRAFT")

    assert widget.row_matches_title(TITLES["B"])
    assert not widget.row_matches_title(TITLES["A"])


def test_query_matches_japanese_substring():
    widget = FakeWidget()
    widget.set_title_query("耳かき")

    assert widget.row_matches_title(TITLES["C"])
    assert not widget.row_matches_title(TITLES["B"])


@pytest.mark.parametrize("title", [None, ""])
def test_row_without_a_title_never_matches_a_query(title):
    # This is what makes a query implicitly narrow the list to live rows:
    # an offline talent has no live title to match against.
    widget = FakeWidget()
    widget.set_title_query("karaoke")

    assert not widget.row_matches_title(title)


def test_row_visible_combines_live_only_with_the_query():
    widget = FakeWidget(live_only=True)
    widget.set_title_query("asmr")

    assert widget.row_visible("C", "live", TITLES)
    # Right title, but not live -- live_only still excludes it.
    assert not widget.row_visible("C", "offline", TITLES)
    # Live, but the title doesn't match.
    assert not widget.row_visible("B", "live", TITLES)


def test_row_visible_without_filters_keeps_offline_rows():
    widget = FakeWidget()

    assert widget.row_visible("D", "offline", TITLES)


def test_show_titles_follows_live_only_or_a_query():
    widget = FakeWidget()
    assert widget.show_titles is False

    widget.set_title_query("x")
    assert widget.show_titles is True

    widget.set_title_query("")
    assert widget.show_titles is False

    widget.live_only = True
    assert widget.show_titles is True


def test_set_title_query_strips_and_renders_once_per_change():
    widget = FakeWidget()

    widget.set_title_query("  karaoke  ")
    assert widget.title_query == "karaoke"
    assert widget.render_requests == 1

    # Re-entering the same effective query (the trace fires on every
    # keystroke, including ones that don't change the stripped text) must not
    # cost another render pass.
    widget.set_title_query("karaoke ")
    assert widget.render_requests == 1


def test_set_title_query_drops_the_keyboard_focus_ring():
    # The focused item is an index into a row list the new query is about to
    # rewrite, so it can't survive the change.
    widget = FakeWidget()

    widget.set_title_query("x")

    assert widget.focus_index is None


def test_clear_title_query_without_an_entry_widget_clears_the_state():
    widget = FakeWidget()
    widget.set_title_query("x")

    widget.clear_title_query()

    assert widget.title_query == ""
    assert widget.show_titles is False


class SilentEntry:
    """An entry whose delete() fires no trace -- i.e. one that had nothing to
    delete because the query state and the widget text had drifted apart."""

    def __init__(self):
        self.deleted = False

    def delete(self, first, last=None):
        self.deleted = True


def test_clear_title_query_clears_state_even_if_the_entry_fires_no_trace():
    # The panel's × button and the context menu's "clear filter" entry both
    # land here, and neither is guaranteed to follow a keystroke -- so the
    # clear must not depend on the widget's own trace to do the work.
    widget = FakeWidget()
    widget.set_title_query("karaoke")
    widget.search_entry = SilentEntry()

    widget.clear_title_query()

    assert widget.search_entry.deleted
    assert widget.title_query == ""
    assert widget.show_titles is False


def test_clear_title_query_renders_once_on_the_normal_path():
    # The usual case: the entry's trace already reported the empty text, so
    # the unconditional set_title_query("") must early-return rather than
    # queue a second render.
    widget = FakeWidget()
    widget.set_title_query("karaoke")
    before = widget.render_requests

    class TracingEntry:
        def delete(self, first, last=None):
            widget.set_title_query("")

    widget.search_entry = TracingEntry()
    widget.clear_title_query()

    assert widget.title_query == ""
    assert widget.render_requests == before + 1
