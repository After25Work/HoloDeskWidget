"""GridMixin's state-dependent geometry: the slider row (now three sliders
wide), the title-filter row wedged between it and the grid, and the
user-adjustable column pitch. Driven through a stub carrying only the handful
of attributes these particular helpers read, so no Tk window is needed."""
import pytest

from deskwidget_core import grid_layout, layout
from deskwidget_core.config import COLUMN_SCALE_MAX, COLUMN_SCALE_MIN, MIN_WIDTH
from deskwidget_core.grid_layout import GridMixin


class FakeWidget(GridMixin):
    def __init__(self, width=MIN_WIDTH, column_scale=1.0):
        self.width = width
        self.column_scale = column_scale

    def has_multiple_productions(self):
        # Collapses the tab strip (and therefore tabs_strip_height()) to zero,
        # so every offset below is the fixed cascade from layout.TABS_TOP.
        return False


def test_slider_row_carries_every_block_left_to_right_without_overlap():
    geometry = FakeWidget(width=1000).slider_geometry()

    assert list(geometry) == [key for key, _width in grid_layout.SLIDER_BLOCKS]
    previous_right = None
    for key, block_width in grid_layout.SLIDER_BLOCKS:
        block = geometry[key]
        assert block["track_start"] == block["x"] + grid_layout.SLIDER_LABEL_OFFSET
        assert block["track_end"] == block["x"] + block_width
        if previous_right is not None:
            assert block["x"] == previous_right + grid_layout.SLIDER_BLOCK_GAP
        previous_right = block["track_end"]
    # The group is right-justified against the panel's right edge.
    assert previous_right == 1000 - 40


def test_slider_row_fits_inside_the_panel_at_minimum_width():
    geometry = FakeWidget().slider_geometry()

    leftmost = min(block["x"] for block in geometry.values())
    assert leftmost >= 40


def test_adding_the_width_slider_left_the_other_two_where_they_were():
    # SLIDER_BLOCKS is packed right-to-left, so the pre-existing
    # background/text pair must still land on the exact pixels it used to --
    # otherwise every user's muscle memory for those two moves on upgrade.
    geometry = FakeWidget(width=1000).slider_geometry()
    content_right = 1000 - 40

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
    assert widget.grid_top() == (widget.slider_row_y() + grid_layout.SLIDER_SEARCH_GAP
                                 + grid_layout.SEARCH_ROW_HEIGHT
                                 + grid_layout.SEARCH_GRID_GAP)
