from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from app.history_orchestration import (
    current_visible_symbols,
    load_remaining_history_in_background,
    preload_visible_group_history,
)


class FakeBootModal:
    def __init__(self) -> None:
        self.total = 0
        self.increments = 0

    def set_total(self, total: int) -> None:
        self.total = total

    def increment(self) -> None:
        self.increments += 1


class FakeQuoteProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def fetch_recent_closes(self, symbol: str, limit: int):
        self.calls.append(("closes", symbol, limit))
        return [(1000, 10.0), (2000, 11.0)]

    def fetch_recent_15m_ohlc(self, symbol: str, limit: int):
        self.calls.append(("candles", symbol, limit))
        return [(1000, 9.0, 12.0, 8.0, 11.0)]


class FakeStockProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def fetch_history(self, symbol: str, points: int, candles: int):
        self.calls.append((symbol, points, candles))
        return ([(3000, 20.0), (4000, 21.0)], [(3000, 19.0, 22.0, 18.0, 21.0)])


class FakeHost:
    def __init__(self) -> None:
        self.crypto_symbols = ["BTCUSDT", "ETHUSDT"]
        self.stock_symbols = ["AAPL", "MSFT"]
        self.main_visible_items = [("BTCUSDT", "crypto"), ("AAPL", "stock")]
        self.quote_provider = FakeQuoteProvider()
        self.stock_provider = FakeStockProvider()
        self.boot_modal = FakeBootModal()
        self.seeded_crypto: list[tuple[str, list[tuple[int, float]], list[tuple[int, float, float, float, float]]]] = []
        self.seeded_stock: list[tuple[str, list[tuple[int, float]], list[tuple[int, float, float, float, float]]]] = []
        self.logs: list[str] = []
        self.main_updates = 0
        self.alert_updates = 0

    def _seed_symbol_history(self, symbol, closes, candles_raw) -> None:
        self.seeded_crypto.append((symbol, closes, candles_raw))

    def _seed_stock_history(self, symbol, closes, candles_raw) -> None:
        self.seeded_stock.append((symbol, closes, candles_raw))

    def _update_main_group_panel(self) -> None:
        self.main_updates += 1

    def _update_alerts_panel(self) -> None:
        self.alert_updates += 1

    def _log(self, message: str) -> None:
        self.logs.append(message)


async def run_io(fn, *args, **kwargs):
    return fn(*args, **kwargs)


class HistoryOrchestrationTests(unittest.TestCase):
    def test_current_visible_symbols(self) -> None:
        crypto, stock = current_visible_symbols([
            ("BTCUSDT", "crypto"),
            ("AAPL", "stock"),
            ("ETHUSDT", "crypto"),
        ])
        self.assertEqual(crypto, ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(stock, ["AAPL"])

    def test_preload_uses_cache_and_fetches_missing(self) -> None:
        async def run() -> None:
            host = FakeHost()
            saved: list[tuple[str, str]] = []

            def load_cache(symbol: str, symbol_type: str, _ttl: int):
                if symbol == "BTCUSDT" and symbol_type == "crypto":
                    return {
                        "closes": [(1, 1.0), (2, 2.0), (3, 3.0)],
                        "candles": [(1, 1.0, 1.0, 1.0, 1.0), (2, 2.0, 2.0, 2.0, 2.0)],
                    }
                return None

            def save_cache(symbol: str, symbol_type: str, **_kwargs):
                saved.append((symbol, symbol_type))

            await preload_visible_group_history(
                host,
                cache_ttl_seconds=300,
                initial_history_points=2,
                initial_candle_limit=1,
                startup_io_concurrency=4,
                load_symbol_history_cache_fn=load_cache,
                save_symbol_history_cache_fn=save_cache,
                run_io=run_io,
            )

            self.assertEqual(host.boot_modal.total, 2)
            self.assertEqual(host.boot_modal.increments, 2)
            self.assertEqual(host.main_updates, 1)
            self.assertEqual(host.alert_updates, 1)
            self.assertEqual(host.seeded_crypto[0][0], "BTCUSDT")
            self.assertEqual(host.seeded_crypto[0][1], [(2, 2.0), (3, 3.0)])
            self.assertEqual(host.seeded_stock[0][0], "AAPL")
            self.assertIn(("AAPL", "stock"), saved)
            self.assertIn("CACHE", " ".join(host.logs))

        asyncio.run(run())

    def test_lazy_load_only_remaining_symbols(self) -> None:
        async def run() -> None:
            host = FakeHost()
            saved: list[tuple[str, str]] = []

            def load_cache(symbol: str, symbol_type: str, _ttl: int):
                if symbol == "ETHUSDT" and symbol_type == "crypto":
                    return {
                        "closes": [(10, 10.0), (11, 11.0)],
                        "candles": [(10, 9.0, 12.0, 8.0, 11.0)],
                    }
                return None

            def save_cache(symbol: str, symbol_type: str, **_kwargs):
                saved.append((symbol, symbol_type))

            await load_remaining_history_in_background(
                host,
                cache_ttl_seconds=300,
                initial_history_points=2,
                initial_candle_limit=1,
                startup_io_concurrency=2,
                load_symbol_history_cache_fn=load_cache,
                save_symbol_history_cache_fn=save_cache,
                run_io=run_io,
            )

            # Visible items BTCUSDT/AAPL are skipped. Remaining are ETHUSDT/MSFT.
            self.assertEqual(host.seeded_crypto[0][0], "ETHUSDT")
            self.assertEqual(host.seeded_stock[0][0], "MSFT")
            self.assertIn(("MSFT", "stock"), saved)
            self.assertIn("lazy background load completed", " ".join(host.logs))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
