"""Capture the documentation screenshots/GIF for HoloDeskWidget or VTDeskWidget.

Launches (or attaches to) the running widget with its default settings.json
state, drives it through the mouse/keyboard the same way a user would, and
saves the shots docs/Readme.html and docs/Readme.en.html already reference
into docs/screenshots/:

    main.png / main_en.png             - the full widget, Japanese/English
    buttons.png / buttons_en.png       - the top-right button row, cropped
    context_menu.png / context_menu_en.png - the right-click menu
    live_ticker.gif                    - the live-only view's scrolling
                                          now-playing ticker, animated

Each shot is grabbed with PrintWindow (see capture_window_rgba below) straight
from the widget's (or the context menu's) own window surface, not a
screen-composite ImageGrab -- so a shot is correct regardless of whatever
else happens to be sitting on top of it on the real desktop at that instant.
An earlier version of this script instead covered the whole screen with a
flat-color backdrop window and relied on always keeping the widget above it
via SetWindowPos(HWND_TOPMOST); that broke on machines where other
already-topmost system chrome (touch keyboard, tray flyouts, the Widgets
board) kept re-inserting itself above the widget, permanently hiding it
behind the backdrop no matter how often the z-order was reasserted.
PrintWindow sidesteps the whole fight by reading hwnd's own pixels directly.
The widget's rounded corners -- and the ~20px margin around the whole panel,
see rendering.py's render() -- are cut out with real per-pixel color-key
transparency (not alpha); PrintWindow renders that margin as solid black
rather than blending through to whatever is really behind it, which is what
every shot below shows there instead.

Windows only (uses ctypes user32 calls the same way deskwidget_core/widget.py
and deskwidget_core/single_instance.py already do -- no extra dependency
beyond the Pillow the app already requires). Run it from a normal desktop
session (not over a remote/headless connection) since it moves the real
mouse cursor and sends real clicks.

Targets one variant per run, chosen by an optional command-line argument --
`python tools/capture_screenshots.py` (default) or `... holo` captures Holo
into variants/holo/docs/screenshots/; `... vt` captures VT into
variants/vt/docs/screenshots/. Each run only ever configures one variant's
profile via appconfig.configure() (see VARIANT below), matching how the app
itself is always launched as a single-variant process.
"""

import ctypes
import os
import subprocess
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from PIL import Image

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "holo"
if VARIANT not in ("holo", "vt"):
    raise SystemExit(f"Unknown variant {VARIANT!r} -- expected 'holo' or 'vt'")

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

if VARIANT == "holo":
    from variants.holo.profile import PROFILE  # noqa: E402
else:
    from variants.vt.profile import PROFILE  # noqa: E402

appconfig.configure(PROFILE)

from deskwidget_core import layout  # noqa: E402
from deskwidget_core.config import DEFAULT_SETTINGS  # noqa: E402
from deskwidget_core.paths import WINDOW_TITLE  # noqa: E402
from deskwidget_core.single_instance import bring_to_front, find_window  # noqa: E402

OUT_DIR = ROOT / "variants" / VARIANT / "docs" / "screenshots"
LAUNCH_SCRIPT = ROOT / f"start_widget_{VARIANT}.py"
# Holo always ships a single production (see variants/holo/productions/
# index.json) so its button row never draws the "productions" button; VT
# ships eleven (see variants/vt/productions/index.json) so it always does --
# see layout.button_order(), the same helper GridMixin.top_button_rects()
# calls, so this can never drift from it.
BUTTON_ORDER = layout.button_order(has_multiple_productions=(VARIANT == "vt"))

# How long to let the widget's initial refresh() (network fetch of every
# talent's live status) settle before the first screenshot, so main.png
# reflects real data instead of the "unknown" placeholder state.
INITIAL_SETTLE_SECONDS = 5.0
GIF_FRAME_COUNT = 135
GIF_FRAME_INTERVAL = 0.08

# --- Win32 bindings (ctypes only, matching the app's own convention) ---
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.POINTER(_BitmapInfoHeader), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002
# Width of just the primary display -- what capture_warning_banner below spans.
SM_CXSCREEN = 0
# PW_RENDERFULLCONTENT: without this flag PrintWindow only reflects a plain
# GDI-drawn window, which misses layered/DWM-composited content -- exactly
# what the widget's own -transparentcolor layering (see widget.py) is.
PW_RENDERFULLCONTENT = 0x00000002
# Native Win32 popup-menu window class -- Tk's tk_popup() on Windows opens a
# real system menu of this class, so it can be located and captured precisely
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


