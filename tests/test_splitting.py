import unittest

from pdf_aio.splitting import RangeSyntaxError, by_source, every, parse_ranges
from pdf_aio.workspace import PageRef


class ParseRangesTest(unittest.TestCase):
    def test_each_comma_separated_part_becomes_one_group(self):
        self.assertEqual(parse_ranges("1-3, 5 ,7-8", 10), [[0, 1, 2], [4], [6, 7]])

    def test_open_ended_ranges_reach_the_first_and_last_page(self):
        self.assertEqual(parse_ranges("-2; 9-", 10), [[0, 1], [8, 9]])

    def test_a_descending_range_lists_pages_backwards(self):
        self.assertEqual(parse_ranges("4-2", 5), [[3, 2, 1]])

    def test_empty_parts_are_ignored(self):
        self.assertEqual(parse_ranges(" 2 ,, ", 3), [[1]])

    def test_pages_beyond_the_document_are_rejected_with_the_offending_part(self):
        with self.assertRaisesRegex(RangeSyntaxError, '"3-12": 12페이지.*전체는 10페이지'):
            parse_ranges("1, 3-12", 10)

    def test_page_zero_is_rejected(self):
        with self.assertRaises(RangeSyntaxError):
            parse_ranges("0-2", 10)

    def test_text_that_is_not_a_range_is_rejected(self):
        with self.assertRaisesRegex(RangeSyntaxError, '"a-b"'):
            parse_ranges("a-b", 10)

    def test_blank_text_is_rejected(self):
        with self.assertRaises(RangeSyntaxError):
            parse_ranges("  ", 10)


class GroupingTest(unittest.TestCase):
    def test_every_leaves_the_remainder_in_a_shorter_last_group(self):
        self.assertEqual(every(5, 2), [[0, 1], [2, 3], [4]])

    def test_every_rejects_a_group_size_below_one(self):
        with self.assertRaises(ValueError):
            every(5, 0)

    def test_by_source_splits_where_the_source_file_changes(self):
        pages = (PageRef(0, 0), PageRef(0, 1), PageRef(1, 0), PageRef(0, 2))
        self.assertEqual(by_source(pages), [[0, 1], [2], [3]])


if __name__ == "__main__":
    unittest.main()
