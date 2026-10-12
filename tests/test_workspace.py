import unittest

from pdf_aio.workspace import PageRef, Run, Workspace, runs


def labels(ws: Workspace) -> list[str]:
    return [f"{p.source}:{p.index}" for p in ws.pages]


def filled(*counts: int) -> Workspace:
    ws = Workspace()
    for source, count in enumerate(counts):
        ws.append(PageRef(source, i) for i in range(count))
    return ws


class MoveTest(unittest.TestCase):
    def test_moving_a_page_forward_lands_before_the_target_gap(self):
        ws = filled(5)
        placed = ws.move([0], 3)
        self.assertEqual(labels(ws), ["0:1", "0:2", "0:0", "0:3", "0:4"])
        self.assertEqual(placed, range(2, 3))

    def test_moving_scattered_pages_backward_keeps_their_order_together(self):
        ws = filled(6)
        placed = ws.move([4, 1, 5], 0)
        self.assertEqual(labels(ws), ["0:1", "0:4", "0:5", "0:0", "0:2", "0:3"])
        self.assertEqual(placed, range(0, 3))

    def test_moving_to_the_end_gap_appends(self):
        ws = filled(3, 2)
        placed = ws.move([0, 1, 2], len(ws))
        self.assertEqual(labels(ws), ["1:0", "1:1", "0:0", "0:1", "0:2"])
        self.assertEqual(placed, range(2, 5))

    def test_moving_onto_its_own_position_records_no_undo_step(self):
        ws = filled(3)
        ws.move([1], 1)
        ws.move([1], 2)
        self.assertEqual(labels(ws), ["0:0", "0:1", "0:2"])
        self.assertEqual(ws.undo(), True)  # only the initial append
        self.assertEqual(len(ws), 0)

    def test_a_target_outside_the_list_is_rejected(self):
        ws = filled(3)
        with self.assertRaises(IndexError):
            ws.move([0], 4)
        with self.assertRaises(IndexError):
            ws.move([3], 0)


class EditTest(unittest.TestCase):
    def test_remove_drops_exactly_the_given_positions(self):
        ws = filled(5)
        ws.remove([0, 3, 3])
        self.assertEqual(labels(ws), ["0:1", "0:2", "0:4"])

    def test_rotation_accumulates_and_wraps_at_360(self):
        ws = filled(2)
        ws.rotate([0], 90)
        ws.rotate([0], 270)
        ws.rotate([1], -90)
        self.assertEqual([p.rotation for p in ws.pages], [0, 270])

    def test_rotation_by_a_non_right_angle_is_rejected(self):
        with self.assertRaises(ValueError):
            filled(1).rotate([0], 45)

    def test_duplicate_inserts_one_block_after_the_last_chosen_page(self):
        ws = filled(4)
        copies = ws.duplicate([2, 0])
        self.assertEqual(labels(ws), ["0:0", "0:1", "0:2", "0:0", "0:2", "0:3"])
        self.assertEqual(copies, range(3, 5))

    def test_reverse_swaps_pages_only_among_their_own_positions(self):
        ws = filled(5)
        ws.reverse([0, 2, 4])
        self.assertEqual(labels(ws), ["0:4", "0:1", "0:2", "0:3", "0:0"])

    def test_insert_places_pages_at_the_gap(self):
        ws = filled(2)
        placed = ws.insert(1, [PageRef(9, 0)])
        self.assertEqual(labels(ws), ["0:0", "9:0", "0:1"])
        self.assertEqual(placed, range(1, 2))


class HistoryTest(unittest.TestCase):
    def test_undo_and_redo_walk_back_and_forth(self):
        ws = filled(3)
        ws.remove([0])
        ws.rotate([0], 90)
        self.assertTrue(ws.undo())
        self.assertEqual(labels(ws), ["0:1", "0:2"])
        self.assertEqual(ws.pages[0].rotation, 0)
        self.assertTrue(ws.undo())
        self.assertEqual(labels(ws), ["0:0", "0:1", "0:2"])
        self.assertTrue(ws.redo())
        self.assertTrue(ws.redo())
        self.assertFalse(ws.redo())
        self.assertEqual(ws.pages[0].rotation, 90)

    def test_a_new_edit_discards_the_redo_branch(self):
        ws = filled(3)
        ws.remove([0])
        ws.undo()
        ws.remove([2])
        self.assertFalse(ws.can_redo)
        self.assertEqual(labels(ws), ["0:0", "0:1"])


class RunsTest(unittest.TestCase):
    def test_each_unbroken_stretch_of_one_source_is_a_run(self):
        pages = (PageRef(0, 0), PageRef(0, 1), PageRef(1, 0), PageRef(0, 2))
        self.assertEqual(runs(pages), [Run(0, 0, 2), Run(1, 2, 3), Run(0, 3, 4)])

    def test_an_empty_workspace_has_no_runs(self):
        self.assertEqual(runs(()), [])


if __name__ == "__main__":
    unittest.main()
