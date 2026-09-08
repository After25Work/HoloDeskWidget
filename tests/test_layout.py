from deskwidget_core import layout


def test_button_order_drops_productions_for_single_production_variant():
    order = layout.button_order(has_multiple_productions=False)

    assert "productions" not in order
    assert order == [key for key in layout.TOP_BUTTON_ORDER if key != "productions"]


def test_button_order_keeps_productions_for_multi_production_variant():
    assert layout.button_order(has_multiple_productions=True) == layout.TOP_BUTTON_ORDER


def test_top_button_rects_lays_out_right_to_left_without_overlap():
    rects = layout.top_button_rects(1000)

    # Walking TOP_BUTTON_ORDER right-to-left, each button's left edge must
    # equal the previous (more-rightward) button's left edge minus its own
    # width and the gap -- i.e. no two buttons overlap and there are no gaps
    # bigger than BUTTON_GAP between neighbors.
    previous_left = 1000 - layout.BUTTON_RIGHT_MARGIN
    for key in layout.TOP_BUTTON_ORDER:
        left, top, right, bottom = rects[key]
        assert right == previous_left
        assert right - left == layout.TOP_BUTTON_WIDTHS[key]
        assert top == layout.BUTTON_ROW_TOP
        assert bottom == layout.BUTTON_ROW_TOP + layout.BUTTON_ROW_HEIGHT
        previous_left = left - layout.BUTTON_GAP


def test_button_row_delta_adds_gap_to_button_width():
    assert layout.button_row_delta("pin") == layout.TOP_BUTTON_WIDTHS["pin"] + layout.BUTTON_GAP


def test_production_tab_rects_returns_empty_for_zero_count():
    assert layout.production_tab_rects(1000, 0) == ([], 0)


def test_production_tab_rects_single_tab():
    rects, total_height = layout.production_tab_rects(1000, 1)

    assert len(rects) == 1
    assert total_height == layout.TAB_ROW_HEIGHT


def test_production_tab_rects_wraps_to_additional_rows_on_narrow_window():
    # A narrow window can only fit one column, so many tabs must wrap into
    # that many rows.
    rects, total_height = layout.production_tab_rects(200, 5)

    rows_used = {round(y) for (x, y, w, h) in rects}
    assert len(rects) == 5
    assert len(rows_used) == 5
    assert total_height == 5 * layout.TAB_ROW_HEIGHT + 4 * layout.TABS_GAP


def test_production_tab_rects_all_tabs_fit_within_window_width():
    width = 1200
    rects, _ = layout.production_tab_rects(width, 7)

    for x, y, w, h in rects:
        assert x >= layout.TABS_MARGIN
        assert x + w <= width - 40 + 1e-6
