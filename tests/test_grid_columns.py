"""compute_grid()'s column-count search: how many columns the talent grid (and
the title view, which is laid out in columns too now) wraps into at a given
window size, and which of the candidate counts it keeps.

Driven through a stub rather than a real widget: everything the search needs
from the rest of the app is a handful of plain attributes plus a label-width
measurement, and the fake one here (proportional to the label's length) keeps
the arithmetic predictable without loading a font or opening a Tk window.
"""
import pytest

from deskwidget_core import grid_layout
from deskwidget_core.grid_layout import (
    DEFAULT_DIVIDER_HEIGHT,
    DEFAULT_ROW_HEIGHT,
    FOOTER_RESERVED_HEIGHT,
    GRID_MARGIN,
    RIGHT_PADDING,
    GridMixin,
)


class FakeGrid(GridMixin):
    def __init__(self, talents, width=1600, height=1000, show_titles=False):
        self.width = width
        self.height = height
        self.show_titles = show_titles
        self.is_fullscreen = False
        self.lang = "ja"
        self.text_scale = 1.0
        self.column_scale = 1.0
        self.name_scale = 1.0
        self.column_widths = None
        self.live_only = show_titles
        self._title_query_folded = ""
        self.active_production = "test"
        # One unit, so the layout is a single divider plus a plain block of
        # rows -- the column count is then the only thing that decides how
        # many rows tall the grid comes out.
        self.targets = [(f"talent{i:03d}", f"slug{i}", "", "unit") for i in range(talents)]
        self.states = {name: "live" for name, _slug, _url, _unit in self.targets}
        self.live_titles = {name: "now playing" for name, _slug, _url, _unit in self.targets}

    def has_multiple_productions(self):
        return False

    def t(self, key, **kwargs):
        return key

    def row_visible(self, name, state, titles):
        return True

    def _visible_talent_labels(self, targets=None, states=None, titles=None):
        return [f"• {name}" for name, _slug, _url, _unit in self.targets]

    @staticmethod
    def _label_width(label, size, bold=True):
        return len(label) * size * 0.5

    def available_width(self):
        return self.width - GRID_MARGIN - RIGHT_PADDING

    def talent_columns(self):
        # How many distinct x positions the talent rows actually landed on --
        # the column count as drawn, read back from the layout rather than
        # from the search's own bookkeeping.
        layout_items, _row_height, _divider_height, _scale = self.compute_grid()
        return len({item["x"] for item in layout_items if item["type"] == "talent"})

    def bottom_gap(self):
        # Panel height left empty below the last row, which is what a column
        # count that doesn't fill the window costs the user.
        layout_items, row_height, _divider_height, _scale = self.compute_grid()
        grid_end = max(item["y"] + item["h"] for item in layout_items)
        return self.height - FOOTER_RESERVED_HEIGHT - grid_end


