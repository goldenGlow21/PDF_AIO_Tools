"""The main window: page grid, toolbar, menus, output panel and status bar.

This module turns user actions into calls on the workspace, the library and
the export functions, and redraws afterwards. It holds no PDF logic itself.
"""

import ctypes
import sys
import tkinter as tk
import traceback
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pdf_aio import __version__
from pdf_aio.export import OutputOptions, named_paths, numbered_paths, write_image, write_pdf
from pdf_aio.gui.dialogs import ImageExportDialog, PasswordDialog, SplitDialog
from pdf_aio.gui.filedrop import FileDropTarget
from pdf_aio.gui.options_panel import OutputPanel
from pdf_aio.gui.pagegrid import PageGrid, Tile
from pdf_aio.gui.preview import PreviewWindow
from pdf_aio.library import (
    A4,
    IMAGE_SUFFIXES,
    PDF_SUFFIXES,
    SUPPORTED_SUFFIXES,
    Library,
    PasswordRequired,
    Source,
    SourceError,
    expand_paths,
)
from pdf_aio.workspace import PageRef, Run, Workspace, runs

APP_NAME = "PDF AIO Tools"
ICON = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
SOURCE_COLORS = ("#e5484d", "#3e63dd", "#30a46c", "#f76b15", "#8e4ec6", "#12a594", "#d6409f", "#978365")
BLANK_COLOR = "#a0a4ad"
ZOOM_STEPS = (80, 110, 150, 200, 260, 340)  # thumbnail sizes in unscaled pixels
MERGED_NAME = "병합"  # suggested file name when the pages come from several files

SHORTCUTS = """\
Ctrl+O    파일 추가
Ctrl+S    모든 페이지를 PDF 하나로 저장
Ctrl+Shift+S    선택한 페이지만 PDF로 저장
Ctrl+A    모두 선택
Delete    선택한 페이지 삭제
Ctrl+D    선택한 페이지 복제
Ctrl+L / Ctrl+R    왼쪽 / 오른쪽으로 회전
Ctrl+Z / Ctrl+Y    실행 취소 / 다시 실행
Enter    선택한 페이지 미리보기
Ctrl+휠, Ctrl+플러스 / 마이너스    썸네일 크기

클릭, Ctrl+클릭, Shift+클릭으로 페이지를 고르고, 빈 곳에서 끌면
사각형 안의 페이지가 선택됩니다. 선택한 페이지는 끌어서 옮깁니다.
페이지 사이에 파일을 끌어다 놓으면 그 자리에 들어갑니다."""


def _file_types(label: str, suffixes: Iterable[str]) -> tuple[str, str]:
    return label, " ".join(f"*{suffix}" for suffix in sorted(suffixes))


