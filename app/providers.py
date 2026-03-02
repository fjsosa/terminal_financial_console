from __future__ import annotations

from typing import Any

from .calendar import fetch_calendar_events
from .descriptions import fetch_symbol_profile
from .feed import BinanceTickerFeed
from .news import fetch_all_news
from .stocks import fetch_stock_candles_timeframe, fetch_stock_history, fetch_stock_quotes


class BinanceQuoteProvider:
    def __init__(self, symbols: list[str] | None = None) -> None:
        self._feed = BinanceTickerFeed(symbols or [])

    @property
    def symbols(self) -> list[str]:
        return list(self._feed.symbols)

    def set_symbols(self, symbols: list[str]) -> None:
        self._feed = BinanceTickerFeed(symbols)

    async def stream(self):
        async for quote in self._feed.stream():
            yield quote

    def fetch_recent_closes(self, symbol: str, limit: int = 240) -> list[tuple[int, float]]:
        return self._feed.fetch_recent_closes(symbol, limit)

    def fetch_recent_15m_ohlc(
        self, symbol: str, limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]:
        return self._feed.fetch_recent_15m_ohlc(symbol, limit)

    def fetch_recent_ohlc(
        self, symbol: str, interval: str = "15m", limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]:
        return self._feed.fetch_recent_ohlc(symbol, interval, limit)


class YFinanceStockProvider:
    def fetch_quotes(self, symbols: list[str]):
        return fetch_stock_quotes(symbols)

    def fetch_history(self, symbol: str, close_limit: int = 240, candle_limit: int = 96):
        return fetch_stock_history(symbol, close_limit, candle_limit)

    def fetch_candles_timeframe(self, symbol: str, timeframe: str = "15m", candle_limit: int = 96):
        return fetch_stock_candles_timeframe(symbol, timeframe, candle_limit)


class FinvizNewsProvider:
    def fetch_all_news(self, limit_per_source: int = 15):
        return fetch_all_news(limit_per_source)


class ForexFactoryCalendarProvider:
    def fetch_events(self, calendars: list[dict[str, Any]], horizon_days: int = 15):
        return fetch_calendar_events(calendars, horizon_days)


class DefaultProfileProvider:
    def fetch_symbol_profile(self, symbol: str, symbol_type: str):
        return fetch_symbol_profile(symbol, symbol_type)