def test_a_short_roster_gives_up_a_column_rather_than_leave_a_gap():
    # Few enough talents that the widest layout runs out of readable text
    # size (the label-fit ceiling) before the rows reach the bottom of the
    # panel. Picking purely by text size keeps that layout and strands the
    # leftover height as empty panel; one column fewer is taller, and fills.
    widget = FakeGrid(talents=24, width=1600, height=900)

    assert widget.talent_columns() < int(widget.available_width() // widget.target_col_width())
    assert widget.bottom_gap() < DEFAULT_ROW_HEIGHT


def test_a_long_roster_still_uses_every_column_the_width_allows():
    # The other end of the same trade: with more rows than the window can
    # show at full size, the widest layout is also the one that fills best,
    # so nothing is given up to reach the bottom.
    widget = FakeGrid(talents=400, width=1600, height=900)

    assert widget.talent_columns() == int(widget.available_width() // widget.target_col_width())


@pytest.mark.parametrize("talents", [8, 24, 60, 200])
@pytest.mark.parametrize("height", [600, 900, 1400])
def test_the_grid_never_leaves_more_than_a_row_of_empty_panel(talents, height):
    # Resizing the window shouldn't be able to strand a band of empty panel
    # under the grid: some column count always reaches the bottom, and the
    # search prefers one that does over a wider one that doesn't.
    widget = FakeGrid(talents=talents, width=1600, height=height)

    assert widget.bottom_gap() < DEFAULT_ROW_HEIGHT + DEFAULT_DIVIDER_HEIGHT


def test_the_title_view_uses_several_columns_on_a_wide_window():
    # It used to be pinned to one full-width row per talent, which left a
    # wide window mostly empty beside a short live list (and shrank a long
    # one to fit rather than using the room next to it).
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=True)

    assert widget.talent_columns() > 1
    # ...but a title column stays wide enough for a name plus its
    # now-playing ticker, unlike the plain grid's much narrower pitch.
    _layout_items, _row_height, _divider, _scale = widget.compute_grid()
    assert widget.available_width() / widget.talent_columns() >= grid_layout.TITLE_COL_WIDTH


def test_the_title_view_stays_single_column_when_a_row_needs_the_whole_width():
    widget = FakeGrid(talents=40, width=700, height=1000, show_titles=True)

    assert widget.talent_columns() == 1


def test_a_dangling_title_view_row_stays_inside_its_own_column():
    # 40 talents over 3 columns leaves a final row with a single entry in
    # column 0. The plain grid lets that kind of leftover entry claim the
    # rest of the row's width (see _layout_talent_section()'s "now-empty
    # trailing columns" note) since its columns are bare names with nothing
    # drawn between them -- but the title view draws a visible gap/divider
    # between columns (see TITLE_COLUMN_GAP), so the same stretch instead
    # runs the row's name+ticker straight through that divider and into the
    # next column's space.
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=True)
    layout_items, _row_height, _divider_height, _scale = widget.compute_grid()
    talent_items = [item for item in layout_items if item["type"] == "talent"]
    col_xs = sorted({item["x"] for item in talent_items})
    assert len(col_xs) > 1
    last_row_y = max(item["y"] for item in talent_items)
    dangling = [item for item in talent_items if item["y"] == last_row_y]
    assert len(dangling) == 1
    item = dangling[0]
    own_column_index = col_xs.index(item["x"])
    next_column_x = col_xs[own_column_index + 1]

    assert item["x"] + item["w"] <= next_column_x


def _talent_column_starts(widget):
    layout_items, _row_height, _divider_height, _scale = widget.compute_grid()
    return sorted({item["x"] for item in layout_items if item["type"] == "talent"})


def test_column_boundary_hit_finds_the_line_between_two_columns():
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=True)
    layout_items, _row_height, _divider_height, _scale = widget.compute_grid()
    talent_items = [item for item in layout_items if item["type"] == "talent"]
    xs = sorted({item["x"] for item in talent_items})
    assert len(xs) > 1
    boundary_x = xs[1]
    row_y = min(item["y"] for item in talent_items) + 2

    assert widget.column_boundary_hit(boundary_x, row_y) == 0
    assert widget.column_boundary_hit(boundary_x + 50, row_y) is None


def test_column_boundary_hit_is_none_outside_the_title_view():
    # The plain grid's columns are bare names -- nothing worth dragging
    # between them (see grid_col_width()) -- so this always misses there,
    # regardless of where the pointer lands.
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=False)

    assert widget.column_boundary_hit(500, 300) is None


def test_dragging_a_column_boundary_only_resizes_its_two_neighbors():
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=True)
    xs = _talent_column_starts(widget)
    assert len(xs) >= 3

    drag = widget.start_column_boundary_drag(0)
    widget.update_column_boundary_drag(drag, xs[1] + 80)

    new_xs = _talent_column_starts(widget)
    assert new_xs[0] == xs[0]
    assert new_xs[1] == pytest.approx(xs[1] + 80, abs=1)
    # Every boundary past the dragged pair is untouched: the two columns
    # after it keep both their original width and position.
    assert new_xs[2:] == pytest.approx(xs[2:], abs=1)


