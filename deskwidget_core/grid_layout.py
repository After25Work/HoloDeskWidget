"""Geometry/hit-testing that depends on live widget state (window size,
loaded productions, current targets/text-scale) -- everything render() draws
and click()/on_motion() hit-test against. Kept separate from layout.py, which
only holds pure, state-free arithmetic (button/tab positions from a width
alone); everything here additionally reads `self`.
"""
import time

from . import layout
from .strings import format_world_clock
from .talents import ALL_PRODUCTION_ID, production_display_name

# The status bar/slider row/grid all shift down together depending on how
# many rows the production tab strip above them wraps to at the current
# window width (see layout.production_tab_rects) — each of these derives
# from the one before it rather than using fixed constants, so they can
# never drift out of sync with the tab strip's actual height. A variant with
# only one production never shows a tab strip at all (see production_tabs()
# below), which collapses tabs_strip_height() to 0 and this whole cascade
# back down to fixed offsets from TABS_TOP alone.
TABS_BOTTOM_GAP = 12
STATUS_BAR_HEIGHT = 37
STATUS_SLIDER_GAP = 5
SLIDER_GRID_GAP = 22

# Shared by build_grid_layout() and compute_grid() -- these two must never
# disagree, since compute_grid() searches for a scale/column-count pair that
# build_grid_layout() (given that same width) will actually lay out within
# the available height; a mismatched margin/column-pitch pair here would let
# the two silently drift apart on some window sizes.
GRID_MARGIN = 40
TARGET_COL_WIDTH = 110


