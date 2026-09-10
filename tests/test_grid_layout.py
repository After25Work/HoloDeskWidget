"""GridMixin's state-dependent geometry: the slider row (which wraps onto
more rows than one when the window is too narrow to carry every slider side
by side), the title-filter row wedged between it and the grid, the
user-adjustable column pitch, and the panel inset fullscreen collapses.
Driven through a stub carrying only the handful of attributes these
particular helpers read, so no Tk window is needed."""
import pytest

from deskwidget_core import grid_layout, layout
from deskwidget_core.config import COLUMN_SCALE_MAX, COLUMN_SCALE_MIN, MIN_WIDTH
from deskwidget_core.grid_layout import GridMixin

# Wide enough that every slider block fits on a single row, so the tests
# about the group's left-to-right packing aren't also testing its wrapping.
ONE_ROW_WIDTH = 1000


class FakeWidget(GridMixin):
    def __init__(self, width=MIN_WIDTH, height=600, column_scale=1.0,
                 show_titles=False, is_fullscreen=False):
        self.width = width
        self.height = height
        self.column_scale = column_scale
        self.show_titles = show_titles
        self.is_fullscreen = is_fullscreen

    def has_multiple_productions(self):
        # Collapses the tab strip (and therefore tabs_strip_height()) to zero,
        # so every offset below is the fixed cascade from layout.TABS_TOP.
        return False


def test_slider_row_carries_every_block_left_to_right_without_overlap():
    geometry = FakeWidget(width=ONE_ROW_WIDTH).slider_geometry()

    assert list(geometry) == [key for key, _width in grid_layout.SLIDER_BLOCKS]
    previous_right = None
    for key, block_width in grid_layout.SLIDER_BLOCKS:
        block = geometry[key]
        assert block["row"] == 0
        assert block["track_start"] == block["x"] + grid_layout.SLIDER_LABEL_OFFSET
        assert block["track_end"] == block["x"] + block_width
        if previous_right is not None:
            assert block["x"] == previous_right + grid_layout.SLIDER_BLOCK_GAP
        previous_right = block["track_end"]
    # The group is right-justified against the panel's right edge.
    assert previous_right == ONE_ROW_WIDTH - 40


def test_slider_row_fits_inside_the_panel_at_minimum_width():
    geometry = FakeWidget().slider_geometry()

    leftmost = min(block["x"] for block in geometry.values())
    assert leftmost >= grid_layout.SLIDER_AREA_LEFT


def test_sliders_too_wide_for_one_row_wrap_onto_another():
    # Four slider blocks no longer fit side by side at MIN_WIDTH; they wrap
    # rather than run off the panel's left edge (or shrink every track for
    # every window size to serve the narrowest one).
    narrow = FakeWidget(width=MIN_WIDTH)

    assert narrow.slider_rows() > 1
    assert FakeWidget(width=ONE_ROW_WIDTH).slider_rows() == 1
    # Every wrapped row is still right-justified and inside the panel, and
    # rows below the first sit lower on screen, never overlapping.
    by_row = {}
    for block in narrow.slider_geometry().values():
        assert block["x"] >= grid_layout.SLIDER_AREA_LEFT
        assert block["track_end"] <= narrow.width - 40
        by_row.setdefault(block["row"], []).append(block)
    for row, blocks in by_row.items():
        assert max(block["track_end"] for block in blocks) == narrow.width - 40
        assert blocks[0]["y"] == narrow.slider_row_y() + row * grid_layout.SLIDER_ROW_PITCH


def test_wrapped_slider_rows_push_the_search_row_and_grid_down():
    narrow, wide = FakeWidget(width=MIN_WIDTH), FakeWidget(width=ONE_ROW_WIDTH)

    assert narrow.search_row_y() - narrow.slider_row_y() == pytest.approx(
        (wide.search_row_y() - wide.slider_row_y())
        * narrow.slider_rows() / wide.slider_rows())
    # The bottom slider row still clears the filter field below it.
    bottom_band = (narrow.slider_row_y()
                   + (narrow.slider_rows() - 1) * grid_layout.SLIDER_ROW_PITCH
                   + grid_layout.SLIDER_HIT_PAD_BOTTOM)
    assert narrow.search_box_rect()[1] > bottom_band


def test_adding_the_width_slider_left_the_other_two_where_they_were():
    # SLIDER_BLOCKS is packed right-to-left, so the pre-existing
    # background/text pair must still land on the exact pixels it used to --
    # otherwise every user's muscle memory for those two moves on upgrade.
    geometry = FakeWidget(width=ONE_ROW_WIDTH).slider_geometry()
    content_right = ONE_ROW_WIDTH - 40

    assert geometry["text"]["track_end"] == content_right
    assert geometry["background"]["track_end"] == content_right - 124 - 14


def test_search_row_sits_between_the_sliders_and_the_grid():
    widget = FakeWidget()

    assert widget.search_row_y() > widget.slider_row_y()
    box_top, box_bottom = widget.search_box_rect()[1], widget.search_box_rect()[3]
    assert box_bottom - box_top == grid_layout.SEARCH_ROW_HEIGHT
    assert widget.grid_top() == box_bottom + grid_layout.SEARCH_GRID_GAP


