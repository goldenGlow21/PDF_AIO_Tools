"""Source documents that workspace pages point into.

Every source is held as an in-memory PDF. PDF files are read into memory in
full, so the original file is never locked and a save may overwrite it.
Images become pages on A4 paper, and blank pages are generated documents.
Sources are never removed: the undo history may still point at them.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from pymupdf import mupdf

from pdf_aio.workspace import PageRef

PDF_SUFFIXES = frozenset({".pdf"})
# Raster formats MuPDF decodes. WebP is absent because MuPDF cannot read it.
IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff",
    ".jp2", ".jpx", ".pnm", ".pbm", ".pgm", ".ppm",
})
SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES

A4 = pymupdf.paper_rect("a4")
BLANK_NAME = "빈 페이지"


class SourceError(Exception):
    """A file could not be turned into a source document."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path.name}: {reason}")
        self.path = path
        self.reason = reason


class PasswordRequired(SourceError):
    """The PDF is encrypted and the password given was missing or wrong."""


@dataclass(frozen=True, eq=False)
class Source:
    id: int
    name: str  # what the interface shows: the file name, or the label of a blank page
    path: Path | None  # None for generated blank pages
    doc: pymupdf.Document


def natural_key(name: str) -> list:
    """Sort key that puts "scan2" before "scan10", the way Explorer does."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)]


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    """Turn dropped or chosen paths into the files that should be opened.

    Folders contribute their supported files (not recursively). Within each
    folder, and among loose files, names are sorted naturally, because the
    order Explorer hands over follows the click order rather than the names.
    """
    files: list[Path] = []
    loose: list[Path] = []
    for path in paths:
        if path.is_dir():
            inside = [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
            files.extend(sorted(inside, key=lambda p: natural_key(p.name)))
        else:
            loose.append(path)
    return sorted(loose, key=lambda p: natural_key(p.name)) + files


def _image_document(data: bytes, suffix: str) -> pymupdf.Document:
    """Place each frame of an image file on its own A4 page, fitted and centred.

    The orientation of the paper follows the image. MuPDF applies the JPEG
    EXIF orientation while decoding, so phone photos come out upright.
    """
    image = pymupdf.open(stream=data, filetype=suffix.lstrip("."))
    frames = pymupdf.open("pdf", image.convert_to_pdf())
    pages = pymupdf.open()
    for frame in frames:
        if frame.rect.width > frame.rect.height:
            width, height = A4.height, A4.width
        else:
            width, height = A4.width, A4.height
        page = pages.new_page(width=width, height=height)
        page.show_pdf_page(page.rect, frames, frame.number)
    return pages


class Library:
    def __init__(self) -> None:
        self._sources: dict[int, Source] = {}

    def _add(self, name: str, path: Path | None, doc: pymupdf.Document) -> Source:
        source = Source(len(self._sources), name, path, doc)
        self._sources[source.id] = source
        return source

    def open_file(self, path: Path, password: str | None = None) -> Source:
        """Read a PDF or image file into a new source.

        Raises PasswordRequired when the PDF is encrypted and `password` is
        missing or wrong, and SourceError for anything else that prevents
        the file from being used.
        """
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise SourceError(path, "PDF나 지원하는 이미지 형식이 아닙니다")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SourceError(path, exc.strerror or str(exc)) from exc
        is_pdf = suffix in PDF_SUFFIXES
        try:
            doc = pymupdf.open(stream=data, filetype="pdf") if is_pdf else _image_document(data, suffix)
        # MuPDF reports unreadable PDFs as FileDataError when opening, and
        # unreadable images as one of its own errors when decoding them.
        except (pymupdf.FileDataError, mupdf.FzErrorBase) as exc:
            kind = "PDF" if is_pdf else "이미지"
            raise SourceError(path, f"파일이 손상되었거나 올바른 {kind} 파일이 아닙니다") from exc
        if doc.needs_pass:
            if password is None:
                raise PasswordRequired(path, "암호로 보호된 PDF입니다")
            if not doc.authenticate(password):
                raise PasswordRequired(path, "암호가 올바르지 않습니다")
        if doc.page_count == 0:
            raise SourceError(path, "페이지가 없는 파일입니다")
        return self._add(path.name, path, doc)

    def add_blank(self, width: float, height: float) -> Source:
        doc = pymupdf.open()
        doc.new_page(width=width, height=height)
        return self._add(BLANK_NAME, None, doc)

    def get(self, source_id: int) -> Source:
        return self._sources[source_id]

    def page(self, ref: PageRef) -> pymupdf.Page:
        return self._sources[ref.source].doc[ref.index]

    def size(self, ref: PageRef) -> tuple[float, float]:
        """Width and height in points as the page appears, rotations included."""
        rect = self.page(ref).rect
        if ref.rotation in (90, 270):
            return rect.height, rect.width
        return rect.width, rect.height

    def pixmap(self, ref: PageRef, zoom: float) -> pymupdf.Pixmap:
        """Render the page as it will appear in the output, at `zoom` pixels per point."""
        matrix = pymupdf.Matrix(zoom, zoom).prerotate(ref.rotation)
        return self.page(ref).get_pixmap(matrix=matrix, alpha=False)
