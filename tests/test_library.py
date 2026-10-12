import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_aio.library import A4, Library, PasswordRequired, SourceError, expand_paths
from pdf_aio.workspace import PageRef
from tests.samples import make_encrypted_pdf, make_image, make_pdf


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.library = Library()

    def tearDown(self):
        self._tmp.cleanup()


class OpenPdfTest(LibraryTestCase):
    def test_a_pdf_becomes_a_source_named_after_the_file(self):
        source = self.library.open_file(make_pdf(self.dir / "report.pdf", 3, "r"))
        self.assertEqual(source.name, "report.pdf")
        self.assertEqual(source.doc.page_count, 3)
        self.assertIs(self.library.get(source.id), source)

    def test_the_original_file_is_not_locked_after_opening(self):
        path = make_pdf(self.dir / "a.pdf", 1, "a")
        source = self.library.open_file(path)
        path.unlink()
        self.assertEqual(source.doc[0].get_text().strip(), "a-1")

    def test_an_encrypted_pdf_needs_the_right_password(self):
        path = make_encrypted_pdf(self.dir / "locked.pdf", "pw")
        with self.assertRaisesRegex(PasswordRequired, "암호로 보호된"):
            self.library.open_file(path)
        with self.assertRaisesRegex(PasswordRequired, "올바르지 않습니다"):
            self.library.open_file(path, "nope")
        source = self.library.open_file(path, "pw")
        self.assertIn("secret page", source.doc[0].get_text())

    def test_a_damaged_pdf_is_reported_by_name(self):
        path = self.dir / "broken.pdf"
        path.write_bytes(b"%PDF-1.7 this is not a pdf")
        with self.assertRaisesRegex(SourceError, "broken.pdf: 파일이 손상되었거나 올바른 PDF"):
            self.library.open_file(path)

    def test_an_unsupported_file_type_is_rejected(self):
        path = self.dir / "notes.txt"
        path.write_text("hello")
        with self.assertRaisesRegex(SourceError, "notes.txt: PDF나 지원하는 이미지 형식이 아닙니다"):
            self.library.open_file(path)

    def test_a_missing_file_is_reported(self):
        with self.assertRaises(SourceError):
            self.library.open_file(self.dir / "gone.pdf")


class OpenImageTest(LibraryTestCase):
    def test_a_tall_image_is_fitted_on_portrait_a4_and_centred(self):
        source = self.library.open_file(make_image(self.dir / "tall.png", 100, 400))
        page = source.doc[0]
        self.assertEqual(page.rect, A4)
        box = page.get_image_info()[0]["bbox"]
        self.assertAlmostEqual(box[1], 0, delta=1)
        self.assertAlmostEqual(box[3], A4.height, delta=1)
        self.assertAlmostEqual((box[0] + box[2]) / 2, A4.width / 2, delta=1)

    def test_a_wide_image_gets_landscape_a4(self):
        source = self.library.open_file(make_image(self.dir / "wide.jpg", 400, 100))
        rect = source.doc[0].rect
        self.assertEqual((rect.width, rect.height), (A4.height, A4.width))

    def test_a_damaged_image_is_reported(self):
        path = self.dir / "photo.jpg"
        path.write_bytes(b"not a jpeg")
        with self.assertRaisesRegex(SourceError, "photo.jpg: 파일이 손상되었거나 올바른 이미지"):
            self.library.open_file(path)


class GeometryTest(LibraryTestCase):
    def test_size_swaps_width_and_height_for_quarter_turns(self):
        source = self.library.add_blank(200, 300)
        self.assertEqual(self.library.size(PageRef(source.id, 0)), (200, 300))
        self.assertEqual(self.library.size(PageRef(source.id, 0, 90)), (300, 200))
        self.assertEqual(self.library.size(PageRef(source.id, 0, 180)), (200, 300))

    def test_rendering_a_rotated_reference_matches_a_rotated_page(self):
        source = self.library.open_file(make_pdf(self.dir / "a.pdf", 1, "corner", 200, 300))
        rendered = self.library.pixmap(PageRef(source.id, 0, 90), 1)
        page = source.doc[0]
        page.set_rotation(90)
        expected = page.get_pixmap(alpha=False)
        page.set_rotation(0)
        self.assertEqual((rendered.width, rendered.height), (300, 200))
        self.assertEqual(rendered.samples, expected.samples)


class ExpandPathsTest(LibraryTestCase):
    def test_folders_contribute_supported_files_in_natural_order(self):
        folder = self.dir / "scans"
        folder.mkdir()
        for name in ("scan10.pdf", "scan2.pdf", "readme.txt", "Scan1.PNG"):
            (folder / name).write_bytes(b"")
        names = [p.name for p in expand_paths([folder])]
        self.assertEqual(names, ["Scan1.PNG", "scan2.pdf", "scan10.pdf"])

    def test_loose_files_are_sorted_naturally_before_folder_contents(self):
        folder = self.dir / "more"
        folder.mkdir()
        (folder / "x.pdf").write_bytes(b"")
        paths = [self.dir / "page10.pdf", folder, self.dir / "page9.pdf"]
        names = [p.name for p in expand_paths(paths)]
        self.assertEqual(names, ["page9.pdf", "page10.pdf", "x.pdf"])


class BlankTest(LibraryTestCase):
    def test_a_blank_source_has_one_empty_page_of_the_requested_size(self):
        source = self.library.add_blank(300, 400)
        self.assertIsNone(source.path)
        self.assertEqual(source.doc[0].rect, pymupdf.Rect(0, 0, 300, 400))
        self.assertEqual(source.doc[0].get_text(), "")


if __name__ == "__main__":
    unittest.main()
