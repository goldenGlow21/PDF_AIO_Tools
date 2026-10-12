"""Modal dialogs: PDF passwords, split settings and image export settings."""

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from pdf_aio.export import IMAGE_FORMATS
from pdf_aio.splitting import by_source, every, parse_ranges
from pdf_aio.workspace import PageRef


class _Dialog(tk.Toplevel):
    """A modal window with OK and Cancel; `result` stays None when cancelled."""

    def __init__(self, master: tk.Misc, title: str, ok_text: str, cancel_text: str = "취소") -> None:
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        self.initial_focus: tk.Misc = self
        self.body = ttk.Frame(self, padding=12)
        self.body.grid(row=0, column=0, sticky="nsew")
        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.grid(row=1, column=0, sticky="e")
        self.ok_button = ttk.Button(buttons, text=ok_text, default="active", command=self._ok)
        self.ok_button.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text=cancel_text, command=self.destroy).grid(row=0, column=1)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())

    def run(self) -> object:
        """Show the dialog centred on its owner and wait until it closes."""
        self.update_idletasks()
        owner = self.master.winfo_toplevel()
        x = owner.winfo_rootx() + (owner.winfo_width() - self.winfo_reqwidth()) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()
        self.initial_focus.focus_set()
        self.wait_window()
        return self.result

    def _ok(self) -> None:
        raise NotImplementedError


class PasswordDialog(_Dialog):
    """Ask for the password of a protected PDF; the result is None when skipped."""

    def __init__(self, master: tk.Misc, file_name: str, retry: bool) -> None:
        super().__init__(master, "암호 입력", "열기", cancel_text="건너뛰기")
        message = f"{file_name} 파일은 암호로 보호되어 있습니다."
        if retry:
            message += "\n입력한 암호가 올바르지 않습니다. 다시 입력하세요."
        ttk.Label(self.body, text=message, justify="left").grid(row=0, column=0, columnspan=2, sticky="w",
                                                               pady=(0, 8))
        ttk.Label(self.body, text="암호").grid(row=1, column=0, sticky="w", padx=(0, 6))
        self._password = tk.StringVar(self)
        self.initial_focus = ttk.Entry(self.body, textvariable=self._password, show="*", width=30)
        self.initial_focus.grid(row=1, column=1, sticky="ew")

    def _ok(self) -> None:
        self.result = self._password.get()
        self.destroy()


class SplitDialog(_Dialog):
    """Choose how to divide the workspace; the result is a list of page groups."""

    def __init__(self, master: tk.Misc, pages: tuple[PageRef, ...]) -> None:
        super().__init__(master, "여러 파일로 분할", "저장 위치 선택...")
        self._pages = pages
        self.by_file = False  # whether the groups follow the source files
        self._mode = tk.StringVar(self, "every")
        self._size = tk.StringVar(self, "1")
        self._ranges = tk.StringVar(self, f"1-{max(1, len(pages) // 2)}, {len(pages) // 2 + 1}-")
        self._summary = tk.StringVar(self)

        ttk.Label(self.body, text=f"현재 순서의 {len(pages)}페이지를 다음 기준으로 나눕니다.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Radiobutton(self.body, text="페이지 수", value="every", variable=self._mode).grid(
            row=1, column=0, sticky="w")
        size_row = ttk.Frame(self.body)
        size_row.grid(row=1, column=1, sticky="w")
        ttk.Spinbox(size_row, textvariable=self._size, from_=1, to=max(1, len(pages)), width=6).grid(row=0, column=0)
        ttk.Label(size_row, text="페이지씩 (1이면 한 페이지마다 파일 하나)").grid(row=0, column=1, padx=(6, 0))
        ttk.Radiobutton(self.body, text="범위", value="ranges", variable=self._mode).grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.body, textvariable=self._ranges, width=32).grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(self.body, text="쉼표로 나눈 범위마다 파일 하나, 예: 1-3, 4, 5-", foreground="#5f6672").grid(
            row=3, column=1, sticky="w")
        ttk.Radiobutton(self.body, text="원본 파일이 바뀌는 곳마다 (병합 되돌리기)", value="source",
                        variable=self._mode).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(self.body, textvariable=self._summary, font="TkHeadingFont").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))
        for variable in (self._mode, self._size, self._ranges):
            variable.trace_add("write", lambda *_: self._refresh())
        self._refresh()

    def _groups(self) -> list[list[int]]:
        mode = self._mode.get()
        if mode == "every":
            try:
                size = int(self._size.get())
            except ValueError:
                raise ValueError(f'"{self._size.get()}": 페이지 수는 정수로 입력하세요') from None
            return every(len(self._pages), size)
        if mode == "ranges":
            return parse_ranges(self._ranges.get(), len(self._pages))
        return by_source(self._pages)

    def _refresh(self) -> None:
        try:
            groups = self._groups()
        except ValueError as exc:  # includes RangeSyntaxError
            self._summary.set(str(exc))
            self.ok_button.state(["disabled"])
            return
        self._summary.set(f"파일 {len(groups)}개가 만들어집니다")
        self.ok_button.state(["!disabled"])

    def _ok(self) -> None:
        if self.ok_button.instate(["disabled"]):
            return
        self.result = self._groups()
        self.by_file = self._mode.get() == "source"
        self.destroy()


