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
from .talents import load_targets
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
        self.font_family = settings["font_family"]
        set_font_family(self.font_family)
        self.dark_mode = settings["dark_mode"]
        self.live_only = settings["live_only"]
        self.text_scale = settings["text_scale"]
        self.suppress_next_click = False
        # Snapshot (by top_button_rects() key) of a menu-owning button that
        # was already open at drag_start()'s press-time -- see the note in
        # drag_start() for why click() needs this to avoid a focus-shift
        # closing a popup only to have the same click's release reopen it.
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
        }

    def close(self):
        save_settings(self.current_settings())
        if self.root.winfo_exists():
            self.root.destroy()
