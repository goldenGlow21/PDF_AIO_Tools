"""A scrollable grid of thumbnails with selection and drag to reorder.

The grid shows tiles. In the page view a tile is one page; in the file view
it is one run of pages from the same file. Only the rows in view are drawn,
so thousands of pages cost no more than one screenful. The grid owns the
selection and reports moves and other requests through callbacks; it never
edits the workspace itself.

Selection follows Explorer: click selects one tile, Ctrl+click toggles,
Shift+click extends from the last clicked tile, and dragging on empty space
draws a selection rectangle. Dragging a selected tile moves the whole
selection; a vertical marker shows the gap it will land in.
"""

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from pdf_aio.gui.thumbnails import ThumbnailCache
from pdf_aio.library import Library
from pdf_aio.workspace import PageRef

BACKGROUND = "#eef0f3"
SELECTED_FILL = "#d6e4fd"
SELECTED_OUTLINE = "#2f6fde"
PAGE_OUTLINE = "#a9aeb8"
MUTED_TEXT = "#5f6672"
EMPTY_TEXT = "#7a808c"

_DRAG_START = 6  # pixels the pointer must travel before a press becomes a drag
_AUTOSCROLL_EDGE = 36  # pixels from the top or bottom edge where dragging scrolls
_AUTOSCROLL_MS = 30
_CTRL = 0x0004
_SHIFT = 0x0001


@dataclass(frozen=True)
class Tile:
    pages: range  # workspace positions the tile stands for
    thumbnail: PageRef  # the page drawn on the tile
    title: str
    detail: str
    color: str  # colour that marks the source file
    stacked: bool = False  # drawn as a pile, for a run of several pages


