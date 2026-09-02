import ctypes
import time

from .paths import SW_RESTORE, WINDOW_TITLE

_MUTEX_NAME = "hololive-liver-board-native-single-instance"
# Tk/Tcl teardown (root.destroy() -> mainloop() return -> interpreter exit)
# lags a beat behind the window disappearing, so the just-closed process can
# still hold the mutex handle for a moment after its window is gone. Give it
# this long to either show its window or actually let go of the mutex before
# treating this launch as blocked.
_RETRY_TIMEOUT_SECONDS = 2.0
_RETRY_INTERVAL_SECONDS = 0.1

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_user32.FindWindowW.restype = ctypes.c_void_p
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.SetForegroundWindow.restype = ctypes.c_bool
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.GetLastError.restype = ctypes.c_uint32
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.restype = ctypes.c_bool


def _create_mutex():
    mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not mutex:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    return mutex, _kernel32.GetLastError() == 183


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
        hwnd = _user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            _user32.ShowWindow(hwnd, SW_RESTORE)
            _user32.SetForegroundWindow(hwnd)
            raise SystemExit(0)
        if time.monotonic() >= deadline:
            raise SystemExit(0)
        _kernel32.CloseHandle(mutex)
        time.sleep(_RETRY_INTERVAL_SECONDS)
        mutex, already_exists = _create_mutex()
        if not already_exists:
            return
