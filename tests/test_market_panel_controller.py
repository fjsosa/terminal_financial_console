from __future__ import annotations

import inspect
from collections import deque
from types import SimpleNamespace
import unittest

from rich.text import Text

from app.market_panel_controller import (
    apply_market_groups_change,
    apply_quote,
    apply_stock_quote,
    ensure_main_row_capacity,
    refresh_main_row,
)
from app.models import Candle, Quote, StockState, SymbolState


class FakeTable:
    def __init__(self) -> None:
        self.rows: list[str] = []
        self.cells: dict[tuple[str, str], object] = {}

    def add_row(self, *_values, key: str):
        self.rows.append(key)
        return key

    def update_cell(self, row_key, col_key, value):
        self.cells[(str(row_key), str(col_key))] = value


class FakeTask:
    def __init__(self, done: bool = False) -> None:
        self._done = done
        self.cancelled = False

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancelled = True


class FakeHost:
    def __init__(self) -> None:
        self.crypto_symbols = ["BTCUSDT"]
        self.stock_symbols = ["AAPL"]
        self.market_groups = [{"name": "MAIN", "symbols": [{"symbol": "BTCUSDT", "type": "crypto"}]}]
        self.main_group_items = [("MAIN", [("BTCUSDT", "crypto")])]
        self.main_group_index = 0
        self.main_row_keys = []
        self.main_col_keys = {k: k for k in ["symbol", "type", "price", "change", "volume", "spark"]}
        self.main_row_item_by_index = {0: ("BTCUSDT", "crypto"), 1: ("AAPL", "stock")}
        self.symbol_data = {"BTCUSDT": SymbolState(symbol="BTCUSDT")}
        self.stock_data = {"AAPL": StockState(symbol="AAPL")}
        self.candles = {"BTCUSDT": deque(maxlen=100)}
        self.stock_candles = {"AAPL": deque(maxlen=100)}
        self.crypto_candles_by_tf = {"1h": {"BTCUSDT": deque(maxlen=100)}}
        self.stock_candles_by_tf = {"1h": {"AAPL": deque(maxlen=100)}}
        self.name_resolve_task = FakeTask(done=False)
        self.last_tick_ms = 0
        self.calls: list[str] = []
        self.table = FakeTable()

    def query_one(self, selector, _cls):
        assert selector == "#crypto_quotes"
        return self.table

    def _update_main_group_panel(self) -> None:
        self.calls.append("update_main")

    def _update_alerts_panel(self) -> None:
        self.calls.append("update_alerts")

    def _spawn_background(self, coro):
        self.calls.append("spawn")
        if inspect.iscoroutine(coro):
            coro.close()
        return FakeTask(done=False)

    async def _refresh_crypto_stream_for_visible_group(self):
        return None

    def _schedule_stock_refresh(self) -> None:
        self.calls.append("schedule_stock")

    async def _resolve_names_background(self):
        return None

    def _sync_market_data_structures(self) -> None:
        self.calls.append("sync")

    def _trend_color(self, is_up: bool, symbol_type: str | None = None) -> str:
        del symbol_type
        return "green" if is_up else "red"

    def _format_volume(self, volume: float, width: int = 17) -> str:
        del width
        return f"{volume:.2f}"

    def _sparkline(self, values: deque[float]) -> Text:
        del values
        return Text("··")

    def _ticker_label(self, symbol: str, symbol_type: str, max_name_len: int = 20) -> Text:
        del max_name_len
        return Text(f"{symbol}:{symbol_type}")

    def _new_stock_state(self, symbol: str):
        return StockState(symbol=symbol)


class MarketPanelControllerTests(unittest.TestCase):
    def test_ensure_main_row_capacity(self) -> None:
        host = FakeHost()
        ensure_main_row_capacity(host, 2)
        self.assertEqual(len(host.main_row_keys), 2)

    def test_apply_market_groups_change(self) -> None:
        host = FakeHost()
        apply_market_groups_change(host, resolve_missing_names=True)
        self.assertIn("sync", host.calls)
        self.assertIn("update_main", host.calls)
        self.assertIn("schedule_stock", host.calls)
        self.assertTrue(host.name_resolve_task is not None)

    def test_apply_quote(self) -> None:
        host = FakeHost()
        q = Quote(symbol="BTCUSDT", price=100.0, change_percent=1.0, volume=1000.0, event_time_ms=15 * 60 * 1000)
        apply_quote(host, q, fifteen_min_ms=15 * 60 * 1000, candle_cls=Candle)
        self.assertEqual(host.last_tick_ms, q.event_time_ms)
        self.assertEqual(len(host.candles["BTCUSDT"]), 1)
        self.assertIn("update_alerts", host.calls)

    def test_apply_stock_quote(self) -> None:
        host = FakeHost()
        q = SimpleNamespace(
            symbol="AAPL",
            price=200.0,
            change_percent=-1.0,
            volume=5000.0,
            event_time_ms=15 * 60 * 1000,
        )
        apply_stock_quote(host, q, fifteen_min_ms=15 * 60 * 1000, candle_cls=Candle)
        self.assertEqual(len(host.stock_candles["AAPL"]), 1)
        self.assertIn("update_main", host.calls)

    def test_refresh_main_row(self) -> None:
        host = FakeHost()
        ensure_main_row_capacity(host, 2)
        refresh_main_row(host, "BTCUSDT", "crypto")
        self.assertIn(("main_0", "symbol"), host.table.cells)


if __name__ == "__main__":
    unittest.main()