class PageGrid(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        library: Library,
        scale: float,
        on_move: Callable[[list[int], int], None],
        on_open: Callable[[int], None],
        on_menu: Callable[[int | None, int, int], None],
        on_selection: Callable[[], None],
        on_empty_click: Callable[[], None],
        on_zoom: Callable[[int], None],
    ) -> None:
        super().__init__(master)
        self._library = library
        self._scale = scale
        self._on_move = on_move
        self._on_open = on_open
        self._on_menu = on_menu
        self._on_selection = on_selection
        self._on_empty_click = on_empty_click
        self._on_zoom = on_zoom

        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0, takefocus=True,
                                yscrollincrement=1)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.canvas.configure(yscrollcommand=self._scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._thumbs = ThumbnailCache(self, library, self.redraw)
        self._title_font = tkfont.nametofont("TkDefaultFont").copy()
        self._title_font.configure(weight="bold")
        self._detail_font = tkfont.nametofont("TkDefaultFont")
        self._elided: dict[tuple[str, int, str], str] = {}

        self._tiles: list[Tile] = []
        self._selected: set[int] = set()
        self._anchor: int | None = None
        self._box = 0  # thumbnail box side in pixels
        self._columns = 1
        self._left = 0
        self._press: tuple[float, float, int | None, int] | None = None  # x, y, tile, modifier state
        self._mode: str | None = None  # "drag" or "band" while the button is held
        self._band_base: set[int] = set()
        self._slot = 0
        self._pointer = (0, 0)  # last pointer position in widget pixels
        self._autoscrolling = False

        self.set_thumbnail_size(150)
        self.canvas.bind("<Configure>", lambda _e: self._layout())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._press_left)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<ButtonPress-3>", self._press_right)
        self.canvas.bind("<Escape>", self._cancel)

    # ----- geometry -------------------------------------------------------

    def _px(self, logical: float) -> int:
        return round(logical * self._scale)

    @property
    def _pad(self) -> int:
        return self._px(10)

    @property
    def _cell_w(self) -> int:
        return self._box + 2 * self._pad

    @property
    def _cell_h(self) -> int:
        text = self._title_font.metrics("linespace") + self._detail_font.metrics("linespace")
        return self._box + 2 * self._pad + self._px(6) + text

    @property
    def _top(self) -> int:
        return self._px(8)

    def set_thumbnail_size(self, logical: int) -> None:
        self._box = self._px(logical)
        self._elided.clear()
        self._layout()

    def _layout(self) -> None:
        width = max(self.canvas.winfo_width(), self._cell_w)
        self._columns = max(1, width // self._cell_w)
        self._left = (width - self._columns * self._cell_w) // 2
        rows = -(-len(self._tiles) // self._columns)
        height = max(self._top * 2 + rows * self._cell_h, self.canvas.winfo_height())
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.redraw()

    def _cell_origin(self, index: int) -> tuple[int, int]:
        row, column = divmod(index, self._columns)
        return self._left + column * self._cell_w, self._top + row * self._cell_h

    def _tile_at(self, x: float, y: float) -> int | None:
        column = int((x - self._left) // self._cell_w)
        row = int((y - self._top) // self._cell_h)
        if not 0 <= column < self._columns or row < 0:
            return None
        index = row * self._columns + column
        return index if index < len(self._tiles) else None

    def _slot_at(self, x: float, y: float) -> tuple[int, int, int]:
        """The gap nearest to a point, as (gap index, row, column of the marker)."""
        row = max(0, int((y - self._top) // self._cell_h))
        column = min(max(0, round((x - self._left) / self._cell_w)), self._columns)
        slot = row * self._columns + column
        if slot >= len(self._tiles):
            slot = len(self._tiles)
            row, column = divmod(slot, self._columns)
            if column == 0 and slot:
                row, column = row - 1, self._columns
        return slot, row, column

    def _to_canvas(self, event: tk.Event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    # ----- public interface -----------------------------------------------

    @property
    def tiles(self) -> list[Tile]:
        return self._tiles

    @property
    def selected_tiles(self) -> list[int]:
        return sorted(self._selected)

    @property
    def selected_pages(self) -> list[int]:
        return sorted(page for i in self._selected for page in self._tiles[i].pages)

    def set_tiles(self, tiles: list[Tile], select_pages: set[int] = frozenset()) -> None:
        """Show new tiles, selecting those whose pages are all in `select_pages`."""
        self._tiles = tiles
        self._selected = {i for i, tile in enumerate(tiles) if tile.pages and set(tile.pages) <= select_pages}
        self._anchor = min(self._selected) if self._selected else None
        self._layout()
        if self._selected:
            self.see(min(self._selected))

    def select_all(self) -> None:
        self._selected = set(range(len(self._tiles)))
        self.redraw()
        self._on_selection()

    def see(self, index: int) -> None:
        """Scroll the least distance that brings tile `index` fully into view."""
        _, y = self._cell_origin(index)
        view = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        total = float(self.canvas.cget("scrollregion").split()[3])
        # A view shorter than one row, as before the window first appears,
        # can only show the tile from its top.
        if y - self._top < top or view < self._cell_h:
            self.canvas.yview_moveto(max(0, y - self._top) / total)
        elif y + self._cell_h > top + view:
            self.canvas.yview_moveto((y + self._cell_h + self._top - view) / total)
        self.redraw()

    def slot_at_screen(self, x_root: int, y_root: int) -> int | None:
        """The gap under a screen point, or None when the point is outside the grid."""
        x, y = x_root - self.canvas.winfo_rootx(), y_root - self.canvas.winfo_rooty()
        if not (0 <= x < self.canvas.winfo_width() and 0 <= y < self.canvas.winfo_height()):
            return None
        return self._slot_at(self.canvas.canvasx(x), self.canvas.canvasy(y))[0]

    # ----- drawing ----------------------------------------------------------

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self._thumbs.begin_frame()
        if not self._tiles:
            self._draw_empty()
            return
        top = canvas.canvasy(0)
        bottom = canvas.canvasy(canvas.winfo_height())
        first = max(0, int((top - self._top) // self._cell_h)) * self._columns
        last = min(len(self._tiles), (int((bottom - self._top) // self._cell_h) + 1) * self._columns)
        for index in range(first, last):
            self._draw_tile(index)
        if self._mode == "drag":
            self._draw_marker()
        elif self._mode == "band":
            self._draw_band()

    def _draw_empty(self) -> None:
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        inset = self._px(24)
        self.canvas.create_rectangle(inset, inset, width - inset, height - inset,
                                     outline=PAGE_OUTLINE, dash=(6, 4), width=self._px(2))
        self.canvas.create_text(
            width / 2, height / 2, fill=EMPTY_TEXT, justify="center", font=self._title_font,
            text="PDF나 이미지 파일을 여기에 끌어다 놓거나\n클릭해서 파일을 고르세요",
        )
        self.canvas.create_text(
            width / 2, height / 2 + self._px(48), fill=EMPTY_TEXT, justify="center", font=self._detail_font,
            text="지원 형식: PDF, PNG, JPEG, TIFF, BMP, GIF, JPEG 2000, PNM",
        )

    def _draw_tile(self, index: int) -> None:
        canvas = self.canvas
        tile = self._tiles[index]
        x0, y0 = self._cell_origin(index)
        gap = self._px(3)
        if index in self._selected:
            canvas.create_rectangle(x0 + gap, y0 + gap, x0 + self._cell_w - gap, y0 + self._cell_h - gap,
                                    fill=SELECTED_FILL, outline=SELECTED_OUTLINE, width=self._px(2))

        width, height = self._library.size(tile.thumbnail)
        ratio = self._box / max(width, height)
        if tile.stacked:
            ratio *= 0.9  # leave room for the sheets drawn behind
        w, h = round(width * ratio), round(height * ratio)
        ix = x0 + self._pad + (self._box - w) // 2
        iy = y0 + self._pad + (self._box - h) // 2
        if tile.stacked:
            shift = self._px(5)
            for step in (2, 1):
                canvas.create_rectangle(ix + shift * step, iy - shift * step, ix + w + shift * step,
                                        iy + h - shift * step, fill="white", outline=PAGE_OUTLINE)
        image = self._thumbs.get(tile.thumbnail, max(w, h))
        if image is None:
            canvas.create_rectangle(ix, iy, ix + w, iy + h, fill="white", outline="")
        else:
            canvas.create_image(ix, iy, image=image, anchor="nw")
        canvas.create_rectangle(ix - 1, iy - 1, ix + w, iy + h, outline=PAGE_OUTLINE)
        strip = self._px(4)
        canvas.create_rectangle(ix, iy + h + self._px(2), ix + w, iy + h + self._px(2) + strip,
                                fill=tile.color, outline="")

        text_width = self._cell_w - 2 * gap - self._px(6)
        centre = x0 + self._cell_w / 2
        text_top = y0 + self._pad + self._box + self._px(6)
        canvas.create_text(centre, text_top, anchor="n", font=self._title_font,
                           text=self._elide(tile.title, self._title_font, text_width))
        canvas.create_text(centre, text_top + self._title_font.metrics("linespace"), anchor="n",
                           font=self._detail_font, fill=MUTED_TEXT,
                           text=self._elide(tile.detail, self._detail_font, text_width))

    def _elide(self, text: str, font: tkfont.Font, width: int) -> str:
        """Shorten text from the middle so both the start and the extension stay visible."""
        key = (text, width, str(font))
        if key not in self._elided:
            shown = text
            keep = len(text)
            while keep > 1 and font.measure(shown) > width:
                keep -= 1
                shown = text[: (keep + 1) // 2] + "..." + text[len(text) - keep // 2:]
            self._elided[key] = shown
        return self._elided[key]

    def _draw_marker(self) -> None:
        _, row, column = self._slot_at(*self._pointer_canvas())
        x = self._left + column * self._cell_w
        y = self._top + row * self._cell_h
        self.canvas.create_line(x, y + self._pad // 2, x, y + self._cell_h - self._pad // 2,
                                fill=SELECTED_OUTLINE, width=self._px(4))
        count = len(self.selected_pages)
        px, py = self._pointer_canvas()
        label = self.canvas.create_text(px + self._px(16), py + self._px(16), anchor="nw",
                                        text=f"{count}페이지", fill="white")
        box = self.canvas.bbox(label)
        pad = self._px(4)
        back = self.canvas.create_rectangle(box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad,
                                            fill=SELECTED_OUTLINE, outline="")
        self.canvas.tag_raise(label, back)

    def _draw_band(self) -> None:
        x0, y0 = self._press[0], self._press[1]
        x1, y1 = self._pointer_canvas()
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=SELECTED_OUTLINE, dash=(4, 2))

    def _pointer_canvas(self) -> tuple[float, float]:
        return self.canvas.canvasx(self._pointer[0]), self.canvas.canvasy(self._pointer[1])

    # ----- scrolling --------------------------------------------------------

    def _yview(self, *args: str) -> None:
        self.canvas.yview(*args)
        self.redraw()

    def _wheel(self, event: tk.Event) -> None:
        if event.state & _CTRL:
            self._on_zoom(1 if event.delta > 0 else -1)
            return
        # One wheel notch reports 120 and scrolls about a third of a row.
        self.canvas.yview_scroll(int(-event.delta / 120 * self._cell_h / 3), "units")
        self.redraw()

    def _autoscroll(self) -> None:
        if self._mode is None:
            self._autoscrolling = False
            return
        y = self._pointer[1]
        height = self.canvas.winfo_height()
        edge = self._px(_AUTOSCROLL_EDGE)
        if y < edge:
            step = -(edge - y)
        elif y > height - edge:
            step = y - (height - edge)
        else:
            self._autoscrolling = False
            return
        self.canvas.yview_scroll(int(step), "units")
        self._update_band()
        self.redraw()
        self.after(_AUTOSCROLL_MS, self._autoscroll)

    # ----- mouse ------------------------------------------------------------

    def _press_left(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        if not self._tiles:
            self._on_empty_click()
            return
        x, y = self._to_canvas(event)
        index = self._tile_at(x, y)
        self._press = (x, y, index, event.state)
        self._pointer = (event.x, event.y)
        if index is None:
            if not event.state & (_CTRL | _SHIFT):
                self._selected = set()
        elif event.state & _SHIFT and self._anchor is not None:
            span = set(range(min(self._anchor, index), max(self._anchor, index) + 1))
            self._selected = self._selected | span if event.state & _CTRL else span
        elif event.state & _CTRL:
            self._selected ^= {index}
            self._anchor = index
        elif index not in self._selected:
            self._selected = {index}
            self._anchor = index
        self.redraw()
        self._on_selection()

    def _motion(self, event: tk.Event) -> None:
        if self._press is None:
            return
        self._pointer = (event.x, event.y)
        x, y = self._to_canvas(event)
        if self._mode is None:
            if abs(x - self._press[0]) < _DRAG_START and abs(y - self._press[1]) < _DRAG_START:
                return
            index = self._press[2]
            if index is None:
                self._mode = "band"
                self._band_base = set(self._selected)
            elif index in self._selected:
                self._mode = "drag"
                self.canvas.configure(cursor="fleur")
            else:
                return
        self._update_band()
        self.redraw()
        if not self._autoscrolling:
            self._autoscrolling = True
            self._autoscroll()

    def _update_band(self) -> None:
        if self._mode != "band":
            return
        x0, y0 = self._press[0], self._press[1]
        x1, y1 = self._pointer_canvas()
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        hit = set()
        for index in range(len(self._tiles)):
            cx, cy = self._cell_origin(index)
            if cx < right and cx + self._cell_w > left and cy < bottom and cy + self._cell_h > top:
                hit.add(index)
        self._selected = self._band_base | hit
        self._on_selection()

    def _release(self, event: tk.Event) -> None:
        if self._press is None:
            return
        mode, (_, _, index, state) = self._mode, self._press
        self._press, self._mode = None, None
        self.canvas.configure(cursor="")
        if mode == "drag":
            slot = self._slot_at(*self._to_canvas(event))[0]
            self.redraw()
            self._on_move(self.selected_tiles, slot)
            return
        if mode is None and index is not None and not state & (_CTRL | _SHIFT):
            # A plain click on a tile that was already part of a selection:
            # keep the selection while a drag might follow, narrow it now.
            self._selected = {index}
            self._anchor = index
            self._on_selection()
        self.redraw()

    def _cancel(self, _event: tk.Event) -> None:
        if self._mode is not None:
            self._press, self._mode = None, None
            self.canvas.configure(cursor="")
            self.redraw()

    def _double_click(self, event: tk.Event) -> None:
        index = self._tile_at(*self._to_canvas(event))
        if index is not None:
            self._on_open(index)

    def _press_right(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        index = self._tile_at(*self._to_canvas(event))
        if index is not None and index not in self._selected:
            self._selected = {index}
            self._anchor = index
            self.redraw()
            self._on_selection()
        self._on_menu(index, event.x_root, event.y_root)
