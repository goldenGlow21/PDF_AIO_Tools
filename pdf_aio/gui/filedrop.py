"""Accept files dragged from Windows Explorer onto a Tk window.

Tk has no file drop support on Windows. The classic Win32 mechanism is
enough: DragAcceptFiles marks a window, the shell then posts WM_DROPFILES to
it (or to the nearest marked ancestor of the window under the cursor) with a
handle listing the files, and a replacement window procedure reads that
handle before passing every other message on to Tk's own procedure.

The replacement procedure runs inside Tcl's event dispatch, where calling
back into Tcl corrupts tkinter's interpreter state and aborts the process.
It therefore only queues the drop; a timer on the Tk event loop delivers it.
"""

import ctypes
import tkinter as tk
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_QUERY_COUNT = 0xFFFFFFFF  # DragQueryFileW index meaning "how many files"
_POLL_MS = 100  # delay between a drop and its delivery, short enough to feel immediate

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32")

_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
_user32.SetWindowLongPtrW.restype = ctypes.c_void_p
_user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.CallWindowProcW.restype = ctypes.c_ssize_t
_user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_user32.ClientToScreen.restype = wintypes.BOOL
_shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
_shell32.DragAcceptFiles.restype = None
_shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
_shell32.DragQueryFileW.restype = wintypes.UINT
_shell32.DragQueryPoint.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.POINT)]
_shell32.DragQueryPoint.restype = wintypes.BOOL
_shell32.DragFinish.argtypes = [wintypes.HANDLE]
_shell32.DragFinish.restype = None

DropHandler = Callable[[list[Path], int, int], None]  # (files, screen x, screen y)


def _read_drop(hwnd: int, hdrop: int) -> tuple[list[Path], int, int]:
    """List the dropped files and the screen point they were released at."""
    paths = []
    for i in range(_shell32.DragQueryFileW(hdrop, _QUERY_COUNT, None, 0)):
        length = _shell32.DragQueryFileW(hdrop, i, None, 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        _shell32.DragQueryFileW(hdrop, i, buffer, length + 1)
        paths.append(Path(buffer.value))
    point = wintypes.POINT()
    _shell32.DragQueryPoint(hdrop, ctypes.byref(point))
    _user32.ClientToScreen(hwnd, ctypes.byref(point))
    _shell32.DragFinish(hdrop)
    return paths, point.x, point.y


class FileDropTarget:
    """Calls `on_drop` with the files dropped anywhere on `window`."""

    def __init__(self, window: tk.Misc, on_drop: DropHandler) -> None:
        self._window = window
        self._on_drop = on_drop
        self._pending: list[tuple[list[Path], int, int]] = []
        hwnd = window.winfo_id()
        # The callback object must outlive the window, or Windows would call
        # into freed memory; holding it on self ties it to this target.
        self._procedure = WNDPROC(self._window_procedure)
        self._previous = _user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(self._procedure, ctypes.c_void_p))
        if not self._previous:
            raise ctypes.WinError(ctypes.get_last_error())
        _shell32.DragAcceptFiles(hwnd, True)
        self._deliver()

    def _window_procedure(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == WM_DROPFILES:
            self._pending.append(_read_drop(hwnd, wparam))
            return 0
        return _user32.CallWindowProcW(self._previous, hwnd, message, wparam, lparam)

    def _deliver(self) -> None:
        # Reschedule first, so a handler that raises does not end the polling.
        self._window.after(_POLL_MS, self._deliver)
        while self._pending:
            self._on_drop(*self._pending.pop(0))
