"""Geometry/hit-testing that depends on live widget state (window size,
current targets/text-scale) -- everything render() draws and click()/
on_motion() hit-test against. Kept separate from layout.py, which only holds
pure, state-free arithmetic (button positions from a width alone); everything
here additionally reads `self`.
"""
import time

from . import layout
from .strings import format_world_clock

# Top of the no-scroll talent grid, below the title/status bar and the
# background-darkness/text-size slider row. The world clock is drawn as the
# grid's own first category (see build_grid_layout()), not a separate block,
# so it no longer needs its own reserved space here.
GRID_TOP = 152


class GridMixin:
    _RESIZE_MARGIN = 8
    _RESIZE_CURSORS = {
        "n": "size_ns", "s": "size_ns",
        "e": "size_we", "w": "size_we",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
        "nw": "size_nw_se", "se": "size_nw_se",
    }

    def top_button_rects(self):
        return layout.top_button_rects(self.width)

    def top_button_actions(self):
        # Single source of truth for "which button does what", keyed the same
        # as top_button_rects()/layout.TOP_BUTTON_ORDER — click() and
        # focusable_items() both dispatch through this instead of each
        # naming every button key independently, so a button added to
        # layout.py can't end up mouse-clickable but unreachable by keyboard
        # (or vice versa) just because one of the two forgot to list it.
        return {
            "close": self.close,
            "fullscreen": self.toggle_fullscreen,
            "pin": self.toggle_topmost,
            "lang": self.toggle_lang,
            "color": self.toggle_palette,
            "font": self.toggle_font_menu,
            "mode": self.toggle_mode,
            "filter": self.toggle_live_only,
        }

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
        y, gap, label_offset = 130, 14, 74
        text_width, bg_width = 124, 134
        text_x = content_right - text_width
        bg_x = text_x - gap - bg_width
        return {
            "background": {"x": bg_x, "y": y, "track_start": bg_x + label_offset,
                           "track_end": bg_x + bg_width},
            "text": {"x": text_x, "y": y, "track_start": text_x + label_offset,
                     "track_end": text_x + text_width},
        }

    def build_grid_layout(self, row_height, divider_height):
        # Shared by render() (drawing) and click() (hit-testing) so the two never
        # drift apart. Column count grows with the window so widening reflows more
        # columns in rather than just stretching 3. Talents are grouped by unit
        # explicitly (not by detecting adjacency in self.targets) so a unit's rows
        # always merge into one section even if talents.json ever lists that unit's
        # members non-contiguously. row_height/divider_height are parameterized so
        # compute_grid() can shrink them (and the matching font sizes) to fit
        # everything with no scrolling.
        margin, target_col_width = 40, 110
        available = self.width - margin - 40
        num_cols = max(1, int(available // target_col_width))
        col_width = available / num_cols
        units = {}
        for index, target in enumerate(self.targets):
            if self.live_only and self.states[target[0]] != "live":
                continue
            units.setdefault(target[3], []).append(index)
        layout_items = []
        y = GRID_TOP
        # World clock: shown as its own category using the exact same
        # divider-header + grid mechanics as a talent unit below, so it
        # scales with everything else instead of living in a separately
        # positioned fixed block. It always gets its own <=3-column sub-grid
        # (capped by num_cols on narrow windows) rather than num_cols, since
        # a date+time string is far longer than a talent name.
        layout_items.append({"type": "divider", "y": y, "unit": self.t("clock_category")})
        y += divider_height
        clock_cols = min(num_cols, 3)
        clock_col_width = available / clock_cols
        col = 0
        for label, date_part, time_part in format_world_clock(self.lang, time.time()):
            layout_items.append({"type": "clock", "x": margin + col * clock_col_width, "y": y,
                          "w": clock_col_width, "text": f"{label} {date_part} {time_part}",
                          "zone": label})
            col += 1
            if col == clock_cols:
                col = 0
                y += row_height
        if col != 0:
            y += row_height
        # While the live-only filter is on, every remaining talent is live, so
        # give each its own full-width row (one line per talent) instead of the
        # normal grid columns — that's the room the program-title ticker in
        # render() needs to the right of the name.
        unit_cols = 1 if self.live_only else num_cols
        unit_col_width = available if self.live_only else col_width
        for unit, indices in units.items():
            layout_items.append({"type": "divider", "y": y, "unit": unit})
            y += divider_height
            col = 0
            for index in indices:
                layout_items.append({"type": "talent", "x": margin + col * unit_col_width, "y": y,
                              "w": unit_col_width, "index": index})
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
        return layout_items, y

    def compute_grid(self):
        # No scroll support: rows/dividers/fonts scale uniformly so nothing is
        # dropped when the window is too short for the content (shrinking),
        # and text grows a bit for readability when the window is taller than
        # the content needs (see the 1.5x cap note below) — but the grid
        # itself always stays top-aligned, like an ordinary list.
        _, natural_end = self.build_grid_layout(25, 18)
        available_height = max(1, self.height - GRID_TOP - 90)
        content_height = max(1, natural_end - GRID_TOP)
        scale = max(0.15, min(1.5, available_height / content_height))
        row_height = 25 * scale
        divider_height = 18 * scale
        # The 1.5x growth cap keeps names readable instead of ballooning on a
        # very tall window with little content (e.g. a small custom list on a
        # maximized window); content stays anchored under GRID_TOP (like an
        # ordinary top-aligned list) rather than being centered, so any space
        # the cap leaves unused simply falls below the grid.
        layout_items, grid_end = self.build_grid_layout(row_height, divider_height)
        return layout_items, row_height, divider_height, scale

    def focusable_items(self, grid_layout=None, row_height=None):
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
        # render() already computes grid_layout/row_height once for its own
        # drawing and passes them straight through here (for the focus-ring
        # rect) so a focused item doesn't force a second, redundant
        # compute_grid() pass on every render — including every ~60ms ticker
        # tick while a live-only now-playing ticker is on screen. Every other
        # caller (keypress handlers) has no such value on hand and computes
        # its own, which is fine since those only run once per keystroke.
        btn = self.top_button_rects()
        actions = self.top_button_actions()
        visual_order = ("filter", "mode", "font", "color", "lang", "pin", "fullscreen", "close")
        items = [{"kind": "button", "rect": btn[key], "activate": actions[key]}
                for key in visual_order]
        for key, geom in self.slider_geometry().items():
            rect = (geom["track_start"], geom["y"] - 5, geom["track_end"], geom["y"] + 15)
            items.append({"kind": "slider", "rect": rect, "slider_key": key})
        if grid_layout is None:
            grid_layout, row_height, _, _ = self.compute_grid()
        for item in grid_layout:
            if item["type"] == "talent":
                rect = (item["x"], item["y"], item["x"] + item["w"], item["y"] + row_height)
                target = self.targets[item["index"]]
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
