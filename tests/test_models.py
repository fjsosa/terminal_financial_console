from __future__ import annotations

import unittest

from app.config import MAX_POINTS
from app.models import Candle, StockState, SymbolState


class ModelsTests(unittest.TestCase):
    def test_symbol_state_initializes_points_with_maxlen(self) -> None:
        state = SymbolState(symbol="BTCUSDT")
        self.assertIsNotNone(state.points)
        assert state.points is not None
        self.assertEqual(state.points.maxlen, MAX_POINTS)

    def test_stock_state_initializes_points_with_maxlen(self) -> None:
        state = StockState(symbol="AAPL")
        self.assertIsNotNone(state.points)
        assert state.points is not None
        self.assertEqual(state.points.maxlen, MAX_POINTS)

    def test_candle_fields(self) -> None:
        candle = Candle(bucket_ms=1, open=1.0, high=2.0, low=0.5, close=1.5)
        self.assertEqual(candle.bucket_ms, 1)
        self.assertEqual(candle.close, 1.5)


if __name__ == "__main__":
    unittest.main()