def test_a_column_boundary_drag_cannot_squeeze_a_column_below_the_minimum():
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=True)
    xs = _talent_column_starts(widget)

    drag = widget.start_column_boundary_drag(0)
    # Dragged far past the neighbor's own right edge -- clamped rather than
    # collapsing column 1 to nothing or inverting the two columns' order.
    widget.update_column_boundary_drag(drag, xs[-1] + 5000)

    new_xs = _talent_column_starts(widget)
    assert new_xs[1] - new_xs[0] >= grid_layout.MIN_TITLE_COLUMN_WIDTH - 1


def test_column_widths_reset_to_equal_when_the_column_count_changes():
    widget = FakeGrid(talents=40, width=1900, height=1000, show_titles=True)
    xs = _talent_column_starts(widget)
    drag = widget.start_column_boundary_drag(0)
    widget.update_column_boundary_drag(drag, xs[1] + 80)
    assert widget.column_widths is not None

    # Narrow enough to force a single column (same window used by the
    # single-column test above) -- the dragged ratios no longer correspond
    # to anything on screen, so they're simply not applied.
    widget.width = 700
    new_xs = _talent_column_starts(widget)
    assert len(new_xs) == 1


def test_plain_grid_never_applies_a_title_view_column_drag():
    widget = FakeGrid(talents=400, width=1600, height=900, show_titles=False)
    xs = _talent_column_starts(widget)
    assert len(xs) > 2
    # A column count that happens to match a list left over from the title
    # view (e.g. after switching tabs) still shouldn't skew the plain grid's
    # always-equal columns.
    widget.column_widths = [0.5] + [0.5 / (len(xs) - 1)] * (len(xs) - 1)

    new_xs = _talent_column_starts(widget)
    widths = [b - a for a, b in zip(new_xs, new_xs[1:])]
    assert all(w == pytest.approx(widths[0], abs=1) for w in widths)


def test_effective_column_fractions_falls_back_to_equal_split():
    widget = FakeGrid(talents=10, width=1000, height=800, show_titles=True)

    assert widget._effective_column_fractions(3) == pytest.approx([1 / 3] * 3)

    widget.column_widths = [0.2, 0.3, 0.5]
    assert widget._effective_column_fractions(3) == [0.2, 0.3, 0.5]


def test_world_clock_text_still_advances_when_nothing_else_about_the_layout_changed(monkeypatch):
    # compute_grid() memoizes the layout it last computed (see cache_key) so a
    # live-only ticker's ~60ms renders don't redo the whole column search when
    # nothing about the roster/window changed -- but the clock section's text
    # is baked into that same cached result, and none of the cache-key fields
    # depend on the current time. tick_clock() calls request_render() once a
    # second specifically to keep the clock moving even when nothing else on
    # screen does, so a quiet render (every other input unchanged) must still
    # show it advance.
    widget = FakeGrid(talents=5, width=1600, height=900)
    monkeypatch.setattr(grid_layout.time, "time", lambda: 1_700_000_000.0)
    layout_items, *_ = widget.compute_grid()
    first_texts = [item["text"] for item in layout_items if item["type"] == "clock"]

    monkeypatch.setattr(grid_layout.time, "time", lambda: 1_700_000_061.0)
    layout_items, *_ = widget.compute_grid()
    second_texts = [item["text"] for item in layout_items if item["type"] == "clock"]

    assert second_texts != first_texts
    # Sized for the wrong column count -- ignored, same as a stale drag after
    # a resize (see test_column_widths_reset_to_equal_when_the_column_count_changes).
    assert widget._effective_column_fractions(4) == pytest.approx([0.25] * 4)
