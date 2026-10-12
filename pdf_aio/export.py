"""Writing workspace pages out as PDF files or page images.

Pages are copied from the sources with insert_pdf, so text, links, form
fields and annotations survive unchanged. Page numbers and watermarks are
drawn upright on a separate overlay document, whose font is subset there and
which is then stamped onto each output page. Drawing on the output pages
directly would embed the full 3.5 MB CJK font, and subsetting the output
itself would also rewrite the fonts of the source files.
"""

import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from pymupdf import mupdf

from pdf_aio.library import Library
from pdf_aio.workspace import PageRef

Progress = Callable[[int, int], None]  # (pages done, pages in total)

POSITIONS = ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right")
IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg"}

# Distance from the paper edge to the page number, in points (0.4 inch).
_EDGE = 29
_WATERMARK_GRAY = (0.45, 0.45, 0.45)


@dataclass(frozen=True)
class PageNumbers:
    position: str = "bottom-center"
    template: str = "{n}"  # {n} is the page number, {total} the last page number
    start: int = 1
    font_size: float = 11

    def __post_init__(self) -> None:
        if self.position not in POSITIONS:
            raise ValueError(f'페이지 번호 위치 "{self.position}"는 {", ".join(POSITIONS)} 중 하나여야 합니다')
        try:
            self.template.format(n=1, total=1)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                f'페이지 번호 형식 "{self.template}"에는 {{n}}과 {{total}}만 쓸 수 있습니다'
            ) from exc
        if self.font_size <= 0:
            raise ValueError(f"페이지 번호 크기는 0보다 커야 합니다 (입력: {self.font_size:g})")

    def text(self, position: int, count: int) -> str:
        return self.template.format(n=self.start + position, total=self.start + count - 1)


@dataclass(frozen=True)
class Watermark:
    text: str
    font_size: float = 60
    opacity: float = 0.3  # 0 is invisible, 1 is solid
    angle: float = 45  # counterclockwise degrees

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("워터마크 문구가 비어 있습니다")
        if not 0 < self.opacity <= 1:
            raise ValueError(f"워터마크 불투명도는 1에서 100% 사이여야 합니다 (입력: {self.opacity * 100:g}%)")
        if self.font_size <= 0:
            raise ValueError(f"워터마크 크기는 0보다 커야 합니다 (입력: {self.font_size:g})")


@dataclass(frozen=True)
class Compression:
    """Downsample images above `dpi` and re-encode them as JPEG at `quality`."""

    dpi: int = 150
    quality: int = 70

    def __post_init__(self) -> None:
        if not 36 <= self.dpi <= 1200:
            raise ValueError(f"이미지 해상도는 36에서 1200 dpi 사이여야 합니다 (입력: {self.dpi})")
        if not 1 <= self.quality <= 100:
            raise ValueError(f"JPEG 품질은 1에서 100 사이여야 합니다 (입력: {self.quality})")


@dataclass(frozen=True)
class OutputOptions:
    page_numbers: PageNumbers | None = None
    watermark: Watermark | None = None
    compression: Compression | None = None
    password: str | None = field(default=None, repr=False)


PLAIN = OutputOptions()  # pages copied exactly as they are


def build(
    library: Library,
    refs: Sequence[PageRef],
    options: OutputOptions = PLAIN,
    progress: Progress | None = None,
) -> pymupdf.Document:
    """Assemble the pages into a new document with the options applied."""
    if not refs:
        raise ValueError("저장할 페이지가 없습니다")
    out = pymupdf.open()
    start = 0
    while start < len(refs):
        # Copy consecutive pages of one source in a single call, so links
        # between them keep working. final=False keeps the graft map, which
        # stops fonts shared by many pages from being copied once per call.
        stop = start + 1
        while (stop < len(refs) and refs[stop].source == refs[start].source
               and refs[stop].index == refs[stop - 1].index + 1):
            stop += 1
        out.insert_pdf(library.get(refs[start].source).doc,
                       from_page=refs[start].index, to_page=refs[stop - 1].index, final=False)
        for n in range(start, stop):
            if refs[n].rotation:
                out[n].set_rotation((out[n].rotation + refs[n].rotation) % 360)
        start = stop
        if progress:
            progress(start, len(refs))
    _decorate(out, options, range(len(refs)), len(refs))
    if options.compression:
        _compress(out, options.compression)
    return out


def _decorate(out: pymupdf.Document, options: OutputOptions, positions: Sequence[int], count: int) -> None:
    """Stamp page numbers and the watermark onto every page of `out`.

    `positions[i]` is the place of out[i] within a file of `count` pages,
    which lets a single page preview carry the number it will really get.
    """
    if not options.page_numbers and not options.watermark:
        return
    font = pymupdf.Font("cjk")  # Droid Sans Fallback: Latin, Hangul, Kana and Han
    overlay = pymupdf.open()
    for page, position in zip(out, positions, strict=True):
        sheet = overlay.new_page(width=page.rect.width, height=page.rect.height)
        if options.watermark:
            _draw_watermark(sheet, font, options.watermark)
        if options.page_numbers:
            _draw_page_number(sheet, font, options.page_numbers.text(position, count), options.page_numbers)
    overlay.subset_fonts()
    for page in out:
        # The overlay is drawn in the orientation the reader sees. Stamping
        # happens in unrotated page space, so the overlay is turned by the
        # page rotation to land upright again.
        rotation = page.rotation
        page.set_rotation(0)
        page.show_pdf_page(page.rect, overlay, page.number, rotate=rotation)
        page.set_rotation(rotation)


