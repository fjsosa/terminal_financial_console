from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import AsyncIterator, Iterable

import websockets

from .config import BINANCE_REST_BASE, BINANCE_WS_BASE, RECONNECT_SECONDS
from .models import Quote


class BinanceTickerFeed:
    """Public Binance mini-ticker stream without API keys."""

    def __init__(self, symbols: Iterable[str]) -> None:
        self.symbols = [symbol.upper() for symbol in symbols]

    def _stream_url(self) -> str:
        streams = "/".join(f"{symbol.lower()}@ticker" for symbol in self.symbols)
        return f"{BINANCE_WS_BASE}?streams={streams}"

    def _rest_url(self, endpoint: str, **params: str | int) -> str:
        return f"{BINANCE_REST_BASE}/{endpoint}?{urlencode(params)}"

    async def stream(self) -> AsyncIterator[Quote]:
        while True:
            url = self._stream_url()
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    async for raw in ws:
                        payload = json.loads(raw)
                        data = payload.get("data", {})
                        symbol = data.get("s")
                        if not symbol:
                            continue
                        try:
                            yield Quote(
                                symbol=symbol,
                                price=float(data["c"]),
                                change_percent=float(data["P"]),
                                volume=float(data["v"]),
                                event_time_ms=int(data["E"]),
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
            except Exception:
                await asyncio.sleep(RECONNECT_SECONDS)

    def fetch_recent_closes(self, symbol: str, limit: int = 240) -> list[tuple[int, float]]:
        url = self._rest_url("klines", symbol=symbol.upper(), interval="1m", limit=limit)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: list[tuple[int, float]] = []
        for row in payload:
            # [openTime, open, high, low, close, volume, closeTime, ...]
            try:
                close_time_ms = int(row[6])
                close_price = float(row[4])
            except (TypeError, ValueError, IndexError):
                continue
            out.append((close_time_ms, close_price))
        return out

    def fetch_recent_15m_ohlc(
        self, symbol: str, limit: int = 96
    ) -> list[tuple[int, float, float, float, float]]:
        url = self._rest_url("klines", symbol=symbol.upper(), interval="15m", limit=limit)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: list[tuple[int, float, float, float, float]] = []
        for row in payload:
            try:
                open_time_ms = int(row[0])
                open_price = float(row[1])
                high_price = float(row[2])
                low_price = float(row[3])
                close_price = float(row[4])
            except (TypeError, ValueError, IndexError):
                continue
            out.append((open_time_ms, open_price, high_price, low_price, close_price))
        return out
