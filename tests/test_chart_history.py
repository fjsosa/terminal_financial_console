from __future__ import annotations

import unittest
from dataclasses import dataclass

from app.chart_history import ChartHistoryConfig, _required_candles, _to_candle_deque


@dataclass
class Candle:
    bucket_ms: int
    open: float
    high: float
    low: float
    close: float


class ChartHistoryTests(unittest.TestCase):
    def test_required_candles_respects_limits(self) -> None:
        cfg = ChartHistoryConfig(candle_buffer_max=1000, chart_history_points=240, max_points=240, initial_candle_limit=32)
        self.assertEqual(_required_candles(40, cfg), 240)
        self.assertEqual(_required_candles(900, cfg), 924)
        self.assertEqual(_required_candles(2000, cfg), 1000)

    def test_to_candle_deque_builds_candle_objects(self) -> None:
        rows = [(1, 1.0, 2.0, 0.5, 1.5), (2, 1.5, 2.5, 1.0, 2.0)]
        series = _to_candle_deque(rows, candle_cls=Candle, maxlen=100)
        self.assertEqual(len(series), 2)
        self.assertEqual(series[0].bucket_ms, 1)
        self.assertEqual(series[-1].close, 2.0)


if __name__ == "__main__":
    unittest.main()
