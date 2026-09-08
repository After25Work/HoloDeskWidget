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

Mirrors how capture_screenshots.py itself freezes/restores the desktop
wallpaper around the shots -- same idea, applied to settings.json.

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
from deskwidget_core.single_instance import find_window  # noqa: E402

CAPTURE_SCRIPT = ROOT / "tools" / "capture_screenshots.py"
CLOSE_TIMEOUT_SECONDS = 5.0

WM_CLOSE = 0x0010
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]


def close_widget_if_running():
    """Best-effort close: posts WM_CLOSE to the widget's window (the same
    message Windows sends on Alt+F4) and waits for the window to disappear.
    A no-op if nothing is running."""
    hwnd = find_window(WINDOW_TITLE, timeout=0)
    if not hwnd:
        return
    _user32.PostMessageW(hwnd, WM_CLOSE, None, None)
    deadline = time.monotonic() + CLOSE_TIMEOUT_SECONDS
    while find_window(WINDOW_TITLE, timeout=0) and time.monotonic() < deadline:
        time.sleep(0.2)


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
