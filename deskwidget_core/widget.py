import ctypes
import time
import tkinter as tk
from typing import Optional, Tuple

from .config import (
    DEFAULT_HEIGHT,
    DEFAULT_SETTINGS,
    MAX_HEIGHT,
    MAX_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
    MIN_WINDOW_ALPHA,
    load_settings,
    save_settings,
)
from .fonts import set_font_family
from .grid_layout import GridMixin
from .interaction import InteractionMixin
from .menus import MenuMixin
from .paths import WINDOW_TITLE
from .rendering import RenderingMixin
from .refresh import RefreshMixin
from .strings import english_name
from .talents import (
    ALL_PRODUCTION,
    ALL_PRODUCTION_ID,
    load_productions,
    load_targets,
    production_display_name,
)
from .theme import KEY_COLOR

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


class LayeredWidget(RenderingMixin, GridMixin, MenuMixin, InteractionMixin, RefreshMixin):
    def __init__(self):
        self.productions = load_productions()
        self._productions_by_id = {p["id"]: p for p in self.productions}
        # Per-production talent/live-state data, lazily populated on first
        # visit to a tab (see _production_slot()) and kept around after
        # that — switching back to a previously-viewed tab shows its
        # last-known state immediately instead of blanking to "unknown".
        # self.targets/states/channel_urls/live_urls/live_titles below are
        # properties reading whichever slot is active_production right now.
        self.production_data = {}
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
        self.font_family = settings["font_family"]
        set_font_family(self.font_family)
        self.dark_mode = settings["dark_mode"]
        self.live_only = settings["live_only"]
        self.text_scale = settings["text_scale"]
        self.active_production = (settings["active_production"]
            if settings["active_production"] in self._valid_production_ids()
            else self.productions[0]["id"])
        # Which productions show as tabs (and count toward the "All" tab).
        # Falls back to every loaded production whenever the saved list is
        # empty or has nothing left that matches the current manifest, so a
        # first run (or one where a production was since removed) never
        # starts with an empty tab strip.
        valid_ids = {p["id"] for p in self.productions}
        saved_enabled = [pid for pid in settings["enabled_productions"] if pid in valid_ids]
        self.enabled_productions = set(saved_enabled) if saved_enabled else set(valid_ids)
        self.suppress_next_click = False
        self.menu_reopen_guard: Optional[str] = None
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
        self.font_win: Optional[tk.Toplevel] = None
        self.productions_win: Optional[tk.Toplevel] = None
        self._production_menu_vars = []
        self.surface: Optional[tk.Label] = None
        self.drag_origin: Optional[Tuple[int, int, int, int]] = None
        self.resize_origin: Optional[Tuple[int, int, int, int, int, int]] = None
        self.resize_drag = False
        self.active_resize_edge: Optional[str] = None
        self.pending_position: Optional[Tuple[int, int]] = None
        # Fullscreen (fill-the-screen) toggle state. _pre_fullscreen holds the
        # (width, height, x, y) to restore on exit -- None whenever
        # is_fullscreen is False, so current_settings() can tell there's
        # nothing to substitute in.
        self.is_fullscreen = False
        self._pre_fullscreen: Optional[Tuple[int, int, int, int]] = None
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

    def has_multiple_productions(self):
        # Drives every "is there a tab strip / productions picker at all"
        # branch across grid_layout.py/rendering.py/menus.py -- a variant
        # shipped with a single-entry productions/index.json (see talents.py)
        # behaves exactly like the old single-talent-list app, with no
        # per-app special-casing needed anywhere else.
        return len(self.productions) > 1

    def _production_slot(self, prod_id):
        slot = self.production_data.get(prod_id)
        if slot is None:
            targets = load_targets(self._productions_by_id[prod_id])
            slot = {
                "targets": targets,
                "states": {name: "unknown" for name, _, _, _ in targets},
                "channel_urls": {},
                "live_urls": {},
                "live_titles": {},
            }
            self.production_data[prod_id] = slot
        return slot

    def _valid_production_ids(self):
        return set(self._productions_by_id) | {ALL_PRODUCTION_ID}

    def _visible_productions(self):
        # self.productions filtered down to the ones the user has left
        # enabled (see open_productions_menu()/set_production_enabled()),
        # in the same order as the manifest -- what shows as a tab, and what
        # the "All" tab aggregates.
        return [p for p in self.productions if p["id"] in self.enabled_productions]

    def _tab_productions(self):
        # Visible productions plus the pseudo "All" tab (ALL_PRODUCTION_ID)
        # that aggregates their talents into one list, shown first so it
        # reads as "everything" rather than one production among equals.
        return [ALL_PRODUCTION] + self._visible_productions()

    def _merge_all_slots(self, key):
        # Dict fields (states/channel_urls/live_urls/live_titles) merged
        # fresh on every access rather than cached, so this always reflects
        # whatever the per-production refresh threads have written into
        # self.production_data[prod_id] directly (see the note below) instead
        # of a stale snapshot from whenever the "All" tab was last entered.
        merged = {}
        for production in self._visible_productions():
            merged.update(self._production_slot(production["id"])[key])
        return merged

    def _all_targets(self):
        # Retags each talent's unit with its own production's display name,
        # so build_grid_layout()'s per-unit grouping renders one category per
        # production here instead of merging same-named units (e.g. "JP")
        # across different productions into one section.
        targets = []
        for production in self._visible_productions():
            label = production_display_name(production, self.lang)
            slot = self._production_slot(production["id"])
            targets.extend((name, slug, url, label) for name, slug, url, _unit in slot["targets"])
        return targets

    # These five reflect whichever production is active_production right
    # now, for every part of the app (rendering, click handling, tooltips,
    # open_target) that only ever cares about "what's currently on screen".
    # When active_production is ALL_PRODUCTION_ID they instead merge every
    # real production's data on the fly (see _all_targets()/_merge_all_slots()
    # above). The refresh machinery (refresh/refresh_worker/check_one)
    # instead threads an explicit prod_id through and reads/writes
    # self.production_data[prod_id] directly, so a background refresh
    # started before a tab switch can never write into the wrong tab's data
    # once the user has switched away from it.
    @property
    def targets(self):
        if self.active_production == ALL_PRODUCTION_ID:
            return self._all_targets()
        return self._production_slot(self.active_production)["targets"]

    def _slot_field(self, key):
        if self.active_production == ALL_PRODUCTION_ID:
            return self._merge_all_slots(key)
        return self._production_slot(self.active_production)[key]

    @property
    def states(self):
        return self._slot_field("states")

    @property
    def channel_urls(self):
        return self._slot_field("channel_urls")

    @property
    def live_urls(self):
        return self._slot_field("live_urls")

    @property
    def live_titles(self):
        return self._slot_field("live_titles")

    def _visible_talent_labels(self, targets=None, states=None):
        # The exact bullet+name text render()'s talent loop draws, without
        # the color/title bookkeeping it also needs — used by compute_grid()
        # to check how large the shared label font (see _shared_label_size())
        # could get before the widest visible name stops fitting the grid's
        # fixed column pitch, which in turn caps how far rows may grow (see
        # the note in compute_grid()).
        labels = []
        # Read once up front, not per iteration -- see the matching note in
        # grid_layout.py's build_grid_layout() for why looping over the
        # states property directly is an O(N^2) trap on the "All" tab.
        # compute_grid() already has its own merged copy on hand and passes
        # it straight through so this doesn't re-merge a third time.
        targets = self.targets if targets is None else targets
        states = self.states if states is None else states
        for name, slug, _url, _unit in targets:
            state = states[name]
            if self.live_only and state != "live":
                continue
            bullet = "● " if state == "live" else "! " if state == "error" else "• "
            display_name = name if self.lang == "ja" else english_name(slug)
            labels.append(bullet + display_name)
        return labels

    def switch_production(self, prod_id):
        if prod_id == self.active_production or prod_id not in self._valid_production_ids():
            return
        self.active_production = prod_id
        if prod_id == ALL_PRODUCTION_ID:
            for production in self._visible_productions():
                self._production_slot(production["id"])
        else:
            self._production_slot(prod_id)
        self.focus_index = None
        if self.live_only:
            self.fit_height()
        self.request_render()
        self.refresh()

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

    def toggle_topmost(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.render()

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()
        self.render()

    def enter_fullscreen(self):
        if self.is_fullscreen:
            return
        self._pre_fullscreen = (self.width, self.height,
                                self.root.winfo_x(), self.root.winfo_y())
        # Clamped to MAX_WIDTH/MAX_HEIGHT (4K) like every other resize, so a
        # screen larger than that doesn't hand the panel a size nothing else
        # in this file was ever laid out to expect.
        self.width = max(MIN_WIDTH, min(MAX_WIDTH, self.root.winfo_screenwidth()))
        self.height = max(MIN_HEIGHT, min(MAX_HEIGHT, self.root.winfo_screenheight()))
        self.is_fullscreen = True
        self.root.geometry(f"{self.width}x{self.height}+0+0")

    def exit_fullscreen(self):
        if not self.is_fullscreen or self._pre_fullscreen is None:
            return
        self.width, self.height, x, y = self._pre_fullscreen
        self.is_fullscreen = False
        self._pre_fullscreen = None
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

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

    def current_settings(self):
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        except tk.TclError:
            x, y = DEFAULT_SETTINGS["x"], DEFAULT_SETTINGS["y"]
        width, height = self.width, self.height
        if self.is_fullscreen and self._pre_fullscreen is not None:
            # Persist the size/position from before the fullscreen toggle, not
            # the maximized dimensions themselves -- otherwise closing while
            # fullscreen would make every future launch start maximized too.
            width, height, x, y = self._pre_fullscreen
        return {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "background_alpha": self.background_alpha,
            "lang": self.lang,
            "topmost": self.topmost,
            "theme_index": self.theme_index,
            "font_family": self.font_family,
            "dark_mode": self.dark_mode,
            "live_only": self.live_only,
            "text_scale": self.text_scale,
            "active_production": self.active_production,
            "enabled_productions": [p["id"] for p in self.productions if p["id"] in self.enabled_productions],
        }

    def close(self):
        save_settings(self.current_settings())
        if self.root.winfo_exists():
            self.root.destroy()
