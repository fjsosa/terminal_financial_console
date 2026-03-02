from __future__ import annotations

import unittest
from collections import deque
from dataclasses import dataclass

from rich.text import Text

from app.chart_rendering import (
    build_chart_from_series,
    build_chart_text,
    build_stock_chart_text,
    compress_series,
    render_candlestick_chart,
    render_plotext_xy,
    render_xy_ascii,
)


@dataclass
class Candle:
    bucket_ms: int
    open: float
    high: float
    low: float
    close: float


class State:
    def __init__(self, symbol: str, price: float = 0.0, change: float = 0.0, volume: float = 0.0):
        self.symbol = symbol
        self.price = price
        self.change_percent = change
        self.volume = volume
        self.points = deque([1.0, 2.0, 3.0], maxlen=240)


class FakeHost:
    def __init__(self) -> None:
        self.candles = {"BTCUSDT": deque([Candle(1, 1, 2, 0.5, 1.5), Candle(2, 1.5, 2.5, 1.0, 2.0)])}
        self.stock_candles = {"AAPL": deque([Candle(1, 10, 11, 9, 10.5), Candle(2, 10.5, 12, 10, 11.5)])}
        self.symbol_names = {("BTCUSDT", "crypto"): "Bitcoin", ("AAPL", "stock"): "Apple"}
        self.symbol_descriptions = {("BTCUSDT", "crypto"): "Crypto description", ("AAPL", "stock"): "Stock description"}
        self.symbol_categories = {("BTCUSDT", "crypto"): "Layer1", ("AAPL", "stock"): "Technology"}
        self.description_fetching: set[tuple[str, str]] = set()

    def _get_crypto_series(self, symbol: str, timeframe: str):
        return self.candles.get(symbol)

    def _get_stock_series(self, symbol: str, timeframe: str):
        return self.stock_candles.get(symbol)

    def _resample_candles(self, candles, timeframe: str):
        return candles

    def _ui_palette(self):
        return {
            "brand": "cyan",
            "muted": "gray",
            "text": "white",
            "accent": "yellow",
            "ok": "green",
        }

    def _trend_color(self, is_up: bool, symbol_type: str | None = None):
        return "green" if is_up else "red"


class DummyPlotext:
    def __init__(self) -> None:
        self.called = []

    def clear_figure(self):
        self.called.append("clear")

    def plot_size(self, w, h):
        self.called.append(("size", w, h))

    def title(self, t):
        self.called.append(("title", t))

    def xlabel(self, x):
        self.called.append(("xlabel", x))

    def ylabel(self, y):
        self.called.append(("ylabel", y))

    def grid(self, *_args):
        self.called.append("grid")

    def plot(self, *_args, **_kwargs):
        self.called.append("plot")

    def build(self):
        return "PLOT\nLINE1\nLINE2"


class ChartRenderingTests(unittest.TestCase):
    def test_compress_series(self):
        self.assertEqual(compress_series([1, 2, 3], 5), [1, 2, 3])
        out = compress_series(list(range(100)), 10)
        self.assertEqual(len(out), 10)

    def test_render_candlestick_chart(self):
        candles = [Candle(1, 1, 2, 0.5, 1.8), Candle(2, 1.8, 2.2, 1.0, 1.2)]
        txt = render_candlestick_chart(
            candles,
            width=10,
            height=6,
            palette={"accent": "cyan"},
            trend_color=lambda up: "green" if up else "red",
        )
        self.assertIn("high", txt.plain)
        self.assertIn("low", txt.plain)

    def test_render_xy_ascii(self):
        txt = render_xy_ascii([1, 2, 3, 2, 4], width=20, height=6, color="green", palette={"accent": "cyan", "muted": "gray"})
        self.assertIsInstance(txt, Text)
        self.assertIn("latest", txt.plain)

    def test_render_plotext_xy_with_dummy_backend(self):
        dummy = DummyPlotext()
        out = render_plotext_xy([1, 2, 3], "BTCUSDT", plotext_module=dummy)
        self.assertIn("PLOT", out)
        self.assertTrue(any(c == "plot" for c in dummy.called))

    def test_build_chart_from_series_and_wrappers(self):
        host = FakeHost()
        txt = build_chart_from_series(
            host,
            symbol="BTCUSDT",
            display_name="Bitcoin",
            market_label="CRYPTO",
            price=100.0,
            change_percent=1.2,
            volume=1_000_000,
            values=[1.0, 2.0, 3.0],
            candles=list(host.candles["BTCUSDT"]),
            timeframe="15m",
            target_candles=32,
        )
        self.assertIn("SNAPSHOT", txt.plain)
        self.assertIn("Category", txt.plain)

        s_crypto = State("BTCUSDT", 100, 1.0, 1000)
        s_stock = State("AAPL", 200, -1.0, 2000)
        txt_crypto = build_chart_text(host, s_crypto, timeframe="15m", target_candles=24)
        txt_stock = build_stock_chart_text(host, s_stock, timeframe="15m", target_candles=24)
        self.assertIn("BTCUSDT", txt_crypto.plain)
        self.assertIn("AAPL", txt_stock.plain)


if __name__ == "__main__":
    unittest.main()