def _draw_watermark(sheet: pymupdf.Page, font: pymupdf.Font, mark: Watermark) -> None:
    centre = pymupdf.Point(sheet.rect.width / 2, sheet.rect.height / 2)
    width = font.text_length(mark.text, fontsize=mark.font_size)
    writer = pymupdf.TextWriter(sheet.rect)
    # 0.35 em below the centre puts the middle of capital letters on it.
    writer.append((centre.x - width / 2, centre.y + mark.font_size * 0.35), mark.text,
                  font=font, fontsize=mark.font_size)
    writer.write_text(sheet, color=_WATERMARK_GRAY, opacity=mark.opacity,
                      morph=(centre, pymupdf.Matrix(mark.angle)))


def _draw_page_number(sheet: pymupdf.Page, font: pymupdf.Font, text: str, numbers: PageNumbers) -> None:
    vertical, horizontal = numbers.position.split("-")
    width = font.text_length(text, fontsize=numbers.font_size)
    x = {"left": _EDGE, "center": (sheet.rect.width - width) / 2,
         "right": sheet.rect.width - _EDGE - width}[horizontal]
    y = _EDGE + numbers.font_size * 0.7 if vertical == "top" else sheet.rect.height - _EDGE
    writer = pymupdf.TextWriter(sheet.rect)
    writer.append((x, y), text, font=font, fontsize=numbers.font_size)
    writer.write_text(sheet, color=(0, 0, 0))


def _compress(out: pymupdf.Document, compression: Compression) -> None:
    """Downsample and re-encode colour and gray images; leave 1-bit scans alone.

    Document.rewrite_images uses MuPDF's averaging resampler, which only
    shrinks by whole factors and so leaves a 280 dpi image untouched when
    asked for 150. The bicubic resampler reaches the requested resolution.
    """
    options = mupdf.PdfImageRewriterOptions()
    # Images only slightly above the target are not worth a resampling pass.
    threshold = compression.dpi * 5 // 4
    for kind in ("color_lossy", "color_lossless", "gray_lossy", "gray_lossless"):
        setattr(options, f"{kind}_image_recompress_method", mupdf.FZ_RECOMPRESS_JPEG)
        setattr(options, f"{kind}_image_recompress_quality", str(compression.quality))
        setattr(options, f"{kind}_image_subsample_method", mupdf.FZ_SUBSAMPLE_BICUBIC)
        setattr(options, f"{kind}_image_subsample_threshold", threshold)
        setattr(options, f"{kind}_image_subsample_to", compression.dpi)
    options.recompress_when = mupdf.FZ_RECOMPRESS_WHEN_SMALLER
    out.rewrite_images(options=options)


def write_pdf(
    library: Library,
    refs: Sequence[PageRef],
    path: Path,
    options: OutputOptions = PLAIN,
    progress: Progress | None = None,
) -> int:
    """Write the pages to `path` and return the size of the file in bytes.

    The file is written beside the target and then moved over it, so a
    failure never leaves a half written PDF where the old one was.
    """
    doc = build(library, refs, options, progress)
    save_args: dict = {"garbage": 3, "deflate": True, "use_objstms": True}
    if options.compression:
        save_args["garbage"] = 4  # also merge identical objects, such as fonts repeated across files
    if options.password:
        save_args.update(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                         user_pw=options.password, owner_pw=options.password)
    handle, temp = tempfile.mkstemp(suffix=".pdf", dir=path.parent)
    os.close(handle)
    try:
        doc.save(temp, **save_args)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    finally:
        doc.close()
    return path.stat().st_size


def preview_pixmap(
    library: Library, refs: Sequence[PageRef], position: int, options: OutputOptions, zoom: float
) -> pymupdf.Pixmap:
    """Render one page as `write_pdf` would produce it, including its page number."""
    out = build(library, [refs[position]], OutputOptions(compression=options.compression))
    _decorate(out, options, [position], len(refs))
    return out[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)


def write_image(library: Library, ref: PageRef, path: Path, dpi: int) -> None:
    """Render one page to a PNG or JPEG file, chosen by the suffix of `path`."""
    pixmap = library.pixmap(ref, dpi / 72)
    pixmap.set_dpi(dpi, dpi)
    if path.suffix.lower() == ".jpg":
        pixmap.save(path, jpg_quality=90)
    else:
        pixmap.save(path)


def numbered_paths(base: Path, count: int) -> list[Path]:
    """report.pdf -> report_01.pdf, report_02.pdf, ... padded so they sort."""
    width = max(2, len(str(count)))
    return [base.with_name(f"{base.stem}_{n:0{width}d}{base.suffix}") for n in range(1, count + 1)]


def named_paths(folder: Path, stems: Sequence[str], suffix: str) -> list[Path]:
    """One path per stem; repeated stems get " (2)", " (3)" like Explorer copies."""
    seen: dict[str, int] = {}
    paths = []
    for stem in stems:
        seen[stem.casefold()] = seen.get(stem.casefold(), 0) + 1
        count = seen[stem.casefold()]
        paths.append(folder / (f"{stem}{suffix}" if count == 1 else f"{stem} ({count}){suffix}"))
    return paths
