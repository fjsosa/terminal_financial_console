from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from app.calendar import CalendarEvent
from app.calendar_ticker_vm import (
    alerts_items_for_ticker,
    build_calendar_text,
    calendar_events_for_ticker,
    calendar_status_label,
    format_hhmmss,
    render_ticker_visible_text,
    ticker_chunks_calendar,
    ticker_chunks_news,
    ticker_chunks_quotes,
)
from app.news import NewsItem


class State:
    def __init__(self, price: float, change: float) -> None:
        self.price = price
        self.change_percent = change


class CalendarTickerVmTests(unittest.TestCase):
    def test_format_hhmmss(self) -> None:
        self.assertEqual(format_hhmmss(3661), "01:01:01")

    def test_calendar_status_label(self) -> None:
        now = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        event = CalendarEvent(
            calendar_name="USA",
            title="NFP",
            start_utc=now + timedelta(hours=1),
            end_utc=now + timedelta(hours=2),
            source="ff",
            region="USA",
            country="US",
            impact="high",
        )
        status, kind = calendar_status_label(event, now_utc=now, soon_hours=8)
        self.assertEqual(kind, "soon")
        self.assertIn("event starts in", status)

    def test_calendar_events_for_ticker_filters_high_today(self) -> None:
        local_tz = UTC
        now = datetime(2026, 3, 2, 12, 0, tzinfo=local_tz)
        events = [
            CalendarEvent(
                calendar_name="USA",
                title="A",
                start_utc=now,
                end_utc=now + timedelta(hours=1),
                source="ff",
                region="USA",
                country="US",
                impact="high",
            ),
            CalendarEvent(
                calendar_name="USA",
                title="B",
                start_utc=now + timedelta(days=1),
                end_utc=now + timedelta(days=1, hours=1),
                source="ff",
                region="USA",
                country="US",
                impact="high",
            ),
        ]
        out = calendar_events_for_ticker(events, local_now=now, local_today=now.date(), local_tz=local_tz)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "A")

    def test_ticker_chunks_and_render(self) -> None:
        alerts = alerts_items_for_ticker({1: ("AAPL", "stock"), 0: ("BTCUSDT", "crypto")})
        self.assertEqual(alerts[0][0], "BTCUSDT")
        quote_chunks = ticker_chunks_quotes(
            alerts_items=alerts,
            symbol_data={"BTCUSDT": State(100.0, 1.0)},
            stock_data={"AAPL": State(200.0, -1.0)},
        )
        self.assertTrue(any("▲" in c or "▼" in c for c in quote_chunks))

        news_chunks = ticker_chunks_news(
            latest_items=[NewsItem(source="x", title="t", url="u", age="now", category="N")],
            limit=10,
        )
        self.assertEqual(len(news_chunks), 1)

        now = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        cal_events = [
            CalendarEvent(
                calendar_name="USA",
                title="Very long title " * 10,
                start_utc=now + timedelta(minutes=30),
                end_utc=now + timedelta(hours=1),
                source="ff",
                region="USA",
                country="US",
                impact="high",
            )
        ]
        cal_chunks = ticker_chunks_calendar(events=cal_events, max_events=12, soon_hours=8)
        self.assertEqual(len(cal_chunks), 1)

        palette = {"text": "white", "ok": "green", "err": "red", "warn": "yellow", "accent": "cyan"}
        txt = render_ticker_visible_text(mode="quotes", visible="A ▲ B ▼", palette=palette, heartbeat=True)
        self.assertIn("▲", txt.plain)

    def test_build_calendar_text(self) -> None:
        palette = {"brand": "cyan", "muted": "gray", "warn": "yellow", "accent": "blue", "text": "white", "err": "red"}
        now = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        txt = build_calendar_text(
            palette=palette,
            calendars=[{"name": "USA"}],
            calendar_events=[],
            calendar_last_update="10:00",
            horizon_days=15,
            now_local=now,
            soon_hours=8,
        )
        self.assertIn("ECONOMIC CALENDAR", txt.plain)


if __name__ == "__main__":
    unittest.main()
