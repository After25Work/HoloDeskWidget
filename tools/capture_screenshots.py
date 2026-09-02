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

While capturing, the desktop wallpaper is temporarily swapped for a static
solid color and restored afterwards (see frozen_desktop below). The widget's
rounded corners are cut out with real per-pixel color-key transparency (not
alpha), so whatever is on the real desktop shows through those corners; a
moving/live wallpaper would otherwise bleed into the shots and, worse, flicker
across the dozens of frames grabbed back to back for the ticker GIF.

Windows only (uses ctypes user32 calls the same way holowidget/widget.py and
holowidget/single_instance.py already do -- no extra dependency beyond the
Pillow the app already requires). Run it from a normal desktop session (not
over a remote/headless connection) since it moves the real mouse cursor and
sends real clicks.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from holowidget.layout import top_button_rects  # noqa: E402
from holowidget.paths import SW_RESTORE, WINDOW_TITLE  # noqa: E402

OUT_DIR = ROOT / "docs" / "screenshots"
LAUNCH_SCRIPT = ROOT / "start_widget_native.py"

# How long to let the widget's initial refresh() (network fetch of every
# talent's live status) settle before the first screenshot, so main.png
# reflects real data instead of the "unknown" placeholder state.
INITIAL_SETTLE_SECONDS = 5.0
GIF_FRAME_COUNT = 135
GIF_FRAME_INTERVAL = 0.08

# --- Win32 bindings (ctypes only, matching the app's own convention) ---
user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPCWSTR, wintypes.UINT]

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002
SPI_GETDESKWALLPAPER = 0x0073
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
# Native Win32 popup-menu window class -- Tk's tk_popup() on Windows opens a
# real system menu of this class, so it can be located and cropped precisely
# instead of guessing how far the context-menu screenshot needs to extend.
MENU_WINDOW_CLASS = "#32768"


def find_window(name, timeout=10.0, by_class=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(name, None) if by_class else user32.FindWindowW(None, name)
        if hwnd:
            return hwnd
        time.sleep(0.2)
    return None


def get_window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def bring_to_front(hwnd):
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


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
    left, top, right, bottom = top_button_rects(width)[key]
    return (left + right) / 2, (top + bottom) / 2


def click_top_button(hwnd, key, settle=0.3):
    left, top, right, _ = get_window_rect(hwnd)
    cx, cy = button_center(right - left, key)
    click_at(left + cx, top + cy)
    time.sleep(settle)


# --- Desktop wallpaper freeze/restore ---------------------------------

class frozen_desktop:
    """Temporarily swaps the desktop wallpaper for a static solid color.

    The widget cuts its rounded corners out with real color-key
    transparency, so the real desktop shows through there. A live/animated
    wallpaper would bleed into every shot and flicker across the
    GIF_FRAME_COUNT frames grabbed back to back for the ticker GIF, so this
    pins the desktop to one flat color for the duration of the capture and
    always restores whatever was there before, even if capture fails
    partway through.
    """

    COLOR = (18, 18, 24)

    def __enter__(self):
        self.previous = None
        self.temp_path = None
        try:
            buf = ctypes.create_unicode_buffer(260)
            user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 260, buf, 0)
            self.previous = buf.value
            fd, path = tempfile.mkstemp(suffix=".bmp", prefix="holodesk_capture_bg_")
            os.close(fd)
            Image.new("RGB", (256, 256), self.COLOR).save(path, "BMP")
            user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path,
                                          SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
            self.temp_path = path
            time.sleep(0.3)
        except OSError as error:
            print(f"warning: could not freeze the desktop background ({error}); "
                  f"capturing over whatever wallpaper is currently active")
            self.previous = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.previous is not None:
            user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, self.previous,
                                          SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
        if self.temp_path:
            try:
                os.remove(self.temp_path)
            except OSError:
                pass
        return False


# --- Capture steps ------------------------------------------------------

def launch_or_attach():
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
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
    rects = top_button_rects(width).values()
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
    # A blank spot in the info bar (above the talent grid, left of the two
    # sliders) so the generic menu opens rather than a talent's row menu.
    click_at(left + 60, top + 130, button="right")
    time.sleep(0.4)
    menu_hwnd = find_window(MENU_WINDOW_CLASS, timeout=1.0, by_class=True)
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
    for _ in range(GIF_FRAME_COUNT):
        frames.append(grab(rect))
        time.sleep(GIF_FRAME_INTERVAL)
    frames[0].save(
        OUT_DIR / "live_ticker.gif", save_all=True, append_images=frames[1:],
        duration=int(GIF_FRAME_INTERVAL * 1000), loop=0,
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
    with frozen_desktop():
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
