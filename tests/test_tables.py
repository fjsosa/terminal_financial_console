from __future__ import annotations

import importlib.util
import unittest

from rich.text import Text

if importlib.util.find_spec("textual") is None:  # pragma: no cover - env dependent
    raise unittest.SkipTest("textual not installed")

from app.tables import update_alerts_panel, update_indicators_panel, update_main_group_panel, update_news_panel


class FakeTable:
    def __init__(self) -> None:
        self.cells: dict[tuple[str, str], object] = {}
        self.border_title = ""

    def update_cell(self, row_key, col_key, value):
        self.cells[(str(row_key), str(col_key))] = value


class FakeHeader:
    def __init__(self) -> None:
        self.value = None

    def update(self, value):
        self.value = value


class State:
    def __init__(self, price=0.0, change=0.0, vol=0.0, last=0):
        self.price = price
        self.change_percent = change
        self.volume = vol
        self.last_update_ms = last


class FakeHost:
    def __init__(self) -> None:
        self.main_group_items = [("MAIN", [("AAPL", "stock"), ("BTCUSDT", "crypto")])]
        self.main_group_index = 0
        self.main_visible_items = []
        self.main_row_item_by_index = {}
        self.main_row_keys = ["r0", "r1", "r2"]
        self.main_col_keys = {k: k for k in ["symbol", "type", "price", "change", "volume", "spark"]}
        self.stocks_last_update = "10:00"

        self.indicator_group_items = [("IDX", [("^GSPC", "stock")])]
        self.indicator_group_index = 0
        self.indicator_visible_items = []
        self.indicator_row_item_by_index = {}
        self.indicator_row_keys = ["i0", "i1"]
        self.indicator_col_keys = {k: k for k in ["symbol", "change", "price"]}
        self.indicators_last_update = "10:00"
        self.indicator_data = {"^GSPC": State(price=5000, change=1.2)}

        self.symbol_data = {"BTCUSDT": State(price=60000, change=2.5, vol=150_000_000, last=1)}
        self.stock_data = {"AAPL": State(price=200, change=-1.0, vol=80_000_000, last=1)}
        self.alerts_row_item_by_index = {}
        self.alerts_row_keys = ["a0", "a1", "a2"]
        self.alerts_col_keys = {k: k for k in ["symbol", "type", "change", "price", "volume"]}

        self.news_groups = []
        self.news_group_index = 0
        self.news_last_update = "10:00"
        self.news_row_links = {}
        self.news_row_keys = ["n0", "n1", "n2"]
        self.news_col_keys = {"title": "title"}

        self.tables = {
            "#crypto_quotes": FakeTable(),
            "#indicators_table": FakeTable(),
            "#stock_quotes": FakeTable(),
            "#news_table": FakeTable(),
        }
        self.header = FakeHeader()

    def query_one(self, selector, _cls):
        if selector == "#news_header":
            return self.header
        return self.tables[selector]

    def _ui_palette(self):
        return {"ok": "green", "warn": "yellow", "accent": "cyan", "muted": "gray"}

    def _trend_color(self, is_up: bool, symbol_type: str | None = None):
        return "green" if is_up else "red"

    def _ticker_label(self, symbol: str, symbol_type: str, max_name_len: int = 20):
        return Text(f"{symbol}:{symbol_type}")

    def _format_volume(self, volume: float, width: int = 17):
        return f"{volume:.2f}"

    def _format_news_headline(self, source: str, age: str, title: str, line_len: int = 86):
        return Text(f"[{source}:{age}] {title}")

    def _refresh_main_row(self, symbol: str, symbol_type: str):
        table = self.tables["#crypto_quotes"]
        row = "r0" if symbol == "AAPL" else "r1"
        table.update_cell(row, "symbol", Text(f"{symbol}:{symbol_type}"))

    def _get_change_percent(self, symbol: str, symbol_type: str) -> float:
        return 1.0 if symbol == "BTCUSDT" else -1.0

    def _new_stock_state(self, symbol: str):
        return State()


class TablesTests(unittest.TestCase):
    def test_update_main_group_panel(self):
        host = FakeHost()
        update_main_group_panel(host)
        self.assertEqual(len(host.main_visible_items), 2)
        self.assertIn(0, host.main_row_item_by_index)

    def test_update_indicators_panel(self):
        host = FakeHost()
        update_indicators_panel(host)
        self.assertIn(0, host.indicator_row_item_by_index)

    def test_update_alerts_panel(self):
        host = FakeHost()
        update_alerts_panel(host, alerts_table_size=2)
        self.assertEqual(len(host.alerts_row_item_by_index), 2)

    def test_update_news_panel_empty(self):
        host = FakeHost()
        update_news_panel(host, news_group_size=3, news_refresh_seconds=600)
        self.assertIsNotNone(host.header.value)


if __name__ == "__main__":
    unittest.main()
