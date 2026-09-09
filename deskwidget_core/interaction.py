"""Mouse/keyboard event handlers: drag/resize, click dispatch, keyboard
focus traversal, hover tooltips, clipboard copy, and slider dragging. These
read the rects/hit-tests GridMixin computes and dispatch into whatever
button/menu/refresh action was hit.
"""
import tkinter as tk

from .config import (
    COLUMN_SCALE_MAX,
    COLUMN_SCALE_MIN,
    FONT_UI_SMALL,
    MAX_HEIGHT,
    MAX_WIDTH,
    MIN_BACKGROUND_DARKNESS,
    MIN_HEIGHT,
    MIN_WIDTH,
    MIN_WINDOW_ALPHA,
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
)

# Pointer movement (px) below which a press+release counts as a click rather
# than a drag that happened to end near a slider.
_DRAG_CLICK_THRESHOLD = 5
# Vertical band (px, relative to grid_top()/self.height) a click has to land
# in to be treated as a grid-row hit rather than the status bar above/below it.
_GRID_HIT_TOP_MARGIN = 5
_GRID_HIT_BOTTOM_MARGIN = 85
_TOOLTIP_DELAY_MS = 450
_TOOLTIP_OFFSET_X = 16
_TOOLTIP_OFFSET_Y = 18
# Fraction of the slider's full range each keyboard Left/Right press moves.
_SLIDER_KEY_STEP = 0.05


