"""Capture the documentation screenshots/GIF for HoloDeskWidget.

Launches (or attaches to) the running widget with its default settings.json
state, drives it through the mouse/keyboard the same way a user would, and
saves the shots docs/Readme.html and docs/Readme.en.html already reference
into docs/screenshots/:

    main.png / main_en.png             - the full widget, Japanese/English
    buttons.png / buttons_en.png       - the top-right button row, cropped
    context_menu.png / context_menu_en.png - the right-click menu
    live_ticker.gif                    - the live-only view's scrolling
                                          now-playing ticker, animated

While capturing, the whole screen is covered with a flat-color topmost window
pinned just below the widget (see opaque_backdrop below) and removed
afterwards. The widget's rounded corners -- and the ~20px margin around the
whole panel, see rendering.py's render() -- are cut out with real per-pixel
color-key transparency (not alpha), so whatever is on the real screen shows
through there; without the backdrop that would be the live desktop (icons,
taskbar, any other window sitting behind it), bleeding into every shot and,
worse, flickering across the dozens of frames grabbed back to back for the
ticker GIF.

Windows only (uses ctypes user32 calls the same way deskwidget_core/widget.py
and deskwidget_core/single_instance.py already do -- no extra dependency
beyond the Pillow the app already requires). Run it from a normal desktop
session (not over a remote/headless connection) since it moves the real
mouse cursor and sends real clicks.

Targets the Holo variant specifically (see appconfig.configure() below) --
re-point PROFILE/LAUNCH_SCRIPT/OUT_DIR at variants/vt if VT ever needs its
own screenshot set.
"""

import ctypes
import os
import subprocess
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

# Must happen before any window/screen coordinates are touched below. Without
# this, this process stays in Windows' legacy DPI-virtualized mode, where
# GetWindowRect() and ImageGrab.grab() disagree on what a pixel is on any
# display scaled above 100% -- the resulting bbox drifts from the widget's
# real on-screen footprint, so captures bleed in whatever sits just outside
# it (taskbar, other windows) instead of the backdrop color.
#
# ctypes.windll (unlike oledll) never raises on a failed HRESULT, so a plain
# `SetProcessDpiAwareness(2)` call that fails silently returns an error code
# instead of raising -- e.g. E_ACCESSDENIED, which Windows returns whenever
# an awareness mode was already set for this process (by an inherited
# manifest, or by this exact call happening to run twice), whether or not
# that mode already happens to be per-monitor. So check what's actually in
# effect first with GetProcessDpiAwareness rather than reacting to the
# HRESULT alone -- otherwise an already-correct per-monitor process would
# hit the "failed" branch below and get needlessly downgraded to the
# coarser SetProcessDPIAware() fallback.
_PROCESS_PER_MONITOR_DPI_AWARE = 2
try:
    _current_awareness = ctypes.c_int(-1)
    ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(_current_awareness))
    if _current_awareness.value != _PROCESS_PER_MONITOR_DPI_AWARE:
        if ctypes.windll.shcore.SetProcessDpiAwareness(_PROCESS_PER_MONITOR_DPI_AWARE) != 0:  # not S_OK
            ctypes.windll.user32.SetProcessDPIAware()
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deskwidget_core import appconfig  # noqa: E402
from variants.holo.profile import PROFILE  # noqa: E402

appconfig.configure(PROFILE)

from deskwidget_core import layout  # noqa: E402
from deskwidget_core.config import DEFAULT_SETTINGS  # noqa: E402
from deskwidget_core.paths import WINDOW_TITLE  # noqa: E402
from deskwidget_core.single_instance import bring_to_front, find_window  # noqa: E402

OUT_DIR = ROOT / "variants" / "holo" / "docs" / "screenshots"
LAUNCH_SCRIPT = ROOT / "start_widget_holo.py"
# The Holo variant always ships a single production (see
# variants/holo/productions/index.json), so its button row never draws the
# "productions" button -- see layout.button_order(), the same helper
# GridMixin.top_button_rects() calls, so this can never drift from it.
BUTTON_ORDER = layout.button_order(has_multiple_productions=False)

# How long to let the widget's initial refresh() (network fetch of every
# talent's live status) settle before the first screenshot, so main.png
# reflects real data instead of the "unknown" placeholder state.
INITIAL_SETTLE_SECONDS = 5.0
GIF_FRAME_COUNT = 135
GIF_FRAME_INTERVAL = 0.08

