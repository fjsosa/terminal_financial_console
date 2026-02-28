from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Iterable

import websockets

from .config import BINANCE_WS_BASE, RECONNECT_SECONDS
from .models import Quote


class BinanceTickerFeed:
    """Public Binance mini-ticker stream without API keys."""

    def __init__(self, symbols: Iterable[str]) -> None:
        self.symbols = [symbol.upper() for symbol in symbols]

    def _stream_url(self) -> str:
        streams = "/".join(f"{symbol.lower()}@ticker" for symbol in self.symbols)
        return f"{BINANCE_WS_BASE}?streams={streams}"

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

