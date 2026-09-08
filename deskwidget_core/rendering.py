"""Pillow-based drawing: the whole render() pass plus every draw_*/label-fit
helper it calls. Split out of widget.py (which still owns all the state this
reads) purely to keep the ~1000 lines of drawing code out of the file that
also owns state/input/menus/refresh -- every method here still reads/writes
`self` exactly as it did as part of LayeredWidget; only the class boundary
moved.
"""
import functools
import math
import re
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from . import appconfig
from .config import MIN_BACKGROUND_DARKNESS, TEXT_SCALE_MIN, TEXT_SCALE_MAX
from .fonts import emoji_font, font
from .grid_layout import PANEL_INSET
from .strings import STRINGS, english_name
from .theme import KEY_COLOR, MIN_LABEL_SIZE, THEME_PALETTE, THEMES, production_band_color

# Ranges covering the emoji live-stream titles actually use (pictographs,
# symbols/dingbats, regional-indicator flags) plus the modifiers that glue
# multi-codepoint emoji sequences together, so a whole sequence is treated
# as one run and handed to the emoji font as a unit.
_EMOJI_SPLIT_RE = re.compile(
    "([\U0001F000-\U0001FFFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0000FE0F\U0000200D\U000020E3]+)"
)


class RenderingMixin:
    @staticmethod
    def talent_bullet_and_display_name(name, slug, state, lang):
        # Shared by render()'s talent loop and widget.py's
        # _visible_talent_labels() (used by compute_grid() to measure the
        # widest visible label) so the two can never draw/measure a
        # different bullet+name than what actually ends up on screen.
        bullet = "● " if state == "live" else "! " if state == "error" else "• "
        display_name = name if lang == "ja" else english_name(slug)
        return bullet, display_name

    def _draw_toggle_button(self, draw, colors, accent, rect, label, active):
        fill = accent if active else self.tint(colors["neutral_btn"]) + (255,)
        text = self.text_color((24, 24, 31)) if active else self.text_color(colors["text"])
        draw.rounded_rectangle(rect, 8, fill=fill)
        self.draw_centered(draw, rect, label, font(11, True), text)

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
        self._draw_top_bar(draw, colors, accent, btn)
        self._draw_tabs(draw, colors, accent)
        # Read once up front, not per access below -- for the "All" tab
        # (active_production == ALL_PRODUCTION_ID) each of these properties
        # re-merges every visible production's dict from scratch (see
        # _merge_all_slots()), so repeating self.targets/self.states/
        # self.live_titles per talent row turned this render pass into an
        # O(N^2) one across a few hundred talents, on every ~60ms ticker tick.
        targets = self.targets
        states = self.states
        live_titles = self.live_titles if self.live_only else {}
        self._draw_status_and_sliders(draw, colors, targets, states)
        grid_layout, row_height, pending_tickers = self._draw_grid_rows(
            draw, colors, targets, states, live_titles)
        self._update_and_draw_tickers(image, colors, pending_tickers)
        self._draw_footer(draw, colors)
        if self.focus_index is not None:
            # Reuse this render()'s own grid_layout/row_height/targets
            # (computed above) instead of letting focusable_items() recompute
            # the grid -- and re-merge self.targets -- from scratch, see the
            # note on those parameters in focusable_items(). Matters most
            # here: this runs on every ~60ms ticker tick for as long as a
            # focus ring stays visible.
            items = self.focusable_items(grid_layout, row_height, targets)
            if 0 <= self.focus_index < len(items):
                fx0, fy0, fx1, fy1 = items[self.focus_index]["rect"]
                draw.rounded_rectangle((fx0 - 3, fy0 - 3, fx1 + 3, fy1 + 3), 6,
                                       outline=accent, width=2)
            else:
                self.focus_index = None
        self.apply_image(image)

    def _draw_top_bar(self, draw, colors, accent, btn):
        draw.rounded_rectangle(
            (PANEL_INSET, PANEL_INSET, self.width - PANEL_INSET, self.height - PANEL_INSET), 22,
            fill=self.tint(colors["panel"][:3]) + (colors["panel"][3],),
            outline=colors["outline"], width=1)
        if self.has_multiple_productions():
            # Only a single compact line fits above the tab strip below (see
            # layout.TABS_TOP) -- the app's own name, not a translatable
            # brand string, since it's identical either language.
            draw.text((38, 40), appconfig.app_name(), font=font(14, True),
                      fill=self.text_color(colors["text"]))
        else:
            # No tab strip to leave room for, so this variant's brand/title
            # gets the taller two-line treatment instead.
            draw.text((38, 36), appconfig.title(self.lang), font=font(18, True),
                      fill=self.text_color(colors["text"]))
            draw.text((38, 59), "LIVE STATUS", font=font(14, True), fill=self.text_color(colors["text"]))
        close_rect_btn = btn["close"]
        draw.rounded_rectangle(close_rect_btn, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        self.draw_centered(draw, close_rect_btn, "×", font(18, True), self.text_color(colors["text"]))
        self.draw_fullscreen_button(draw, btn["fullscreen"], colors)
        self.draw_tray_button(draw, btn["tray"], colors)
        self._draw_toggle_button(draw, colors, accent, btn["pin"], self.t("pin"), self.topmost)
        lang_rect = btn["lang"]
        draw.rounded_rectangle(lang_rect, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        self.draw_centered(draw, lang_rect, self.t("lang_toggle"), font(11, True),
                           self.text_color(colors["text"]))
        self.draw_theme_button(draw, btn["color"], colors)
        self.draw_font_button(draw, btn["font"], colors)
        self.draw_mode_button(draw, btn["mode"], colors)
        self._draw_toggle_button(draw, colors, accent, btn["filter"], self.t("live_filter"), self.live_only)
        if self.has_multiple_productions():
            self._draw_toggle_button(draw, colors, accent, btn["productions"],
                                      self.t("productions_button"), self.productions_win is not None)

    def _draw_tabs(self, draw, colors, accent):
        tabs = self.production_tabs()
        for tab in tabs:
            rect = (tab["x"], tab["y"], tab["x"] + tab["w"], tab["y"] + tab["h"])
            active = tab["id"] == self.active_production
            tab_fill = accent if active else self.tint(colors["neutral_btn"]) + (255,)
            tab_text = self.text_color((24, 24, 31)) if active else self.text_color(colors["text"])
            draw.rounded_rectangle(rect, 7, fill=tab_fill)
            fitted_label, tab_font = self._fit_label(tab["label"], 12, 8,
                                                     tab["w"] - 10, bold=active)
            self.draw_centered(draw, rect, fitted_label, tab_font, tab_text)
            self.row_info[("tab", tab["id"])] = {
                "rect": rect, "clickable": True,
                "tooltip": tab["label"] if fitted_label != tab["label"] else None,
                "copy_name": None, "copy_title": None,
            }

    def _draw_status_and_sliders(self, draw, colors, targets, states):
        live_count = sum(state == "live" for state in states.values())
        status_top, status_bottom = self.status_bar_top(), self.status_bar_bottom()
        draw.rounded_rectangle((38, status_top, self.width - 38, status_bottom), 8,
                               fill=self.background_color(colors["status_bg"]))
        count_font = font(12, True)
        count_text = self.t("count", live=live_count, total=len(targets))
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

    def _draw_grid_rows(self, draw, colors, targets, states, live_titles):
        # No scroll support: instead of dropping rows that don't fit, compute_grid()
        # shrinks row/divider height and font size uniformly so everything is shown.
        # targets/states were already merged in render() for the status bar/talent
        # loop -- passed straight through so compute_grid() doesn't re-merge them
        # a second time on the "All" tab (see the note in compute_grid() itself).
        grid_layout, row_height, divider_height, grid_scale = self.compute_grid(targets, states)
        # The clock category is always present, so an empty-state message is
        # judged on talent rows specifically, not on grid_layout being empty.
        # A production with zero talents at all (e.g. a freshly-empty
        # custom.json) takes priority over the live-only "no one is live"
        # message, since that's the more useful thing to tell the user here.
        has_talent_row = any(item["type"] == "talent" for item in grid_layout)
        if not targets:
            empty_text = self.t("no_talents")
        elif self.live_only and not has_talent_row:
            empty_text = self.t("no_live")
        else:
            empty_text = None
        if empty_text:
            empty_font = font(13, True)
            bbox = empty_font.getbbox(empty_text)
            # Placed below the world-clock section (which is always drawn,
            # live filter or not) rather than at grid_top(), so this message
            # doesn't overlap the clock category's own header/rows.
            clock_bottom = self.grid_top()
            for item in grid_layout:
                clock_bottom = max(clock_bottom, item["y"] + item["h"])
            draw.text(((self.width - bbox[2]) / 2, clock_bottom + 10), empty_text, font=empty_font,
                      fill=self.text_color(colors["muted"]))
        label_scale = grid_scale * self.text_scale
        base_label_size = max(2, round(16 * label_scale))
        min_label_size = min(MIN_LABEL_SIZE, base_label_size)
        # Unlike the talent grid (which intentionally grows/shrinks per tab to
        # fill the panel — see compute_grid()'s note), the clock time and its
        # own category divider label are scaled off text_scale alone, not
        # grid_scale: grid_scale reflects how many rows the *current* tab's
        # talent list needs, so tying these to it made the clock text visibly
        # change size when switching tabs even though its own content doesn't
        # change. Talent unit-header dividers ("JP"/"ID"/"EN", etc.) don't
        # share that reasoning -- their row height (divider_height, above) is
        # still fully grid_scale-compressed, so their font has to move with
        # it the same way the pre-refactor single-file widget kept both in
        # lockstep, or a dense roster at a small window size shrinks the row
        # far more than the text drawn into it, overlapping neighboring rows.
        clock_divider_font = font(max(2, round(10 * self.text_scale)), True)
        unit_divider_font = font(max(2, round(10 * label_scale)), True)
        clock_label_size = max(2, round(16 * self.text_scale))
        clock_min_label_size = min(MIN_LABEL_SIZE, clock_label_size)
        # "band" items only exist on the "All" tab (see build_grid_layout()'s
        # own guard) -- on a single production's own tab every unit is just a
        # sub-group (e.g. "JP") within that one production, so there's
        # nothing to distinguish with a background shade.
        band_base = self.tint(colors["panel"][:3])
        pending_tickers = []
        talent_entries = []
        clock_entries = []
        for item in grid_layout:
            if item["type"] == "band":
                draw.rounded_rectangle(
                    (32, item["y"] + 1, self.width - 32, item["y"] + item["h"] - 1),
                    8, fill=production_band_color(band_base, item["position"]))
                continue
            if item["type"] == "divider":
                divider_font = (clock_divider_font if item.get("kind") == "clock"
                                 else unit_divider_font)
                draw.text((40, item["y"]), item["unit"], font=divider_font,
                          fill=self.text_color(colors["muted"]))
                label_w = divider_font.getbbox(item["unit"])[2]
                line_y = item["y"] + item["h"] / 2
                draw.line((40 + label_w + 8, line_y, self.width - 40, line_y),
                         fill=self.text_color(colors["divider"]), width=1)
                continue
            if item["type"] == "clock":
                # Drawing is deferred to a second pass below (once every
                # entry's own max_label_width is known) so the whole clock
                # grid can share one font size instead of each entry
                # shrinking independently to fit its own column — see the
                # matching note by the talent grid's shared_label_size.
                clock_entries.append({"item": item, "max_label_width": item["w"] - 12})
                continue
            x, y = item["x"], item["y"]
            name, slug, _, _ = targets[item["index"]]
            state = states[name]
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
            bullet, display_name = self.talent_bullet_and_display_name(name, slug, state, self.lang)
            label = bullet + display_name
            # In the live-only view every row is one talent wide, so the name
            # only needs a modest fixed-width lane — the rest of the row goes
            # to the now-playing ticker built below.
            title = live_titles.get(name) if self.live_only else None
            label_area_w = min(item["w"] * 0.4, max(90, 170 * label_scale)) if title else item["w"]
            max_label_width = label_area_w - 12
            # Drawing is deferred to a second pass below (once every label's
            # own max_label_width is known) so the whole grid can share one
            # font size instead of each name shrinking independently to fit
            # its own column — see the note by _shared_label_size().
            talent_entries.append({
                "item": item, "x": x, "y": y, "name": name, "color": color,
                "label": label, "display_name": display_name, "title": title,
                "label_area_w": label_area_w, "max_label_width": max_label_width,
            })
        # One shared size for every clock entry in this render, same reason
        # as the talent grid's shared_label_size below — a zone with a long
        # region name (e.g. "PDT(Los Angeles)") would otherwise land visibly
        # smaller than "UTC" sitting right next to it. Unlike the talent
        # grid, entries that don't fit at the base size aren't excluded from
        # this search: a clock column is sized to its own content (see
        # grid_layout.py), so every entry is expected to fit once the shared
        # size shrinks enough -- excluding the poor-fitting one would leave
        # it at a size that still doesn't fit, sending it to _fit_label()'s
        # ellipsis truncation below instead of just rendering the whole grid
        # a size smaller.
        shared_clock_label_size = clock_label_size
        if clock_entries:
            shared_clock_label_size = self._shared_label_size(
                [(c["item"]["text"], c["max_label_width"]) for c in clock_entries],
                clock_label_size, clock_min_label_size)
        for c in clock_entries:
            item, max_label_width = c["item"], c["max_label_width"]
            x, y = item["x"], item["y"]
            label, label_font = self._fit_label(item["text"], shared_clock_label_size,
                                                 shared_clock_label_size, max_label_width)
            draw.text((x, y), label, font=label_font, fill=self.text_color(colors["muted"]))
            self.row_info[("clock", item["zone"])] = {
                "rect": (x, item["y"], x + item["w"], item["y"] + item["h"]),
                "clickable": False,
                "tooltip": item["text"] if label != item["text"] else None,
                "copy_name": None, "copy_title": None,
            }
        # One shared size for every talent name in this render, rather than
        # _fit_label() picking each name's own best-fitting size in
        # isolation — otherwise a long name (many kana) would land visibly
        # smaller than a short one sitting right next to it in the same grid,
        # which reads as broken/inconsistent rather than as intentional
        # variety.
        shared_label_size = base_label_size
        if talent_entries:
            # Names that don't even fit their column at the normal
            # (unscaled) size are excluded from this batch, same as
            # compute_grid()'s own max_scale check above — they're headed
            # for _fit_label()'s ellipsis truncation below regardless of
            # shared size, so they shouldn't drag every *other* name's size
            # down to whatever tiny value it'd take to spell them out in
            # full (e.g. one long roster entry forcing an entire roster of
            # normal-length names to render smaller than the grid's own
            # growth-cap math intended).
            sizing_entries = [e for e in talent_entries
                               if self._label_width(e["label"], base_label_size, True)
                               <= e["max_label_width"]] \
                              or talent_entries
            shared_label_size = self._shared_label_size(
                [(e["label"], e["max_label_width"]) for e in sizing_entries],
                base_label_size, min_label_size)
        # The now-playing ticker should start at the same x on every row
        # instead of wherever each row's own name happens to end, so every
        # row with a title shares one label-lane width — wide enough for the
        # widest of those names (so none of them get truncated either, same
        # as the no-abbreviation goal below) — rather than each row's ticker
        # starting at a different x depending on that row's own name length.
        title_entries = [e for e in talent_entries if e["title"]]
        shared_title_label_area_w = max(
            (min(e["item"]["w"], self._label_width(e["label"], shared_label_size, True) + 12)
             for e in title_entries), default=None)
        for e in talent_entries:
            item, x, y, name, color, label, display_name, title, label_area_w, max_label_width = (
                e["item"], e["x"], e["y"], e["name"], e["color"], e["label"], e["display_name"],
                e["title"], e["label_area_w"], e["max_label_width"])
            if title:
                # Never abbreviate the talent name to make room for the
                # now-playing ticker: use the shared lane width computed
                # above (wide enough for the widest name that has a title)
                # instead of the fixed lane computed when this row was first
                # built, so the name isn't truncated and every ticker still
                # lines up at the same x.
                label_area_w = shared_title_label_area_w
                max_label_width = label_area_w - 12
            fitted_label, label_font = self._fit_label(label, shared_label_size, shared_label_size,
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
        return grid_layout, row_height, pending_tickers

    def _update_and_draw_tickers(self, image, colors, pending_tickers):
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

    def _draw_footer(self, draw, colors):
        updated_text = (self.t("updated", time=self.last_updated) if self.last_updated
                        else self.t("updated_none"))
        updated_font = font(10, True)
        draw.text((40, self.height - 84), updated_text, font=updated_font,
                  fill=self.text_color(colors["muted"]))
        version_text = f"v{appconfig.version()}"
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

    def t(self, key, **kwargs):
        text = STRINGS[self.lang][key]
        return text.format(**kwargs) if kwargs else text

    @staticmethod
    def draw_centered(draw, rect, text, fnt, fill):
        left, top, right, bottom = rect
        bbox = fnt.getbbox(text)
        x = left + ((right - left) - (bbox[2] - bbox[0])) // 2 - bbox[0]
        # Shares its y-centering math with vcenter_y() below rather than
        # duplicating the formula, so a future tweak to one can't silently
        # drift out of alignment with the other.
        y = RenderingMixin.vcenter_y(fnt, text, top, bottom)
        draw.text((x, y), text, font=fnt, fill=fill)

    @staticmethod
    @functools.lru_cache(maxsize=4096)
    def vcenter_y(fnt, text, top, bottom):
        # Cached like _fit_label() below: called again for every row on every
        # ~60ms ticker tick even when the row's font/text/bounds haven't
        # changed since the last frame, which used to repeat this getbbox()
        # call for nothing on every single tick. maxsize must clear the "All"
        # tab's own per-frame call count (talent rows + tabs + clock cells,
        # a few hundred) with room to spare -- 256 was smaller than that
        # count, so every call evicted an entry another call in the very same
        # frame still needed, leaving this at a permanent 0% hit rate on the
        # tab this caching exists for. Matches _label_width()'s maxsize below
        # for the same reason.
        bbox = fnt.getbbox(text)
        return top + ((bottom - top) - (bbox[3] - bbox[1])) // 2 - bbox[1]

    @staticmethod
    @functools.lru_cache(maxsize=4096)
    def _fit_label(label, base_size, min_size, max_label_width, bold=True):
        # Shrinks the font a point at a time, then falls back to ellipsis
        # truncation, until label fits max_label_width — used for every talent
        # and world-clock row. Cached because the ticker's ~60ms render tick
        # calls this again for every row every frame even though the label
        # text/size/width triple it depends on is unchanged between actual
        # data/layout updates, which used to repeat the whole getbbox() search
        # for nothing on every single tick. maxsize must clear the "All" tab's
        # own per-frame call count (talent rows + tabs + clock cells, a few
        # hundred) with room to spare -- 256 was smaller than that count, so
        # every call evicted an entry another call in the very same frame
        # still needed, leaving this at a permanent 0% hit rate on exactly the
        # tab this caching exists for. Matches _label_width()'s maxsize below.
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
    @functools.lru_cache(maxsize=4096)
    def _label_width(label, size, bold=True):
        # A label's rendered width at one (size, bold) combination, factored
        # out so compute_grid()'s column-count search (which re-measures the
        # same handful of talent labels across many candidate column widths
        # and many candidate font sizes every time it runs) doesn't repeat
        # the same getbbox() call for a pairing it already measured a moment
        # ago in this same call.
        return font(size, bold).getbbox(label)[2]

    @staticmethod
    def _shared_label_size(labels_and_widths, base_size, min_size, bold=True):
        # Picks one size the whole batch of labels can render at, instead of
        # render()'s talent loop calling _fit_label() per row and letting
        # each name shrink to its own best-fitting size — a long name would
        # then land visibly smaller than a short one next to it even though
        # both sit in same-width columns.
        for size in range(base_size, min_size - 1, -1):
            if all(RenderingMixin._label_width(label, size, bold) <= width
                   for label, width in labels_and_widths):
                return size
        return min_size

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
        runs = RenderingMixin._emoji_runs(text, fnt)
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
        runs = RenderingMixin._emoji_runs(text, fnt)
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

    def draw_font_button(self, draw, rect, colors):
        # A big "A" next to a small "a" -- the conventional font-picker glyph
        # (Word, Google Docs, Figma all use it) -- rendered in the
        # currently-selected font family itself, so the button doubles as a
        # live preview of the active choice. A uniform-size "Aa" (the
        # previous icon here) reads as plain text and blends in next to this
        # row's actual text-label buttons (EN, 最前面) instead of standing
        # out as an icon.
        draw.rounded_rectangle(rect, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        color = self.text_color(colors["text"])
        big_font, small_font = font(15, True), font(10, True)
        big_bbox, small_bbox = big_font.getbbox("A"), small_font.getbbox("a")
        big_w, small_w = big_bbox[2] - big_bbox[0], small_bbox[2] - small_bbox[0]
        gap = 1
        left = rect[0] + ((rect[2] - rect[0]) - (big_w + gap + small_w)) // 2
        # Baselines aligned (not centers) so the two letters sit together
        # like real text, the way every reference icon above does it.
        baseline = rect[1] + ((rect[3] - rect[1]) + (big_bbox[3] - big_bbox[1])) // 2
        draw.text((left - big_bbox[0], baseline - big_bbox[3]), "A", font=big_font, fill=color)
        small_x = left + big_w + gap
        draw.text((small_x - small_bbox[0], baseline - small_bbox[3]), "a", font=small_font, fill=color)

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

    def draw_fullscreen_button(self, draw, rect, colors):
        # Four corner brackets, like a camera viewfinder. Not fullscreen: they
        # sit out near the icon's own corners (an "expand" glyph); fullscreen
        # active: they pull in near the center (a "restore" glyph) and the
        # button gets the same accent-fill treatment as pin/filter's active
        # state.
        fill = self.accent_color() if self.is_fullscreen else self.tint(colors["neutral_btn"]) + (255,)
        draw.rounded_rectangle(rect, 8, fill=fill)
        icon_color = self.text_color((24, 24, 31)) if self.is_fullscreen else self.text_color(colors["text"])
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        offset, arm = (3, 2) if self.is_fullscreen else (7, 4)
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x, y = cx + sx * offset, cy + sy * offset
            draw.line((x, y, x - sx * arm, y), fill=icon_color, width=2)
            draw.line((x, y, x, y - sy * arm), fill=icon_color, width=2)

    def draw_tray_button(self, draw, rect, colors):
        # "Minimize to tray": an underscore sitting near the bottom of the
        # icon (not a centered dash), the same glyph a normal window's own
        # minimize button uses, so together with fullscreen and close
        # alongside it this reads as the familiar minimize/maximize/close
        # trio (see TOP_BUTTON_ORDER's comment) instead of a bespoke icon
        # that read as "download" (arrow dropping onto a line) rather than
        # "minimize". Not a toggle (there's no "in the tray" visual state to
        # reflect once the window is withdrawn), so this always uses the
        # same plain neutral fill as e.g. the close button rather than
        # pin/fullscreen's accent-when-active treatment.
        draw.rounded_rectangle(rect, 8, fill=self.tint(colors["neutral_btn"]) + (255,))
        icon_color = self.text_color(colors["text"])
        cx = (rect[0] + rect[2]) // 2
        y = rect[3] - 11
        draw.line((cx - 6, y, cx + 6, y), fill=icon_color, width=2)

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

    @staticmethod
    def _hex(rgb):
        return "#{:02x}{:02x}{:02x}".format(*rgb[:3])

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
            self._bind_surface_events()
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
