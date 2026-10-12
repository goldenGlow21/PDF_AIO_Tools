"""Exercise the WM_DROPFILES hook by posting the message Explorer would post."""

import ctypes
import sys
import time
import tkinter as tk
import unittest
from ctypes import wintypes
from pathlib import Path

GMEM_MOVEABLE_ZEROINIT = 0x0042


class DROPFILES(ctypes.Structure):
    _fields_ = [("pFiles", wintypes.DWORD), ("pt", wintypes.POINT), ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]


def post_drop(hwnd: int, files: list[str], x: int, y: int) -> None:
    """Hand the window a drop handle laid out exactly as the shell builds one."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    names = ("\0".join(files) + "\0\0").encode("utf-16-le")
    header = DROPFILES(ctypes.sizeof(DROPFILES), wintypes.POINT(x, y), False, True)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE_ZEROINIT, ctypes.sizeof(header) + len(names))
    memory = kernel32.GlobalLock(handle)
    ctypes.memmove(memory, ctypes.byref(header), ctypes.sizeof(header))
    ctypes.memmove(memory + ctypes.sizeof(header), names, len(names))
    kernel32.GlobalUnlock(handle)
    if not user32.PostMessageW(hwnd, 0x0233, handle, 0):
        raise ctypes.WinError(ctypes.get_last_error())


@unittest.skipUnless(sys.platform == "win32", "WM_DROPFILES exists only on Windows")
class FileDropTargetTest(unittest.TestCase):
    def test_dropped_files_reach_the_handler_with_the_screen_position(self):
        from pdf_aio.gui.filedrop import FileDropTarget

        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry("200x150+120+140")
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True)
        received = []
        target = FileDropTarget(root, lambda paths, x, y: received.append((paths, x, y)))
        root.update()

        hangul = r"C:\docs\한글 이름.png"
        post_drop(root.winfo_id(), [r"C:\docs\a.pdf", hangul], 10, 20)
        deadline = time.monotonic() + 5
        while not received and time.monotonic() < deadline:
            root.update()

        self.assertEqual(len(received), 1)
        paths, x, y = received[0]
        self.assertEqual(paths, [Path(r"C:\docs\a.pdf"), Path(hangul)])
        self.assertEqual((x, y), (root.winfo_rootx() + 10, root.winfo_rooty() + 20))
        self.assertIsNotNone(target)


if __name__ == "__main__":
    unittest.main()
