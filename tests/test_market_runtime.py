from __future__ import annotations

from collections import deque
import unittest

from app.market_runtime import apply_quote_to_state, resample_candles, seed_history_state, update_candles
from app.models import Candle, SymbolState


class MarketRuntimeTests(unittest.TestCase):
    def test_update_candles_appends_and_updates(self) -> None:
        series: deque[Candle] = deque(maxlen=10)
        update_candles(
            series=series,
            candle_cls=Candle,
            price=100.0,
            event_time_ms=15 * 60 * 1000,
            fifteen_min_ms=15 * 60 * 1000,
        )
        self.assertEqual(len(series), 1)
        update_candles(
            series=series,
            candle_cls=Candle,
            price=105.0,
            event_time_ms=15 * 60 * 1000 + 1000,
            fifteen_min_ms=15 * 60 * 1000,
        )
        self.assertEqual(series[-1].high, 105.0)
        self.assertEqual(series[-1].close, 105.0)

    def test_apply_quote_to_state(self) -> None:
        state = SymbolState(symbol="BTCUSDT")
        apply_quote_to_state(
            state=state,
            price=123.4,
            change_percent=1.2,
            volume=1000,
            event_time_ms=7,
        )
        self.assertEqual(state.price, 123.4)
        self.assertEqual(state.last_update_ms, 7)
        assert state.points is not None
        self.assertEqual(state.points[-1], 123.4)

    def test_seed_history_state(self) -> None:
        state = SymbolState(symbol="BTCUSDT")
        series: deque[Candle] = deque(maxlen=100)
        seed_history_state(
            state=state,
            series=series,
            closes=[(1, 10.0), (2, 11.0), (3, 12.0)],
            candles_raw=[(1, 10.0, 12.0, 9.0, 11.0)],
            max_points=2,
            candle_cls=Candle,
        )
        assert state.points is not None
        self.assertEqual(list(state.points), [11.0, 12.0])
        self.assertEqual(state.price, 12.0)
        self.assertEqual(len(series), 1)

    def test_resample_candles(self) -> None:
        candles = [
            Candle(bucket_ms=0, open=1, high=2, low=1, close=2),
            Candle(bucket_ms=15 * 60 * 1000, open=2, high=3, low=2, close=2.5),
            Candle(bucket_ms=30 * 60 * 1000, open=2.5, high=4, low=2, close=3.5),
            Candle(bucket_ms=60 * 60 * 1000, open=3.5, high=5, low=3, close=4.5),
        ]
        hourly = resample_candles(candles, "1h")
        self.assertEqual(len(hourly), 2)
        self.assertEqual(hourly[0].high, 4)


if __name__ == "__main__":
    unittest.main()
