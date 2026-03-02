from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Protocol, TypeVar

from .calendar import CalendarEvent
from .news import NewsItem


T = TypeVar("T")


class NewsProviderLike(Protocol):
    def fetch_all_news(self, max_items: int) -> dict[str, list[NewsItem]]: ...


class CalendarProviderLike(Protocol):
    def fetch_events(
        self, calendars: list[dict[str, str]], horizon_days: int
    ) -> list[CalendarEvent]: ...


class StockProviderLike(Protocol):
    def fetch_quotes(self, symbols: list[str]) -> list[object]: ...


@dataclass(slots=True)
class NewsRefreshResult:
    groups: list[tuple[str, list[NewsItem]]]
    latest_items: list[NewsItem]
    last_update_hhmm: str
    total_items: int
    feed_count: int


@dataclass(slots=True)
class CalendarRefreshResult:
    events: list[CalendarEvent]
    last_update_hhmm: str
    calendar_count: int


@dataclass(slots=True)
class StockRefreshResult:
    quotes: list[object]
    symbols_requested: int
    last_update_hhmm: str


def build_news_groups(
    by_category: dict[str, list[NewsItem]], *, group_size: int
) -> list[tuple[str, list[NewsItem]]]:
    groups: list[tuple[str, list[NewsItem]]] = []
    for category, items in by_category.items():
        for i in range(0, len(items), group_size):
            chunk = items[i : i + group_size]
            if chunk:
                groups.append((category, chunk))
    return groups


async def refresh_news_data(
    *,
    provider: NewsProviderLike,
    max_items: int,
    group_size: int,
    ticker_limit: int,
    local_now: Callable[[], datetime],
    age_minutes: Callable[[str], int],
    run_io: Callable[..., Awaitable[T]] = asyncio.to_thread,
) -> NewsRefreshResult:
    by_category = await run_io(provider.fetch_all_news, max_items)
    groups = build_news_groups(by_category, group_size=group_size)
    flat_items: list[NewsItem] = []
    for items in by_category.values():
        flat_items.extend(items)
    flat_items.sort(key=lambda item: age_minutes(item.age))
    latest_items = flat_items[:ticker_limit]
    return NewsRefreshResult(
        groups=groups,
        latest_items=latest_items,
        last_update_hhmm=local_now().strftime("%H:%M"),
        total_items=sum(len(items) for items in by_category.values()),
        feed_count=len(by_category),
    )


async def refresh_calendar_data(
    *,
    provider: CalendarProviderLike,
    calendars: list[dict[str, str]],
    horizon_days: int,
    local_now: Callable[[], datetime],
    run_io: Callable[..., Awaitable[T]] = asyncio.to_thread,
) -> CalendarRefreshResult:
    events = await run_io(provider.fetch_events, calendars, horizon_days)
    return CalendarRefreshResult(
        events=events,
        last_update_hhmm=local_now().strftime("%H:%M"),
        calendar_count=len(calendars),
    )


async def refresh_stock_quotes(
    *,
    provider: StockProviderLike,
    symbols: list[str],
    local_now: Callable[[], datetime],
    run_io: Callable[..., Awaitable[T]] = asyncio.to_thread,
) -> StockRefreshResult:
    quotes = await run_io(provider.fetch_quotes, symbols)
    return StockRefreshResult(
        quotes=quotes,
        symbols_requested=len(symbols),
        last_update_hhmm=local_now().strftime("%H:%M"),
    )
