from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from .calendar import CalendarEvent
from .models import Quote
from .news import NewsItem
from .stocks import StockQuote


class QuoteProvider(Protocol):
    symbols: list[str]

    def set_symbols(self, symbols: list[str]) -> None: ...

    async def stream(self) -> AsyncIterator[Quote]: ...

    def fetch_recent_closes(self, symbol: str, limit: int = 240) -> list[tuple[int, float]]: ...

    def fetch_recent_15m_ohlc(
        self, symbol: str, limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]: ...

    def fetch_recent_ohlc(
        self, symbol: str, interval: str = "15m", limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]: ...


class StockProvider(Protocol):
    def fetch_quotes(self, symbols: list[str]) -> list[StockQuote]: ...

    def fetch_history(
        self, symbol: str, close_limit: int = 240, candle_limit: int = 96
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float, float, float, float]]]: ...

    def fetch_candles_timeframe(
        self, symbol: str, timeframe: str = "15m", candle_limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]: ...


class NewsProvider(Protocol):
    def fetch_all_news(self, limit_per_source: int = 15) -> dict[str, list[NewsItem]]: ...


class CalendarProvider(Protocol):
    def fetch_events(self, calendars: list[dict[str, Any]], horizon_days: int = 15) -> list[CalendarEvent]: ...


class ProfileProvider(Protocol):
    def fetch_symbol_profile(self, symbol: str, symbol_type: str) -> tuple[str, str]: ...


class ConfigRepository(Protocol):
    def serialize_runtime_config(
        self,
        *,
        config_name: str,
        timezone: str,
        language: str,
        quick_actions: dict[str, str],
        calendars: list[dict[str, Any]],
        indicator_groups: list[dict[str, Any]],
        market_groups: list[dict[str, Any]],
    ) -> str: ...

    def persist_runtime_config(
        self,
        *,
        path: str,
        config_name: str,
        timezone: str,
        language: str,
        quick_actions: dict[str, str],
        calendars: list[dict[str, Any]],
        indicator_groups: list[dict[str, Any]],
        market_groups: list[dict[str, Any]],
    ) -> bool: ...
