import ctypes
import time

from .paths import SW_RESTORE, WINDOW_TITLE
from .win32 import bind, kernel32 as _kernel32, user32 as _user32

# Derived from WINDOW_TITLE (not a bare fixed string) so a sibling app built
# from the same codebase under a different name -- e.g. VTDeskWidget, whose
# WINDOW_TITLE is "VTDeskWidget::SingleInstance" -- doesn't grab the same
# system-wide named mutex and block this one (or vice versa) just because
# neither app's own window can be found under the other's title.
_MUTEX_NAME = f"{WINDOW_TITLE}-native-single-instance"
# Tk/Tcl teardown (root.destroy() -> mainloop() return -> interpreter exit)
# lags a beat behind the window disappearing, so the just-closed process can
# still hold the mutex handle for a moment after its window is gone. Give it
# this long to either show its window or actually let go of the mutex before
# treating this launch as blocked.
_RETRY_TIMEOUT_SECONDS = 2.0
_RETRY_INTERVAL_SECONDS = 0.1

bind(_user32.FindWindowW, [ctypes.c_wchar_p, ctypes.c_wchar_p], ctypes.c_void_p)
bind(_user32.ShowWindow, [ctypes.c_void_p, ctypes.c_int], ctypes.c_int)
bind(_user32.SetForegroundWindow, [ctypes.c_void_p], ctypes.c_bool)
bind(_kernel32.CreateMutexW, None, ctypes.c_void_p)
bind(_kernel32.GetLastError, None, ctypes.c_uint32)
bind(_kernel32.CloseHandle, [ctypes.c_void_p], ctypes.c_bool)


def _create_mutex():
    mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not mutex:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    return mutex, _kernel32.GetLastError() == 183


def bring_to_front(hwnd):
    """Restore and foreground a window handle. Shared with
    tools/capture_screenshots.py, which needs the same sequence to bring the
    widget forward before driving it."""
    _user32.ShowWindow(hwnd, SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)


def find_window(title=None, class_name=None, timeout=10.0, poll_interval=0.2):
    """Poll FindWindowW for a window by title or class until it appears or
    `timeout` elapses (timeout=0 checks once, no polling), returning None on
    timeout. Shared with tools/capture_screenshots.py, which looks up both
    the widget's own window (by title) and its native right-click menu (by
    class) this same way."""
    deadline = time.monotonic() + timeout
    while True:
        hwnd = _user32.FindWindowW(class_name, title)
        if hwnd:
            return hwnd
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_interval)


def ensure_single_instance():
    # A named Win32 mutex (not a lockfile) so a crashed process can't leave a
    # stale lock behind — the OS releases the mutex automatically. Call this
    # only from the entry point's `__main__` guard: importing this module
    # must stay side-effect-free so the app is importable/testable without
    # racing a real running instance.
    mutex, already_exists = _create_mutex()
    if not already_exists:
        return

    # The name is still taken. That's either a genuinely running instance,
    # or the previous instance closing its window and exiting the process
    # right as we start — in which case its mutex handle hasn't been
    # released yet. Poll for the real window, and retry the mutex in between
    # so a lingering handle from a just-closed process doesn't get mistaken
    # for a live one.
    deadline = time.monotonic() + _RETRY_TIMEOUT_SECONDS
    while True:
        hwnd = find_window(WINDOW_TITLE, timeout=0)
        if hwnd:
            bring_to_front(hwnd)
            raise SystemExit(0)
        if time.monotonic() >= deadline:
            raise SystemExit(0)
        _kernel32.CloseHandle(mutex)
        time.sleep(_RETRY_INTERVAL_SECONDS)
        mutex, already_exists = _create_mutex()
        if not already_exists:
            return