def capture_window_rgba(hwnd):
    """Grab hwnd's own current pixels directly off its window surface via
    PrintWindow, not a screen-composite grab -- correct regardless of
    whatever else happens to be sitting on top of it on the real desktop
    right now (see the module docstring for why a screen grab isn't)."""
    left, top, right, bottom = get_window_rect(hwnd)
    width, height = right - left, bottom - top
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    try:
        user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
        info = _BitmapInfoHeader()
        info.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.biWidth = width
        info.biHeight = -height  # negative: top-down rows, matching screen order
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = 0
        buf = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(info), 0)
        return Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)


def button_center(width, key):
    left, top, right, bottom = layout.top_button_rects(width, BUTTON_ORDER)[key]
    return (left + right) / 2, (top + bottom) / 2


def click_top_button(hwnd, key, settle=0.3):
    left, top, right, _ = get_window_rect(hwnd)
    cx, cy = button_center(right - left, key)
    click_at(left + cx, top + cy)
    time.sleep(settle)


# --- On-screen warning banner --------------------------------------------

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


class capture_warning_banner:
    """A always-on-top strip pinned to the very top of the primary screen
    (y=0 through HEIGHT) for the whole capture run, telling whoever is at the
    keyboard not to touch the mouse/keyboard while this script drives real
    input. HEIGHT is derived from (not just hand-verified against)
    DEFAULT_SETTINGS["y"] -- the widget's default top-left corner, see
    deskwidget_core/config.py -- so this can never overlap the widget's own
    default position, and can't silently drift out of sync if that default
    ever changes.

    Purely informational -- capture_window_rgba reads the widget's own pixels
    directly (see the module docstring), so unlike an earlier version of this
    script this banner doesn't need to out-rank anything in z-order for the
    captures themselves to come out correct.
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
        print(f"{appconfig.app_name()} is not running -- launching it...")
        subprocess.Popen([sys.executable, str(LAUNCH_SCRIPT)], cwd=str(ROOT))
    hwnd = find_window(WINDOW_TITLE, timeout=15.0)
    if not hwnd:
        raise RuntimeError(f"{appconfig.app_name()} window did not appear within 15s")
    bring_to_front(hwnd)
    return hwnd


def capture_main(hwnd, suffix):
    rect = get_window_rect(hwnd)
    img = capture_window_rgba(hwnd).convert("RGB")
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
    widget_img = capture_window_rgba(hwnd).convert("RGB")
    # The widget and the menu are two separate top-level windows, so each is
    # captured on its own via PrintWindow and composited by hand onto one
    # canvas sized to their combined bounding box, in screen-coordinate
    # terms, exactly like a screen grab of both would have looked.
    if menu_hwnd:
        ml, mt, mr, mb = get_window_rect(menu_hwnd)
        menu_img = capture_window_rgba(menu_hwnd).convert("RGB")
        box = (min(left, ml), min(top, mt), max(right, mr), max(bottom, mb))
    else:
        menu_img = None
        box = (left, top, right, bottom)
    canvas = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (0, 0, 0))
    canvas.paste(widget_img, (left - box[0], top - box[1]))
    if menu_img is not None:
        canvas.paste(menu_img, (ml - box[0], mt - box[1]))
    canvas.save(OUT_DIR / f"context_menu{suffix}.png")
    print(f"  saved context_menu{suffix}.png")
    press_escape()
    time.sleep(0.2)


def capture_live_ticker_gif(hwnd):
    click_top_button(hwnd, "filter", settle=1.0)  # live-only ON; resizes the window
    frames = []
    durations = []
    for _ in range(GIF_FRAME_COUNT):
        # capture_window_rgba() itself takes non-trivial wall-clock time on
        # top of the sleep below, so the real gap between frames is longer
        # than GIF_FRAME_INTERVAL alone -- record the actual elapsed time per
        # frame instead of assuming it, so the saved GIF's playback speed
        # matches how fast the ticker actually scrolled during capture.
        start = time.monotonic()
        frames.append(capture_window_rgba(hwnd).convert("RGB"))
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
    with capture_warning_banner():
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
