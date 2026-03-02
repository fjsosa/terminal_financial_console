from __future__ import annotations

import asyncio
import unittest

from app.startup_orchestration import run_startup_sequence


class FakeHost:
    def __init__(self) -> None:
        self.is_shutting_down = False
        self.lazy_history_task = None
        self.calls: list[str] = []

    async def _show_boot_modal(self) -> None:
        self.calls.append("show")

    async def _preload_visible_group_history(self) -> None:
        self.calls.append("preload")

    async def _hide_boot_modal(self) -> None:
        self.calls.append("hide")

    async def _refresh_crypto_stream_for_visible_group(self) -> None:
        self.calls.append("refresh_stream")

    async def _load_remaining_history_in_background(self) -> None:
        self.calls.append("lazy")

    def _schedule_news_refresh(self) -> None:
        self.calls.append("news")

    def _schedule_calendar_refresh(self) -> None:
        self.calls.append("calendar")

    def _schedule_stock_refresh(self) -> None:
        self.calls.append("stocks")

    def _schedule_indicator_refresh(self) -> None:
        self.calls.append("indicators")

    def _spawn_background(self, coro):
        self.calls.append("spawn")
        return asyncio.create_task(coro)

    def _log(self, message: str) -> None:
        self.calls.append(f"log:{message}")


class StartupOrchestrationTests(unittest.TestCase):
    def test_run_startup_sequence_happy_path(self) -> None:
        async def run() -> None:
            host = FakeHost()
            await run_startup_sequence(host)
            self.assertIn("show", host.calls)
            self.assertIn("preload", host.calls)
            self.assertIn("hide", host.calls)
            self.assertIn("refresh_stream", host.calls)
            self.assertIn("spawn", host.calls)
            self.assertIn("news", host.calls)
            self.assertIn("calendar", host.calls)
            self.assertIn("stocks", host.calls)
            self.assertIn("indicators", host.calls)
            assert host.lazy_history_task is not None
            host.lazy_history_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await host.lazy_history_task

        asyncio.run(run())

    def test_run_startup_sequence_skips_when_shutting_down(self) -> None:
        async def run() -> None:
            host = FakeHost()
            host.is_shutting_down = True
            await run_startup_sequence(host)
            self.assertNotIn("hide", host.calls)
            self.assertIsNone(host.lazy_history_task)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
