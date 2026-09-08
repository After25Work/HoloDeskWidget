"""Refresh HoloDeskWidget's documentation screenshots with the app's default
settings.json state, then put back whatever settings.json held before.

tools/capture_screenshots.py drives whichever widget instance is already
running (or launches one) with whatever settings.json it finds on disk --
great for a real user, but it means the shots can end up reflecting a
developer's own window position/theme/language instead of the default state
docs/Readme*.html actually documents. This wrapper:

  1. closes any already-running instance (so a stale process holding old
     settings in memory can't shadow the reset file below),
  2. moves settings.json aside so the next launch falls back to
     deskwidget_core.config.DEFAULT_SETTINGS whole-cloth,
  3. runs the real capture script,
  4. closes the instance it started, and
  5. restores the original settings.json untouched (or removes the file
     again if there wasn't one to begin with).

Mirrors how capture_screenshots.py itself covers/uncovers the screen with a
backdrop window around the shots -- same idea, applied to settings.json.

Windows only, same as capture_screenshots.py. Only targets the Holo variant
(the only one capture_screenshots.py currently knows how to drive).
"""

import ctypes
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from deskwidget_core import appconfig  # noqa: E402
from variants.holo.profile import PROFILE  # noqa: E402

appconfig.configure(PROFILE)

from deskwidget_core.paths import SETTINGS_PATH, WINDOW_TITLE  # noqa: E402
from deskwidget_core.single_instance import bring_to_front, find_window  # noqa: E402

CAPTURE_SCRIPT = ROOT / "tools" / "capture_screenshots.py"
CLOSE_TIMEOUT_SECONDS = 5.0

# Alt+F4, not a raw WM_CLOSE: deskwidget_core/widget.py binds this exact
# keystroke to its own close() (see the comment there) specifically because
# Windows' default WM_CLOSE handling for this overrideredirect window
# destroys it directly and skips close() entirely -- no tray-icon teardown,
# no settings save. A posted WM_CLOSE would hit exactly that default path,
# so this simulates the keystroke Tk's binding actually listens for instead.
VK_MENU = 0x12
VK_F4 = 0x73
KEYEVENTF_KEYUP = 0x0002
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]


def close_widget_if_running():
    """Best-effort close: brings the widget to the foreground and sends
    Alt+F4, then waits for the window to disappear. A no-op if nothing is
    running. Prints a warning (rather than failing silently) if the window
    is still there when CLOSE_TIMEOUT_SECONDS runs out -- main()'s callers
    rely on the widget actually being gone before they touch settings.json
    or launch a fresh instance, so a caller ignoring that warning could
    otherwise silently end up capturing against a stale, already-running
    instance's settings instead of the defaults this script exists to reset
    to."""
    hwnd = find_window(WINDOW_TITLE, timeout=0)
    if not hwnd:
        return
    bring_to_front(hwnd)
    time.sleep(0.2)
    _user32.keybd_event(VK_MENU, 0, 0, None)
    _user32.keybd_event(VK_F4, 0, 0, None)
    _user32.keybd_event(VK_F4, 0, KEYEVENTF_KEYUP, None)
    _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
    deadline = time.monotonic() + CLOSE_TIMEOUT_SECONDS
    while find_window(WINDOW_TITLE, timeout=0) and time.monotonic() < deadline:
        time.sleep(0.2)
    if find_window(WINDOW_TITLE, timeout=0):
        print(f"warning: HoloDeskWidget did not close within {CLOSE_TIMEOUT_SECONDS:.0f}s; "
              f"it may still be running with its own settings, which the next step could "
              f"end up capturing instead of the defaults")


def main():
    if sys.platform != "win32":
        raise SystemExit("This only runs on Windows.")

    print("Closing any already-running HoloDeskWidget instance...")
    close_widget_if_running()

    backup_dir = Path(tempfile.mkdtemp(prefix="holodesk_settings_backup_"))
    backup_path = backup_dir / "settings.json"
    had_settings = SETTINGS_PATH.exists()
    if had_settings:
        shutil.move(str(SETTINGS_PATH), str(backup_path))
        print("Set aside your current settings.json (restoring it when done).")
    else:
        print("No existing settings.json -- already starting from defaults.")

    try:
        print("Capturing with default settings...")
        subprocess.run([sys.executable, str(CAPTURE_SCRIPT)], cwd=str(ROOT), check=True)
    finally:
        print("Closing the widget instance this launched...")
        close_widget_if_running()
        if had_settings:
            shutil.move(str(backup_path), str(SETTINGS_PATH))
            print("Restored your original settings.json.")
        else:
            SETTINGS_PATH.unlink(missing_ok=True)
        backup_dir.rmdir()


if __name__ == "__main__":
    main()
