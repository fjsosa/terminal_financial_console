from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .config import MAX_POINTS


@dataclass(slots=True)
class Quote:
    symbol: str
    price: float
    change_percent: float
    volume: float
    event_time_ms: int


@dataclass(slots=True)
class SymbolState:
    symbol: str
    price: float = 0.0
    change_percent: float = 0.0
    volume: float = 0.0
    points: deque[float] | None = None
    last_update_ms: int = 0

    def __post_init__(self) -> None:
        if self.points is None:
            self.points = deque(maxlen=MAX_POINTS)


@dataclass(slots=True)
class StockState:
    symbol: str
    price: float = 0.0
    change_percent: float = 0.0
    volume: float = 0.0
    points: deque[float] | None = None
    last_update_ms: int = 0

    def __post_init__(self) -> None:
        if self.points is None:
            self.points = deque(maxlen=MAX_POINTS)


@dataclass(slots=True)
class Candle:
    bucket_ms: int
    open: float
    high: float
    low: float
    close: float
