from __future__ import annotations

import unittest

from app.focus_navigation import focus_symbol
from app.models import StockState, SymbolState


class FakeTable:
    def __init__(self) -> None:
        self.cursor_row = None

    def move_cursor(self, row: int) -> None:
        self.cursor_row = row


class FakeHost:
    def __init__(self) -> None:
        self.symbol_data = {"BTCUSDT": SymbolState(symbol="BTCUSDT")}
        self.stock_data = {"AAPL": StockState(symbol="AAPL")}
        self.indicator_data = {"^GSPC": StockState(symbol="^GSPC")}
        self.main_group_items = [("MAIN", [("BTCUSDT", "crypto"), ("AAPL", "stock")])]
        self.indicator_group_items = [("IDX", [("^GSPC", "stock")])]
        self.main_group_index = 0
        self.indicator_group_index = 0
        self.main_row_item_by_index = {0: ("BTCUSDT", "crypto"), 1: ("AAPL", "stock")}
        self.indicator_row_item_by_index = {0: ("^GSPC", "stock")}
        self.focused_symbol = None
        self.logs: list[str] = []
        self.pauses: list[str] = []
        self.main_updates = 0
        self.ind_updates = 0
        self.main_table = FakeTable()
        self.ind_table = FakeTable()

    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None:
        self.pauses.append(f"{table_id}:{seconds}")

    def _update_main_group_panel(self) -> None:
        self.main_updates += 1

    def _update_indicators_panel(self) -> None:
        self.ind_updates += 1

    def query_one(self, selector, _cls):
        if selector == "#crypto_quotes":
            return self.main_table
        if selector == "#indicators_table":
            return self.ind_table
        raise AssertionError(selector)

    def _log(self, message: str) -> None:
        self.logs.append(message)


class FocusNavigationTests(unittest.TestCase):
    def test_focus_crypto(self) -> None:
        host = FakeHost()
        focus_symbol(host, "BTCUSDT")
        self.assertEqual(host.focused_symbol, "BTCUSDT")
        self.assertEqual(host.main_table.cursor_row, 0)
        self.assertGreater(host.main_updates, 0)

    def test_focus_indicator(self) -> None:
        host = FakeHost()
        focus_symbol(host, "^GSPC")
        self.assertEqual(host.focused_symbol, "^GSPC")
        self.assertEqual(host.ind_table.cursor_row, 0)
        self.assertGreater(host.ind_updates, 0)

    def test_focus_missing_logs(self) -> None:
        host = FakeHost()
        focus_symbol(host, "UNKNOWN")
        self.assertTrue(any("not found" in m for m in host.logs))


if __name__ == "__main__":
    unittest.main()