def test_search_entry_sits_inside_its_drawn_box():
    widget = FakeWidget(width=1200)
    box = widget.search_box_rect()
    entry = widget.search_entry_rect()

    assert box[0] < entry[0] and entry[2] < box[2]
    assert box[1] < entry[1] and entry[3] < box[3]
    # The magnifier drawn by rendering.py needs its lane on the left.
    assert entry[0] - box[0] == grid_layout.SEARCH_ICON_LANE


def test_clear_button_sits_beside_the_box_without_overlapping_it():
    widget = FakeWidget(width=1200)

    box, clear = widget.search_box_rect(), widget.search_clear_rect()

    assert clear[0] == box[2] + grid_layout.SEARCH_CLEAR_GAP
    assert clear[3] == box[3] and clear[1] == box[1]


@pytest.mark.parametrize("width", [MIN_WIDTH, 900, 1600, 3840])
def test_search_row_stays_inside_the_panel_at_every_width(width):
    widget = FakeWidget(width=width)

    box, clear = widget.search_box_rect(), widget.search_clear_rect()

    assert box[0] == 38
    assert box[2] > box[0]
    assert clear[2] <= width - 38


def test_search_box_width_is_clamped_at_both_ends():
    assert (FakeWidget(width=3840).search_box_rect()[2] - 38
            == grid_layout.SEARCH_BOX_MAX_WIDTH)
    # A narrow window still gets at least the minimum, as long as the clear
    # button beside it still fits.
    narrow = FakeWidget(width=MIN_WIDTH).search_box_rect()
    assert narrow[2] - narrow[0] >= grid_layout.SEARCH_BOX_MIN_WIDTH


def test_search_row_clears_the_slider_hit_band():
    # The sliders and the filter field are on adjacent rows and are hit-tested
    # independently, so a click meant for one must never land in the other's
    # band (see SLIDER_HIT_PAD_BOTTOM).
    widget = FakeWidget()

    slider_band_bottom = widget.slider_row_y() + grid_layout.SLIDER_HIT_PAD_BOTTOM
    assert widget.search_box_rect()[1] > slider_band_bottom


@pytest.mark.parametrize("scale", [COLUMN_SCALE_MIN, 1.0, COLUMN_SCALE_MAX])
def test_target_col_width_scales_the_base_pitch(scale):
    assert (FakeWidget(column_scale=scale).target_col_width()
            == pytest.approx(grid_layout.TARGET_COL_WIDTH * scale))


def test_widening_the_pitch_never_increases_the_column_count():
    available = 1600 - grid_layout.GRID_MARGIN - grid_layout.RIGHT_PADDING

    counts = [int(available // FakeWidget(column_scale=scale).target_col_width())
              for scale in (COLUMN_SCALE_MIN, 1.0, COLUMN_SCALE_MAX)]

    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]


def test_default_column_scale_reproduces_the_old_fixed_pitch():
    assert FakeWidget().target_col_width() == grid_layout.TARGET_COL_WIDTH


def test_grid_top_cascade_starts_at_the_tab_strip():
    widget = FakeWidget()

    assert widget.status_bar_top() == layout.TABS_TOP + grid_layout.TABS_BOTTOM_GAP
    assert widget.grid_top() == (widget.slider_row_y()
                                 + widget.slider_rows() * grid_layout.SLIDER_ROW_PITCH
                                 + grid_layout.SEARCH_ROW_HEIGHT
                                 + grid_layout.SEARCH_GRID_GAP)


def test_title_view_columns_are_wider_than_plain_grid_columns():
    # A title-view row carries the now-playing ticker beside the name, so it
    # takes a much wider column before a second one fits -- but it is still a
    # column count, not the one-full-width-row-per-talent it used to be.
    assert (FakeWidget(show_titles=True).grid_col_width()
            > FakeWidget(show_titles=False).grid_col_width())
    assert FakeWidget(show_titles=True).grid_col_width() == grid_layout.TITLE_COL_WIDTH
    assert FakeWidget(show_titles=False).grid_col_width() == grid_layout.TARGET_COL_WIDTH


def test_fullscreen_collapses_the_panel_inset_and_corner_radius():
    # Everything outside the drawn panel is transparent, so a floating
    # widget's inset/rounded corners would show the desktop through the edges
    # of a window that is meant to be covering the whole screen.
    floating, full = FakeWidget(), FakeWidget(is_fullscreen=True)

    assert (floating.panel_inset(), floating.panel_radius()) == (
        grid_layout.PANEL_INSET, grid_layout.PANEL_RADIUS)
    assert (full.panel_inset(), full.panel_radius()) == (0, 0)
    # The resize hit-band follows the panel's drawn edge either way: at the
    # window's literal left edge when fullscreen squares the panel off, and
    # PANEL_INSET further in while the panel floats.
    assert full.resize_edge(0, 300) == "w"
    assert floating.resize_edge(0, 300) is None
    assert floating.resize_edge(grid_layout.PANEL_INSET, 300) == "w"
