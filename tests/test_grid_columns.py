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
