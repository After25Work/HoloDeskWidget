import ctypes
import functools
import math
import re
import threading
import time
import tkinter as tk
import webbrowser
from typing import Optional, Tuple
from urllib.error import HTTPError

from PIL import Image, ImageDraw, ImageTk

from . import layout, youtube
from .config import (
    DEFAULT_HEIGHT,
    MAX_HEIGHT,
    MAX_WIDTH,
    MIN_BACKGROUND_DARKNESS,
    MIN_HEIGHT,
    MIN_WIDTH,
    MIN_WINDOW_ALPHA,
    TEXT_SCALE_MIN,
    TEXT_SCALE_MAX,
    DEFAULT_SETTINGS,
    load_settings,
    save_settings,
)
from .fonts import emoji_font, font
from .paths import WINDOW_TITLE, log_error
from .strings import STRINGS, english_name, format_world_clock
from .talents import load_targets
from .theme import KEY_COLOR, MIN_LABEL_SIZE, THEME_PALETTE, THEMES

# Ranges covering the emoji live-stream titles actually use (pictographs,
# symbols/dingbats, regional-indicator flags) plus the modifiers that glue
# multi-codepoint emoji sequences together, so a whole sequence is treated
# as one run and handed to the emoji font as a unit.
_EMOJI_SPLIT_RE = re.compile(
    "([\U0001F000-\U0001FFFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0000FE0F\U0000200D\U000020E3]+)"
)
from .version import __version__

# Declared once at module scope, argtypes/restype pinned explicitly — same
# convention as single_instance.py's own user32 bindings, and for the same
# reason: without an explicit restype, ctypes defaults a Win32 call's return
# value to c_int (32-bit signed), which happens to round-trip a HWND
# correctly today only by coincidence (every HWND fits in 32 bits, and the
# equally-undeclared argtypes on the write-back call happen to re-sign-extend
# it the same way) rather than by any documented guarantee.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetParent.argtypes = [ctypes.c_void_p]
_user32.GetParent.restype = ctypes.c_void_p
_user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long

# Top of the no-scroll talent grid, below the title/status bar and the
# background-darkness/text-size slider row. The world clock is drawn as the
# grid's own first category (see build_grid_layout()), not a separate block,
# so it no longer needs its own reserved space here.
GRID_TOP = 152


