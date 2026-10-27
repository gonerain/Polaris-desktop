import itertools
import unittest

from polaris.panels import PanelAllocator, normalize_cells, shape_regions


class PanelAllocatorTests(unittest.TestCase):
    def test_size_count_gap_and_partial_last_row(self):
        board = PanelAllocator((20, 10), 10, 3)
        self.assertEqual((board.columns, board.rows), (4, 3))
        self.assertEqual((board.width, board.height), (89, 36))
        placements = [board.request() for _ in range(10)]
        self.assertEqual([p.origin for p in placements], [(i % 4, i // 4) for i in range(10)])
        self.assertEqual(board.free_count, 0)
        self.assertIsNone(board.request())

    def test_l_shape_leaves_missing_cell_available(self):
        board = PanelAllocator((20, 10), 4, 4)
        shape = board.request([[0, 0], [1, 0], [0, 1]])
        self.assertEqual((shape.width, shape.height), (44, 24))
        self.assertEqual(board.free_count, 1)
        hole = board.request()
        self.assertEqual(hole.origin, (1, 1))
        self.assertFalse(any(r.contains(30, 18) for r in shape.regions))
        self.assertTrue(any(r.contains(22, 5) for r in shape.regions))
        self.assertTrue(any(r.contains(5, 12) for r in shape.regions))
        self.assertIsNone(board.request())

    def test_rectangular_span_has_no_internal_seams(self):
        board = PanelAllocator((20, 10), 4, 4)
        shape = board.request([[0, 0], [1, 0], [0, 1], [1, 1]])
        self.assertEqual(len(shape.regions), 1)
        self.assertTrue(shape.regions[0].contains(22, 12))
        self.assertEqual((shape.regions[0].width, shape.regions[0].height), (44, 24))

    def test_hole_and_disconnected_shapes(self):
        board = PanelAllocator((20, 10), 9, 4)
        ring = board.request([[x, y] for y in range(3) for x in range(3) if (x, y) != (1, 1)])
        self.assertFalse(any(r.contains(30, 18) for r in ring.regions))
        self.assertEqual(board.request().origin, (1, 1))
        board = PanelAllocator((20, 10), 4, 4)
        diagonal = board.request([[0, 0], [1, 1]])
        self.assertEqual(len(diagonal.regions), 2)
        self.assertEqual(board.free_count, 2)

    def test_failed_requests_are_atomic(self):
        board = PanelAllocator((20, 10), 3, 4)
        first = board.request()
        self.assertIsNone(board.request([[0, 0], [1, 0], [0, 1], [1, 1]]))
        self.assertEqual(board.free_count, 2)
        for cells in ([], [[0, 0], [0, 0]], [[-1, 0]], [[0.5, 0]], [[True, 0]], [0], None):
            with self.subTest(cells=cells):
                with self.assertRaises(ValueError):
                    board.request(cells)
                self.assertEqual(board.free_count, 2)
        self.assertTrue(board.release(first.id))
        self.assertEqual(board.free_count, 3)
        self.assertFalse(board.release(first.id))

    def test_reconfigure_requires_empty_board_and_preserves_unique_ids(self):
        board = PanelAllocator((20, 10), 4, 4)
        first = board.request()
        with self.assertRaises(ValueError):
            board.configure((30, 30), 8, 5)
        self.assertEqual(board.panel_count, 4)
        board.release(first.id)
        board.configure((30, 30), 8, 5)
        second = board.request()
        self.assertNotEqual(first.id, second.id)
        self.assertFalse(board.release(first.id))
        self.assertEqual(board.free_count, 7)

    def test_invalid_initialization(self):
        for size, count, gap in (((0, 10), 2, 0), ((10, -1), 2, 0), ((10, 10), 0, 0),
                                 ((10, 10), True, 0), ((10, 10), 2, -1), ((float('inf'), 10), 2, 0)):
            with self.subTest(size=size, count=count, gap=gap):
                with self.assertRaises(ValueError):
                    PanelAllocator(size, count, gap)

    def test_every_small_shape_has_an_exact_nonoverlapping_region_cover(self):
        coordinates = list(itertools.product(range(3), repeat=2))
        for bits in range(1, 1 << 9):
            shape = normalize_cells([cell for index, cell in enumerate(coordinates) if bits & (1 << index)])
            occupied = set(shape)
            columns, rows = max(x for x, _ in shape) + 1, max(y for _, y in shape) + 1
            for gap in (0, 3.5):
                regions = shape_regions(shape, 10, 8, gap)
                for row in range(rows * 2 - 1):
                    for column in range(columns * 2 - 1):
                        if gap == 0 and (row % 2 or column % 2):
                            continue
                        x = (column // 2) * (10 + gap) + (5 if column % 2 == 0 else 10 + gap / 2)
                        y = (row // 2) * (8 + gap) + (4 if row % 2 == 0 else 8 + gap / 2)
                        cx = (column // 2,) if column % 2 == 0 else (column // 2, column // 2 + 1)
                        cy = (row // 2,) if row % 2 == 0 else (row // 2, row // 2 + 1)
                        expected = all((i, j) in occupied for i in cx for j in cy)
                        self.assertEqual(sum(r.contains(x, y) for r in regions), int(expected))


if __name__ == "__main__":
    unittest.main()
