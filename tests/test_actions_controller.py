from __future__ import annotations

from collections import deque
import unittest

from app.actions_controller import (
    enter_command_mode_action,
    exit_command_mode_action,
    open_calendar_modal,
    quick_quit,
    refresh_news_action,
    reset_local_buffers,
)
from app.models import StockState, SymbolState


class FakeScreen:
    def __init__(self) -> None:
        self.dismissed = False

    def dismiss(self, _value) -> None:
        self.dismissed = True


class FakeCalendarModal:
    def __init__(self, builder) -> None:
        self.builder = builder


class FakeHost:
    def __init__(self) -> None:
        self.command_mode = False
        self.screen = object()
        self.crypto_symbols = ["BTCUSDT"]
        self.stock_symbols = ["AAPL"]
        self.indicator_symbols = ["^GSPC"]
        self.symbol_data = {"BTCUSDT": SymbolState(symbol="BTCUSDT")}
        self.stock_data = {"AAPL": StockState(symbol="AAPL")}
        self.indicator_data = {"^GSPC": StockState(symbol="^GSPC")}
        self.crypto_candles_by_tf = {"1h": {"BTCUSDT": deque([1])}}
        self.stock_candles_by_tf = {"1h": {"AAPL": deque([1])}}
        self.stock_candles = {"AAPL": deque([1])}
        self.logs: list[str] = []
        self.calls: list[str] = []
        self.pushed_screen = None

    def _refresh_main_row(self, symbol: str, symbol_type: str) -> None:
        self.calls.append(f"refresh:{symbol}:{symbol_type}")

    def _update_main_group_panel(self) -> None:
        self.calls.append("main")

    def _update_indicators_panel(self) -> None:
        self.calls.append("ind")

    def _update_alerts_panel(self) -> None:
        self.calls.append("alerts")

    def _schedule_news_refresh(self) -> None:
        self.calls.append("news_refresh")

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _ui_palette(self) -> dict[str, str]:
        return {"accent": "cyan"}

    def _build_calendar_text(self):
        return "calendar"

    def call_after_refresh(self, callback) -> None:
        callback()

    def push_screen(self, screen) -> None:
        self.pushed_screen = screen

    def _enter_command_mode(self) -> None:
        self.calls.append("enter_cmd")

    def _exit_command_mode(self) -> None:
        self.calls.append("exit_cmd")

    def exit(self) -> None:
        self.calls.append("exit")


class ActionsControllerTests(unittest.TestCase):
    def test_open_calendar_modal(self) -> None:
        host = FakeHost()
        open_calendar_modal(host, FakeCalendarModal)
        self.assertIsNotNone(host.pushed_screen)
        self.assertIsInstance(host.pushed_screen, FakeCalendarModal)

    def test_refresh_news_action(self) -> None:
        host = FakeHost()
        refresh_news_action(host)
        self.assertIn("news_refresh", host.calls)

    def test_quick_quit(self) -> None:
        host = FakeHost()
        quick_quit(host, modal_types=(FakeScreen,))
        self.assertIn("exit", host.calls)

        host = FakeHost()
        host.screen = FakeScreen()
        quick_quit(host, modal_types=(FakeScreen,))
        self.assertTrue(host.screen.dismissed)

    def test_enter_exit_command_mode_actions(self) -> None:
        host = FakeHost()
        enter_command_mode_action(host)
        self.assertIn("enter_cmd", host.calls)

        host = FakeHost()
        host.command_mode = True
        exit_command_mode_action(host, chart_modal_type=FakeScreen)
        self.assertIn("exit_cmd", host.calls)

    def test_reset_local_buffers(self) -> None:
        host = FakeHost()
        reset_local_buffers(
            host,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )
        self.assertEqual(len(host.crypto_candles_by_tf["1h"]["BTCUSDT"]), 0)
        self.assertEqual(len(host.stock_candles_by_tf["1h"]["AAPL"]), 0)
        self.assertIn("main", host.calls)
        self.assertIn("ind", host.calls)
        self.assertIn("alerts", host.calls)


if __name__ == "__main__":
    unittest.main()
