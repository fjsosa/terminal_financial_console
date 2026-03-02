from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

if importlib.util.find_spec("yfinance") is None:  # pragma: no cover - env dependent
    raise unittest.SkipTest("yfinance not installed")

from app.providers import (
    BinanceQuoteProvider,
    DefaultProfileProvider,
    FinvizNewsProvider,
    ForexFactoryCalendarProvider,
    YFinanceStockProvider,
)


class ProvidersTests(unittest.TestCase):
    def test_binance_quote_provider_set_symbols(self) -> None:
        provider = BinanceQuoteProvider(["BTCUSDT"])
        self.assertEqual(provider.symbols, ["BTCUSDT"])
        provider.set_symbols(["ETHUSDT", "SOLUSDT"])
        self.assertEqual(provider.symbols, ["ETHUSDT", "SOLUSDT"])

    @patch("app.providers.fetch_stock_quotes", return_value=["ok"])
    def test_stock_provider_fetch_quotes(self, mock_fetch):
        provider = YFinanceStockProvider()
        result = provider.fetch_quotes(["AAPL"])
        self.assertEqual(result, ["ok"])
        mock_fetch.assert_called_once_with(["AAPL"])

    @patch("app.providers.fetch_stock_history", return_value=([(1, 2.0)], [(1, 1.0, 2.0, 0.5, 1.5)]))
    def test_stock_provider_fetch_history(self, mock_fetch):
        provider = YFinanceStockProvider()
        closes, candles = provider.fetch_history("AAPL", 10, 5)
        self.assertEqual(len(closes), 1)
        self.assertEqual(len(candles), 1)
        mock_fetch.assert_called_once_with("AAPL", 10, 5)

    @patch("app.providers.fetch_all_news", return_value={"NEWS": []})
    def test_news_provider(self, mock_fetch):
        provider = FinvizNewsProvider()
        result = provider.fetch_all_news(7)
        self.assertIn("NEWS", result)
        mock_fetch.assert_called_once_with(7)

    @patch("app.providers.fetch_calendar_events", return_value=[])
    def test_calendar_provider(self, mock_fetch):
        provider = ForexFactoryCalendarProvider()
        result = provider.fetch_events([{"name": "USA"}], 15)
        self.assertEqual(result, [])
        mock_fetch.assert_called_once()

    @patch("app.providers.fetch_symbol_profile", return_value=("desc", "cat"))
    def test_profile_provider(self, mock_fetch):
        provider = DefaultProfileProvider()
        desc, cat = provider.fetch_symbol_profile("AAPL", "stock")
        self.assertEqual(desc, "desc")
        self.assertEqual(cat, "cat")
        mock_fetch.assert_called_once_with("AAPL", "stock")


if __name__ == "__main__":
    unittest.main()
