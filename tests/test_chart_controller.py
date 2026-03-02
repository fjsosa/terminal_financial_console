from __future__ import annotations

from collections import deque
import unittest

from app.chart_controller import (
    handle_row_selected,
    open_alert_chart_for_row,
    open_chart_for_symbol,
    open_main_chart_for_row,
)
from app.models import StockState, SymbolState


class FakeChartModal:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakeHost:
    def __init__(self) -> None:
        self.main_group_items = [("Main", [("BTCUSDT", "crypto"), ("AAPL", "stock")])]
        self.main_group_index = 0
        self.main_row_item_by_index = {0: ("BTCUSDT", "crypto")}
        self.alerts_row_item_by_index = {0: ("AAPL", "stock")}
        self.symbol_data = {"BTCUSDT": SymbolState(symbol="BTCUSDT")}
        self.stock_data = {"AAPL": StockState(symbol="AAPL")}
        self.candles = {"BTCUSDT": deque(maxlen=10)}
        self.stock_candles = {"AAPL": deque(maxlen=10)}
        self.crypto_candles_by_tf = {"1h": {"BTCUSDT": deque(maxlen=10)}}
        self.stock_candles_by_tf = {"1h": {"AAPL": deque(maxlen=10)}}
        self.pauses: list[str] = []
        self.main_updates = 0
        self.copied_news: list[int] = []
        self.scheduled_desc: list[tuple[str, str]] = []
        self.pushed = []

    def _schedule_symbol_description_fetch(self, symbol: str, symbol_type: str) -> None:
        self.scheduled_desc.append((symbol, symbol_type))

    def _build_chart_for_item(self, symbol: str, symbol_type: str, timeframe: str, target_candles: int):
        return f"{symbol}:{symbol_type}:{timeframe}:{target_candles}"

    async def _ensure_chart_history_for_item(
        self, symbol: str, symbol_type: str, timeframe: str, target_candles: int
    ) -> None:
        return None

    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None:
        self.pauses.append(f"{table_id}:{seconds}")

    def _update_main_group_panel(self) -> None:
        self.main_updates += 1

    def _copy_news_link(self, row_index: int) -> None:
        self.copied_news.append(row_index)

    def push_screen(self, screen) -> None:
        self.pushed.append(screen)


class ChartControllerTests(unittest.TestCase):
    def test_open_chart_for_symbol(self) -> None:
        host = FakeHost()
        open_chart_for_symbol(
            host,
            "BTCUSDT",
            "crypto",
            chart_modal_cls=FakeChartModal,
            candle_buffer_max=100,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )
        self.assertEqual(len(host.pushed), 1)
        self.assertEqual(host.scheduled_desc[0], ("BTCUSDT", "crypto"))

    def test_open_chart_for_rows(self) -> None:
        host = FakeHost()
        open_main_chart_for_row(
            host,
            0,
            chart_modal_cls=FakeChartModal,
            candle_buffer_max=100,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )
        open_alert_chart_for_row(
            host,
            0,
            chart_modal_cls=FakeChartModal,
            candle_buffer_max=100,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )
        self.assertEqual(len(host.pushed), 2)

    def test_handle_row_selected(self) -> None:
        host = FakeHost()
        handle_row_selected(
            host,
            table_id="news_table",
            cursor_row=3,
            chart_modal_cls=FakeChartModal,
            candle_buffer_max=100,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )
        self.assertEqual(host.copied_news, [3])


if __name__ == "__main__":
    unittest.main()
