"""A large view of one workspace page, optionally as it will look when saved."""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from pdf_aio.export import OutputOptions, preview_pixmap
from pdf_aio.gui.pagegrid import BACKGROUND, PAGE_OUTLINE
from pdf_aio.library import Library
from pdf_aio.workspace import PageRef

_RESIZE_SETTLE_MS = 80  # wait for a window drag to pause before rendering again


class PreviewWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        library: Library,
        get_pages: Callable[[], tuple[PageRef, ...]],
        get_options: Callable[[], OutputOptions],
        as_saved: bool,
    ) -> None:
        super().__init__(master)
        self.title("미리보기")
        self.geometry(f"{master.winfo_width() * 2 // 3}x{master.winfo_height() * 9 // 10}")
        self._library = library
        self._get_pages = get_pages
        self._get_options = get_options
        self._position = 0
        self._photo: tk.PhotoImage | None = None
        self._pending: str | None = None
        self._as_saved = tk.BooleanVar(self, as_saved)
        self._caption = tk.StringVar(self)

        bar = ttk.Frame(self, padding=6)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Button(bar, text="< 이전", command=lambda: self.show(self._position - 1)).grid(row=0, column=0)
        ttk.Button(bar, text="다음 >", command=lambda: self.show(self._position + 1)).grid(row=0, column=1, padx=6)
        ttk.Label(bar, textvariable=self._caption).grid(row=0, column=2, sticky="w", padx=6)
        ttk.Checkbutton(bar, text="저장될 모습으로 보기 (페이지 번호, 워터마크, 압축 적용)",
                        variable=self._as_saved, command=self.refresh).grid(row=0, column=3, sticky="e")
        bar.columnconfigure(2, weight=1)
        self._canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self._canvas.bind("<Configure>", lambda _e: self.refresh())
        for key, step in (("<Left>", -1), ("<Prior>", -1), ("<Right>", 1), ("<Next>", 1), ("<space>", 1)):
            self.bind(key, lambda _e, s=step: self.show(self._position + s))
        self.bind("<Home>", lambda _e: self.show(0))
        self.bind("<End>", lambda _e: self.show(len(self._get_pages()) - 1))
        self.bind("<Escape>", lambda _e: self.destroy())

    def show(self, position: int) -> None:
        self._position = position
        self.refresh()

    def refresh(self) -> None:
        """Render again once the window has settled; also call this after workspace edits."""
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = self.after(_RESIZE_SETTLE_MS, self._draw)

    def _draw(self) -> None:
        self._pending = None
        canvas = self._canvas
        canvas.delete("all")
        pages = self._get_pages()
        if not pages:
            self._caption.set("작업 공간이 비어 있습니다")
            return
        self._position = min(max(self._position, 0), len(pages) - 1)
        ref = pages[self._position]
        source = self._library.get(ref.source)
        where = source.name if source.path is None else f"{source.name} {ref.index + 1}페이지"
        self._caption.set(f"{self._position + 1} / {len(pages)}페이지    원본: {where}")

        margin = 16
        width, height = self._library.size(ref)
        room_w, room_h = canvas.winfo_width() - 2 * margin, canvas.winfo_height() - 2 * margin
        zoom = max(min(room_w / width, room_h / height), 0.05)
        if self._as_saved.get():
            try:
                options = self._get_options()
            except ValueError as exc:
                # The options are being edited; say what is wrong instead of a stale picture.
                canvas.create_text(canvas.winfo_width() / 2, canvas.winfo_height() / 2, width=room_w,
                                   text=f"저장될 모습을 표시할 수 없습니다.\n{exc}", fill="#c62828")
                return
            pixmap = preview_pixmap(self._library, pages, self._position, options, zoom)
        else:
            pixmap = self._library.pixmap(ref, zoom)
        self._photo = tk.PhotoImage(master=self, data=pixmap.tobytes("ppm"))
        x = (canvas.winfo_width() - pixmap.width) // 2
        y = (canvas.winfo_height() - pixmap.height) // 2
        canvas.create_image(x, y, image=self._photo, anchor="nw")
        canvas.create_rectangle(x - 1, y - 1, x + pixmap.width, y + pixmap.height, outline=PAGE_OUTLINE)