class InteractionMixin:
    def _bind_surface_events(self):
        # Wires the render surface to every handler this mixin (plus
        # show_context_menu(), owned by MenuMixin) defines. Called once, the
        # first time apply_image() creates self.surface -- kept here rather
        # than alongside that creation so RenderingMixin doesn't need to name
        # every handler its own module doesn't define.
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
        # Ctrl+F jumps to the title filter box without reaching for the mouse,
        # the same shortcut every browser/editor uses for "find". Both cases
        # are bound because Tk reports the keysym's own case, which follows
        # whether Shift/CapsLock is down.
        self.surface.bind("<Control-f>", self.focus_search)
        self.surface.bind("<Control-F>", self.focus_search)

    def _hit_button_at(self, x, y):
        return next((key for key, rect in self.top_button_rects().items()
                     if self._in_rect(x, y, rect)), None)

    def _apply_background_alpha(self):
        self.root.attributes("-alpha", max(1.0 - self.background_alpha, MIN_WINDOW_ALPHA))

    def drag_start(self, event):
        # Snapshot, before focus_set() below steals focus, whether this press
        # landed on the button whose own popup is currently open. focus_set()
        # fires an async FocusOut on that popup (font_win's entry defers it a
        # tick; palette_win/productions_win bind it directly), which closes
        # the popup well before this same click's ButtonRelease reaches
        # click() -- so without this snapshot, toggle_*_menu() would see the
        # popup already gone and reopen it instead of leaving it closed,
        # making a second press on the button look like it does nothing.
        menu_wins = {"font": self.font_win, "color": self.palette_win,
                     "productions": self.productions_win}
        hit_key = self._hit_button_at(event.x, event.y)
        self.menu_reopen_guard = hit_key if menu_wins.get(hit_key) is not None else None
        self.surface.focus_set()
        self._hide_tooltip()
        if self.focus_index is not None:
            self.focus_index = None
            self.request_render()
        edge = ("se" if self._in_rect(event.x, event.y, self.resize_grip_rect())
                else self.resize_edge(event.x, event.y))
        if edge:
            # A manual resize means the window is no longer "fullscreen" in
            # any tracked sense -- drop the flag (and the now-meaningless
            # restore point) so the button's icon and close()'s saved size
            # both reflect what's actually on screen.
            self.is_fullscreen = False
            self._pre_fullscreen = None
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
            # Always set (not just when it differs from start_x/start_y):
            # request_render() coalesces bursts of drag_move() calls into one
            # render, so an unconditional assignment here is what keeps
            # _render_now() from applying a stale offset left over from an
            # earlier call in the same burst whose new_x/new_y happened not
            # to match this one's.
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
        guard, self.menu_reopen_guard = self.menu_reopen_guard, None
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
            if (abs(event.x_root - sx) > _DRAG_CLICK_THRESHOLD
                    or abs(event.y_root - sy) > _DRAG_CLICK_THRESHOLD):
                self.slider_drag = False
                return
        hit_button = self._hit_button_at(event.x, event.y)
        hit_tab = next((tab for tab in self.production_tabs()
                        if self._in_rect(event.x, event.y, tab["rect"])),
                       None)
        if hit_button is not None:
            if hit_button == guard:
                # The popup this button owns was already open at press-time
                # and got closed by the focus shift in drag_start -- treat
                # that as the toggle's "close" and don't reopen it.
                pass
            else:
                self.top_button_actions()[hit_button]()
        elif hit_tab is not None:
            self.switch_production(hit_tab["id"])
        elif self._in_rect(event.x, event.y, self.refresh_btn_rect()):
            self.refresh()
        elif self.title_query and self._in_rect(event.x, event.y, self.search_clear_rect()):
            # Only hit-tested while a query is active -- the same rect carries
            # the "filter by stream title" hint text when the field is empty,
            # and clicking a hint shouldn't do anything.
            self.clear_title_query()
        elif self.grid_top() - _GRID_HIT_TOP_MARGIN <= event.y < self.height - _GRID_HIT_BOTTOM_MARGIN:
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
        key = item["slider_key"]
        low, high = self.slider_range(key)
        self.set_slider_value(key, self.slider_value(key) + direction * (high - low) * _SLIDER_KEY_STEP)
        self.request_render()
        return "break"

    def clear_focus(self, event=None):
        if self.focus_index is not None:
            self.focus_index = None
            self.request_render()
        return "break"

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
        self._tooltip_after = self.root.after(
            _TOOLTIP_DELAY_MS, lambda: self._show_tooltip(text, root_x, root_y))

    def _show_tooltip(self, text, root_x, root_y):
        self._tooltip_after = None
        colors = self.theme_colors()
        bg = self._hex(self.tint(colors["neutral_btn"]))
        win = self._make_popup_toplevel(bg)
        label = tk.Label(win, text=text, justify="left", font=FONT_UI_SMALL, padx=8, pady=4,
                         relief="solid", borderwidth=1,
                         bg=bg, fg=self._hex(colors["text"]))
        label.pack()
        win.geometry(f"+{root_x + _TOOLTIP_OFFSET_X}+{root_y + _TOOLTIP_OFFSET_Y}")
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

    # The three slider row controls, expressed once as range/read/write so
    # pointer drags (update_slider), keyboard Left/Right (adjust_focus_slider)
    # and the slider drawing in rendering.py all share one definition of what
    # each slider's value means. Adding a fourth slider is then a matter of
    # naming it in grid_layout.SLIDER_BLOCKS and adding a branch to these
    # three, rather than a set_*_from_pointer() plus a keyboard branch plus a
    # bespoke draw call that can each drift from the others.
    @staticmethod
    def slider_range(key):
        if key == "background":
            # Darkness (the inverse of background_alpha) rather than the alpha
            # itself, so the value rises to the right like the other two and
            # the whole track maps onto the range darkness can actually take.
            return MIN_BACKGROUND_DARKNESS, 1.0
        if key == "text":
            return TEXT_SCALE_MIN, TEXT_SCALE_MAX
        return COLUMN_SCALE_MIN, COLUMN_SCALE_MAX

    def slider_value(self, key):
        if key == "background":
            return 1.0 - self.background_alpha
        if key == "text":
            return self.text_scale
        return self.column_scale

    def set_slider_value(self, key, value):
        low, high = self.slider_range(key)
        value = max(low, min(high, value))
        if key == "background":
            self.background_alpha = 1.0 - value
            self._apply_background_alpha()
        elif key == "text":
            self.text_scale = value
        else:
            self.column_scale = value

    def slider_fraction(self, key):
        low, high = self.slider_range(key)
        return (self.slider_value(key) - low) / (high - low)

    def update_slider(self, key, x):
        geometry = self.slider_geometry()[key]
        low, high = self.slider_range(key)
        fraction = max(0.0, min(1.0, (x - geometry["track_start"])
                                / (geometry["track_end"] - geometry["track_start"])))
        self.set_slider_value(key, low + fraction * (high - low))
        self.request_render()