# --- Win32 bindings (ctypes only, matching the app's own convention) ---
user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002
# Width of just the primary display -- what capture_warning_banner below
# spans (unlike opaque_backdrop, which covers every monitor).
SM_CXSCREEN = 0
# Bounding box of the whole multi-monitor desktop, not just the primary
# display -- what opaque_backdrop below covers.
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
# For re-asserting the widget's z-order above opaque_backdrop below, and
# restoring it afterwards. SetWindowPos(HWND_TOPMOST/HWND_NOTOPMOST) isn't
# subject to the foreground-lock restrictions SetForegroundWindow is, so it
# reliably reorders z even across processes without needing (or granting)
# input focus.
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
# For reading the widget's *current* WS_EX_TOPMOST bit before touching it, so
# opaque_backdrop can restore whatever state it found rather than always
# clearing topmost afterwards (which would un-pin a window the user, or
# settings.json, had deliberately pinned before this script ran).
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
# Native Win32 popup-menu window class -- Tk's tk_popup() on Windows opens a
# real system menu of this class, so it can be located and cropped precisely
# instead of guessing how far the context-menu screenshot needs to extend.
MENU_WINDOW_CLASS = "#32768"


def get_window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def click_at(x, y, button="left"):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    down, up = (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left" \
        else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    user32.mouse_event(down, 0, 0, 0, None)
    time.sleep(0.05)
    user32.mouse_event(up, 0, 0, 0, None)


def press_escape():
    user32.keybd_event(VK_ESCAPE, 0, 0, None)
    time.sleep(0.03)
    user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, None)


def grab(bbox):
    return ImageGrab.grab(bbox=bbox, all_screens=True)


def button_center(width, key):
    left, top, right, bottom = layout.top_button_rects(width, BUTTON_ORDER)[key]
    return (left + right) / 2, (top + bottom) / 2


def click_top_button(hwnd, key, settle=0.3):
    left, top, right, _ = get_window_rect(hwnd)
    cx, cy = button_center(right - left, key)
    click_at(left + cx, top + cy)
    time.sleep(settle)


# --- Screen backdrop ---------------------------------------------------

def _hex_to_rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _create_overlay_window(width, height, x, y, bg):
    """Create a topmost, borderless, flat-color Tk window covering the given
    rect. Returns the Tk root, or None (after printing a warning) if Tk setup
    fails at any point -- including partway through (e.g. geometry()/update()
    raising after tk.Tk() itself already succeeded), in which case the
    partially-built root is destroyed here before returning None, so a
    caller that only ever destroys a non-None self.root can't inherit an
    unreferenced, undestroyable window left on screen.
    """
    root = None
    try:
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=bg)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.update()
        return root
    except tk.TclError as error:
        print(f"warning: could not create a capture overlay window ({error})")
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        return None


def _destroy_quietly(root):
    if root is not None:
        try:
            root.destroy()
        except tk.TclError:
            pass


