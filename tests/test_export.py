import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_aio.export import (
    Compression,
    OutputOptions,
    PageNumbers,
    Watermark,
    build,
    named_paths,
    numbered_paths,
    preview_pixmap,
    write_image,
    write_pdf,
)
from pdf_aio.library import Library
from pdf_aio.workspace import PageRef
from tests.samples import make_pdf, make_photo_pdf


def visual_lines(page: pymupdf.Page) -> list[tuple[str, pymupdf.Rect, pymupdf.Point]]:
    """Text lines of a page with their box and writing direction as the reader sees them.

    MuPDF reports text in unrotated page space; the rotation matrix turns
    that into the orientation shown on screen.
    """
    turn = page.rotation_matrix
    spin = pymupdf.Matrix(turn.a, turn.b, turn.c, turn.d, 0, 0)
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"])
            lines.append((text, pymupdf.Rect(line["bbox"]) * turn, pymupdf.Point(line["dir"]) * spin))
    return lines


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.library = Library()

    def tearDown(self):
        self._tmp.cleanup()

    def source(self, name: str, pages: int, label: str, **size) -> int:
        return self.library.open_file(make_pdf(self.dir / name, pages, label, **size)).id


class BuildTest(ExportTestCase):
    def test_pages_follow_the_workspace_order_with_added_rotation(self):
        a = self.source("a.pdf", 3, "a")
        b = self.source("b.pdf", 2, "b")
        refs = [PageRef(b, 1), PageRef(a, 0), PageRef(a, 1, 90), PageRef(b, 0), PageRef(a, 2, 270)]
        out = build(self.library, refs)
        self.assertEqual([p.get_text().strip() for p in out], ["b-2", "a-1", "a-2", "b-1", "a-3"])
        self.assertEqual([p.rotation for p in out], [0, 0, 90, 0, 270])

    def test_added_rotation_combines_with_the_page_own_rotation(self):
        doc = pymupdf.open()
        doc.new_page().set_rotation(90)
        doc.save(self.dir / "turned.pdf")
        source = self.library.open_file(self.dir / "turned.pdf")
        out = build(self.library, [PageRef(source.id, 0, 270)])
        self.assertEqual(out[0].rotation, 0)

    def test_links_between_pages_copied_together_keep_working(self):
        doc = pymupdf.open()
        for _ in range(3):
            doc.new_page()
        doc[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 50, 50), "page": 2})
        doc.save(self.dir / "linked.pdf")
        source = self.library.open_file(self.dir / "linked.pdf").id
        out = build(self.library, [PageRef(source, i) for i in range(3)])
        self.assertEqual(out[0].get_links()[0]["page"], 2)

    def test_resources_shared_by_scattered_pages_are_copied_once(self):
        doc = pymupdf.open()
        font = pymupdf.Font("cjk")
        for i in range(12):
            page = doc.new_page()
            writer = pymupdf.TextWriter(page.rect)
            writer.append((50, 100), f"page {i}", font=font)
            writer.write_text(page)
        doc.save(self.dir / "fonts.pdf", garbage=3, deflate=True)
        source = self.library.open_file(self.dir / "fonts.pdf").id
        refs = [PageRef(source, i) for i in reversed(range(12))]  # reversed: one copy call per page
        size = write_pdf(self.library, refs, self.dir / "out.pdf")
        self.assertLess(size, (self.dir / "fonts.pdf").stat().st_size * 1.2)

    def test_building_nothing_is_an_error(self):
        with self.assertRaises(ValueError):
            build(self.library, [])

    def test_progress_reaches_the_page_count(self):
        a = self.source("a.pdf", 4, "a")
        calls = []
        build(self.library, [PageRef(a, i) for i in (0, 1, 3)], progress=lambda *args: calls.append(args))
        self.assertEqual(calls[-1], (3, 3))


class DecorationTest(ExportTestCase):
    def test_page_numbers_read_upright_at_the_bottom_centre_on_every_rotation(self):
        a = self.source("a.pdf", 4, "a", width=300, height=420)
        refs = [PageRef(a, i, rotation) for i, rotation in enumerate((0, 90, 180, 270))]
        options = OutputOptions(page_numbers=PageNumbers("bottom-center", "{n} / {total}"))
        out = build(self.library, refs, options)
        for n, page in enumerate(out, start=1):
            with self.subTest(rotation=page.rotation):
                text, box, direction = next(line for line in visual_lines(page) if "/" in line[0])
                self.assertEqual(text, f"{n} / 4")
                self.assertAlmostEqual(direction.x, 1, places=3)
                self.assertGreater(box.y1, page.rect.height - 40)
                self.assertAlmostEqual((box.x0 + box.x1) / 2, page.rect.width / 2, delta=3)

    def test_page_numbers_start_at_the_chosen_number(self):
        a = self.source("a.pdf", 2, "a")
        options = OutputOptions(page_numbers=PageNumbers("top-right", "p{n} of {total}", start=7))
        out = build(self.library, [PageRef(a, 0), PageRef(a, 1)], options)
        texts = [line[0] for line in visual_lines(out[1])]
        self.assertIn("p8 of 8", texts)
        box = next(line[1] for line in visual_lines(out[1]) if line[0] == "p8 of 8")
        self.assertLess(box.y0, 50)
        self.assertGreater(box.x1, out[1].rect.width - 50)

    def test_a_korean_watermark_is_embedded_as_a_small_subset(self):
        a = self.source("a.pdf", 3, "a")
        text = "대외비 CONFIDENTIAL"  # Hangul and Latin in one line
        options = OutputOptions(watermark=Watermark(text))
        size = write_pdf(self.library, [PageRef(a, i) for i in range(3)], self.dir / "w.pdf", options)
        out = pymupdf.open(self.dir / "w.pdf")
        self.assertIn(text, out[2].get_text())
        self.assertLess(size, 100_000)  # the full font alone is 3.5 MB

    def test_invalid_page_number_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"\{page\}"):
            PageNumbers(template="{page}")
        with self.assertRaises(ValueError):
            PageNumbers(position="middle")

    def test_blank_watermark_text_is_rejected(self):
        with self.assertRaises(ValueError):
            Watermark("   ")

    def test_preview_shows_the_page_exactly_as_it_is_written(self):
        a = self.source("a.pdf", 5, "a")
        refs = [PageRef(a, i, 90 if i == 2 else 0) for i in range(5)]
        options = OutputOptions(page_numbers=PageNumbers(template="{n}/{total}"), watermark=Watermark("draft"))
        preview = preview_pixmap(self.library, refs, 2, options, 0.5)
        written = build(self.library, refs, options)[2].get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5), alpha=False)
        self.assertEqual((preview.width, preview.height), (421, 298))
        self.assertEqual(preview.samples, written.samples)


