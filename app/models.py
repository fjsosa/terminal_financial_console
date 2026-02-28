from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Quote:
    symbol: str
    price: float
    change_percent: float
    volume: float
    event_time_ms: int

