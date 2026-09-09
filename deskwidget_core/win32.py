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
