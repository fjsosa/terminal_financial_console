from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from app.calendar import CalendarEvent
from app.news import NewsItem
from app.refresh_services import (
    build_news_groups,
    refresh_calendar_data,
    refresh_news_data,
    refresh_stock_quotes,
)


class FakeNewsProvider:
    def fetch_all_news(self, max_items: int):
        del max_items
        return {
            "CRYPTO NEWS": [
                NewsItem(source="a.com", title="Old", url="u1", age="2 hour", category="CRYPTO NEWS"),
                NewsItem(source="b.com", title="Now", url="u2", age="now", category="CRYPTO NEWS"),
            ],
            "STOCKS NEWS": [
                NewsItem(source="c.com", title="Mid", url="u3", age="10 min", category="STOCKS NEWS"),
            ],
        }


class FakeCalendarProvider:
    def fetch_events(self, calendars, horizon_days: int):
        del calendars, horizon_days
        now = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        return [
            CalendarEvent(
                calendar_name="USA",
                title="NFP",
                impact="high",
                start_utc=now,
                end_utc=now + timedelta(hours=1),
                source="forexfactory",
                region="USA",
                country="US",
            )
        ]


class FakeStockProvider:
    def fetch_quotes(self, symbols: list[str]):
        return [
            SimpleNamespace(symbol=s, price=100.0, change_percent=1.5, volume=1000.0, event_time_ms=123)
            for s in symbols
        ]


class RefreshServicesTests(unittest.TestCase):
    def test_build_news_groups(self) -> None:
        by_category = {
            "A": [NewsItem(source="x", title="t1", url="u1", age="now", category="A") for _ in range(5)]
        }
        groups = build_news_groups(by_category, group_size=2)
        self.assertEqual(len(groups), 3)

    def test_refresh_news_data(self) -> None:
        async def run_io(fn, *args):
            return fn(*args)

        async def run() -> None:
            result = await refresh_news_data(
                provider=FakeNewsProvider(),
                max_items=30,
                group_size=2,
                ticker_limit=2,
                local_now=lambda: datetime(2026, 3, 2, 10, 30),
                age_minutes=lambda age: 0 if age == "now" else 999,
                run_io=run_io,
            )
            self.assertEqual(result.feed_count, 2)
            self.assertEqual(result.total_items, 3)
            self.assertEqual(len(result.latest_items), 2)
            self.assertEqual(result.last_update_hhmm, "10:30")

        asyncio.run(run())

    def test_refresh_calendar_data(self) -> None:
        async def run_io(fn, *args):
            return fn(*args)

        async def run() -> None:
            result = await refresh_calendar_data(
                provider=FakeCalendarProvider(),
                calendars=[{"name": "USA"}],
                horizon_days=15,
                local_now=lambda: datetime(2026, 3, 2, 10, 45),
                run_io=run_io,
            )
            self.assertEqual(result.calendar_count, 1)
            self.assertEqual(len(result.events), 1)
            self.assertEqual(result.last_update_hhmm, "10:45")

        asyncio.run(run())

    def test_refresh_stock_quotes(self) -> None:
        async def run_io(fn, *args):
            return fn(*args)

        async def run() -> None:
            result = await refresh_stock_quotes(
                provider=FakeStockProvider(),
                symbols=["AAPL", "MSFT"],
                local_now=lambda: datetime(2026, 3, 2, 11, 0),
                run_io=run_io,
            )
            self.assertEqual(result.symbols_requested, 2)
            self.assertEqual(len(result.quotes), 2)
            self.assertEqual(result.last_update_hhmm, "11:00")
            self.assertEqual(result.quotes[0].symbol, "AAPL")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
