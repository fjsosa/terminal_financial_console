from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.refresh_controller import (
    refresh_calendar,
    refresh_indicators,
    refresh_news,
    refresh_stocks,
    schedule_calendar_refresh,
    schedule_indicator_refresh,
    schedule_news_refresh,
    schedule_stock_refresh,
)
from app.refresh_services import CalendarRefreshResult, NewsRefreshResult, StockRefreshResult


class FakeHost:
    def __init__(self) -> None:
        self.is_shutting_down = False
        self.local_tz = None
        self.calendars = [{"name": "USA"}]
        self.calendar_events = []
        self.calendar_last_update = "never"
        self.news_groups = []
        self.news_latest_items = []
        self.news_last_update = "never"
        self.news_group_index = 0
        self.stock_symbols = ["AAPL"]
        self.indicator_symbols = ["^GSPC"]
        self.main_visible_items = [("AAPL", "stock")]
        self.indicator_visible_items = [("^GSPC", "stock")]
        self.indicator_data = {}
        self.stocks_last_update = "never"
        self.indicators_last_update = "never"
        self.news_provider = object()
        self.calendar_provider = object()
        self.stock_provider = object()
        self.spawns: list[object] = []
        self.logs: list[str] = []
        self.updates: list[str] = []
        self.stock_applied = 0

    def _spawn_background(self, coro):
        self.spawns.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()
        return object()

    async def _refresh_news(self) -> None:
        return None

    async def _refresh_calendar(self) -> None:
        return None

    async def _refresh_stocks(self) -> None:
        return None

    async def _refresh_indicators(self) -> None:
        return None

    def _news_age_minutes(self, age: str) -> int:
        return 0 if age == "now" else 1

    def _update_news_panel(self) -> None:
        self.updates.append("news")

    def _update_main_group_panel(self) -> None:
        self.updates.append("main")

    def _update_alerts_panel(self) -> None:
        self.updates.append("alerts")

    def _update_indicators_panel(self) -> None:
        self.updates.append("indicators")

    def _apply_stock_quote(self, quote) -> None:
        self.stock_applied += 1

    def _new_stock_state(self, symbol: str):
        return SimpleNamespace(symbol=symbol, price=0.0, change_percent=0.0, volume=0.0, last_update_ms=0)

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _ui_palette(self):
        return {"warn": "yellow", "accent": "cyan"}


class RefreshControllerTests(unittest.TestCase):
    def test_schedule_functions(self) -> None:
        host = FakeHost()
        schedule_news_refresh(host)
        schedule_calendar_refresh(host)
        schedule_stock_refresh(host)
        schedule_indicator_refresh(host)
        self.assertEqual(len(host.spawns), 4)

        host = FakeHost()
        host.is_shutting_down = True
        schedule_news_refresh(host)
        self.assertEqual(len(host.spawns), 0)

    def test_refresh_news(self) -> None:
        async def run() -> None:
            host = FakeHost()
            with patch(
                "app.refresh_controller.refresh_news_data",
                new=AsyncMock(
                    return_value=NewsRefreshResult(
                        groups=[("N", [])],
                        latest_items=[],
                        last_update_hhmm="10:00",
                        total_items=3,
                        feed_count=2,
                    )
                ),
            ):
                await refresh_news(host, max_items=30, group_size=7, ticker_limit=10)
            self.assertEqual(host.news_last_update, "10:00")
            self.assertEqual(host.news_group_index, 0)
            self.assertIn("news", host.updates)

        asyncio.run(run())

    def test_refresh_calendar(self) -> None:
        async def run() -> None:
            host = FakeHost()
            with patch(
                "app.refresh_controller.refresh_calendar_data",
                new=AsyncMock(
                    return_value=CalendarRefreshResult(events=[SimpleNamespace()], last_update_hhmm="11:00", calendar_count=1)
                ),
            ):
                await refresh_calendar(host, horizon_days=15)
            self.assertEqual(host.calendar_last_update, "11:00")
            self.assertEqual(len(host.calendar_events), 1)

        asyncio.run(run())

    def test_refresh_stocks_and_indicators(self) -> None:
        async def run() -> None:
            host = FakeHost()
            quotes = [SimpleNamespace(symbol="AAPL", price=1.0, change_percent=1.0, volume=1.0, event_time_ms=1)]
            with patch(
                "app.refresh_controller.refresh_stock_quotes",
                new=AsyncMock(return_value=StockRefreshResult(quotes=quotes, symbols_requested=1, last_update_hhmm="12:00")),
            ):
                await refresh_stocks(host)
            self.assertEqual(host.stocks_last_update, "12:00")
            self.assertGreater(host.stock_applied, 0)
            self.assertIn("alerts", host.updates)

            host = FakeHost()
            host.indicator_visible_items = [("^GSPC", "stock")]
            quotes = [SimpleNamespace(symbol="^GSPC", price=2.0, change_percent=-1.0, volume=5.0, event_time_ms=2)]
            with patch(
                "app.refresh_controller.refresh_stock_quotes",
                new=AsyncMock(return_value=StockRefreshResult(quotes=quotes, symbols_requested=1, last_update_hhmm="12:30")),
            ):
                await refresh_indicators(host)
            self.assertEqual(host.indicators_last_update, "12:30")
            self.assertIn("^GSPC", host.indicator_data)
            self.assertIn("indicators", host.updates)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
