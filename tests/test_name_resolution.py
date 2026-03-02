from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

from app.name_resolution import (
    load_cached_descriptions,
    load_cached_symbol_names,
    resolve_names_background,
)


class FakeHost:
    def __init__(self) -> None:
        self.market_groups = [{"name": "Main", "symbols": [{"symbol": "AAPL", "type": "stock"}]}]
        self.indicator_groups = [{"name": "Idx", "symbols": [{"symbol": "^GSPC", "type": "stock"}]}]
        self.indicator_group_items = []
        self.indicator_symbols = []
        self.indicator_data = {}
        self.symbol_names = {}
        self.symbol_descriptions = {}
        self.symbol_categories = {}
        self.symbols_from_config = True
        self.config_path = "config.yml"
        self.logs: list[str] = []
        self.updated = 0

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _update_main_group_panel(self) -> None:
        self.updated += 1

    def _update_indicators_panel(self) -> None:
        self.updated += 1

    def _update_alerts_panel(self) -> None:
        self.updated += 1

    def _new_stock_state(self, symbol: str):
        return SimpleNamespace(symbol=symbol)


class NameResolutionTests(unittest.TestCase):
    def test_load_cached_names_and_descriptions(self) -> None:
        host = FakeHost()
        load_cached_symbol_names(
            host,
            ttl_seconds=60,
            load_names_cache_fn=lambda _ttl: {("AAPL", "stock"): "Apple"},
        )
        self.assertEqual(host.symbol_names[("AAPL", "stock")], "Apple")

        load_cached_descriptions(
            host,
            ttl_seconds=60,
            load_descriptions_cache_fn=lambda _ttl: {("AAPL", "stock"): "Company"},
            load_categories_cache_fn=lambda _ttl: {("AAPL", "stock"): "Tech"},
        )
        self.assertEqual(host.symbol_descriptions[("AAPL", "stock")], "Company")
        self.assertEqual(host.symbol_categories[("AAPL", "stock")], "Tech")

    def test_resolve_names_background(self) -> None:
        async def run_io(fn, *args):
            return fn(*args)

        def resolve_fn(_groups, _indicator_groups):
            return (
                [{"name": "Main", "symbols": [{"symbol": "AAPL", "type": "stock", "name": "Apple"}]}],
                [{"name": "Idx", "symbols": [{"symbol": "^GSPC", "type": "stock", "name": "S&P500"}]}],
                {("AAPL", "stock"): "Apple", ("^GSPC", "stock"): "S&P500"},
                {
                    "stocks_total": 2,
                    "stocks_missing_name": 0,
                    "stocks_resolved_remote": 1,
                    "crypto_total": 0,
                    "crypto_missing_name": 0,
                    "crypto_resolved_remote": 0,
                },
            )

        async def run() -> None:
            host = FakeHost()
            saved: dict = {}

            def save_names(names):
                saved.update(names)

            await resolve_names_background(
                host,
                run_io=run_io,
                resolve_symbol_names_fn=resolve_fn,
                save_names_cache_fn=save_names,
                update_config_group_names_fn=lambda *_args: True,
            )
            self.assertIn(("AAPL", "stock"), host.symbol_names)
            self.assertIn("^GSPC", host.indicator_data)
            self.assertGreaterEqual(host.updated, 3)
            self.assertIn(("AAPL", "stock"), saved)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