class App:
    def __init__(self, root: tk.Tk, files: Sequence[Path]) -> None:
        self.root = root
        self.library = Library()
        self.workspace = Workspace()
        self._saved_pages: tuple[PageRef, ...] = ()
        self._view = tk.StringVar(root, "pages")
        self._zoom = ZOOM_STEPS.index(150)
        self._preview: PreviewWindow | None = None
        self._scale = root.winfo_fpixels("1i") / 96

        root.title(APP_NAME)
        root.geometry(f"{self._px(1240)}x{self._px(800)}")
        root.minsize(self._px(760), self._px(520))
        root.iconbitmap(default=str(ICON))
        root.report_callback_exception = self._report_error
        root.protocol("WM_DELETE_WINDOW", self._close)

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._bind_keys()
        FileDropTarget(root, self._on_drop)
        self._refresh()
        if files:
            root.after_idle(self.add_paths, list(files))

    def _px(self, logical: float) -> int:
        return round(logical * self._scale)

    # ----- layout -------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = tk.Menu(self.root)
        file = tk.Menu(bar, tearoff=False)
        file.add_command(label="파일 추가...", accelerator="Ctrl+O", command=self.add_files)
        file.add_command(label="빈 페이지 넣기", command=self.insert_blank)
        file.add_separator()
        file.add_command(label="PDF로 저장...", accelerator="Ctrl+S", command=self.save_all)
        file.add_command(label="선택한 페이지만 PDF로 저장...", accelerator="Ctrl+Shift+S",
                         command=self.save_selection)
        file.add_command(label="여러 파일로 분할...", command=self.split)
        file.add_command(label="페이지를 이미지로 내보내기...", command=self.export_images)
        file.add_separator()
        file.add_command(label="끝내기", command=self._close)
        bar.add_cascade(label="파일", menu=file)

        edit = tk.Menu(bar, tearoff=False)
        edit.add_command(label="실행 취소", accelerator="Ctrl+Z", command=self.undo)
        edit.add_command(label="다시 실행", accelerator="Ctrl+Y", command=self.redo)
        edit.add_separator()
        edit.add_command(label="모두 선택", accelerator="Ctrl+A", command=self.select_all)
        edit.add_command(label="왼쪽으로 회전", accelerator="Ctrl+L", command=lambda: self.rotate(-90))
        edit.add_command(label="오른쪽으로 회전", accelerator="Ctrl+R", command=lambda: self.rotate(90))
        edit.add_command(label="복제", accelerator="Ctrl+D", command=self.duplicate)
        edit.add_command(label="맨 앞으로 이동", command=lambda: self.move_selection(0))
        edit.add_command(label="맨 뒤로 이동", command=lambda: self.move_selection(None))
        edit.add_command(label="순서 뒤집기", command=self.reverse)
        edit.add_command(label="삭제", accelerator="Del", command=self.delete)
        edit.add_separator()
        edit.add_command(label="모든 페이지 비우기", command=self.clear)
        bar.add_cascade(label="편집", menu=edit)

        view = tk.Menu(bar, tearoff=False)
        view.add_radiobutton(label="페이지별 보기", variable=self._view, value="pages", command=self._refresh)
        view.add_radiobutton(label="파일별 보기", variable=self._view, value="files", command=self._refresh)
        view.add_separator()
        view.add_command(label="썸네일 크게", accelerator="Ctrl++", command=lambda: self.zoom(1))
        view.add_command(label="썸네일 작게", accelerator="Ctrl+-", command=lambda: self.zoom(-1))
        view.add_command(label="미리보기", accelerator="Enter", command=self.open_preview)
        bar.add_cascade(label="보기", menu=view)

        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="키보드와 마우스", command=lambda: messagebox.showinfo(
            "키보드와 마우스", SHORTCUTS, parent=self.root))
        help_menu.add_command(label="프로그램 정보", command=lambda: messagebox.showinfo(
            "프로그램 정보", f"{APP_NAME} {__version__}\n\nPDF 페이지 병합, 분할, 순서 변경, 회전, 변환을 "
                       "이 컴퓨터 안에서 처리합니다. 파일은 밖으로 나가지 않습니다.", parent=self.root))
        bar.add_cascade(label="도움말", menu=help_menu)
        self.root.configure(menu=bar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 6, 6, 4))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._needs_selection: list[ttk.Widget] = []

        def button(text: str, command: Callable[[], object], needs_selection: bool = False) -> ttk.Button:
            widget = ttk.Button(bar, text=text, command=command)
            widget.pack(side="left", padx=2)
            if needs_selection:
                self._needs_selection.append(widget)
            return widget

        def gap() -> None:
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        button("파일 추가...", self.add_files)
        button("빈 페이지", self.insert_blank)
        gap()
        button("왼쪽 회전", lambda: self.rotate(-90), True)
        button("오른쪽 회전", lambda: self.rotate(90), True)
        button("복제", self.duplicate, True)
        button("삭제", self.delete, True)
        gap()
        self._undo_button = button("실행 취소", self.undo)
        self._redo_button = button("다시 실행", self.redo)
        gap()
        ttk.Label(bar, text="보기").pack(side="left", padx=(2, 4))
        for text, value in (("페이지별", "pages"), ("파일별", "files")):
            ttk.Radiobutton(bar, text=text, value=value, variable=self._view, style="Toolbutton",
                            command=self._refresh).pack(side="left")
        gap()
        ttk.Button(bar, text="-", width=3, command=lambda: self.zoom(-1)).pack(side="left")
        ttk.Button(bar, text="+", width=3, command=lambda: self.zoom(1)).pack(side="left", padx=2)

    def _build_body(self) -> None:
        self.grid = PageGrid(
            self.root, self.library, self._scale,
            on_move=self._on_move, on_open=self._on_open, on_menu=self._on_menu,
            on_selection=self._update_controls, on_empty_click=self.add_files, on_zoom=self.zoom,
        )
        self.grid.grid(row=1, column=0, sticky="nsew")
        self.grid.set_thumbnail_size(ZOOM_STEPS[self._zoom])

        side = ttk.Frame(self.root)
        side.grid(row=1, column=1, sticky="ns")
        self.panel = OutputPanel(side)
        self.panel.grid(row=0, column=0, sticky="new")
        actions = ttk.Frame(side, padding=(8, 4, 8, 8))
        actions.grid(row=1, column=0, sticky="sew")
        side.rowconfigure(1, weight=1)
        actions.columnconfigure(0, weight=1)
        ttk.Style(self.root).configure("Primary.TButton", font="TkHeadingFont", padding=(6, 6))
        self._needs_pages: list[ttk.Widget] = []
        for row, (text, command, style, needs) in enumerate((
            ("옵션 적용 미리보기", self.open_preview, "TButton", self._needs_pages),
            ("이미지로 내보내기...", self.export_images, "TButton", self._needs_pages),
            ("여러 파일로 분할...", self.split, "TButton", self._needs_pages),
            ("선택한 페이지만 저장...", self.save_selection, "TButton", self._needs_selection),
            ("PDF로 저장...", self.save_all, "Primary.TButton", self._needs_pages),
        )):
            widget = ttk.Button(actions, text=text, command=command, style=style)
            widget.grid(row=row, column=0, sticky="ew", pady=2)
            needs.append(widget)
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

    def _build_status(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 3))
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._message = tk.StringVar(self.root, "PDF나 이미지 파일을 추가해서 시작하세요.")
        self._counts = tk.StringVar(self.root)
        ttk.Label(bar, textvariable=self._message).pack(side="left")
        ttk.Label(bar, textvariable=self._counts).pack(side="right")
        self._progress_bar = ttk.Progressbar(bar, length=self._px(180), mode="determinate")

    def _bind_keys(self) -> None:
        def key(sequence: str, action: Callable[[], object], in_text_fields: bool = False) -> None:
            def handler(event: tk.Event) -> str | None:
                if not in_text_fields and isinstance(event.widget, ttk.Entry | tk.Entry):
                    return None  # Delete, Ctrl+A and the like belong to the text field
                action()
                return "break"
            self.root.bind(sequence, handler)
            # With Caps Lock on, Tk reports letters in upper case.
            name = sequence[1:-1].split("-")[-1]
            if len(name) == 1 and name.islower():
                self.root.bind(sequence.replace(f"-{name}>", f"-{name.upper()}>"), handler)

        key("<Control-o>", self.add_files, True)
        key("<Control-s>", self.save_all, True)
        key("<Control-Shift-S>", self.save_selection, True)
        key("<Control-a>", self.select_all)
        key("<Control-z>", self.undo)
        key("<Control-y>", self.redo)
        key("<Control-Shift-Z>", self.redo)
        key("<Control-d>", self.duplicate)
        key("<Control-l>", lambda: self.rotate(-90))
        key("<Control-r>", lambda: self.rotate(90))
        key("<Delete>", self.delete)
        key("<BackSpace>", self.delete)
        key("<Return>", self.open_preview)
        key("<Control-plus>", lambda: self.zoom(1), True)
        key("<Control-equal>", lambda: self.zoom(1), True)
        key("<Control-minus>", lambda: self.zoom(-1), True)

    # ----- state shown in the window ---------------------------------------

    def _color(self, source: Source) -> str:
        return BLANK_COLOR if source.path is None else SOURCE_COLORS[source.id % len(SOURCE_COLORS)]

    def _page_tile(self, position: int, ref: PageRef) -> Tile:
        source = self.library.get(ref.source)
        detail = source.name if source.path is None else f"{source.name} {ref.index + 1}페이지"
        return Tile(range(position, position + 1), ref, str(position + 1), detail, self._color(source))

    def _run_tile(self, run: Run) -> Tile:
        refs = self.workspace.pages[run.start:run.stop]
        source = self.library.get(run.source)
        total = source.doc.page_count
        indices = [ref.index for ref in refs]
        if indices == list(range(total)):
            detail = f"{total}페이지"
        elif len(indices) == 1:
            detail = f"{indices[0] + 1}페이지 (전체 {total})"
        elif indices == list(range(indices[0], indices[0] + len(indices))):
            detail = f"{indices[0] + 1}-{indices[-1] + 1}페이지 (전체 {total})"
        else:
            detail = f"전체 {total}페이지 중 {len(indices)}페이지"
        return Tile(run.indices, refs[0], source.name, detail, self._color(source), stacked=len(refs) > 1)

    def _refresh(self, select: Iterable[int] = ()) -> None:
        """Rebuild the tiles from the workspace and update everything that depends on it."""
        pages = self.workspace.pages
        if self._view.get() == "files":
            tiles = [self._run_tile(run) for run in runs(pages)]
        else:
            tiles = [self._page_tile(i, ref) for i, ref in enumerate(pages)]
        self.grid.set_tiles(tiles, set(select))
        dirty = bool(pages) and pages != self._saved_pages
        self.root.title(f"{APP_NAME} - {len(pages)}페이지{' *' if dirty else ''}" if pages else APP_NAME)
        self._update_controls()
        if self._preview is not None and self._preview.winfo_exists():
            self._preview.refresh()

    def _update_controls(self) -> None:
        selected = self.grid.selected_pages
        pages = self.workspace.pages
        files = {ref.source for ref in pages if self.library.get(ref.source).path is not None}
        counts = f"{len(pages)}페이지, 파일 {len(files)}개" if pages else ""
        self._counts.set(f"{len(selected)}페이지 선택됨    {counts}" if selected else counts)
        for widget in self._needs_selection:
            widget.state(["!disabled"] if selected else ["disabled"])
        for widget in self._needs_pages:
            widget.state(["!disabled"] if pages else ["disabled"])
        self._undo_button.state(["!disabled"] if self.workspace.can_undo else ["disabled"])
        self._redo_button.state(["!disabled"] if self.workspace.can_redo else ["disabled"])

    def _say(self, message: str) -> None:
        self._message.set(message)

    @contextmanager
    def _busy(self, message: str) -> Iterator[None]:
        self._say(message)
        self.root.configure(cursor="watch")
        self._progress_bar.configure(value=0)
        self._progress_bar.pack(side="right", padx=8)
        self.root.update_idletasks()
        try:
            yield
        finally:
            self._progress_bar.pack_forget()
            self.root.configure(cursor="")

    def _progress(self, done: int, total: int) -> None:
        self._progress_bar.configure(maximum=max(total, 1), value=done)
        self.root.update_idletasks()

    def _report_error(self, kind: type[BaseException], error: BaseException, trace: object) -> None:
        if sys.stderr is not None:  # a windowed build has no console
            traceback.print_exception(kind, error, trace)
        messagebox.showerror(APP_NAME, f"문제가 발생했습니다.\n\n{kind.__name__}: {error}", parent=self.root)

    # ----- adding pages -------------------------------------------------------

    def add_files(self) -> None:
        names = filedialog.askopenfilenames(
            parent=self.root, title="PDF 또는 이미지 파일 추가",
            filetypes=[_file_types("PDF와 이미지", SUPPORTED_SUFFIXES), _file_types("PDF", PDF_SUFFIXES),
                       _file_types("이미지", IMAGE_SUFFIXES), ("모든 파일", "*.*")],
        )
        if names:
            self.add_paths([Path(name) for name in names])

    def add_paths(self, paths: list[Path], at: int | None = None) -> None:
        """Open the files and insert their pages at gap `at`, or at the end."""
        files = expand_paths(paths)
        refs: list[PageRef] = []
        problems: list[str] = []
        opened = 0
        with self._busy(f"파일 {len(files)}개를 여는 중..."):
            for done, path in enumerate(files):
                source = self._open(path, problems)
                if source is not None:
                    opened += 1
                    refs.extend(PageRef(source.id, i) for i in range(source.doc.page_count))
                self._progress(done + 1, len(files))
        if refs:
            had_pages = bool(self.workspace.pages)
            placed = self.workspace.insert(len(self.workspace) if at is None else at, refs)
            # Highlight what arrived only when it joins existing pages.
            self._refresh(select=placed if had_pages else ())
            self._say(f"파일 {opened}개에서 {len(refs)}페이지를 추가했습니다.")
        elif not files:
            self._say("그 위치에서 PDF나 이미지 파일을 찾지 못했습니다.")
        if problems:
            messagebox.showwarning("추가하지 못한 파일", "\n".join(problems), parent=self.root)

    def _open(self, path: Path, problems: list[str]) -> Source | None:
        password = None
        while True:
            try:
                return self.library.open_file(path, password)
            except PasswordRequired:
                password = PasswordDialog(self.root, path.name, retry=password is not None).run()
                if password is None:
                    problems.append(f"{path.name}: 암호를 입력하지 않아 건너뛰었습니다")
                    return None
            except SourceError as exc:
                problems.append(str(exc))
                return None

    def _on_drop(self, paths: list[Path], x: int, y: int) -> None:
        slot = self.grid.slot_at_screen(x, y)
        at = None
        if slot is not None:
            tiles = self.grid.tiles
            at = tiles[slot].pages.start if slot < len(tiles) else len(self.workspace)
        self.add_paths(paths, at)

    def insert_blank(self) -> None:
        """Insert a blank page after the selection, as large as the page before it."""
        selected = self.grid.selected_pages
        at = selected[-1] + 1 if selected else len(self.workspace)
        width, height = self.library.size(self.workspace.pages[at - 1]) if at else (A4.width, A4.height)
        source = self.library.add_blank(width, height)
        self._refresh(select=self.workspace.insert(at, [PageRef(source.id, 0)]))

    # ----- editing --------------------------------------------------------------

    def _selection_or_hint(self) -> list[int]:
        selected = self.grid.selected_pages
        if not selected:
            self._say("먼저 페이지를 하나 이상 선택하세요.")
        return selected

    def rotate(self, degrees: int) -> None:
        if selected := self._selection_or_hint():
            self.workspace.rotate(selected, degrees)
            self._refresh(select=selected)

    def delete(self) -> None:
        if selected := self._selection_or_hint():
            self.workspace.remove(selected)
            self._refresh()
            self._say(f"{len(selected)}페이지를 삭제했습니다. Ctrl+Z로 되돌릴 수 있습니다.")

    def duplicate(self) -> None:
        if selected := self._selection_or_hint():
            self._refresh(select=self.workspace.duplicate(selected))

    def reverse(self) -> None:
        """Reverse the selected pages, or every page when nothing is selected."""
        selected = self.grid.selected_pages
        self.workspace.reverse(selected or range(len(self.workspace)))
        self._refresh(select=selected)

    def move_selection(self, target: int | None) -> None:
        """Move the selection to gap `target`; None means the end."""
        if selected := self._selection_or_hint():
            self._refresh(select=self.workspace.move(selected, len(self.workspace) if target is None else target))

    def _on_move(self, tiles: list[int], slot: int) -> None:
        shown = self.grid.tiles
        pages = [page for i in tiles for page in shown[i].pages]
        target = shown[slot].pages.start if slot < len(shown) else len(self.workspace)
        self._refresh(select=self.workspace.move(pages, target))

    def clear(self) -> None:
        if self.workspace.pages and messagebox.askyesno(
                "모든 페이지 비우기", "작업 공간의 페이지를 모두 비울까요? Ctrl+Z로 되돌릴 수 있습니다.",
                parent=self.root):
            self.workspace.clear()
            self._refresh()

    def undo(self) -> None:
        if self.workspace.undo():
            self._refresh()

    def redo(self) -> None:
        if self.workspace.redo():
            self._refresh()

    def select_all(self) -> None:
        self.grid.select_all()

    def zoom(self, step: int) -> None:
        self._zoom = min(max(self._zoom + step, 0), len(ZOOM_STEPS) - 1)
        self.grid.set_thumbnail_size(ZOOM_STEPS[self._zoom])

    # ----- viewing ----------------------------------------------------------------

    def _on_open(self, tile: int) -> None:
        self.open_preview(self.grid.tiles[tile].pages.start)

    def open_preview(self, position: int | None = None) -> None:
        if not self.workspace.pages:
            return
        if position is None:
            selected = self.grid.selected_pages
            position = selected[0] if selected else 0
        if self._preview is None or not self._preview.winfo_exists():
            self._preview = PreviewWindow(self.root, self.library, lambda: self.workspace.pages,
                                          self.panel.options, as_saved=self.panel.decorates)
        self._preview.show(position)
        self._preview.lift()
        self._preview.focus_set()

    def _on_menu(self, tile: int | None, x: int, y: int) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        if tile is None:
            menu.add_command(label="파일 추가...", command=self.add_files)
            menu.add_command(label="빈 페이지 넣기", command=self.insert_blank)
            menu.add_command(label="모두 선택", command=self.select_all)
        else:
            menu.add_command(label="미리보기", command=lambda: self._on_open(tile))
            menu.add_separator()
            menu.add_command(label="왼쪽으로 회전", command=lambda: self.rotate(-90))
            menu.add_command(label="오른쪽으로 회전", command=lambda: self.rotate(90))
            menu.add_command(label="복제", command=self.duplicate)
            menu.add_command(label="뒤에 빈 페이지 넣기", command=self.insert_blank)
            menu.add_command(label="맨 앞으로 이동", command=lambda: self.move_selection(0))
            menu.add_command(label="맨 뒤로 이동", command=lambda: self.move_selection(None))
            menu.add_command(label="순서 뒤집기", command=self.reverse)
            menu.add_separator()
            menu.add_command(label="선택한 페이지만 PDF로 저장...", command=self.save_selection)
            menu.add_command(label="선택한 페이지를 이미지로 내보내기...", command=self.export_images)
            menu.add_separator()
            menu.add_command(label="삭제", command=self.delete)
        menu.tk_popup(x, y)

    # ----- output -----------------------------------------------------------------

    def _options(self) -> OutputOptions | None:
        try:
            return self.panel.options()
        except ValueError as exc:
            messagebox.showerror("옵션을 확인하세요", str(exc), parent=self.root)
            return None

    def _default_place(self, refs: Sequence[PageRef]) -> tuple[str | None, str]:
        """A folder and file stem to suggest: those of the single source, or a generic name."""
        files = [source for source in dict.fromkeys(self.library.get(ref.source) for ref in refs)
                 if source.path is not None]
        if not files:
            return None, MERGED_NAME
        return str(files[0].path.parent), Path(files[0].name).stem if len(files) == 1 else MERGED_NAME

    def _ask_base(self, title: str, refs: Sequence[PageRef], suffix: str, kind: str) -> Path | None:
        """Ask for a folder and a base name; numbered or per-file names are derived from it."""
        folder, stem = self._default_place(refs)
        name = filedialog.asksaveasfilename(
            parent=self.root, title=title, initialdir=folder, initialfile=f"{stem}{suffix}",
            defaultextension=suffix, filetypes=[(kind, f"*{suffix}")], confirmoverwrite=False,
        )
        return Path(name) if name else None

    def _confirm_replace(self, paths: Sequence[Path]) -> bool:
        existing = [path for path in paths if path.exists()]
        if not existing:
            return True
        names = "\n".join(path.name for path in existing[:5]) + ("\n..." if len(existing) > 5 else "")
        return messagebox.askyesno(
            "파일 덮어쓰기", f"{existing[0].parent} 폴더에 같은 이름의 파일이 {len(existing)}개 있습니다.\n\n"
                            f"{names}\n\n덮어쓸까요?", parent=self.root)

    def _write_pdfs(self, jobs: Sequence[tuple[Sequence[PageRef], Path]], options: OutputOptions) -> int:
        """Write each page list to its file; on failure, explain and return how many were written."""
        total_pages = sum(len(refs) for refs, _ in jobs)
        done = 0
        for written, (refs, path) in enumerate(jobs):
            try:
                write_pdf(self.library, refs, path, options,
                          lambda n, _total, base=done: self._progress(base + n, total_pages))
            except OSError as exc:
                messagebox.showerror(
                    "저장하지 못했습니다", f"{path}\n\n{exc.strerror or exc}\n\n다른 프로그램에서 이 파일을 "
                                     "열어 두었다면 닫은 뒤 다시 시도하세요.", parent=self.root)
                return written
            done += len(refs)
        return len(jobs)

    def save_all(self) -> None:
        self._save(list(self.workspace.pages), "모든 페이지를 PDF 하나로 저장", "")

    def save_selection(self) -> None:
        if selected := self._selection_or_hint():
            self._save([self.workspace.pages[i] for i in selected], "선택한 페이지만 PDF로 저장", "_선택")

    def _save(self, refs: list[PageRef], title: str, suggest: str) -> None:
        if not refs or (options := self._options()) is None:
            return
        folder, stem = self._default_place(refs)
        name = filedialog.asksaveasfilename(
            parent=self.root, title=title, initialdir=folder, initialfile=f"{stem}{suggest}.pdf",
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
        )
        if not name:
            return
        path = Path(name)
        with self._busy(f"{len(refs)}페이지를 저장하는 중..."):
            written = self._write_pdfs([(refs, path)], options)
        if written:
            self._mark_saved(f"{len(refs)}페이지를 {path}에 저장했습니다 ({path.stat().st_size / 1e6:.1f} MB).")

    def split(self) -> None:
        pages = self.workspace.pages
        if not pages or (options := self._options()) is None:
            return
        dialog = SplitDialog(self.root, pages)
        groups = dialog.run()
        if not groups:
            return
        base = self._ask_base("분할한 파일을 저장할 폴더와 기본 이름 정하기", pages, ".pdf", "PDF")
        if base is None:
            return
        if dialog.by_file:
            stems = [Path(self.library.get(pages[group[0]].source).name).stem for group in groups]
            paths = named_paths(base.parent, stems, ".pdf")
        else:
            paths = numbered_paths(base, len(groups))
        if not self._confirm_replace(paths):
            return
        with self._busy(f"파일 {len(paths)}개를 저장하는 중..."):
            jobs = [([pages[i] for i in group], path) for group, path in zip(groups, paths, strict=True)]
            written = self._write_pdfs(jobs, options)
        if written:
            self._mark_saved(f"PDF 파일 {written}개를 {base.parent}에 저장했습니다.")

    def export_images(self) -> None:
        pages = self.workspace.pages
        if not pages:
            return
        selected = self.grid.selected_pages
        choice = ImageExportDialog(self.root, len(pages), len(selected)).run()
        if choice is None:
            return
        refs = [pages[i] for i in (selected if choice.selection_only else range(len(pages)))]
        kind = "PNG" if choice.suffix == ".png" else "JPEG"
        base = self._ask_base("이미지를 저장할 폴더와 기본 이름 정하기", refs, choice.suffix, kind)
        if base is None:
            return
        paths = numbered_paths(base.with_suffix(choice.suffix), len(refs))
        if not self._confirm_replace(paths):
            return
        with self._busy(f"이미지 {len(refs)}개를 내보내는 중..."):
            for done, (ref, path) in enumerate(zip(refs, paths, strict=True)):
                try:
                    write_image(self.library, ref, path, choice.dpi)
                except OSError as exc:
                    messagebox.showerror("저장하지 못했습니다", f"{path}\n\n{exc.strerror or exc}", parent=self.root)
                    return
                self._progress(done + 1, len(refs))
        self._mark_saved(f"이미지 {len(refs)}개를 {base.parent}에 내보냈습니다.")

    def _mark_saved(self, message: str) -> None:
        self._saved_pages = self.workspace.pages
        self._refresh(select=self.grid.selected_pages)
        self._say(message)

    def _close(self) -> None:
        pages = self.workspace.pages
        if pages and pages != self._saved_pages and not messagebox.askyesno(
                "닫기", "현재 페이지 배치를 저장하지 않았습니다. 그래도 닫을까요?", parent=self.root):
            return
        self.root.destroy()


def run(files: Sequence[Path]) -> None:
    # Without DPI awareness Windows scales the window as a bitmap and blurs
    # every thumbnail; with it, Tk sizes fonts for the real screen density.
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    # Group the window under its own taskbar icon instead of python.exe's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFAIOTools.App")
    root = tk.Tk()
    App(root, files)
    root.mainloop()