@dataclass(frozen=True)
class ImageExport:
    suffix: str  # ".png" or ".jpg"
    dpi: int
    selection_only: bool


class ImageExportDialog(_Dialog):
    def __init__(self, master: tk.Misc, page_count: int, selected_count: int) -> None:
        super().__init__(master, "페이지를 이미지로 내보내기", "저장 위치 선택...")
        self._format = tk.StringVar(self, "PNG")
        self._dpi = tk.StringVar(self, "150")
        self._scope = tk.StringVar(self, "selection" if selected_count else "all")

        ttk.Label(self.body, text="형식").grid(row=0, column=0, sticky="w")
        formats = ttk.Frame(self.body)
        formats.grid(row=0, column=1, sticky="w")
        for column, name in enumerate(IMAGE_FORMATS):
            ttk.Radiobutton(formats, text=name, value=name, variable=self._format).grid(
                row=0, column=column, padx=(0, 12))
        ttk.Label(self.body, text="해상도").grid(row=1, column=0, sticky="w", pady=(8, 0))
        dpi_row = ttk.Frame(self.body)
        dpi_row.grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Combobox(dpi_row, textvariable=self._dpi, values=("72", "96", "150", "200", "300", "600"),
                     width=6).grid(row=0, column=0)
        ttk.Label(dpi_row, text="dpi (화면용 150, 인쇄용 300)").grid(row=0, column=1, padx=(6, 0))
        ttk.Label(self.body, text="페이지").grid(row=2, column=0, sticky="nw", pady=(8, 0), padx=(0, 6))
        scope = ttk.Frame(self.body)
        scope.grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(scope, text=f"전체 {page_count}페이지", value="all", variable=self._scope).grid(sticky="w")
        selected = ttk.Radiobutton(scope, text=f"선택한 페이지 ({selected_count}페이지)", value="selection",
                                   variable=self._scope)
        selected.grid(sticky="w")
        if not selected_count:
            selected.state(["disabled"])
        self._error = tk.StringVar(self)
        ttk.Label(self.body, textvariable=self._error, foreground="#c62828").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _ok(self) -> None:
        try:
            dpi = int(self._dpi.get())
        except ValueError:
            dpi = 0
        if not 36 <= dpi <= 1200:
            self._error.set("해상도는 36에서 1200 사이의 정수로 입력하세요.")
            return
        self.result = ImageExport(IMAGE_FORMATS[self._format.get()], dpi, self._scope.get() == "selection")
        self.destroy()
