from __future__ import annotations

import unittest

from app.rotation import RotationController


class RotationControllerTests(unittest.TestCase):
    def test_cycle_index_wraps_both_directions(self) -> None:
        self.assertEqual(RotationController.cycle_index(0, 5, 1), 1)
        self.assertEqual(RotationController.cycle_index(4, 5, 1), 0)
        self.assertEqual(RotationController.cycle_index(0, 5, -1), 4)
        self.assertEqual(RotationController.cycle_index(2, 0, 1), 0)

    def test_pause_and_is_paused(self) -> None:
        ctrl = RotationController()
        ctrl.pause("main", 60, now=100.0)
        self.assertTrue(ctrl.is_paused("main", now=120.0))
        self.assertFalse(ctrl.is_paused("main", now=160.1))

    def test_try_rotate_respects_pause_and_size(self) -> None:
        ctrl = RotationController()
        changed, idx = ctrl.try_rotate(key="news", current=2, size=5, now=10.0)
        self.assertTrue(changed)
        self.assertEqual(idx, 3)

        ctrl.pause("news", 30, now=20.0)
        changed, idx = ctrl.try_rotate(key="news", current=3, size=5, now=25.0)
        self.assertFalse(changed)
        self.assertEqual(idx, 3)

        changed, idx = ctrl.try_rotate(key="empty", current=3, size=0, now=25.0)
        self.assertFalse(changed)
        self.assertEqual(idx, 0)


if __name__ == "__main__":
    unittest.main()
