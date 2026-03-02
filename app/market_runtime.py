from __future__ import annotations

from collections import deque
from typing import Any


def update_candles(
    *,
    series: deque[Any],
    candle_cls: type[Any],
    price: float,
    event_time_ms: int,
    fifteen_min_ms: int,
) -> None:
    bucket = (event_time_ms // fifteen_min_ms) * fifteen_min_ms
    if not series or series[-1].bucket_ms != bucket:
        series.append(candle_cls(bucket_ms=bucket, open=price, high=price, low=price, close=price))
        return
    candle = series[-1]
    candle.high = max(candle.high, price)
    candle.low = min(candle.low, price)
    candle.close = price


def apply_quote_to_state(
    *,
    state: Any,
    price: float,
    change_percent: float,
    volume: float,
    event_time_ms: int,
) -> None:
    state.price = price
    state.change_percent = change_percent
    state.volume = volume
    state.last_update_ms = event_time_ms
    assert state.points is not None
    state.points.append(price)


def seed_history_state(
    *,
    state: Any,
    series: deque[Any],
    closes: list[tuple[int, float]],
    candles_raw: list[tuple[int, float, float, float, float]],
    max_points: int,
    candle_cls: type[Any],
) -> None:
    assert state.points is not None
    state.points.clear()
    for _, close_price in closes[-max_points:]:
        state.points.append(close_price)
    if closes:
        last_ts, last_close = closes[-1]
        state.last_update_ms = last_ts
        state.price = last_close

    series.clear()
    for open_ts, open_p, high_p, low_p, close_p in candles_raw:
        series.append(
            candle_cls(
                bucket_ms=open_ts,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
            )
        )


def resample_candles(candles: list[Any], timeframe: str) -> list[Any]:
    if timeframe == "15m":
        return candles
    if not candles:
        return []

    bucket_by_tf = {
        "1h": 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
        "1w": 7 * 24 * 60 * 60 * 1000,
        "1mo": 30 * 24 * 60 * 60 * 1000,
    }
    bucket_ms = bucket_by_tf.get(timeframe)
    if bucket_ms is None:
        return candles

    out: list[Any] = []
    current: Any | None = None

    for candle in candles:
        bucket = (candle.bucket_ms // bucket_ms) * bucket_ms
        if current is None or current.bucket_ms != bucket:
            if current is not None:
                out.append(current)
            current = type(candle)(
                bucket_ms=bucket,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
            )
            continue
        current.high = max(current.high, candle.high)
        current.low = min(current.low, candle.low)
        current.close = candle.close

    if current is not None:
        out.append(current)
    return out
