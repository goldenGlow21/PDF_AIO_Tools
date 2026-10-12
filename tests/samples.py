"""Small PDF and image files generated on the fly for the tests."""

from pathlib import Path

import pymupdf


def make_pdf(path: Path, pages: int, label: str, width: float = 595, height: float = 842) -> Path:
    """A PDF whose page i carries the text "<label>-<i+1>" near its top left corner."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((40, 60), f"{label}-{i + 1}", fontsize=20)
    doc.save(path)
    return path


def make_encrypted_pdf(path: Path, password: str) -> Path:
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 60), "secret page", fontsize=20)
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    return path


def make_image(path: Path, width: int, height: int) -> Path:
    """A solid image in a format chosen by the suffix (.png or .jpg)."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.clear_with(200)
    pixmap.save(path)
    return path


def make_photo_pdf(path: Path, pixels_wide: int) -> Path:
    """A Letter page covered by one striped JPEG, `pixels_wide` pixels across."""
    tall = int(pixels_wide * 11 / 8.5)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, pixels_wide, tall), False)
    pixmap.clear_with(255)
    for y in range(0, tall, 40):
        pixmap.set_rect(pymupdf.IRect(0, y, pixels_wide, y + 20), ((y * 7) % 256, (y * 3) % 256, 90))
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(page.rect, stream=pixmap.tobytes("jpg", jpg_quality=95))
    doc.save(path)
    return path
