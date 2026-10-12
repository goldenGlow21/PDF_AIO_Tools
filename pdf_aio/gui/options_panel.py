"""The side panel that collects the options applied to every saved PDF."""

import tkinter as tk
from tkinter import ttk

from pdf_aio.export import Compression, OutputOptions, PageNumbers, Watermark

_POSITIONS = {
    "아래 가운데": "bottom-center",
    "아래 오른쪽": "bottom-right",
    "아래 왼쪽": "bottom-left",
    "위 가운데": "top-center",
    "위 오른쪽": "top-right",
    "위 왼쪽": "top-left",
}
_RESOLUTIONS = ("72", "96", "120", "150", "200", "300")


def _number(variable: tk.StringVar, what: str, kind: type = int) -> float:
    text = variable.get().strip()
    try:
        return kind(text)
    except ValueError:
        expected = "정수" if kind is int else "숫자"
        raise ValueError(f'{what}: {expected}를 입력하세요 (입력: "{text}")') from None


class _Section(ttk.LabelFrame):
    """A titled group whose controls are enabled by the checkbox in its title."""

    def __init__(self, master: tk.Misc, title: str) -> None:
        self.enabled = tk.BooleanVar(master, value=False)
        toggle = ttk.Checkbutton(master, text=title, variable=self.enabled, command=self._sync)
        super().__init__(master, labelwidget=toggle, padding=(8, 4, 8, 8))
        self.columnconfigure(1, weight=1)
        self._controls: list[ttk.Widget] = []

    def row(self, label: str, control: ttk.Widget, hint: str = "") -> None:
        row = self.grid_size()[1]
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
        control.grid(row=row, column=1, sticky="ew", pady=2)
        self._controls.append(control)
        if hint:
            ttk.Label(self, text=hint, foreground="#5f6672").grid(row=row + 1, column=1, sticky="w")
        self._sync()

    def _sync(self) -> None:
        state = ["!disabled"] if self.enabled.get() else ["disabled"]
        for control in self._controls:
            control.state(state)


class OutputPanel(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=(8, 8, 8, 0))
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="저장할 PDF에 적용할 옵션", font="TkHeadingFont").grid(sticky="w", pady=(0, 6))

        self._numbers = _Section(self, "페이지 번호")
        self._position = tk.StringVar(self, "아래 가운데")
        self._template = tk.StringVar(self, "{n}")
        self._start = tk.StringVar(self, "1")
        self._number_size = tk.StringVar(self, "11")
        self._numbers.row("위치", ttk.Combobox(self._numbers, textvariable=self._position,
                                             values=list(_POSITIONS), state="readonly", width=14))
        self._numbers.row("형식", ttk.Entry(self._numbers, textvariable=self._template, width=16),
                          hint="{n} 페이지 번호, {total} 마지막 번호")
        self._numbers.row("시작 번호", ttk.Spinbox(self._numbers, textvariable=self._start, from_=0, to=99999, width=8))
        self._numbers.row("크기 (pt)", ttk.Spinbox(self._numbers, textvariable=self._number_size,
                                                 from_=5, to=72, width=8))
        self._numbers.grid(sticky="ew", pady=4)

        self._watermark = _Section(self, "워터마크")
        self._mark_text = tk.StringVar(self, "대외비")
        self._mark_size = tk.StringVar(self, "60")
        self._mark_opacity = tk.StringVar(self, "30")
        self._mark_angle = tk.StringVar(self, "45")
        self._watermark.row("문구", ttk.Entry(self._watermark, textvariable=self._mark_text, width=16))
        self._watermark.row("크기 (pt)", ttk.Spinbox(self._watermark, textvariable=self._mark_size,
                                                   from_=8, to=300, width=8))
        self._watermark.row("불투명도 (%)", ttk.Spinbox(self._watermark, textvariable=self._mark_opacity,
                                                     from_=5, to=100, increment=5, width=8))
        self._watermark.row("각도", ttk.Spinbox(self._watermark, textvariable=self._mark_angle,
                                              from_=-90, to=90, increment=15, width=8))
        self._watermark.grid(sticky="ew", pady=4)

        self._compress = _Section(self, "이미지 압축")
        self._dpi = tk.StringVar(self, "150")
        self._quality = tk.StringVar(self, "70")
        self._compress.row("최대 해상도 (dpi)", ttk.Combobox(self._compress, textvariable=self._dpi,
                                                        values=_RESOLUTIONS, width=8))
        self._compress.row("JPEG 품질", ttk.Spinbox(self._compress, textvariable=self._quality,
                                                  from_=10, to=100, increment=5, width=8),
                           hint="낮을수록 파일이 작아짐, 70이 적당")
        self._compress.grid(sticky="ew", pady=4)

        self._protect = _Section(self, "암호")
        self._password = tk.StringVar(self)
        self._confirm = tk.StringVar(self)
        self._protect.row("암호", ttk.Entry(self._protect, textvariable=self._password, show="*", width=16))
        self._protect.row("암호 확인", ttk.Entry(self._protect, textvariable=self._confirm, show="*", width=16),
                          hint="저장한 파일을 열 때 필요합니다")
        self._protect.grid(sticky="ew", pady=4)

    def options(self) -> OutputOptions:
        """The options as entered; raises ValueError naming the field that is wrong."""
        numbers = watermark = compression = password = None
        if self._numbers.enabled.get():
            numbers = PageNumbers(
                position=_POSITIONS[self._position.get()],
                template=self._template.get(),
                start=_number(self._start, "페이지 번호의 시작 번호"),
                font_size=_number(self._number_size, "페이지 번호의 크기", float),
            )
        if self._watermark.enabled.get():
            watermark = Watermark(
                text=self._mark_text.get(),
                font_size=_number(self._mark_size, "워터마크 크기", float),
                opacity=_number(self._mark_opacity, "워터마크 불투명도", float) / 100,
                angle=_number(self._mark_angle, "워터마크 각도", float),
            )
        if self._compress.enabled.get():
            compression = Compression(
                dpi=_number(self._dpi, "이미지 압축의 최대 해상도"),
                quality=_number(self._quality, "이미지 압축의 JPEG 품질"),
            )
        if self._protect.enabled.get():
            if not self._password.get():
                raise ValueError("암호를 입력하거나 암호 옵션을 끄세요")
            if self._password.get() != self._confirm.get():
                raise ValueError("두 번 입력한 암호가 서로 다릅니다")
            password = self._password.get()
        return OutputOptions(numbers, watermark, compression, password)

    @property
    def decorates(self) -> bool:
        """Whether saved pages will look different from the workspace pages."""
        return any(s.enabled.get() for s in (self._numbers, self._watermark, self._compress))
