from __future__ import annotations

import asyncio
import unittest

from app.group_rotation_controller import (
    cycle_indicator_group,
    cycle_main_group,
    cycle_news_group,
    pause_group_rotation,
    rotate_indicator_group,
    rotate_main_group,
    rotate_news_group,
)
from app.rotation import RotationController


class DummyTask:
    def __init__(self) -> None:
        self._done = False
        self.cancelled = False

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancelled = True
        self._done = True


class FakeHost:
    def __init__(self) -> None:
        self.is_shutting_down = False
        self.news_groups = [("n", [])]
        self.main_group_items = [("g1", [("BTCUSDT", "crypto")]), ("g2", [("ETHUSDT", "crypto")])]
        self.indicator_group_items = [("i1", [("^GSPC", "stock")]), ("i2", [("^DJI", "stock")])]
        self.news_group_index = 0
        self.main_group_index = 0
        self.indicator_group_index = 0
        self.rotation = RotationController()
        self.updated: list[str] = []
        self.scheduled: list[str] = []
        self.spawned: list[str] = []
        self.lazy_history_task = None

    def _update_news_panel(self) -> None:
        self.updated.append("news")

    def _update_main_group_panel(self) -> None:
        self.updated.append("main")

    def _update_indicators_panel(self) -> None:
        self.updated.append("indicators")

    def _schedule_stock_refresh(self) -> None:
        self.scheduled.append("stock")

    def _schedule_indicator_refresh(self) -> None:
        self.scheduled.append("indicator")

    async def _refresh_crypto_stream_for_visible_group(self):
        return None

    async def _load_remaining_history_in_background(self):
        return None

    def _spawn_background(self, coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        self.spawned.append("spawn")
        return DummyTask()


class GroupRotationControllerTests(unittest.TestCase):
    def test_rotate_news_group(self) -> None:
        host = FakeHost()
        rotate_news_group(host)
        self.assertEqual(host.news_group_index, 0)
        self.assertIn("news", host.updated)

        host = FakeHost()
        host.news_groups = []
        rotate_news_group(host)
        self.assertEqual(host.updated, [])

    def test_rotate_main_group_with_lazy_cancel_and_spawn(self) -> None:
        host = FakeHost()
        host.lazy_history_task = DummyTask()
        rotate_main_group(host)
        self.assertEqual(host.main_group_index, 1)
        self.assertIn("main", host.updated)
        self.assertIn("stock", host.scheduled)
        self.assertEqual(len(host.spawned), 2)
        self.assertTrue(host.lazy_history_task is not None)

    def test_rotate_main_group_respects_pause_and_shutdown(self) -> None:
        host = FakeHost()
        pause_group_rotation(host, "crypto_quotes", 60)
        rotate_main_group(host)
        self.assertEqual(host.main_group_index, 0)

        host = FakeHost()
        host.is_shutting_down = True
        rotate_main_group(host)
        self.assertEqual(host.main_group_index, 0)

    def test_rotate_indicator_group(self) -> None:
        host = FakeHost()
        rotate_indicator_group(host)
        self.assertEqual(host.indicator_group_index, 1)
        self.assertIn("indicators", host.updated)
        self.assertIn("indicator", host.scheduled)

    def test_pause_and_cycle_functions(self) -> None:
        host = FakeHost()
        pause_group_rotation(host, "news_table", 60)
        self.assertTrue(host.rotation.is_paused("news_table"))

        cycle_main_group(host, 1)
        self.assertEqual(host.main_group_index, 1)
        self.assertTrue(host.rotation.is_paused("crypto_quotes"))

        cycle_news_group(host, 1)
        self.assertEqual(host.news_group_index, 0)
        self.assertTrue(host.rotation.is_paused("news_table"))

        cycle_indicator_group(host, 1)
        self.assertEqual(host.indicator_group_index, 1)
        self.assertTrue(host.rotation.is_paused("indicators_table"))


if __name__ == "__main__":
    unittest.main()
