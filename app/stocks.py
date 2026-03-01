from __future__ import annotations

import time
from dataclasses import dataclass

import yfinance as yf


@dataclass(slots=True)
class StockQuote:
    symbol: str
    price: float
    change_percent: float
    volume: float
    event_time_ms: int


def fetch_stock_quotes(symbols: list[str]) -> list[StockQuote]:
    if not symbols:
        return []

    joined = " ".join(symbols)
    tickers = yf.Tickers(joined)
    results: list[StockQuote] = []

    for symbol in symbols:
        ticker = tickers.tickers.get(symbol.upper())
        if ticker is None:
            continue
        try:
            hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
        except Exception:
            continue
        if hist is None or hist.empty:
            continue

        try:
            close = float(hist["Close"].iloc[-1])
            volume = float(hist["Volume"].iloc[-1])
        except Exception:
            continue

        if len(hist) >= 2:
            try:
                prev_close = float(hist["Close"].iloc[-2])
                change = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
            except Exception:
                change = 0.0
        else:
            change = 0.0

        results.append(
            StockQuote(
                symbol=symbol.upper(),
                price=close,
                change_percent=change,
                volume=volume,
                event_time_ms=int(time.time() * 1000),
            )
        )

    return results


def fetch_stock_candles(
    symbol: str, candle_limit: int = 96
) -> list[tuple[int, float, float, float, float]]:
    return fetch_stock_candles_timeframe(symbol, "15m", candle_limit)


def fetch_stock_candles_timeframe(
    symbol: str, timeframe: str = "15m", candle_limit: int = 96
) -> list[tuple[int, float, float, float, float]]:
    ticker = yf.Ticker(symbol.upper())
    candles: list[tuple[int, float, float, float, float]] = []
    if candle_limit <= 0:
        return candles

    interval_map = {
        "15m": "15m",
        "1h": "60m",
        "1d": "1d",
        "1w": "1wk",
        "1mo": "1mo",
    }
    period_map = {
        "15m": "60d",
        "1h": "730d",
        "1d": "max",
        "1w": "max",
        "1mo": "max",
    }
    interval = interval_map.get(timeframe, "15m")
    period = period_map.get(timeframe, "60d")

    try:
        hist_15m = ticker.history(period=period, interval=interval, auto_adjust=False)
    except Exception:
        hist_15m = None
    if hist_15m is None or hist_15m.empty:
        return candles

    for ts, row in hist_15m.tail(candle_limit).iterrows():
        try:
            ts_ms = int(ts.timestamp() * 1000)
            open_price = float(row["Open"])
            high_price = float(row["High"])
            low_price = float(row["Low"])
            close_price = float(row["Close"])
        except Exception:
            continue
        candles.append((ts_ms, open_price, high_price, low_price, close_price))
    return candles


def fetch_stock_history(
    symbol: str, close_limit: int = 240, candle_limit: int = 96
) -> tuple[list[tuple[int, float]], list[tuple[int, float, float, float, float]]]:
    ticker = yf.Ticker(symbol.upper())
    closes: list[tuple[int, float]] = []
    candles: list[tuple[int, float, float, float, float]] = []

    try:
        hist_1m = ticker.history(period="7d", interval="1m", auto_adjust=False)
    except Exception:
        hist_1m = None
    if hist_1m is not None and not hist_1m.empty:
        for ts, row in hist_1m.tail(close_limit).iterrows():
            try:
                ts_ms = int(ts.timestamp() * 1000)
                close_price = float(row["Close"])
            except Exception:
                continue
            closes.append((ts_ms, close_price))

    candles = fetch_stock_candles(symbol, candle_limit)

    return closes, candles
