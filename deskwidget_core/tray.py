"""Windows system tray icon, implemented directly on Shell_NotifyIcon/user32
via ctypes rather than pulling in a tray-icon dependency (e.g. pystray) into
the PyInstaller build -- same "plain ctypes, explicit argtypes/restype"
convention as single_instance.py and widget.py's own Win32 calls.

The tray window and its message loop run on their own dedicated thread,
never on Tk's own thread. An earlier version relied on Tcl's Windows
notifier to dispatch WM_TRAYICON to a WNDPROC living on Tk's thread instead
-- Tcl's notifier does happen to pump this thread's *entire* message queue
(not just Tk's own windows) while mainloop() is idle, so the tray icon did
receive clicks that way. But mainloop() releases the GIL for the duration of
that underlying blocking Win32 wait (Py_BEGIN_ALLOW_THREADS), and a ctypes
callback invoked from inside that window corrupts CPython's per-thread GIL
bookkeeping when it calls back into Python -- reproducibly crashing the
process (Fatal Python error: PyEval_RestoreThread) the moment a click
actually fired the callback. A window's messages can only be pumped by the
thread that created it, so the fix is to give the tray its own thread with
its own GetMessage/DispatchMessage loop -- a thread Tk's mainloop never
touches, so this GIL conflict can't occur. Everything the WNDPROC needs to
do beyond that (show/restore the widget, run a menu command) is handed back
to the Tk thread via self.root.after(0, ...), the same cross-thread
hand-off refresh.py's own background check_one() workers already rely on.
"""
import ctypes
import threading
from ctypes import wintypes

from .paths import WINDOW_TITLE, log_error

WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_QUIT = 0x0012
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_TRAY_QUIT = WM_APP + 2  # posted by destroy() to end the pump thread's loop

WS_OVERLAPPED = 0x00000000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
SM_CXSMICON = 49
IDI_APPLICATION = 32512
TPM_RETURNCMD = 0x0100

# Bounds how long destroy() waits for the pump thread to unwind before giving
# up -- it's a daemon thread, so a hang there (which should never happen)
# would otherwise never stop close() from continuing, just delay it.
_SHUTDOWN_JOIN_SECONDS = 2.0

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)

_TOOLTIP_MAX = 127  # leaves room for szTip's own null terminator (WCHAR[128])