class SaveTest(ExportTestCase):
    def test_compression_downsamples_large_images_to_the_target_resolution(self):
        source = self.library.open_file(make_photo_pdf(self.dir / "photo.pdf", 2400)).id
        plain = write_pdf(self.library, [PageRef(source, 0)], self.dir / "plain.pdf")
        small = write_pdf(self.library, [PageRef(source, 0)], self.dir / "small.pdf",
                          OutputOptions(compression=Compression(dpi=150, quality=60)))
        self.assertLess(small, plain * 0.8)
        width = pymupdf.open(self.dir / "small.pdf")[0].get_images()[0][2]
        self.assertAlmostEqual(width, 150 * 8.5, delta=40)

    def test_images_near_the_target_resolution_are_not_resampled(self):
        source = self.library.open_file(make_photo_pdf(self.dir / "photo.pdf", 1300)).id
        write_pdf(self.library, [PageRef(source, 0)], self.dir / "out.pdf",
                  OutputOptions(compression=Compression(dpi=150)))
        self.assertEqual(pymupdf.open(self.dir / "out.pdf")[0].get_images()[0][2], 1300)

    def test_a_password_protects_the_saved_file(self):
        a = self.source("a.pdf", 1, "a")
        write_pdf(self.library, [PageRef(a, 0)], self.dir / "locked.pdf", OutputOptions(password="s3cret"))
        locked = pymupdf.open(self.dir / "locked.pdf")
        self.assertTrue(locked.needs_pass)
        self.assertFalse(locked.authenticate("wrong"))
        self.assertTrue(locked.authenticate("s3cret"))
        self.assertEqual(locked[0].get_text().strip(), "a-1")

    def test_saving_over_a_loaded_source_file_works(self):
        path = make_pdf(self.dir / "a.pdf", 3, "a")
        a = self.library.open_file(path).id
        write_pdf(self.library, [PageRef(a, 2), PageRef(a, 0)], path)
        self.assertEqual([p.get_text().strip() for p in pymupdf.open(path)], ["a-3", "a-1"])

    def test_a_failed_save_leaves_no_temporary_file_behind(self):
        a = self.source("a.pdf", 1, "a")
        target = self.dir / "folder.pdf"
        target.mkdir()
        before = set(self.dir.iterdir())
        with self.assertRaises(OSError):
            write_pdf(self.library, [PageRef(a, 0)], target)
        self.assertEqual(set(self.dir.iterdir()), before)


class ImageExportTest(ExportTestCase):
    def test_png_and_jpeg_pages_are_rendered_at_the_requested_dpi(self):
        a = self.source("a.pdf", 1, "a", width=144, height=72)
        write_image(self.library, PageRef(a, 0, 90), self.dir / "p.png", 100)
        write_image(self.library, PageRef(a, 0), self.dir / "p.jpg", 144)
        png = pymupdf.Pixmap(self.dir / "p.png")
        jpg = pymupdf.Pixmap(self.dir / "p.jpg")
        self.assertEqual((png.width, png.height), (100, 200))
        self.assertEqual((jpg.width, jpg.height), (288, 144))
        self.assertEqual(png.xres, 100)


class NamingTest(unittest.TestCase):
    def test_numbered_paths_are_padded_to_sort_correctly(self):
        names = [p.name for p in numbered_paths(Path("out/report.pdf"), 120)]
        self.assertEqual(names[0], "report_001.pdf")
        self.assertEqual(names[-1], "report_120.pdf")
        self.assertEqual(numbered_paths(Path("x.png"), 3)[2].name, "x_03.png")

    def test_repeated_names_get_a_counter(self):
        names = [p.name for p in named_paths(Path("out"), ["a", "b", "A"], ".pdf")]
        self.assertEqual(names, ["a.pdf", "b.pdf", "A (2).pdf"])


if __name__ == "__main__":
    unittest.main()
