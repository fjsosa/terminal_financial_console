from __future__ import annotations

from collections import deque
import unittest

from app.models import StockState, SymbolState
from app.runtime_config import (
    clear_quick_actions_for_symbol,
    find_group_index,
    find_symbol_entry,
    normalize_symbol_type,
    sync_market_data_structures,
)


class RuntimeConfigTests(unittest.TestCase):
    def test_normalize_symbol_type(self) -> None:
        self.assertEqual(normalize_symbol_type("BTCUSDT", ""), "crypto")
        self.assertEqual(normalize_symbol_type("AAPL", ""), "stock")
        self.assertEqual(normalize_symbol_type("X", "stock"), "stock")

    def test_find_helpers(self) -> None:
        groups = [{"name": "Tech", "symbols": [{"symbol": "AAPL", "type": "stock"}]}]
        self.assertEqual(find_group_index(groups, "tech"), 0)
        entry = find_symbol_entry(groups, "aapl")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry[0], 0)

    def test_clear_quick_actions(self) -> None:
        qa = {"1": "AAPL", "2": "MSFT", "3": "AAPL"}
        removed = clear_quick_actions_for_symbol(qa, "aapl")
        self.assertEqual(sorted(removed), ["1", "3"])
        self.assertEqual(qa["1"], "")
        self.assertEqual(qa["3"], "")

    def test_sync_market_data_structures(self) -> None:
        main_group_items = [("MAIN", [("BTCUSDT", "crypto"), ("AAPL", "stock")])]
        symbol_data = {"OLD": SymbolState(symbol="OLD")}
        stock_data = {"OLDSTK": StockState(symbol="OLDSTK")}
        candles = {"OLD": deque(maxlen=10)}
        stock_candles = {"OLDSTK": deque(maxlen=10)}
        crypto_by_tf = {"1h": {"OLD": deque(maxlen=10)}}
        stock_by_tf = {"1h": {"OLDSTK": deque(maxlen=10)}}

        crypto_symbols, stock_symbols = sync_market_data_structures(
            main_group_items=main_group_items,
            symbol_data=symbol_data,
            stock_data=stock_data,
            candles=candles,
            stock_candles=stock_candles,
            crypto_candles_by_tf=crypto_by_tf,
            stock_candles_by_tf=stock_by_tf,
            candle_buffer_max=100,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )

        self.assertEqual(crypto_symbols, ["BTCUSDT"])
        self.assertEqual(stock_symbols, ["AAPL"])
        self.assertIn("BTCUSDT", symbol_data)
        self.assertIn("AAPL", stock_data)
        self.assertNotIn("OLD", symbol_data)
        self.assertNotIn("OLDSTK", stock_data)


if __name__ == "__main__":
    unittest.main()