def _make_int_resource(res_id):
    # MAKEINTRESOURCE: a "string pointer" whose value is actually a small
    # integer resource id (e.g. IDI_APPLICATION) -- LoadIconW tells the two
    # apart by whether the pointer's high bits are zero, not by any separate
    # flag, so this has to be an actual pointer-typed value, not a Python int.
    return ctypes.cast(res_id, wintypes.LPCWSTR)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hWnd", wintypes.HWND),
        ("uID", ctypes.c_uint32),
        ("uFlags", ctypes.c_uint32),
        ("uCallbackMessage", ctypes.c_uint32),
        ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_uint32),
        ("dwStateMask", ctypes.c_uint32),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint32),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_uint32),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.UnregisterClassW.restype = wintypes.BOOL
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, ctypes.c_uint,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_user32.LoadImageW.restype = wintypes.HICON
_user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
_user32.LoadIconW.restype = wintypes.HICON
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.CreatePopupMenu.argtypes = []
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.DestroyMenu.argtypes = [wintypes.HMENU]
_user32.DestroyMenu.restype = wintypes.BOOL
_user32.AppendMenuW.argtypes = [wintypes.HMENU, ctypes.c_uint, ctypes.c_size_t, wintypes.LPCWSTR]
_user32.AppendMenuW.restype = wintypes.BOOL
_user32.TrackPopupMenu.argtypes = [wintypes.HMENU, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
_user32.TrackPopupMenu.restype = wintypes.BOOL
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
_user32.TranslateMessage.restype = wintypes.BOOL
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
_user32.DispatchMessageW.restype = LRESULT
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.PostQuitMessage.restype = None
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_shell32.Shell_NotifyIconW.argtypes = [ctypes.c_uint32, ctypes.POINTER(_NOTIFYICONDATAW)]
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL

# Derived from WINDOW_TITLE (already unique per variant -- see paths.py) so a
# sibling variant built from this same codebase never collides with this
# process's window class.
_CLASS_NAME = f"{WINDOW_TITLE}-tray"


def build_icon_file(path, accent_rgb):
    """Renders a small solid-color dot in the given accent color as a
    multi-size .ico, cached at `path` (regenerated only if missing -- the
    accent doesn't change across runs, see appconfig.default_accent()).
    Best-effort: leaves `path` absent on any failure, which just means the
    tray icon falls back to the generic system icon (see TrayIcon.__init__).
    """
    if path.exists():
        return
    try:
        from PIL import Image, ImageDraw
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((2, 2, size - 2, size - 2), fill=(*accent_rgb, 255))
        image.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    except Exception as error:  # noqa: BLE001 -- purely cosmetic, never fatal
        log_error("tray_icon", error)


class TrayIcon:
    def __init__(self, tooltip, icon_path, menu_items_provider, on_activate):
        # menu_items_provider: callable() -> list of (label, callback) pairs,
        # built fresh on each right-click -- mirrors show_context_menu()'s own
        # "always reflect current language/state" convention -- rather than a
        # menu built once at __init__ time and left stale if the user changes
        # language later. Both this and on_activate run on the pump thread
        # (see the module docstring), so callers hand back to the Tk thread
        # themselves (self.root.after(0, ...)) rather than touching Tk here.
        self._menu_items_provider = menu_items_provider
        self._on_activate = on_activate
        self._tooltip = tooltip
        self._icon_path = icon_path
        self._hwnd = None
        self._hicon = None
        self._hinstance = _kernel32.GetModuleHandleW(None)
        # Kept alive on self: the C side only holds a raw function pointer,
        # so if this were a bare local the wrapper would be free to be
        # garbage-collected while Windows still expects to be able to call it.
        self._wndproc = WNDPROC(self._wnd_proc)
        self._nid = _NOTIFYICONDATAW()

        ready = threading.Event()
        self._init_error = None
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait()
        if self._init_error is not None:
            raise self._init_error

    def _run(self, ready):
        # Everything Win32 -- window/class creation, the icon itself, and the
        # message loop that delivers clicks to _wnd_proc -- lives on this one
        # thread for its whole life, since a window's messages can only be
        # pumped by the thread that created it. Never touches Tk directly;
        # see the module docstring for why.
        try:
            self._create_window()
            self._add_icon()
        except Exception as error:  # noqa: BLE001 -- must always unblock ready.wait()
            self._init_error = error
            ready.set()
            return
        ready.set()

        msg = _MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        try:
            self._nid.uFlags = 0
            _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        finally:
            _user32.DestroyWindow(self._hwnd)
            _user32.UnregisterClassW(_CLASS_NAME, self._hinstance)

    def _create_window(self):
        wc = _WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self._hinstance
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = _CLASS_NAME
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            raise OSError(ctypes.get_last_error(), "RegisterClassW failed")

        self._hwnd = _user32.CreateWindowExW(
            0, _CLASS_NAME, _CLASS_NAME, WS_OVERLAPPED,
            0, 0, 0, 0, None, None, self._hinstance, None)
        if not self._hwnd:
            error = OSError(ctypes.get_last_error(), "CreateWindowExW failed")
            _user32.UnregisterClassW(_CLASS_NAME, self._hinstance)
            raise error

    def _add_icon(self):
        icon_size = _user32.GetSystemMetrics(SM_CXSMICON) or 16
        self._hicon = _user32.LoadImageW(None, str(self._icon_path), IMAGE_ICON,
                                          icon_size, icon_size, LR_LOADFROMFILE)
        if not self._hicon:
            self._hicon = _user32.LoadIconW(None, _make_int_resource(IDI_APPLICATION))

        self._nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        self._nid.hWnd = self._hwnd
        self._nid.uID = 1
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._nid.uCallbackMessage = WM_TRAYICON
        self._nid.hIcon = self._hicon
        self._nid.szTip = self._tooltip[:_TOOLTIP_MAX]
        if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)):
            error = OSError(ctypes.get_last_error(), "Shell_NotifyIconW(ADD) failed")
            _user32.DestroyWindow(self._hwnd)
            _user32.UnregisterClassW(_CLASS_NAME, self._hinstance)
            self._hwnd = None
            raise error

    def update_tooltip(self, tooltip):
        # Shell_NotifyIconW is a shell RPC keyed off hWnd/uID, not tied to
        # the calling thread, so this is safe to call from the Tk thread
        # (see refresh_complete()) even though the icon itself lives on the
        # pump thread -- unlike the window-message calls in _run()/destroy(),
        # which do need to run on (or be posted to) that thread.
        if self._hwnd is None:
            return
        self._nid.uFlags = NIF_TIP
        self._nid.szTip = tooltip[:_TOOLTIP_MAX]
        _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def destroy(self):
        if self._hwnd is None:
            return
        _user32.PostMessageW(self._hwnd, WM_TRAY_QUIT, 0, 0)
        self._thread.join(_SHUTDOWN_JOIN_SECONDS)
        # Only clear _hwnd once the pump thread has actually exited: _run()'s
        # own finally block reads self._hwnd to DestroyWindow/UnregisterClassW
        # on its way out, so nulling it here first (e.g. after the join times
        # out on a stalled Win32 call) would make that cleanup silently fail
        # against None and leak the window class instead.
        if not self._thread.is_alive():
            self._hwnd = None

    def _show_menu(self):
        items = self._menu_items_provider()
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for index, (label, _callback) in enumerate(items):
                _user32.AppendMenuW(menu, 0, index + 1, label)
            point = wintypes.POINT()
            _user32.GetCursorPos(ctypes.byref(point))
            # Standard tray-menu dance: the popup must be owned by a
            # foreground window to dismiss itself on an outside click, and
            # the follow-up WM_NULL nudge (below) is needed so it actually
            # closes when the user clicks away instead of lingering.
            _user32.SetForegroundWindow(self._hwnd)
            selected = _user32.TrackPopupMenu(
                menu, TPM_RETURNCMD, point.x, point.y, 0, self._hwnd, None)
            _user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
            if selected:
                _, callback = items[selected - 1]
                callback()
        finally:
            _user32.DestroyMenu(menu)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAYICON:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._on_activate()
                elif event == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_TRAY_QUIT:
                _user32.PostQuitMessage(0)
                return 0
            if msg == WM_DESTROY:
                return 0
        except Exception as error:  # noqa: BLE001 -- must never escape into Windows' dispatcher
            log_error("tray_wndproc", error)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