class GridMixin:
    _RESIZE_MARGIN = 8
    _RESIZE_CURSORS = {
        "n": "size_ns", "s": "size_ns",
        "e": "size_we", "w": "size_we",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
        "nw": "size_nw_se", "se": "size_nw_se",
    }

    def top_button_rects(self):
        order = layout.button_order(self.has_multiple_productions())
        return layout.top_button_rects(self.width, order)

    def top_button_actions(self):
        # Single source of truth for "which button does what", keyed the same
        # as top_button_rects()/layout.TOP_BUTTON_ORDER — click() and
        # focusable_items() both dispatch through this instead of each
        # naming every button key independently, so a button added to
        # layout.py can't end up mouse-clickable but unreachable by keyboard
        # (or vice versa). Always includes "productions" even for a
        # single-production variant (which never draws or hit-tests that key
        # — see top_button_rects() above) so this dict's shape doesn't itself
        # depend on how many productions are loaded.
        return {
            "close": self.close,
            "fullscreen": self.toggle_fullscreen,
            "tray": self.minimize_to_tray,
            "pin": self.toggle_topmost,
            "lang": self.toggle_lang,
            "color": self.toggle_palette,
            "font": self.toggle_font_menu,
            "mode": self.toggle_mode,
            "productions": self.toggle_productions_menu,
            "filter": self.toggle_live_only,
        }

    def production_tabs(self):
        # Geometry + label for every production tab (including the pseudo
        # "All" tab, see _tab_productions()), in display order. A variant
        # with only one production has nothing to switch between, so it
        # shows no tab strip at all (not even a single "All" tab) rather than
        # a strip that can never do anything useful. Recomputed on every call
        # (cheap: pure arithmetic, no I/O) rather than cached, so a language
        # toggle or window resize is reflected immediately without a
        # separate invalidation path.
        if not self.has_multiple_productions():
            return []
        tab_productions = self._tab_productions()
        rects, _ = layout.production_tab_rects(self.width, len(tab_productions))
        return [
            {"id": production["id"], "x": x, "y": y, "w": w, "h": h,
             "label": production_display_name(production, self.lang)}
            for production, (x, y, w, h) in zip(tab_productions, rects)
        ]

    def tabs_strip_height(self):
        _, total_height = layout.production_tab_rects(self.width, len(self.production_tabs()))
        return total_height

    def status_bar_top(self):
        return layout.TABS_TOP + self.tabs_strip_height() + TABS_BOTTOM_GAP

    def status_bar_bottom(self):
        return self.status_bar_top() + STATUS_BAR_HEIGHT

    def slider_row_y(self):
        return self.status_bar_bottom() + STATUS_SLIDER_GAP

    def grid_top(self):
        return self.slider_row_y() + SLIDER_GRID_GAP

    def resize_grip_rect(self):
        # Kept clear of refresh_btn_rect()'s bottom-right corner (which ends at
        # width-44, height-34) so the two hit-zones never overlap, and kept
        # inside the panel's own edge (width-20, height-20) so it never reaches
        # into the transparentcolor margin, where clicks pass straight through
        # to whatever's behind the window.
        return (self.width - 44, self.height - 44, self.width - 22, self.height - 22)

    def resize_edge(self, x, y):
        # An ordinary window can be resized by dragging any of its edges;
        # this one only ever offered the small bottom-right grip. That grip
        # stays (it's the only visible affordance for "this can resize" —
        # see draw_resize_grip()), but every panel edge now also grabs a
        # resize, catching the common "drag the border" habit too. The catch
        # band hugs the PANEL's own edge (20px in from the window edge), not
        # the window's literal edge: everything outside the panel is
        # -transparentcolor, where clicks pass through to whatever's behind
        # the window and never reach this widget at all (see the note on
        # resize_grip_rect() above).
        m = self._RESIZE_MARGIN
        near_left = 20 <= x <= 20 + m
        near_right = self.width - 20 - m <= x <= self.width - 20
        near_top = 20 <= y <= 20 + m
        near_bottom = self.height - 20 - m <= y <= self.height - 20
        if near_top and near_left:
            return "nw"
        if near_top and near_right:
            return "ne"
        if near_bottom and near_left:
            return "sw"
        if near_bottom and near_right:
            return "se"
        if near_left:
            return "w"
        if near_right:
            return "e"
        if near_top:
            return "n"
        if near_bottom:
            return "s"
        return None

    def refresh_btn_rect(self):
        return (38, self.height - 65, self.width - 44, self.height - 34)

    def slider_geometry(self):
        # Both sliders sit on one row, right-justified as a pair against the
        # panel's right edge — fixed (not width-proportional) block widths so
        # they still fit side by side at MIN_WIDTH. Label offset (74px) is
        # sized for the longer of the two languages' "label + 100%" text
        # ("背景濃さ 100%"), reused for both sliders for simplicity.
        content_right = self.width - 40
        y, gap, label_offset = self.slider_row_y(), 14, 74
        text_width, bg_width = 124, 134
        text_x = content_right - text_width
        bg_x = text_x - gap - bg_width
        return {
            "background": {"x": bg_x, "y": y, "track_start": bg_x + label_offset,
                           "track_end": bg_x + bg_width},
            "text": {"x": text_x, "y": y, "track_start": text_x + label_offset,
                     "track_end": text_x + text_width},
        }

    def _clock_layout(self, available, natural_cols):
        # Picks how many columns (<=3, capped by natural_cols on a narrow
        # window) the world clock packs into at this window width, trying
        # the widest layout first and falling back to fewer/wider columns
        # whenever the natural (unshrunk) text doesn't fit -- see the note
        # in build_grid_layout() for why fewer, wider columns beat shrinking
        # everything down to MIN_LABEL_SIZE and past it into ellipsis
        # truncation. Shared by build_grid_layout() (which draws the clock
        # at the resulting column count) and compute_grid() (which needs
        # that same column count to know how many rows tall the clock
        # section is when carving its footprint out of the talent grid's
        # available height) so the two can never disagree about how tall
        # the clock section actually ends up.
        clock_entries = list(format_world_clock(self.lang, time.time()))
        # Date leads (not the zone label) so every row's date starts at the
        # same x within its column regardless of how long that zone's own
        # label is -- with the label first, a short "UTC" and a long
        # "PDT(Los Angeles)" pushed their date/time portions to different
        # offsets even though both rows started at the same column x.
        clock_texts = [f"{date_part} {label} {time_part}" for label, date_part, time_part in clock_entries]
        clock_label_size = max(2, round(16 * self.text_scale))
        clock_col_gap = 24
        max_clock_cols = min(natural_cols, 3)
        clock_cols, col_widths = max_clock_cols, None
        for candidate_cols in range(max_clock_cols, 0, -1):
            # Columns are packed to their own natural content width (each one
            # only as wide as its widest entry needs), rather than splitting
            # the available width evenly -- an even split left a huge,
            # ragged gap between a short zone's text and the next column's
            # start, which read as misaligned even though the column
            # *positions* were evenly spaced. Measured at the same font size
            # render() actually draws with (self.text_scale, not
            # clock_row_height/clock_divider_height, for the reasons noted
            # by clock_label_size in render()) so a column is exactly as
            # wide as its text needs at 1:1, with no leftover slack for
            # _fit_label() to shrink into.
            widths = [0.0] * candidate_cols
            for i, text in enumerate(clock_texts):
                c = i % candidate_cols
                widths[c] = max(widths[c], self._label_width(text, clock_label_size, True) + 12)
            total = sum(widths) + clock_col_gap * (candidate_cols - 1)
            if total <= available or candidate_cols == 1:
                clock_cols, col_widths = candidate_cols, widths
                break
        return clock_entries, clock_texts, clock_cols, col_widths, clock_col_gap

    def build_grid_layout(self, row_height, divider_height, num_cols=None,
                           clock_row_height=None, clock_divider_height=None,
                           clock_layout=None, targets=None, states=None):
        # Shared by render() (drawing) and click() (hit-testing) so the two never
        # drift apart. Column count grows with the window so widening reflows more
        # columns in rather than just stretching 3. Talents are grouped by unit
        # explicitly (not by detecting adjacency in self.targets) so a unit's rows
        # always merge into one section even if a production's talent-list JSON
        # ever lists that unit's members non-contiguously. row_height/divider_height
        # are parameterized so
        # compute_grid() can shrink them (and the matching font sizes) to fit
        # everything with no scrolling. num_cols lets compute_grid() try
        # narrower columns counts than the width alone would give, so a tall
        # window with few talents wraps into more rows instead of leaving the
        # bottom of the panel empty. Unlike the world clock's own sub-grid
        # below (always natural_cols-pitched), the talent grid's column width
        # stretches to available/num_cols whenever compute_grid() picks fewer
        # columns than natural_cols — otherwise the freed-up columns would
        # just sit empty on the right instead of giving compute_grid() a
        # wider (and therefore taller-scaling) pitch to size the shared label
        # font against.
        margin, target_col_width = GRID_MARGIN, TARGET_COL_WIDTH
        available = self.width - margin - 40
        natural_cols = max(1, int(available // target_col_width))
        if num_cols is None:
            num_cols = natural_cols
        # The world clock's own row/divider height defaults to the talent
        # grid's (for callers that don't care, e.g. compute_grid()'s own
        # "natural size at scale 1" probe) but compute_grid()'s real render
        # pass always supplies its own fixed values — see the note by
        # clock_row_height in compute_grid() for why the clock section can't
        # just use row_height/divider_height like everything else here.
        if clock_row_height is None:
            clock_row_height = row_height
        if clock_divider_height is None:
            clock_divider_height = divider_height
        units = {}
        # Read the targets/states properties once up front rather than once
        # per loop iteration -- for the "All" tab (active_production ==
        # ALL_PRODUCTION_ID) each read re-merges every visible production's
        # dict from scratch (see _merge_all_slots()), so calling it inside
        # this loop turned an O(N) pass into an O(N^2) one across a few
        # hundred talents, repeated for every candidate column count
        # compute_grid() tries and on every ~60ms ticker tick. compute_grid()
        # merges these once itself and passes them straight through (see its
        # own note) so the merge doesn't repeat once per candidate column
        # count on top of that; callers that don't have a merge on hand yet
        # (fit_height()'s one-shot call) just let this fall through to self.
        targets = self.targets if targets is None else targets
        states = self.states if states is None else states
        for index, target in enumerate(targets):
            if self.live_only and states[target[0]] != "live":
                continue
            units.setdefault(target[3], []).append(index)
        layout_items = []
        y = self.grid_top()
        # World clock: shown as its own category using the exact same
        # divider-header + grid mechanics as a talent unit below, so it
        # scales with everything else instead of living in a separately
        # positioned fixed block. It always gets its own <=3-column sub-grid
        # (capped by natural_cols on narrow windows, and narrowed further
        # still if even that doesn't fit -- see _clock_layout() -- never by
        # the talent grid's possibly-overridden num_cols) rather than
        # num_cols, since a date+time string is far longer than a talent
        # name and the clock should look the same regardless of how the
        # talent grid below wraps.
        layout_items.append({"type": "divider", "kind": "clock", "y": y,
                              "unit": self.t("clock_category"), "h": clock_divider_height})
        y += clock_divider_height
        # clock_layout lets a caller that already computed this (compute_grid(),
        # across every candidate column count it tries plus its final build)
        # pass the same tuple straight through instead of recomputing it --
        # available/natural_cols above never vary with num_cols, so every one
        # of those calls would otherwise redo the exact same _clock_layout()
        # search and measurement work for an identical result.
        clock_entries, clock_texts, clock_cols, col_widths, clock_col_gap = (
            clock_layout if clock_layout is not None
            else self._clock_layout(available, natural_cols))
        natural_total = sum(col_widths) + clock_col_gap * (clock_cols - 1)
        if natural_total > available:
            # Still too wide even at 1 column (an unusually narrow window, or
            # an unusually long custom label in clock_zones.json) -- shrink
            # every column proportionally (uniformly, so the columns still
            # line up with each other) rather than overflow the panel;
            # render()'s _fit_label() then shrinks each cell's font a little
            # further to fit its now-tighter column.
            shrink = available / natural_total
            col_widths = [w * shrink for w in col_widths]
            clock_col_gap *= shrink
        col_x = []
        cursor = margin
        for w in col_widths:
            col_x.append(cursor)
            cursor += w + clock_col_gap
        col = 0
        for i, text in enumerate(clock_texts):
            label = clock_entries[i][0]
            layout_items.append({"type": "clock", "x": col_x[col], "y": y,
                          "w": col_widths[col], "text": text,
                          "zone": label, "h": clock_row_height})
            col += 1
            if col == clock_cols:
                col = 0
                y += clock_row_height
        if col != 0:
            y += clock_row_height
        # While the live-only filter is on, every remaining talent is live, so
        # give each its own full-width row (one line per talent) instead of the
        # normal grid columns — that's the room the program-title ticker in
        # render() needs to the right of the name.
        unit_cols = 1 if self.live_only else num_cols
        unit_col_width = available if self.live_only else available / num_cols
        group_position = 0
        for unit, indices in units.items():
            # On the "All" tab each unit is a whole production (see
            # _all_targets()'s retagging), so its rows get a shaded background
            # band -- the divider text alone was too easy to miss when
            # several productions' rows sit back-to-back with the same plain
            # panel background. Recorded as its own layout item (inserted
            # before this unit's divider/rows below) rather than drawn ad hoc
            # in render(), so it stays in the same y-computed-once place as
            # everything else here. Keyed by this group's position in the
            # rendered order (not the production's own identity), so
            # production_band_color() only needs to alternate shades between
            # neighbors -- see its own note.
            band_index = len(layout_items)
            band_start_y = y
            layout_items.append({"type": "divider", "kind": "unit", "y": y, "unit": unit, "h": divider_height})
            y += divider_height
            col = 0
            for index in indices:
                layout_items.append({"type": "talent", "x": margin + col * unit_col_width, "y": y,
                              "w": unit_col_width, "index": index, "h": row_height})
                col += 1
                if col == unit_cols:
                    col = 0
                    y += row_height
            if col != 0:
                # This unit's last row didn't fill every column — let its last
                # entry's label claim the now-empty trailing columns instead of
                # being shrunk/truncated to a single column's width.
                last_item = layout_items[-1]
                last_item["w"] = margin + available - last_item["x"]
                y += row_height
            if self.active_production == ALL_PRODUCTION_ID:
                layout_items.insert(band_index, {"type": "band", "y": band_start_y,
                                                  "h": y - band_start_y, "position": group_position})
                group_position += 1
        return layout_items, y

    def compute_grid(self, targets=None, states=None):
        # No scroll support: rows/dividers/fonts scale uniformly so nothing is
        # dropped when the window is too short for the content (shrinking),
        # and text grows a bit for readability when the window is taller than
        # the content needs (see the growth-cap note below) — but the grid
        # itself always stays top-aligned, like an ordinary list.
        grid_top = self.grid_top()
        available_height = max(1, self.height - grid_top - 90)
        margin, target_col_width = GRID_MARGIN, TARGET_COL_WIDTH
        available_width = self.width - margin - 40
        natural_cols = max(1, int(available_width // target_col_width))

        # The world clock's row/divider height is pinned to the text-size
        # slider alone (self.text_scale), not to the per-tab `scale` this
        # function solves for below — see the matching note by
        # divider_font/clock_label_size in render(). Switching tabs changes
        # how many talent rows there are, which used to feed back into the
        # clock's own row height too, so the world clock's line spacing
        # visibly shifted every time you changed tabs even though the clock
        # itself never changed. Its real (fixed) footprint is carved out of
        # available_height up front so measure() below only fits the talent
        # grid into whatever's left, and its *base* (scale-1) footprint is
        # subtracted from each candidate's natural content height so the
        # resulting talent-only scale isn't skewed by clock rows that no
        # longer actually scale with it.
        clock_row_height = 25 * self.text_scale
        clock_divider_height = 18 * self.text_scale
        # Column count must match _clock_layout()'s own search (used by
        # build_grid_layout() to actually draw the clock) rather than the
        # naive min(natural_cols, 3) this used to hardcode here -- on a
        # window too narrow to fit 3 columns of a date+region+time string at
        # its natural width, build_grid_layout() falls back to fewer, wider
        # columns (see the note there), which means more rows than this
        # would otherwise have assumed. Leaving this at a fixed 3 columns
        # made the clock's real (fallen-back) row count taller than the
        # footprint carved out for it below, so the talent grid's own
        # available_height came out too generous and its last rows could
        # run past the bottom of the window.
        # Computed once and passed straight through to every build_grid_layout()
        # call below (each candidate column count in measure()'s search, plus
        # the final build past the loop) instead of letting each one redo this
        # same search -- available_width/natural_cols never vary with the
        # talent grid's candidate column count, so every one of those calls
        # would otherwise recompute an identical result.
        clock_layout = self._clock_layout(available_width, natural_cols)
        clock_entries, _, clock_cols, _, _ = clock_layout
        clock_rows = -(-len(clock_entries) // clock_cols)
        clock_height = clock_divider_height + clock_rows * clock_row_height
        clock_base_height = 18 + clock_rows * 25
        available_height = max(1, available_height - clock_height)

        # Merged once here rather than left for each measure() candidate's
        # build_grid_layout() call to re-fetch: on the "All" tab, self.targets
        # /self.states each re-merge every visible production's dict from
        # scratch (see _merge_all_slots()), so leaving that inside the
        # column-count search below repeated the merge once per candidate
        # (and again for the final build_grid_layout() call past the loop),
        # on every render -- including every ~60ms ticker tick. render()
        # already has its own merged copy on hand (for the status bar/talent
        # loop) and passes it straight through so this doesn't merge a second
        # time on top of that; callers with no merge on hand yet (click(),
        # focus_next()/focus_prev()) just let this fall through to self.
        targets = self.targets if targets is None else targets
        states = self.states if states is None else states

        # The column-count search below (and every build_grid_layout()/
        # widest_fit() call inside it) is pure given (width, height,
        # text_scale, live_only, targets, states) -- but render() calls this
        # unconditionally on every ~60ms live-only ticker tick, and those
        # inputs are almost always unchanged between one tick and the next
        # (nothing resizes/rescales/goes live or offline mid-scroll). Cached
        # on exactly those inputs so a tick that changes none of them reuses
        # last call's result instead of re-running the whole search; any
        # actual change (resize, a text-scale drag, a state transition) still
        # falls through and recomputes normally.
        cache_key = (self.width, self.height, self.text_scale, self.live_only,
                     tuple(targets), tuple(sorted(states.items())))
        cached = getattr(self, "_grid_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        # Visible labels are the same regardless of which column count ends
        # up chosen below — only the column *width* they're measured against
        # changes per candidate — so this is gathered once rather than
        # inside the per-candidate closure.
        all_labels = None if self.live_only else self._visible_talent_labels(targets, states)

        def widest_fit(labels, max_label_width, bold=True):
            # Largest integer font size at/above 16 for which every label in
            # `labels` still fits max_label_width — found by doubling until
            # it no longer fits, then binary-searching that bracket, so the
            # cost stays ~log2(answer) regardless of how far a very wide
            # column (or a very short name) lets this grow, rather than
            # scanning every point size up to whatever the ceiling turns out
            # to be. Uses the cached _label_width() rather than a fresh
            # getbbox() per check: this runs once per candidate column count
            # in the search below, and neighboring candidates' searches
            # revisit a lot of the same (label, size) pairs.
            def fits(size):
                return all(self._label_width(label, size, bold) <= max_label_width
                           for label in labels)
            lo, hi = 16, 16
            while fits(hi * 2):
                hi *= 2
            hi *= 2
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits(mid):
                    lo = mid
                else:
                    hi = mid - 1
            return lo

        def label_fit_scale(col_width):
            # How far row/divider height (and, via label_scale in render(),
            # the shared talent-label font) may grow past 1x at this column
            # width before the widest *normal-length* visible name would stop
            # fitting it (see _visible_talent_labels()/_shared_label_size())
            # — otherwise render() would have to shrink the shared font back
            # down to make everyone fit (see the note above render()'s
            # talent loop), leaving rows taller than the text now sitting
            # inside them. Names that don't even fit at the normal 1x size
            # (e.g. a long EN transliterated name) are excluded from this
            # check rather than left to drag the ceiling down to 1x for
            # every *other* name in the room — they're headed for
            # _fit_label()'s ellipsis truncation regardless of scale (dense
            # rosters like hololive's already relied on exactly that before
            # any of this growth/wrap logic existed), so their presence
            # shouldn't cancel out growth that every normal-length name
            # could otherwise use. No flat readability ceiling above 1x:
            # unlike the old fixed 1.5x cap, a gap left on screen is worse
            # than text this column can genuinely still fit — measure()'s
            # own raw_scale (bounded by the actual available height) is what
            # stops this from growing past what the window can show.
            if not all_labels:
                return 1.5
            max_label_width = col_width - 12
            labels = [label for label in all_labels
                      if self._label_width(label, 16, True) <= max_label_width]
            if not labels:
                return 1.5
            return widest_fit(labels, max_label_width) / 16

        def measure(cols):
            # build_grid_layout() stretches its talent column pitch to
            # available_width/cols whenever cols < natural_cols (see its own
            # note), so the label-fit ceiling has to be recomputed against
            # that same stretched width per candidate — a narrower cols
            # count widens each column, which can raise the ceiling (more
            # room per name) even as it also raises content_height (fewer
            # columns means more rows).
            scale_cap = label_fit_scale(available_width / cols)
            _, natural_end = self.build_grid_layout(25, 18, num_cols=cols,
                                                      clock_layout=clock_layout,
                                                      targets=targets, states=states)
            content_height = max(1, natural_end - grid_top - clock_base_height)
            raw_scale = available_height / content_height
            return max(0.15, min(scale_cap, raw_scale))

        # Try every column count from the width-derived natural_cols down to
        # a single column and keep whichever yields the largest resulting
        # scale. Fewer columns stretch each one wider (see build_grid_layout)
        # instead of leaving the freed-up columns empty on the right, so
        # there's no horizontal cost to weigh against the vertical one
        # anymore — the best column count is simply whichever fills the
        # panel with the biggest readable text, favoring natural_cols on
        # ties so a wide layout is preferred when several counts tie.
        num_cols, scale = natural_cols, measure(natural_cols)
        for cols in range(natural_cols - 1, 0, -1):
            cand_scale = measure(cols)
            if cand_scale > scale:
                num_cols, scale = cols, cand_scale
        row_height = 25 * scale
        divider_height = 18 * scale
        # The label-fit ceiling derived above (or raw_scale itself, if that's
        # smaller) is what keeps rows from ballooning past what a very tall
        # window with little content (e.g. a small custom list on a
        # maximized 4K window) can actually fill; content stays anchored
        # under grid_top() (like an ordinary top-aligned list) rather than
        # being centered, so any space still left over — a name too long to
        # spell out at any scale without wrapping — simply falls below the
        # grid instead of stretching to hide it.
        layout_items, grid_end = self.build_grid_layout(row_height, divider_height, num_cols=num_cols,
                                                         clock_row_height=clock_row_height,
                                                         clock_divider_height=clock_divider_height,
                                                         clock_layout=clock_layout,
                                                         targets=targets, states=states)
        result = (layout_items, row_height, divider_height, scale)
        self._grid_cache = (cache_key, result)
        return result

    def focusable_items(self, grid_layout=None, row_height=None, targets=None):
        # Ordered list of keyboard-focusable regions, built from the same
        # rect helpers click() uses so Tab-order rects can never drift from
        # what a mouse click actually hits, and from top_button_actions() so
        # every top button is wired here automatically (adding one to
        # layout.py can't leave it mouse-clickable but keyboard-unreachable,
        # or vice versa). Order follows the button row's visual left-to-right
        # reading order (the reverse of layout.TOP_BUTTON_ORDER, which is
        # laid out right-to-left), then the two sliders, then each talent row
        # in grid order, then the bottom refresh button.
        #
        # render() already computes grid_layout/row_height/targets once for
        # its own drawing and passes them straight through here (for the
        # focus-ring rect) so a focused item doesn't force a second,
        # redundant compute_grid() pass -- or, on the "All" tab, a second
        # self.targets re-merge (see _merge_all_slots()) -- on every render,
        # including every ~60ms ticker tick while a live-only now-playing
        # ticker is on screen. Every other caller (keypress handlers) has no
        # such value on hand and computes its own, which is fine since those
        # only run once per keystroke.
        btn = self.top_button_rects()
        actions = self.top_button_actions()
        visual_order = ("filter", "productions", "mode", "color", "lang", "font", "pin", "tray", "fullscreen", "close")
        items = [{"kind": "button", "rect": btn[key], "activate": actions[key]}
                for key in visual_order if key in btn]
        for tab in self.production_tabs():
            rect = (tab["x"], tab["y"], tab["x"] + tab["w"], tab["y"] + tab["h"])
            items.append({"kind": "tab", "rect": rect,
                         "activate": lambda t=tab["id"]: self.switch_production(t)})
        for key, geom in self.slider_geometry().items():
            rect = (geom["track_start"], geom["y"] - 5, geom["track_end"], geom["y"] + 15)
            items.append({"kind": "slider", "rect": rect, "slider_key": key})
        if grid_layout is None:
            grid_layout, row_height, _, _ = self.compute_grid()
        targets = self.targets if targets is None else targets
        for item in grid_layout:
            if item["type"] == "talent":
                rect = (item["x"], item["y"], item["x"] + item["w"], item["y"] + row_height)
                target = targets[item["index"]]
                items.append({"kind": "talent", "rect": rect,
                             "activate": lambda t=target: self.open_target(t)})
        items.append({"kind": "button", "rect": self.refresh_btn_rect(), "activate": self.refresh})
        return items

    def slider_hit(self, x, y):
        # Returns which slider (by key) the point falls in, or False for none,
        # so drag/click handlers can dispatch to the right setter via
        # update_slider() instead of assuming there's only ever one slider.
        for key, geom in self.slider_geometry().items():
            if geom["y"] - 5 <= y <= geom["y"] + 15 and geom["track_start"] <= x <= geom["track_end"]:
                return key
        return False

    def _hit_row(self, x, y):
        for key, info in self.row_info.items():
            if self._in_rect(x, y, info["rect"]):
                return key, info
        return None, None

    @staticmethod
    def _in_rect(x, y, rect):
        left, top, right, bottom = rect
        return left <= x <= right and top <= y <= bottom