class opaque_backdrop:
    """Covers the whole (possibly multi-monitor) screen with a flat-color,
    topmost, borderless window for the duration of the capture, then
    destroys it.

    The widget cuts its rounded corners -- and the ~20px margin around the
    whole panel, see rendering.py's render() -- out with real per-pixel
    color-key transparency, so whatever is on the real screen shows through
    there. An earlier version of this script tried to handle that by
    swapping the desktop wallpaper for a solid color and toggling "Show
    desktop icons" via a WM_COMMAND sent to Progman, but that toggle turned
    out to be a silent no-op on current Windows builds (SendMessageW returns
    without changing anything), and neither trick hides a real window that
    happens to be sitting behind the widget (e.g. an always-on-top overlay
    from some other app). A real covering window sidesteps both problems: it
    hides everything underneath regardless of what it is, and this class
    always destroys it on exit, even if capture fails partway through, so
    the user's desktop is never left covered.

    Entered *before* capture_warning_banner in main() -- see the note there:
    window-creation order alone gives the banner the correct final z-order
    without needing a second re-assert pass just for it.
    """

    COLOR = "#121218"

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.root = None
        self._was_topmost = False

    def __enter__(self):
        x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        self.root = _create_overlay_window(width, height, x, y, self.COLOR)
        if self.root is None:
            print("warning: capturing over whatever is currently on screen")
        # Creating the backdrop just made it the newest topmost window, which
        # HWND_TOPMOST places at the very top of the topmost band -- above
        # the widget. bring_to_front's SetForegroundWindow can't reliably
        # undo that here (Windows can silently refuse a background process
        # foregrounding a *different* process's window), so reclaim the top
        # with a direct z-order call instead, which carries no such
        # restriction. Remember whatever topmost state the widget already
        # had (a user, or settings.json, may have deliberately pinned it)
        # so __exit__ can put it back rather than always clearing it.
        self._was_topmost = bool(user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
        if not user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE):
            print("warning: could not bring the widget above the capture backdrop; "
                  "screenshots may show the backdrop instead of the widget")
        self._wait_for_composited(x, y)
        return self

    def _wait_for_composited(self, x, y):
        # DWM needs a moment to actually composite the new window before a
        # screen grab reflects it -- without this, the very first capture can
        # win the race and still show whatever was on screen a frame earlier.
        # Poll the backdrop's own top-left corner (outside the widget's
        # default footprint -- see capture_warning_banner's HEIGHT note)
        # for its actual color instead of guessing a fixed duration, so this
        # only waits as long as the real machine needs, rather than a flat
        # 0.3s that a slower/loaded machine could lose the race against.
        if self.root is None:
            return
        target = _hex_to_rgb(self.COLOR)
        deadline = time.monotonic() + 2.0
        try:
            while time.monotonic() < deadline:
                pixel = grab((x, y, x + 1, y + 1)).getpixel((0, 0))
                if pixel[:3] == target:
                    return
                time.sleep(0.05)
        except OSError:
            pass
        time.sleep(0.3)

    def __exit__(self, exc_type, exc, tb):
        _destroy_quietly(self.root)
        if not self._was_topmost:
            user32.SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return False


class capture_warning_banner:
    """A always-on-top strip pinned to the very top of the primary screen
    (y=0 through HEIGHT) for the whole capture run, telling whoever is at the
    keyboard not to touch the mouse/keyboard while this script drives real
    input. HEIGHT is derived from (not just hand-verified against)
    DEFAULT_SETTINGS["y"] -- the widget's default top-left corner, see
    deskwidget_core/config.py -- so this can never overlap the widget's own
    default position and bleed into any grabbed region, and can't silently
    drift out of sync if that default ever changes.

    Entered *after* opaque_backdrop in main() so it's the newest topmost
    window and lands above the backdrop (which would otherwise cover this
    banner's strip too, hiding the one warning telling the user not to touch
    the keyboard while this script drives real input).
    """

    HEIGHT = min(32, DEFAULT_SETTINGS["y"] - 8)
    BG = "#c0392b"
    FG = "white"
    TEXT = ("自動操作でスクリーンショットを撮影中です。"
            "完了するまでマウス・キーボードに触れないでください。")

    def __enter__(self):
        width = user32.GetSystemMetrics(SM_CXSCREEN)
        self.root = _create_overlay_window(width, self.HEIGHT, 0, 0, self.BG)
        if self.root is not None:
            tk.Label(self.root, text=self.TEXT, bg=self.BG, fg=self.FG,
                     font=("Yu Gothic UI", 11, "bold")).pack(expand=True)
            self.root.update()
        else:
            print("warning: capturing without the on-screen keyboard/mouse warning")
        return self

    def __exit__(self, exc_type, exc, tb):
        _destroy_quietly(self.root)
        return False


# --- Capture steps ------------------------------------------------------

def launch_or_attach():
    hwnd = find_window(WINDOW_TITLE, timeout=0)
    if not hwnd:
        print("HoloDeskWidget is not running -- launching it...")
        subprocess.Popen([sys.executable, str(LAUNCH_SCRIPT)], cwd=str(ROOT))
    hwnd = find_window(WINDOW_TITLE, timeout=15.0)
    if not hwnd:
        raise RuntimeError("HoloDeskWidget window did not appear within 15s")
    bring_to_front(hwnd)
    return hwnd