class LayeredWidget:
    def __init__(self):
        self.targets = load_targets()
        self.channel_urls = {}
        self.states = {name: "unknown" for name, _, _, _ in self.targets}
        self.live_urls = {}
        self.live_titles = {}
        # Shared now-playing ticker clock — see the sync note in render().
        # ticker_progress tracks moving-time since the shared marquee last
        # resumed, and is reset to 0 every time a new cycle starts so every
        # row's text is back at its head in the same instant; it also drives
        # each row's on-screen shift (progress modulo that row's own lap
        # width). ticker_pause_until is the epoch the current shared pause
        # ends at (0.0 while moving).
        self.ticker_progress = 0.0
        self.ticker_pause_until = 0.0
        self.ticker_last_tick = time.time()
        self.last_opened = (None, 0.0)
        self.refresh_in_progress = False
        settings = load_settings()
        self.background_alpha = settings["background_alpha"]
        self.lang = settings["lang"]
        self.topmost = settings["topmost"]
        self.theme_index = settings["theme_index"]
        self.dark_mode = settings["dark_mode"]
        self.live_only = settings["live_only"]
        self.text_scale = settings["text_scale"]
        self.suppress_next_click = False
        self.slider_drag = False
        self.render_pending = False
        self.geometry_pending = False
        self.last_updated: Optional[str] = None
        self.width, self.height = settings["width"], settings["height"]
        # Attributes below only ever materialize conditionally in the old
        # single-file version (via hasattr/getattr/del), which is what let
        # _all_height go unset and produce the live-only-filter height bug
        # fixed in commit c36679a. Initializing every one of them up front
        # means "not currently active" is always a real value (None/False),
        # never "attribute doesn't exist yet".
        self.palette_win: Optional[tk.Toplevel] = None
        self.surface: Optional[tk.Label] = None
        self.drag_origin: Optional[Tuple[int, int, int, int]] = None
        self.resize_origin: Optional[Tuple[int, int, int, int, int, int]] = None
        self.resize_drag = False
        self.active_resize_edge: Optional[str] = None
        self.pending_position: Optional[Tuple[int, int]] = None
        # Keyboard-focus index into focusable_items() — None means no item
        # currently has the keyboard focus ring (mouse-only interaction).
        self.focus_index: Optional[int] = None
        # Populated fresh every render() with each drawn row's hit-rect,
        # hover tooltip text, and clipboard payload, keyed by a unique row
        # id — read back by on_motion() (hover cursor/tooltip) and
        # show_context_menu() (copy-to-clipboard) so those never recompute
        # or duplicate render()'s own label/truncation logic.
        self.row_info = {}
        self.tooltip_win: Optional[tk.Toplevel] = None
        self._tooltip_key = None
        self._tooltip_after = None
        # The "all talents" height fit_height() restores when live_only is
        # switched back off. If settings.json was saved while live_only was
        # already on, there is no real "before" height on record — seed it
        # with the app's normal default instead of leaving it unset.
        self._all_height: float = DEFAULT_HEIGHT if self.live_only else self.height
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.topmost)
        # Keep the window opaque so background and text transparency stay independent.
        self.root.attributes("-alpha", max(1.0 - self.background_alpha, MIN_WINDOW_ALPHA))
        self.root.geometry(f"{self.width}x{self.height}+{settings['x']}+{settings['y']}")
        self.root.configure(bg=KEY_COLOR)
        self.root.attributes("-transparentcolor", KEY_COLOR)
        self.root.deiconify()
        self.root.update_idletasks()
        self._force_taskbar_visible()
        # Windows still closes an overrideredirect toplevel on Alt+F4 even
        # with no system menu to route it through, but that default path
        # destroys the window directly and skips close()'s save_settings()
        # entirely — Alt+F4 would silently drop the current position/size to
        # whatever was last saved. Binding it ourselves makes close() (and
        # the save) run first, so by the time Windows' own handling follows,
        # there's nothing left for it to do.
        self.root.bind("<Alt-F4>", lambda event: self.close())
        self.root.after(100, self.setup_layered_window)
        self.root.after(300, self.refresh)
        self.root.after(1000, self.tick_clock)
        self.root.after(60, self.tick_ticker)

    def _force_taskbar_visible(self):
        # overrideredirect(True) makes Tk stamp the window WS_EX_TOOLWINDOW,
        # which Windows hides from both the taskbar and Alt+Tab — normal for
        # a transient popup, but this is the app's only window, so losing it
        # behind something else (once un-pinned) would otherwise mean no way
        # back to it short of relaunching the exe. Swap in WS_EX_APPWINDOW
        # instead, then briefly hide/show the window: the taskbar only
        # re-evaluates a window's ex-style when it is (re)shown, not live.
        try:
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            hwnd = _user32.GetParent(self.root.winfo_id())
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            self.root.withdraw()
            self.root.deiconify()
        except OSError:
            pass

    def setup_layered_window(self):
        self.render()
        self.root.lift()

    def tick_clock(self):
        # Ticks the "now" clock next to the last-updated timestamp once a
        # second, independent of the 60s data refresh in refresh_complete().
        self.request_render()
        self.root.after(1000, self.tick_clock)

    def tick_ticker(self):
        # Drives the live-only view's scrolling program-title ticker at a much
        # finer grain than tick_clock()'s 1s cadence, so the scroll reads as
        # smooth motion. Only requests a render when there's actually a ticker
        # on screen, so this costs nothing while live_only is off.
        if self.live_only and self.live_titles:
            self.request_render()
        self.root.after(60, self.tick_ticker)

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
            "pin": self.toggle_topmost,
            "lang": self.toggle_lang,
            "color": self.toggle_palette,
            "mode": self.toggle_mode,
            "filter": self.toggle_live_only,
        }

    def accent_color(self):
        return THEME_PALETTE[self.theme_index][1] + (255,)

    def theme_colors(self):
        return THEMES["dark"] if self.dark_mode else THEMES["light"]

    def tint(self, base_rgb, weight=0.15):
        # Shifts a dark neutral surface color a bit toward the current accent hue
        # so panels/buttons feel coordinated with the picked theme, not just the
        # small accent-colored details (icon, knobs, active buttons).
        accent = THEME_PALETTE[self.theme_index][1]
        return tuple(int(base_rgb[i] + (accent[i] - base_rgb[i]) * weight) for i in range(3))

    def resize_grip_rect(self):
        # Kept clear of refresh_btn_rect()'s bottom-right corner (which ends at
        # width-44, height-34) so the two hit-zones never overlap, and kept
        # inside the panel's own edge (width-20, height-20) so it never reaches
        # into the transparentcolor margin, where clicks pass straight through
        # to whatever's behind the window.
        return (self.width - 44, self.height - 44, self.width - 22, self.height - 22)

    _RESIZE_MARGIN = 8
    _RESIZE_CURSORS = {
        "n": "size_ns", "s": "size_ns",
        "e": "size_we", "w": "size_we",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
        "nw": "size_nw_se", "se": "size_nw_se",
    }

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
        # No scroll support: rows/dividers/fonts scale uniformly to always fill the
        # available vertical space exactly — shrinking so nothing is dropped when
        # it's too tall for the window, growing to use the space rather than
        # leaving it blank when the window is taller than the content needs.
        _, natural_end = self.build_grid_layout(25, 18)
        available_height = max(1, self.height - GRID_TOP - 90)
        content_height = max(1, natural_end - GRID_TOP)
        scale = max(0.15, min(1.15, available_height / content_height))
        row_height = 25 * scale
        divider_height = 18 * scale
        layout_items, grid_end = self.build_grid_layout(row_height, divider_height)
        return layout_items, row_height, divider_height, scale

    def render(self):
        colors = self.theme_colors()
        # Rebuilt fresh every render so on_motion()/show_context_menu() always
        # hit-test against exactly what's on screen right now — see the note
        # on self.row_info in __init__.
        self.row_info = {}
        image = Image.new("RGB", (self.width, self.height), (1, 0, 1))
        draw = ImageDraw.Draw(image)
        accent = self.accent_color()
        btn = self.top_button_rects()
        draw.rounded_rectangle((20, 20, self.width - 20, self.height - 20), 22,
                               fill=self.tint(colors["panel"][:3]) + (colors["panel"][3],),
                               outline=colors["outline"], width=1)
        draw.text((38, 36), self.t("title"), font=font(18, True), fill=self.text_color(colors["text"]))
        draw.text((38, 59), "LIVE STATUS", font=font(14, True), fill=self.text_color(colors["text"]))
        close_rect_btn = btn["close"]
        draw.rounded_rectangle(close_rect_btn, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        self.draw_centered(draw, close_rect_btn, "×", font(18, True), self.text_color(colors["text"]))
        pin_fill = accent if self.topmost else self.tint(colors["neutral_btn"]) + (255,)
        pin_text = self.text_color((24, 24, 31)) if self.topmost else self.text_color(colors["text"])
        pin_rect = btn["pin"]
        draw.rounded_rectangle(pin_rect, 8, fill=pin_fill)
        self.draw_centered(draw, pin_rect, self.t("pin"), font(11, True), pin_text)
        lang_rect = btn["lang"]
        draw.rounded_rectangle(lang_rect, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        self.draw_centered(draw, lang_rect, self.t("lang_toggle"), font(11, True),
                           self.text_color(colors["text"]))
        self.draw_theme_button(draw, btn["color"], colors)
        self.draw_mode_button(draw, btn["mode"], colors)
        filter_fill = accent if self.live_only else self.tint(colors["neutral_btn"]) + (255,)
        filter_text = self.text_color((24, 24, 31)) if self.live_only else self.text_color(colors["text"])
        filter_rect = btn["filter"]
        draw.rounded_rectangle(filter_rect, 8, fill=filter_fill)
        self.draw_centered(draw, filter_rect, self.t("live_filter"), font(11, True), filter_text)
        live_count = sum(state == "live" for state in self.states.values())
        status_top, status_bottom = 88, 125
        draw.rounded_rectangle((38, status_top, self.width - 38, status_bottom), 8,
                               fill=self.background_color(colors["status_bg"]))
        count_font = font(12, True)
        count_text = self.t("count", live=live_count, total=len(self.targets))
        draw.text((50, self.vcenter_y(count_font, count_text, status_top, status_bottom)),
                  count_text, font=count_font, fill=self.text_color(colors["text"]))
        legend_font = font(10, True)
        # Anchored to the right edge (rather than fixed x offsets) so the legend
        # stays inside the status bar at any window width, including MIN_WIDTH.
        legend_items = [
            (f"! {self.t('legend_error')}", colors["error"]),
            (f"• {self.t('legend_idle')}", colors["muted"]),
            (f"● {self.t('legend_live')}", colors["live"]),
        ]
        legend_y = self.vcenter_y(legend_font, legend_items[0][0], status_top, status_bottom)
        cursor = self.width - 46
        for label, color in legend_items:
            label_width = legend_font.getbbox(label)[2]
            cursor -= label_width
            draw.text((cursor, legend_y), label, font=legend_font, fill=self.text_color(color))
            cursor -= 14
        sliders = self.slider_geometry()
        # "濃さ" (darkness) is opacity, the inverse of background_alpha: it rises to
        # the right, so the displayed percent and the knob both increase with the drag.
        # The knob fraction is renormalized across MIN_BACKGROUND_DARKNESS..1.0 so the
        # full track is used even though darkness never actually reaches 0%.
        background_darkness = 1.0 - self.background_alpha
        knob_fraction = ((background_darkness - MIN_BACKGROUND_DARKNESS)
                         / (1.0 - MIN_BACKGROUND_DARKNESS))
        bg = sliders["background"]
        self.draw_slider(draw, bg["x"], bg["y"], self.t("bg_slider"), background_darkness * 100,
                         knob_fraction, bg["track_start"], bg["track_end"], colors)
        # Text size is a separate user preference from grid_scale (which only
        # auto-shrinks to keep the no-scroll grid fitting the window): it just
        # multiplies the resulting label/divider font sizes below.
        text_fraction = (self.text_scale - TEXT_SCALE_MIN) / (TEXT_SCALE_MAX - TEXT_SCALE_MIN)
        txt = sliders["text"]
        self.draw_slider(draw, txt["x"], txt["y"], self.t("text_slider"), self.text_scale * 100,
                         text_fraction, txt["track_start"], txt["track_end"], colors)
        # No scroll support: instead of dropping rows that don't fit, compute_grid()
        # shrinks row/divider height and font size uniformly so everything is shown.
        grid_layout, row_height, divider_height, grid_scale = self.compute_grid()
        # The clock category is always present, so "no live talents" is
        # judged on talent rows specifically, not on grid_layout being empty.
        if self.live_only and not any(item["type"] == "talent" for item in grid_layout):
            no_live_font = font(13, True)
            no_live_text = self.t("no_live")
            bbox = no_live_font.getbbox(no_live_text)
            # Placed below the world-clock section (which is always drawn,
            # live filter or not) rather than at GRID_TOP, so this message
            # doesn't overlap the clock category's own header/rows.
            clock_bottom = GRID_TOP
            for item in grid_layout:
                item_h = divider_height if item["type"] == "divider" else row_height
                clock_bottom = max(clock_bottom, item["y"] + item_h)
            draw.text(((self.width - bbox[2]) / 2, clock_bottom + 10), no_live_text, font=no_live_font,
                      fill=self.text_color(colors["muted"]))
        label_scale = grid_scale * self.text_scale
        divider_font = font(max(2, round(10 * label_scale)), True)
        base_label_size = max(2, round(16 * label_scale))
        min_label_size = min(MIN_LABEL_SIZE, base_label_size)
        clock_label_size = base_label_size
        clock_min_label_size = min_label_size
        pending_tickers = []
        for item in grid_layout:
            if item["type"] == "divider":
                draw.text((40, item["y"]), item["unit"], font=divider_font,
                          fill=self.text_color(colors["muted"]))
                label_w = divider_font.getbbox(item["unit"])[2]
                line_y = item["y"] + divider_height / 2
                draw.line((40 + label_w + 8, line_y, self.width - 40, line_y),
                         fill=self.text_color(colors["divider"]), width=1)
                continue
            if item["type"] == "clock":
                x, y, max_label_width = item["x"], item["y"], item["w"] - 12
                label, label_font = self._fit_label(item["text"], clock_label_size,
                                                     clock_min_label_size, max_label_width)
                draw.text((x, y), label, font=label_font, fill=self.text_color(colors["muted"]))
                self.row_info[("clock", item["zone"])] = {
                    "rect": (x, item["y"], x + item["w"], item["y"] + row_height),
                    "clickable": False,
                    "tooltip": item["text"] if label != item["text"] else None,
                    "copy_name": None, "copy_title": None,
                }
                continue
            x, y = item["x"], item["y"]
            name, slug, _, _ = self.targets[item["index"]]
            state = self.states[name]
            # Every row in the live-only view is already live
            # (build_grid_layout() only includes state=="live" rows there),
            # so repeating the "live" highlight on every single row adds no
            # information there — plain text color reads better. Guarded on
            # state=="live" explicitly (not just self.live_only) so this
            # can't silently mis-color a row if that filter's behavior ever
            # changes.
            color = (colors["text"] if self.live_only and state == "live"
                     else colors["live"] if state == "live"
                     else colors["error"] if state == "error" else colors["muted"])
            bullet = "● " if state == "live" else "! " if state == "error" else "• "
            display_name = name if self.lang == "ja" else english_name(slug)
            label = bullet + display_name
            # In the live-only view every row is one talent wide, so the name
            # only needs a modest fixed-width lane — the rest of the row goes
            # to the now-playing ticker built below.
            title = self.live_titles.get(name) if self.live_only else None
            label_area_w = min(item["w"] * 0.4, max(90, 170 * label_scale)) if title else item["w"]
            max_label_width = label_area_w - 12
            fitted_label, label_font = self._fit_label(label, base_label_size, min_label_size,
                                                        max_label_width)
            # Vertically centered within the row (rather than drawn flush to
            # its top) so the name lines up with the now-playing ticker text,
            # which draw_ticker centers within the same row_height.
            name_y = self.vcenter_y(label_font, fitted_label, y, y + row_height)
            draw.text((x, name_y), fitted_label, font=label_font,
                      fill=self.text_color(color), stroke_width=2,
                      stroke_fill=self.text_color(colors["label_stroke"]))
            if title:
                tooltip_text = f"{display_name}\n{title}"
            elif fitted_label != label:
                tooltip_text = display_name
            else:
                tooltip_text = None
            self.row_info[("talent", name)] = {
                "rect": (x, y, x + item["w"], y + row_height),
                "clickable": True,
                "tooltip": tooltip_text,
                "copy_name": display_name,
                "copy_title": title,
            }
            if title:
                ticker_gap = 10
                ticker_x = x + label_area_w + ticker_gap
                ticker_w = item["w"] - label_area_w - ticker_gap
                ticker_font = font(max(2, round(label_font.size * 0.85)), False)
                pending_tickers.append((name, ticker_x, y, ticker_w, row_height, title, ticker_font))
        if pending_tickers:
            # All rows share one clock (ticker_progress) so every ticker on
            # screen starts moving at the same instant, from its head. A row
            # whose title is short enough to fit doesn't scroll (unit_w is
            # None below) and is unaffected by any of this. Among the rows
            # that do scroll, each row's own speed is picked so its lap takes
            # about ticker_lap_seconds — longer titles move faster, shorter
            # ones slower — so all rows tend to finish together instead of
            # the pace being set by whichever title happens to be longest;
            # speed is still clamped to a sane range so a very short or very
            # long title doesn't crawl or blur. Each row's own progress is
            # then clamped to its own lap length (see the row loop below), so
            # it completes exactly one lap and then holds — which looks like
            # holding at its head, since one full lap is visually seamless
            # with the start (see draw_ticker) — rather than looping extra
            # times while any row that was clamped to the speed limits is
            # still finishing. The shared "moving" phase lasts as long as it
            # takes the slowest-finishing row to complete its lap
            # (move_seconds); once that happens every row pauses together for
            # ticker_pause_seconds, then ticker_progress resets to 0 and they
            # all resume together from their heads.
            # ticker_speed_scale multiplies the whole speed formula (target
            # and clamp range alike): 0.7 for an earlier 30% slowdown, then
            # /3 on top of that for a further 3x slowdown.
            ticker_speed_scale = 0.7 / 3
            ticker_lap_seconds = 4.0 / ticker_speed_scale
            ticker_min_speed = 40 * ticker_speed_scale
            ticker_max_speed = 160 * ticker_speed_scale
            ticker_pause_seconds = 3.0
            now = time.time()
            dt = max(0.0, min(now - self.ticker_last_tick, 1.0))
            self.ticker_last_tick = now
            rows = []
            lap_seconds = []
            for name, tx, ty, tw, th, text, fnt in pending_tickers:
                text_w = self._ticker_text_width(text, fnt)
                if text_w > tw:
                    unit_w = text_w + fnt.getlength("    ")
                    speed = max(ticker_min_speed, min(ticker_max_speed, unit_w / ticker_lap_seconds))
                    lap_seconds.append(unit_w / speed)
                else:
                    unit_w = None
                    speed = None
                rows.append((tx, ty, tw, th, text, fnt, unit_w, speed))
            if lap_seconds:
                move_seconds = max(lap_seconds)
                if self.ticker_pause_until and now < self.ticker_pause_until:
                    pass
                else:
                    if self.ticker_pause_until:
                        self.ticker_pause_until = 0.0
                        self.ticker_progress = 0.0
                    self.ticker_progress += dt
                    if self.ticker_progress >= move_seconds:
                        self.ticker_pause_until = now + ticker_pause_seconds
            for tx, ty, tw, th, text, fnt, unit_w, speed in rows:
                row_progress = (min(self.ticker_progress, unit_w / speed)
                                if unit_w else self.ticker_progress)
                self.draw_ticker(image, tx, ty, tw, th, text, fnt,
                                 self.text_color(colors["text"]), row_progress,
                                 speed or 0, unit_w)
        else:
            self.ticker_progress = 0.0
            self.ticker_pause_until = 0.0
            self.ticker_last_tick = time.time()
        updated_text = (self.t("updated", time=self.last_updated) if self.last_updated
                        else self.t("updated_none"))
        updated_font = font(10, True)
        draw.text((40, self.height - 84), updated_text, font=updated_font,
                  fill=self.text_color(colors["muted"]))
        version_text = f"v{__version__}"
        version_bbox = updated_font.getbbox(version_text)
        draw.text((self.width - 40 - version_bbox[2], self.height - 84), version_text,
                  font=updated_font, fill=self.text_color(colors["muted"]))
        refresh_rect = self.refresh_btn_rect()
        # While a refresh is in flight, dim the button and swap its label to
        # "Refreshing…" so clicking it again (already a silent no-op — see
        # refresh()) at least visibly explains why nothing happens.
        refresh_base = colors["status_bg"] if self.refresh_in_progress else colors["neutral_btn"]
        refresh_text_color = colors["muted"] if self.refresh_in_progress else colors["text"]
        draw.rounded_rectangle(refresh_rect, 7, fill=self.background_color(refresh_base))
        refresh_label = self.t("refreshing") if self.refresh_in_progress else self.t("refresh")
        self.draw_centered(draw, refresh_rect, refresh_label, font(13, True),
                           self.text_color(refresh_text_color))
        self.draw_resize_grip(draw, colors)
        if self.focus_index is not None:
            # Reuse this render()'s own grid_layout/row_height (computed
            # above) instead of letting focusable_items() recompute the grid
            # from scratch — see the note on that parameter in
            # focusable_items(). Matters most here: this runs on every
            # ~60ms ticker tick for as long as a focus ring stays visible.
            items = self.focusable_items(grid_layout, row_height)
            if 0 <= self.focus_index < len(items):
                fx0, fy0, fx1, fy1 = items[self.focus_index]["rect"]
                draw.rounded_rectangle((fx0 - 3, fy0 - 3, fx1 + 3, fy1 + 3), 6,
                                       outline=accent, width=2)
            else:
                self.focus_index = None
        self.apply_image(image)

    def t(self, key, **kwargs):
        text = STRINGS[self.lang][key]
        return text.format(**kwargs) if kwargs else text

    @staticmethod
    def draw_centered(draw, rect, text, fnt, fill):
        left, top, right, bottom = rect
        bbox = fnt.getbbox(text)
        x = left + ((right - left) - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = top + ((bottom - top) - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), text, font=fnt, fill=fill)

    @staticmethod
    @functools.lru_cache(maxsize=256)
    def vcenter_y(fnt, text, top, bottom):
        # Cached like _fit_label() below: called again for every row on every
        # ~60ms ticker tick even when the row's font/text/bounds haven't
        # changed since the last frame, which used to repeat this getbbox()
        # call for nothing on every single tick.
        bbox = fnt.getbbox(text)
        return top + ((bottom - top) - (bbox[3] - bbox[1])) // 2 - bbox[1]

    @staticmethod
    @functools.lru_cache(maxsize=256)
    def _fit_label(label, base_size, min_size, max_label_width, bold=True):
        # Shrinks the font a point at a time, then falls back to ellipsis
        # truncation, until label fits max_label_width — used for every talent
        # and world-clock row. Cached because the ticker's ~60ms render tick
        # calls this again for every row every frame even though the label
        # text/size/width triple it depends on is unchanged between actual
        # data/layout updates, which used to repeat the whole getbbox() search
        # for nothing on every single tick.
        label_size = base_size
        label_font = font(label_size, bold)
        while label_font.getbbox(label)[2] > max_label_width and label_size > min_size:
            label_size -= 1
            label_font = font(label_size, bold)
        if label_font.getbbox(label)[2] > max_label_width:
            while len(label) > 3 and label_font.getbbox(label + "…")[2] > max_label_width:
                label = label[:-1]
            label += "…"
        return label, label_font

    @staticmethod
    @functools.lru_cache(maxsize=256)
    def _emoji_runs(text, fnt):
        # Yu Gothic (fnt) has no emoji glyphs, so emoji substrings are split
        # out and handed to the Segoe UI Emoji font instead; everything else
        # stays on fnt. re.split with a capturing group alternates
        # [non-emoji, emoji, non-emoji, ...], so odd indices are emoji runs.
        # Cached: the live-only ticker calls this for the same (text, fnt)
        # pair on every ~60ms tick until the title next changes, and the
        # regex split + font lookup is pure work otherwise repeated for
        # nothing every single frame.
        parts = _EMOJI_SPLIT_RE.split(text)
        efont = emoji_font(fnt.size) if len(parts) > 1 else None
        if efont is None:
            return [(text, fnt)]
        return [(part, efont if i % 2 else fnt) for i, part in enumerate(parts) if part]

    @staticmethod
    @functools.lru_cache(maxsize=256)
    def _ticker_text_width(text, fnt):
        runs = LayeredWidget._emoji_runs(text, fnt)
        return sum(run_font.getlength(run_text) for run_text, run_font in runs)

    @staticmethod
    def draw_ticker(image, x, y, w, h, text, fnt, fill, progress, speed_px_per_sec, unit_w):
        # Renders onto its own small RGBA tile and pastes that (using its own
        # alpha as the mask) rather than drawing straight onto the panel, so
        # the scrolling title is clipped to its lane instead of bleeding into
        # neighboring rows/columns — PIL text drawing has no clip rect of its
        # own to lean on here.
        if w <= 4:
            return
        runs = LayeredWidget._emoji_runs(text, fnt)
        bbox = fnt.getbbox(text or " ")
        text_h = bbox[3] - bbox[1]
        tile = Image.new("RGBA", (max(1, round(w)), max(1, round(h))), (0, 0, 0, 0))
        tile_draw = ImageDraw.Draw(tile)
        ty = (h - text_h) / 2 - bbox[1]

        def draw_runs(start_x):
            cursor = start_x
            for run_text, run_font in runs:
                tile_draw.text((cursor, ty), run_text, font=run_font, fill=fill + (255,),
                                embedded_color=(run_font is not fnt))
                cursor += run_font.getlength(run_text)

        if unit_w is None:
            draw_runs(-bbox[0])
        else:
            # The same title is redrawn every unit_w pixels (its own width
            # plus a 4-space gap) so the lane is always full of text, and the
            # whole row of copies is shifted left by `shift`, derived from
            # `progress` (see the sync note in render(), which clamps this to
            # at most one lap) taken modulo this row's own unit_w. Because
            # copies repeat every unit_w, progress reaching exactly unit_w
            # wraps seamlessly back to a shift of 0 — indistinguishable from
            # the row's head — which is what makes holding a finished row
            # there look like a clean stop rather than a jump.
            shift = (progress * speed_px_per_sec) % unit_w
            start_x = -shift - bbox[0]
            while start_x < w:
                draw_runs(start_x)
                start_x += unit_w
        image.paste(tile, (round(x), round(y)), tile)

    def draw_resize_grip(self, draw, colors):
        # Sits inside resize_grip_rect(), which is itself kept inside the
        # panel's own rounded edge — the icon is drawn straight onto the
        # existing panel fill rather than a patch of its own, so nothing pokes
        # out past the panel into the transparentcolor margin.
        corner_x, corner_y = self.width - 28, self.height - 28
        color = self.text_color(colors["muted"])
        for offset in (0, 6, 12):
            draw.line((corner_x - 12 + offset, corner_y, corner_x, corner_y - 12 + offset),
                     fill=color, width=2)

    def draw_theme_button(self, draw, rect, colors):
        # A little three-dot "palette" icon rather than the current accent color
        # itself, so it stays a recognizable button regardless of the active theme.
        draw.rounded_rectangle(rect, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        dots = [((-7, -4), (255, 141, 178)), ((7, -4), (66, 133, 227)), ((0, 7), (247, 202, 62))]
        for (dx, dy), color in dots:
            x, y = cx + dx, cy + dy
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=self.text_color(color))

    def draw_mode_button(self, draw, rect, colors):
        # Icon reflects the CURRENT mode (moon while dark, sun while light) so
        # clicking always means "switch to the other one," like the OS toggles.
        draw.rounded_rectangle(rect, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        icon_color = self.text_color(self.accent_color()[:3])
        if self.dark_mode:
            r = 8
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=icon_color)
            cutout = self.tint(colors["neutral_btn"]) + (255,)
            draw.ellipse((cx - r + 5, cy - r - 2, cx + r + 5, cy + r - 2), fill=cutout)
        else:
            r = 6
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=icon_color)
            for angle_deg in range(0, 360, 45):
                angle = math.radians(angle_deg)
                x1, y1 = cx + math.cos(angle) * (r + 3), cy + math.sin(angle) * (r + 3)
                x2, y2 = cx + math.cos(angle) * (r + 7), cy + math.sin(angle) * (r + 7)
                draw.line((x1, y1, x2, y2), fill=icon_color, width=2)

    def text_color(self, color):
        return tuple(color[:3])

    def background_color(self, color):
        return self.tint(color[:3])

    def draw_slider(self, draw, x, y, label, display_percent, knob_fraction, track_start, track_end,
                     colors):
        draw.text((x, y), f"{label} {round(display_percent)}%", font=font(10, True),
                  fill=self.text_color(colors["text"]))
        draw.rounded_rectangle((track_start, y + 3, track_end, y + 9), 3, fill=colors["divider"])
        knob = track_start + int((track_end - track_start) * knob_fraction)
        # Always fully opaque so the knob stays grabbable even at max text transparency.
        draw.ellipse((knob - 5, y, knob + 5, y + 12), fill=self.accent_color())

    def apply_image(self, image):
        if self.surface is None:
            # bg matches the window's own transparentcolor key: if the window
            # frame is ever momentarily larger than the label's image (e.g.
            # mid-resize, before the next render catches up), the gap reads
            # as see-through instead of flashing an opaque system-default gray.
            self.image = ImageTk.PhotoImage(image)
            self.surface = tk.Label(self.root, image=self.image, bg=KEY_COLOR, borderwidth=0,
                                    takefocus=True, highlightthickness=0)
            self.surface.pack(fill="both", expand=True)
            self.surface.bind("<ButtonPress-1>", self.drag_start)
            self.surface.bind("<B1-Motion>", self.drag_move)
            self.surface.bind("<ButtonRelease-1>", self.click)
            self.surface.bind("<Button-3>", self.show_context_menu)
            self.surface.bind("<Motion>", self.on_motion)
            self.surface.bind("<Leave>", self.on_leave)
            self.surface.bind("<Tab>", self.focus_next)
            self.surface.bind("<Shift-Tab>", self.focus_prev)
            self.surface.bind("<Return>", self.activate_focus)
            self.surface.bind("<KP_Enter>", self.activate_focus)
            self.surface.bind("<space>", self.activate_focus)
            self.surface.bind("<Left>", lambda event: self.adjust_focus_slider(-1))
            self.surface.bind("<Right>", lambda event: self.adjust_focus_slider(1))
            self.surface.bind("<Escape>", self.clear_focus)
        elif (self.image.width(), self.image.height()) != image.size:
            # Size changed (resize) — the existing Tcl photo buffer can't be
            # reused in place, so fall back to a fresh one.
            self.image = ImageTk.PhotoImage(image)
            self.surface.configure(image=self.image)
        else:
            # Same size as last frame (the common case — the live-only ticker
            # re-renders every ~60ms with the window unchanged): push the new
            # pixels into the existing Tcl photo image in place instead of
            # allocating and registering a brand-new one every single frame.
            self.image.paste(image)

    def drag_start(self, event):
        self.surface.focus_set()
        self._hide_tooltip()
        if self.focus_index is not None:
            self.focus_index = None
            self.request_render()
        edge = ("se" if self._in_rect(event.x, event.y, self.resize_grip_rect())
                else self.resize_edge(event.x, event.y))
        if edge:
            self.resize_drag = True
            self.active_resize_edge = edge
            self.resize_origin = (event.x_root, event.y_root, self.width, self.height,
                                  self.root.winfo_x(), self.root.winfo_y())
            return
        self.resize_drag = False
        self.slider_drag = self.slider_hit(event.x, event.y)
        self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag_move(self, event):
        if self.resize_drag:
            sx, sy, start_w, start_h, start_x, start_y = self.resize_origin
            edge = self.active_resize_edge
            dx, dy = event.x_root - sx, event.y_root - sy
            new_w = start_w + dx if "e" in edge else start_w - dx if "w" in edge else start_w
            new_h = start_h + dy if "s" in edge else start_h - dy if "n" in edge else start_h
            self.width = max(MIN_WIDTH, min(MAX_WIDTH, round(new_w)))
            self.height = max(MIN_HEIGHT, min(MAX_HEIGHT, round(new_h)))
            # Dragging the top or left edge keeps the OPPOSITE edge fixed in
            # place, like a normal window border — so the origin (top-left
            # corner) has to move along with the size, unlike the plain "se"
            # grip drag where the origin never changes.
            new_x = start_x + (start_w - self.width) if "w" in edge else start_x
            new_y = start_y + (start_h - self.height) if "n" in edge else start_y
            if (new_x, new_y) != (start_x, start_y):
                self.pending_position = (new_x, new_y)
            self.geometry_pending = True
            self.request_render()
            return
        if self.slider_drag:
            self.update_slider(self.slider_drag, event.x)
            return
        if self.drag_origin is not None:
            sx, sy, x, y = self.drag_origin
            self.root.geometry(f"+{x + event.x_root - sx}+{y + event.y_root - sy}")

    def request_render(self):
        # B1-Motion during a resize/slider drag can fire faster than a full PIL
        # composite + GDI blit can keep up with; coalesce bursts of these into a
        # single render on the next idle tick instead of one render per event.
        if self.render_pending:
            return
        self.render_pending = True
        self.root.after_idle(self._render_now)

    def _render_now(self):
        self.render_pending = False
        if self.geometry_pending:
            self.geometry_pending = False
            if self.pending_position is not None:
                x, y = self.pending_position
                self.pending_position = None
            else:
                x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        self.render()

    def click(self, event):
        if self.suppress_next_click:
            # Picking a color destroys the palette popup mid-click; the orphaned
            # ButtonRelease can otherwise land on the main window underneath and
            # fire whatever's at that position (e.g. opening a talent's link).
            self.suppress_next_click = False
            return
        if self.resize_drag:
            self.resize_drag = False
            return
        slider_click = self.slider_hit(event.x, event.y)
        if self.drag_origin is not None:
            sx, sy, x, y = self.drag_origin
            self.drag_origin = None
            if abs(event.x_root - sx) > 5 or abs(event.y_root - sy) > 5:
                self.slider_drag = False
                return
        btn = self.top_button_rects()
        hit_button = next((key for key, rect in btn.items()
                           if self._in_rect(event.x, event.y, rect)), None)
        if hit_button is not None:
            self.top_button_actions()[hit_button]()
        elif self._in_rect(event.x, event.y, self.refresh_btn_rect()):
            self.refresh()
        elif GRID_TOP - 5 <= event.y < self.height - 85:
            grid_layout, row_height, _, _ = self.compute_grid()
            for item in grid_layout:
                if (item["type"] == "talent"
                        and item["x"] <= event.x < item["x"] + item["w"]
                        and item["y"] <= event.y < item["y"] + row_height):
                    self.open_target(self.targets[item["index"]])
                    break

        elif slider_click:
            self.update_slider(slider_click, event.x)
        self.slider_drag = False

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
        visual_order = ("filter", "mode", "color", "lang", "pin", "close")
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

    def focus_next(self, event=None):
        items = self.focusable_items()
        if items:
            self.focus_index = 0 if self.focus_index is None else (self.focus_index + 1) % len(items)
            self.request_render()
        return "break"

    def focus_prev(self, event=None):
        items = self.focusable_items()
        if items:
            self.focus_index = (len(items) - 1 if self.focus_index is None
                                else (self.focus_index - 1) % len(items))
            self.request_render()
        return "break"

    def activate_focus(self, event=None):
        items = self.focusable_items()
        if self.focus_index is not None and 0 <= self.focus_index < len(items):
            # Sliders have no "activate" callback — Left/Right (see
            # adjust_focus_slider) is how a focused slider is operated, so
            # Enter/Space on one is simply a no-op rather than a KeyError.
            activate = items[self.focus_index].get("activate")
            if activate is not None:
                activate()
        return "break"

    def adjust_focus_slider(self, direction):
        items = self.focusable_items()
        if self.focus_index is None or not (0 <= self.focus_index < len(items)):
            return "break"
        item = items[self.focus_index]
        if item["kind"] != "slider":
            return "break"
        if item["slider_key"] == "background":
            darkness = 1.0 - self.background_alpha
            darkness = max(MIN_BACKGROUND_DARKNESS, min(1.0, darkness + direction * 0.05))
            self.background_alpha = 1.0 - darkness
            self.root.attributes("-alpha", max(1.0 - self.background_alpha, MIN_WINDOW_ALPHA))
        else:
            step = (TEXT_SCALE_MAX - TEXT_SCALE_MIN) * 0.05
            self.text_scale = max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, self.text_scale + direction * step))
        self.request_render()
        return "break"

    def clear_focus(self, event=None):
        if self.focus_index is not None:
            self.focus_index = None
            self.request_render()
        return "break"

    def _hit_row(self, x, y):
        for key, info in self.row_info.items():
            if self._in_rect(x, y, info["rect"]):
                return key, info
        return None, None

    def on_motion(self, event):
        if self.resize_drag or self.slider_drag or self.drag_origin is not None:
            return
        x, y = event.x, event.y
        edge = "se" if self._in_rect(x, y, self.resize_grip_rect()) else self.resize_edge(x, y)
        row_key, row = self._hit_row(x, y)
        if edge:
            cursor = self._RESIZE_CURSORS[edge]
        elif (self.slider_hit(x, y)
              or any(self._in_rect(x, y, r) for r in self.top_button_rects().values())
              or self._in_rect(x, y, self.refresh_btn_rect())
              or (row and row["clickable"])):
            cursor = "hand2"
        else:
            cursor = ""
        if self.surface.cget("cursor") != cursor:
            self.surface.configure(cursor=cursor)
        self._update_tooltip(row_key, row, event.x_root, event.y_root)

    def on_leave(self, event):
        if self.surface.cget("cursor") != "":
            self.surface.configure(cursor="")
        self._hide_tooltip()

    def _update_tooltip(self, row_key, row, root_x, root_y):
        text = row["tooltip"] if row else None
        if text is None:
            self._hide_tooltip()
            return
        if row_key == self._tooltip_key and (self.tooltip_win is not None or self._tooltip_after is not None):
            return
        self._hide_tooltip()
        self._tooltip_key = row_key
        self._tooltip_after = self.root.after(450, lambda: self._show_tooltip(text, root_x, root_y))

    def _show_tooltip(self, text, root_x, root_y):
        self._tooltip_after = None
        colors = self.theme_colors()
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        label = tk.Label(win, text=text, justify="left", font=("Yu Gothic UI", 9), padx=8, pady=4,
                         relief="solid", borderwidth=1,
                         bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]))
        label.pack()
        win.geometry(f"+{root_x + 16}+{root_y + 18}")
        self.tooltip_win = win

    def _hide_tooltip(self):
        if self._tooltip_after is not None:
            self.root.after_cancel(self._tooltip_after)
            self._tooltip_after = None
        self._tooltip_key = None
        if self.tooltip_win is not None:
            try:
                self.tooltip_win.destroy()
            except tk.TclError:
                pass
            self.tooltip_win = None

    def _copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    @staticmethod
    def _hex(rgb):
        return "#{:02x}{:02x}{:02x}".format(*rgb[:3])

    def show_context_menu(self, event):
        # Built fresh on each right-click (rather than a persistent Menu kept in
        # sync via traced Variables) so its colors/checkmarks/labels always match
        # whatever theme/language/state is current at click time.
        colors = self.theme_colors()
        menu = tk.Menu(
            self.root, tearoff=0,
            bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]),
            activebackground=self._hex(self.accent_color()),
            activeforeground=self._hex((24, 24, 31)),
            disabledforeground=self._hex(colors["muted"]),
            relief="flat", borderwidth=1,
        )
        _, row = self._hit_row(event.x, event.y)
        if row and row.get("copy_name"):
            menu.add_command(label=self.t("copy_name"),
                             command=lambda t=row["copy_name"]: self._copy_to_clipboard(t))
            if row.get("copy_title"):
                menu.add_command(label=self.t("copy_title"),
                                 command=lambda t=row["copy_title"]: self._copy_to_clipboard(t))
            menu.add_separator()
        # Plain commands with a "✓ " prefix on the label when active, not
        # checkbuttons — like dark_mode below, a Menu checkbutton's native
        # checkmark glyph is barely visible against this menu's custom dark
        # colors, so pin/live_only would otherwise look permanently unchecked.
        pin_label = f"✓ {self.t('pin')}" if self.topmost else self.t("pin")
        menu.add_command(label=pin_label, command=self.toggle_topmost)
        live_label = f"✓ {self.t('live_filter')}" if self.live_only else self.t("live_filter")
        menu.add_command(label=live_label, command=self.toggle_live_only)
        # Label names the CURRENT mode (like draw_mode_button()'s moon/sun icon),
        # not a fixed "Dark Mode" checkbox, for the same reason.
        menu.add_command(label=self.t("dark_mode") if self.dark_mode else self.t("light_mode"),
                         command=self.toggle_mode)
        menu.add_separator()
        lang_menu = tk.Menu(
            menu, tearoff=0,
            bg=self._hex(self.tint(colors["neutral_btn"])), fg=self._hex(colors["text"]),
            activebackground=self._hex(self.accent_color()),
            activeforeground=self._hex((24, 24, 31)),
        )
        # Plain commands with a "✓ " prefix on the active language, not
        # radiobuttons — same invisible-indicator issue as pin/live_only above.
        ja_label = f"✓ {self.t('lang_ja')}" if self.lang == "ja" else self.t("lang_ja")
        lang_menu.add_command(label=ja_label, command=lambda: self.set_lang("ja"))
        en_label = f"✓ {self.t('lang_en')}" if self.lang == "en" else self.t("lang_en")
        lang_menu.add_command(label=en_label, command=lambda: self.set_lang("en"))
        menu.add_cascade(label=self.t("language"), menu=lang_menu)
        menu.add_command(label=self.t("theme_color"), command=self.open_palette)
        menu.add_separator()
        menu.add_command(label=self.t("refresh"), command=self.refresh)
        menu.add_command(label=self.t("close"), command=self.close)
        menu.add_separator()
        menu.add_command(label=f"HoloDeskWidget v{__version__}", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _in_rect(x, y, rect):
        left, top, right, bottom = rect
        return left <= x <= right and top <= y <= bottom

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.render()

    def toggle_lang(self):
        self.lang = "en" if self.lang == "ja" else "ja"
        self.render()

    def set_lang(self, lang):
        self.lang = lang
        self.render()

    def toggle_mode(self):
        self.dark_mode = not self.dark_mode
        self.render()

    def toggle_live_only(self):
        if not self.live_only:
            # Remember the "all talents" height so switching the filter back
            # off restores it, instead of forcing a recomputed size every time.
            self._all_height = self.height
        self.live_only = not self.live_only
        self.fit_height()
        self.render()

    def fit_height(self):
        if self.live_only:
            _, natural_end = self.build_grid_layout(25, 18)
            target_height = natural_end + 90
        else:
            target_height = self._all_height
        target_height = max(MIN_HEIGHT, min(MAX_HEIGHT, round(target_height)))
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.height = target_height
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def toggle_palette(self):
        if self.palette_win is not None:
            self.close_palette()
            return
        self.open_palette()

    def open_palette(self):
        colors = self.theme_colors()
        panel_hex = "#{:02x}{:02x}{:02x}".format(*colors["panel"][:3])
        muted_hex = "#{:02x}{:02x}{:02x}".format(*colors["muted"][:3])
        win = tk.Toplevel(self.root)
        self.palette_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=panel_hex)
        cols, swatch = 5, 40
        preview = tk.Label(win, text=self.t("palette_hint"), bg=panel_hex, fg=muted_hex,
                           font=("Yu Gothic UI", 9, "bold"), anchor="w")
        preview.grid(row=0, column=0, columnspan=cols, sticky="we", padx=6, pady=(6, 2))
        for i, (name, rgb) in enumerate(THEME_PALETTE):
            row, col = divmod(i, cols)
            cv = tk.Canvas(win, width=swatch, height=swatch, bg=panel_hex,
                          highlightthickness=0, cursor="hand2")
            if name == "Monochrome":
                # Drawn half-black/half-white so it reads as the neutral option
                # among all the hues, rather than just another flat swatch.
                cv.create_polygon(0, 0, swatch, 0, 0, swatch, fill="#000000", outline="")
                cv.create_polygon(swatch, 0, swatch, swatch, 0, swatch, fill="#ffffff", outline="")
            else:
                hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)
                cv.create_rectangle(0, 0, swatch, swatch, fill=hex_color, outline="")
            cv.bind("<Button-1>", lambda event, idx=i: self.select_theme(idx))
            cv.bind("<Enter>", lambda event, n=name: preview.configure(text=n))
            cv.bind("<Leave>", lambda event: preview.configure(text=self.t("palette_hint")))
            cv.grid(row=row + 1, column=col, padx=2, pady=2)
        win.update_idletasks()
        rect = self.top_button_rects()["color"]
        bx = self.root.winfo_x() + int(rect[0])
        by = self.root.winfo_y() + int(rect[3]) + 6
        win.geometry(f"+{bx}+{by}")
        win.bind("<FocusOut>", lambda event: self.close_palette())
        win.focus_force()

    def close_palette(self):
        win = self.palette_win
        if win is not None:
            self.palette_win = None
            try:
                win.destroy()
            except tk.TclError:
                pass

    def select_theme(self, index):
        self.theme_index = index
        self.suppress_next_click = True
        self.close_palette()
        self.render()

    def slider_hit(self, x, y):
        # Returns which slider (by key) the point falls in, or False for none,
        # so drag/click handlers can dispatch to the right setter via
        # update_slider() instead of assuming there's only ever one slider.
        for key, geom in self.slider_geometry().items():
            if geom["y"] - 5 <= y <= geom["y"] + 15 and geom["track_start"] <= x <= geom["track_end"]:
                return key
        return False

    def update_slider(self, key, x):
        if key == "background":
            self.set_alpha_from_pointer(x)
        elif key == "text":
            self.set_text_scale_from_pointer(x)

    def set_alpha_from_pointer(self, x):
        # Dragging right increases darkness/opacity (matches "背景濃さ"/"BG"). The
        # full track maps onto MIN_BACKGROUND_DARKNESS..1.0 darkness so the knob can
        # reach both ends even though darkness never actually reaches 0%.
        bg = self.slider_geometry()["background"]
        fraction = max(0.0, min(1.0, (x - bg["track_start"]) / (bg["track_end"] - bg["track_start"])))
        background_darkness = MIN_BACKGROUND_DARKNESS + fraction * (1.0 - MIN_BACKGROUND_DARKNESS)
        self.background_alpha = 1.0 - background_darkness
        self.root.attributes("-alpha", max(1.0 - self.background_alpha, MIN_WINDOW_ALPHA))
        self.request_render()

    def set_text_scale_from_pointer(self, x):
        txt = self.slider_geometry()["text"]
        fraction = max(0.0, min(1.0, (x - txt["track_start"]) / (txt["track_end"] - txt["track_start"])))
        self.text_scale = TEXT_SCALE_MIN + fraction * (TEXT_SCALE_MAX - TEXT_SCALE_MIN)
        self.request_render()

    def open_target(self, target):
        name, _, url, _ = target
        now = time.monotonic()
        if self.last_opened[0] == name and now - self.last_opened[1] < 0.5:
            return
        self.last_opened = (name, now)
        if self.states.get(name) == "live" and self.live_urls.get(name):
            webbrowser.open(self.live_urls[name], new=2)
            return
        # check_one() may have already resolved a better URL than talents.json's
        # guess; prefer that cached copy over the (possibly stale) tuple field.
        url = self.channel_urls.get(name, url)
        if "/channel/" in url:
            webbrowser.open(url, new=2)
            return
        # Resolve off the Tk main thread: this is a network call and click() runs
        # on the UI thread, so doing it inline would freeze the whole window.
        threading.Thread(target=self._resolve_and_open, args=(name, url), daemon=True).start()

    @staticmethod
    def _resolve_and_open(name, url):
        try:
            webbrowser.open(youtube.resolve_watch_page_url(url), new=2)
        except (HTTPError, OSError, ValueError):
            webbrowser.open(youtube.build_search_fallback_url(name), new=2)

    def refresh(self):
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        self.render()  # show the "refreshing" button state right away, not
                       # whenever the next tick/ticker render happens to land
        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        try:
            # Plain daemon threads instead of ThreadPoolExecutor: its worker
            # threads register with concurrent.futures' own atexit hook and
            # get joined before the interpreter is allowed to exit, so a
            # single slow/hanging youtube.fetch_live_info() call — which can
            # stack multiple 20s-timeout network requests (channel-id
            # resolution, an internal retry on the browse call, and this
            # module's own 404 channel re-resolve path) well past a single
            # 20s bound — would keep the whole process — and the
            # single-instance mutex it holds — alive well after the window
            # closes. Daemon threads are simply abandoned on exit instead.
            semaphore = threading.Semaphore(12)

            def bounded_check(name, target):
                with semaphore:
                    self.check_one(name, target)

            workers = [threading.Thread(target=bounded_check, args=(name, target), daemon=True)
                       for name, _, target, _ in self.targets]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        finally:
            try:
                self.root.after(0, self.refresh_complete)
            except (RuntimeError, tk.TclError):
                # The window can be closed while a refresh is still in flight;
                # self.root is already destroyed at that point, nothing to update.
                pass

    def refresh_complete(self):
        self.refresh_in_progress = False
        self.last_updated = time.strftime("%H:%M:%S")
        self.render()
        self.root.after(60_000, self.refresh)

    def check_one(self, name, target):
        try:
            slug = next(slug for target_name, slug, _, _ in self.targets
                        if target_name == name)
            if name not in self.channel_urls:
                try:
                    self.channel_urls[name] = youtube.resolve_channel_url(slug)
                except (HTTPError, OSError, UnicodeError, ValueError):
                    self.channel_urls[name] = target
            target = self.channel_urls[name]
            try:
                video_id, title = youtube.fetch_live_info(target)
            except HTTPError as error:
                # code == 404 here covers both a real transport 404 and
                # youtube.ChannelNotFoundError (a real HTTPError subclass
                # fetch_live_info() raises when the browse API answers 200 OK
                # with an "alerts" ERROR banner instead) — both mean the same
                # thing to this retry: re-resolve the channel and try once more.
                if error.code != 404:
                    raise
                try:
                    target = youtube.resolve_channel_url(slug)
                except (HTTPError, OSError, UnicodeError, ValueError):
                    # A 404 on /live can be a transient YouTube-side hiccup, and
                    # some talents' hololivepro profile page no longer scrapes a
                    # channel link (e.g. after graduation) so this retry can fail
                    # every single cycle. Keep last-known state instead of
                    # escalating to "error" and re-logging the same failure on
                    # every refresh forever.
                    return
                self.channel_urls[name] = target
                for index, (target_name, slug, _, unit) in enumerate(self.targets):
                    if target_name == name:
                        self.targets[index] = (target_name, slug, target, unit)
                        break
                video_id, title = youtube.fetch_live_info(target)
            if video_id:
                # Set live_urls before states: open_target() reads states
                # first, so this ordering keeps it from ever observing
                # state == "live" with live_urls not yet populated.
                self.live_urls[name] = f"https://www.youtube.com/watch?v={video_id}"
                if title:
                    self.live_titles[name] = title
                else:
                    self.live_titles.pop(name, None)
                self.states[name] = "live"
            else:
                self.live_urls.pop(name, None)
                self.live_titles.pop(name, None)
                self.states[name] = "offline"
        except (HTTPError, OSError, UnicodeError, ValueError) as error:
            self.states[name] = "error"
            self.live_urls.pop(name, None)
            self.live_titles.pop(name, None)
            log_error(name, error)

    def current_settings(self):
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        except tk.TclError:
            x, y = DEFAULT_SETTINGS["x"], DEFAULT_SETTINGS["y"]
        return {
            "x": x,
            "y": y,
            "width": self.width,
            "height": self.height,
            "background_alpha": self.background_alpha,
            "lang": self.lang,
            "topmost": self.topmost,
            "theme_index": self.theme_index,
            "dark_mode": self.dark_mode,
            "live_only": self.live_only,
            "text_scale": self.text_scale,
        }

    def close(self):
        save_settings(self.current_settings())
        if self.root.winfo_exists():
            self.root.destroy()
