from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from .constants import SYMBOL_TYPE_CRYPTO, SYMBOL_TYPE_STOCK, TIMEFRAME_15M
from .cache import save_symbol_history_cache


class QuoteProviderLike(Protocol):
    def fetch_recent_ohlc(
        self, symbol: str, interval: str = TIMEFRAME_15M, limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]: ...

    def fetch_recent_closes(self, symbol: str, limit: int = 240) -> list[tuple[int, float]]: ...


class StockProviderLike(Protocol):
    def fetch_candles_timeframe(
        self, symbol: str, timeframe: str = TIMEFRAME_15M, candle_limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]: ...

    def fetch_history(
        self, symbol: str, close_limit: int = 240, candle_limit: int = 96
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float, float, float, float]]]: ...


class ChartHistoryHost(Protocol):
    quote_provider: QuoteProviderLike
    stock_provider: StockProviderLike
    candles: dict[str, deque[Any]]
    stock_candles: dict[str, deque[Any]]
    crypto_candles_by_tf: dict[str, dict[str, deque[Any]]]
    stock_candles_by_tf: dict[str, dict[str, deque[Any]]]
    symbol_data: dict[str, Any]
    stock_data: dict[str, Any]

    def _get_crypto_series(self, symbol: str, timeframe: str) -> deque[Any] | None: ...
    def _get_stock_series(self, symbol: str, timeframe: str) -> deque[Any] | None: ...


@dataclass(slots=True)
class ChartHistoryConfig:
    candle_buffer_max: int
    chart_history_points: int
    max_points: int
    initial_candle_limit: int


def _required_candles(target_candles: int, cfg: ChartHistoryConfig) -> int:
    return min(cfg.candle_buffer_max, max(cfg.chart_history_points, target_candles + 24))


def _to_candle_deque(
    candles_raw: list[tuple[int, float, float, float, float]],
    *,
    candle_cls: type[Any],
    maxlen: int,
) -> deque[Any]:
    fresh = deque(maxlen=maxlen)
    for open_ts, open_p, high_p, low_p, close_p in candles_raw:
        fresh.append(
            candle_cls(
                bucket_ms=open_ts,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
            )
        )
    return fresh


async def ensure_crypto_chart_history(
    host: ChartHistoryHost,
    *,
    symbol: str,
    timeframe: str,
    target_candles: int,
    candle_cls: type[Any],
    cfg: ChartHistoryConfig,
) -> None:
    series = host._get_crypto_series(symbol, timeframe)
    if series is None:
        return
    required = _required_candles(target_candles, cfg)
    if len(series) >= required:
        state = host.symbol_data.get(symbol)
        if state is not None and state.points is not None and len(state.points) >= cfg.chart_history_points:
            return

    candles_raw = await asyncio.to_thread(host.quote_provider.fetch_recent_ohlc, symbol, timeframe, required)
    if candles_raw:
        fresh = _to_candle_deque(candles_raw, candle_cls=candle_cls, maxlen=cfg.candle_buffer_max)
        if timeframe == TIMEFRAME_15M:
            host.candles[symbol] = fresh
        else:
            host.crypto_candles_by_tf[timeframe][symbol] = fresh

    if timeframe == TIMEFRAME_15M:
        closes = await asyncio.to_thread(
            host.quote_provider.fetch_recent_closes,
            symbol,
            cfg.chart_history_points,
        )
        if closes:
            state = host.symbol_data.get(symbol)
            if state is not None and state.points is not None:
                state.points.clear()
                for _, close_price in closes[-cfg.max_points :]:
                    state.points.append(close_price)
            candles_for_cache = [
                (c.bucket_ms, c.open, c.high, c.low, c.close)
                for c in list(host.candles.get(symbol, deque()))[-cfg.chart_history_points :]
            ]
            await asyncio.to_thread(
                save_symbol_history_cache,
                symbol,
                SYMBOL_TYPE_CRYPTO,
                closes=closes[-cfg.chart_history_points :],
                candles=candles_for_cache,
            )


async def ensure_stock_chart_history(
    host: ChartHistoryHost,
    *,
    symbol: str,
    timeframe: str,
    target_candles: int,
    candle_cls: type[Any],
    cfg: ChartHistoryConfig,
) -> None:
    series = host._get_stock_series(symbol, timeframe)
    if series is None:
        return
    required = _required_candles(target_candles, cfg)
    if len(series) >= required:
        state = host.stock_data.get(symbol)
        if state is not None and state.points is not None and len(state.points) >= cfg.chart_history_points:
            return

    candles_raw = await asyncio.to_thread(
        host.stock_provider.fetch_candles_timeframe,
        symbol,
        timeframe,
        required,
    )
    if candles_raw:
        fresh = _to_candle_deque(candles_raw, candle_cls=candle_cls, maxlen=cfg.candle_buffer_max)
        if timeframe == TIMEFRAME_15M:
            host.stock_candles[symbol] = fresh
        else:
            host.stock_candles_by_tf[timeframe][symbol] = fresh

    if timeframe == TIMEFRAME_15M:
        closes, _ = await asyncio.to_thread(
            host.stock_provider.fetch_history,
            symbol,
            cfg.chart_history_points,
            cfg.initial_candle_limit,
        )
        if closes:
            state = host.stock_data.get(symbol)
            if state is not None and state.points is not None:
                state.points.clear()
                for _, close_price in closes[-cfg.max_points :]:
                    state.points.append(close_price)
            candles_for_cache = [
                (c.bucket_ms, c.open, c.high, c.low, c.close)
                for c in list(host.stock_candles.get(symbol, deque()))[-cfg.chart_history_points :]
            ]
            await asyncio.to_thread(
                save_symbol_history_cache,
                symbol,
                SYMBOL_TYPE_STOCK,
                closes=closes[-cfg.chart_history_points :],
                candles=candles_for_cache,
            )