def capture_main(hwnd, suffix):
    rect = get_window_rect(hwnd)
    img = grab(rect)
    img.save(OUT_DIR / f"main{suffix}.png")
    print(f"  saved main{suffix}.png")
    return rect, img


def capture_buttons(width, full_img, suffix):
    rects = layout.top_button_rects(width, BUTTON_ORDER).values()
    pad = 8
    box = (
        min(r[0] for r in rects) - pad,
        min(r[1] for r in rects) - pad,
        max(r[2] for r in rects) + pad,
        max(r[3] for r in rects) + pad,
    )
    full_img.crop(box).save(OUT_DIR / f"buttons{suffix}.png")
    print(f"  saved buttons{suffix}.png")


def capture_context_menu(hwnd, suffix):
    left, top, right, bottom = get_window_rect(hwnd)
    # A blank spot in the info bar (above the talent grid, left of the
    # slider row and above the title-filter row) so the generic menu opens
    # rather than a talent's row menu.
    click_at(left + 60, top + 130, button="right")
    time.sleep(0.4)
    menu_hwnd = find_window(class_name=MENU_WINDOW_CLASS, timeout=1.0)
    if menu_hwnd:
        ml, mt, mr, mb = get_window_rect(menu_hwnd)
        box = (min(left, ml), min(top, mt), max(right, mr), max(bottom, mb))
    else:
        box = (left, top, right + 220, bottom)
    grab(box).save(OUT_DIR / f"context_menu{suffix}.png")
    print(f"  saved context_menu{suffix}.png")
    press_escape()
    time.sleep(0.2)


def capture_live_ticker_gif(hwnd):
    click_top_button(hwnd, "filter", settle=1.0)  # live-only ON; resizes the window
    rect = get_window_rect(hwnd)
    frames = []
    durations = []
    for _ in range(GIF_FRAME_COUNT):
        # grab() itself takes non-trivial wall-clock time on top of the
        # sleep below, so the real gap between frames is longer than
        # GIF_FRAME_INTERVAL alone -- record the actual elapsed time per
        # frame instead of assuming it, so the saved GIF's playback speed
        # matches how fast the ticker actually scrolled during capture.
        start = time.monotonic()
        frames.append(grab(rect))
        time.sleep(GIF_FRAME_INTERVAL)
        durations.append(int((time.monotonic() - start) * 1000))
    frames[0].save(
        OUT_DIR / "live_ticker.gif", save_all=True, append_images=frames[1:],
        duration=durations, loop=0,
    )
    print(f"  saved live_ticker.gif ({len(frames)} frames)")
    click_top_button(hwnd, "filter", settle=1.0)  # back to the default (all talents)


def main():
    if os.name != "nt":
        raise SystemExit("This capture script only runs on Windows.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    hwnd = launch_or_attach()
    print(f"Letting the widget's initial data refresh settle "
          f"({INITIAL_SETTLE_SECONDS:.0f}s)...")
    time.sleep(INITIAL_SETTLE_SECONDS)

    lang_toggled = False
    # opaque_backdrop first, capture_warning_banner second: each newly
    # created topmost window lands above every topmost window that already
    # existed (see opaque_backdrop's own z-order note), so entering the
    # banner last is what keeps it visible above the backdrop for the whole
    # run instead of getting buried under it.
    with opaque_backdrop(hwnd), capture_warning_banner():
        print("Capturing Japanese (default) screenshots...")
        rect, img = capture_main(hwnd, "")
        capture_buttons(rect[2] - rect[0], img, "")
        capture_context_menu(hwnd, "")

        print("Capturing the live-only ticker GIF...")
        capture_live_ticker_gif(hwnd)

        try:
            print("Switching to English...")
            click_top_button(hwnd, "lang", settle=0.5)
            lang_toggled = True
            rect, img = capture_main(hwnd, "_en")
            capture_buttons(rect[2] - rect[0], img, "_en")
            capture_context_menu(hwnd, "_en")
        finally:
            if lang_toggled:
                print("Switching back to Japanese (default)...")
                click_top_button(hwnd, "lang", settle=0.5)

    print(f"\nDone. Files written to {OUT_DIR}")
    print("Note: live_ticker.gif only shows visible scrolling if at least one "
          "tracked talent is actually live with a long enough title right now -- "
          "re-run later if it looks static.")


if __name__ == "__main__":
    main()
