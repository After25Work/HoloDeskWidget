"""Shared user32/kernel32 ctypes handles and the argtypes/restype binding
helper used by every module here that talks to Win32 directly (rather than
through tkinter) -- widget.py, single_instance.py, and tray.py each declared
their own WinDLL handle and repeated the same "assign argtypes, then restype"
pair per function; this just gives the mechanical part of that one home so
the per-call bindings in each module stay the only thing that varies.

tray.py keeps its own separate shell32 handle (Shell_NotifyIcon has no
equivalent here) but otherwise binds through bind() below too.
"""
import ctypes

# Declared once at module scope, argtypes/restype pinned explicitly on every
# call bound through bind() below: without an explicit restype, ctypes
# defaults a Win32 call's return value to c_int (32-bit signed), which
# happens to round-trip a HWND correctly today only by coincidence (every
# HWND fits in 32 bits, and an equally-undeclared argtypes on the write-back
# call happens to re-sign-extend it the same way) rather than by any
# documented guarantee.
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def bind(func, argtypes, restype):
    func.argtypes = argtypes
    func.restype = restype


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]


# MonitorFromWindow's "if the window isn't on any monitor, use the nearest
# one" flag -- the only sensible fallback for a window dragged partly off the
# desktop, which is exactly when this would otherwise return NULL.
MONITOR_DEFAULTTONEAREST = 2

bind(user32.MonitorFromWindow, [ctypes.c_void_p, ctypes.c_ulong], ctypes.c_void_p)
bind(user32.GetMonitorInfoW, [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)], ctypes.c_int)


def monitor_rect(hwnd):
    """(left, top, right, bottom) of the whole monitor `hwnd` sits on, or None
    if Windows wouldn't say.

    rcMonitor, not rcWork: this is what "cover the screen" means for the
    fullscreen toggle, and the work area deliberately excludes the taskbar --
    the one piece of non-app screen furniture fullscreen is supposed to hide.
    Coordinates are in the same virtualized space tkinter's own geometry uses
    (Win32 scales both alike for a given process's DPI awareness), and they
    are per-monitor, so a window on a secondary screen fills THAT screen
    rather than the primary one winfo_screenwidth() would report.
    """
    if not hwnd:
        return None
    handle = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not handle:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        return None
    rect = info.rcMonitor
    return (rect.left, rect.top, rect.right, rect.bottom)
