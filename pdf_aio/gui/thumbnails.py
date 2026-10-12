"""Page thumbnails rendered in small slices of time on the Tk event loop.

PyMuPDF must not be used from several threads, so rendering stays on the
interface thread. Each slice renders pages until a time budget is spent and
then yields, which keeps scrolling smooth while a large file is loading.
Only thumbnails requested since the last `begin_frame` are rendered, so
scrolling past a thousand pages does not queue a thousand renders.
"""

import time
import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable

from pdf_aio.library import Library
from pdf_aio.workspace import PageRef

Key = tuple[PageRef, int]  # page and the longest side of the thumbnail in pixels

_SLICE_SECONDS = 0.04  # one slice stays below a frame at 25 frames per second
_KEEP = 600  # thumbnails kept in memory, a few screens' worth at any zoom


class ThumbnailCache:
    def __init__(self, widget: tk.Misc, library: Library, on_ready: Callable[[], None]) -> None:
        self._widget = widget
        self._library = library
        self._on_ready = on_ready
        self._images: OrderedDict[Key, tk.PhotoImage] = OrderedDict()
        self._wanted: dict[Key, None] = {}  # insertion ordered set
        self._failed: set[Key] = set()
        self._scheduled = False

    def begin_frame(self) -> None:
        """Forget earlier requests; the caller is about to request what is visible now."""
        self._wanted.clear()

    def get(self, ref: PageRef, size: int) -> tk.PhotoImage | None:
        """The thumbnail if it is ready; otherwise None, and it is queued for rendering."""
        key = (ref, size)
        image = self._images.get(key)
        if image is not None:
            self._images.move_to_end(key)
            return image
        if key not in self._failed:
            self._wanted[key] = None
            self._schedule()
        return None

    def _schedule(self) -> None:
        if self._wanted and not self._scheduled:
            self._scheduled = True
            self._widget.after(1, self._render_slice)

    def _render_slice(self) -> None:
        self._scheduled = False
        deadline = time.perf_counter() + _SLICE_SECONDS
        rendered = False
        while self._wanted and time.perf_counter() < deadline:
            key = next(iter(self._wanted))
            del self._wanted[key]
            try:
                self._images[key] = self._render(*key)
            except Exception:
                # A page MuPDF cannot draw would fail again on every redraw.
                # Remembering it reports the error once; the tile keeps its
                # placeholder and the other thumbnails keep coming.
                self._failed.add(key)
                self._schedule()
                raise
            rendered = True
        while len(self._images) > _KEEP:
            self._images.popitem(last=False)
        self._schedule()
        if rendered:
            self._on_ready()

    def _render(self, ref: PageRef, size: int) -> tk.PhotoImage:
        width, height = self._library.size(ref)
        pixmap = self._library.pixmap(ref, size / max(width, height))
        # PPM is a raw pixel dump that Tk reads without any decoding library.
        return tk.PhotoImage(master=self._widget, data=pixmap.tobytes("ppm"))
