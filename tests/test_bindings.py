from __future__ import annotations

import importlib.util
import unittest

if importlib.util.find_spec("textual") is None:  # pragma: no cover - env dependent
    raise unittest.SkipTest("textual not installed")

from app.bindings import (
    handle_command_mode_keys,
    handle_global_shortcuts,
    handle_modal_shortcuts,
    handle_table_navigation,
)
from app.screens import CalendarModal, ReadmeModal


class FakeEvent:
    def __init__(self, key: str, character: str | None = None) -> None:
        self.key = key
        self.character = character
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeTable:
    def __init__(self, has_focus: bool = False) -> None:
        self.has_focus = has_focus


class FakeScreen:
    def __init__(self) -> None:
        self.dismissed = False

    def dismiss(self, _value) -> None:
        self.dismissed = True


class FakeHost:
    def __init__(self) -> None:
        self.screen = FakeScreen()
        self.command_mode = False
        self.quick_actions = {"1": "AAPL"}
        self.calls: list[str] = []
        self._tab_cycle_key = object()
        self._tab_cycle_index = 3
        self._input = type("CI", (), {"value": ":q"})()
        self._tables = {
            "#crypto_quotes": FakeTable(False),
            "#indicators_table": FakeTable(False),
            "#news_table": FakeTable(False),
        }

    def query_one(self, selector, _cls):
        if selector == "#command_input":
            return self._input
        return self._tables[selector]

    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None:
        self.calls.append(f"pause:{table_id}:{seconds}")

    def _cycle_main_group(self, step: int) -> None:
        self.calls.append(f"main:{step}")

    def _cycle_news_group(self, step: int) -> None:
        self.calls.append(f"news:{step}")

    def _cycle_indicator_group(self, step: int) -> None:
        self.calls.append(f"ind:{step}")

    def _exit_command_mode(self) -> None:
        self.calls.append("exit_cmd")

    def _execute_command(self, command: str) -> None:
        self.calls.append(f"exec:{command}")

    def _enter_command_mode(self) -> None:
        self.calls.append("enter_cmd")

    def action_focus_symbol(self, symbol: str) -> None:
        self.calls.append(f"focus:{symbol}")

    def action_show_help_tip(self) -> None:
        self.calls.append("help")

    def exit(self) -> None:
        self.calls.append("exit")


class BindingsTests(unittest.TestCase):
    def test_modal_shortcuts(self) -> None:
        host = FakeHost()
        host.screen = CalendarModal(lambda: "")
        # Monkeypatch dismiss side effect
        called = {"dismissed": False}
        host.screen.dismiss = lambda _v: called.__setitem__("dismissed", True)
        ev = FakeEvent("escape")
        handled = handle_modal_shortcuts(host, ev)
        self.assertTrue(handled)
        self.assertTrue(called["dismissed"])

    def test_table_navigation_main(self) -> None:
        host = FakeHost()
        host._tables["#crypto_quotes"].has_focus = True
        ev = FakeEvent("right", ".")
        handled = handle_table_navigation(host, ev)
        self.assertTrue(handled)
        self.assertIn("main:1", host.calls)

    def test_command_mode_enter_executes(self) -> None:
        host = FakeHost()
        host.command_mode = True
        ev = FakeEvent("enter")
        handled = handle_command_mode_keys(host, ev)
        self.assertTrue(handled)
        self.assertIn("exec:q", host.calls)
        self.assertIn("exit_cmd", host.calls)
        self.assertEqual(host._tab_cycle_index, -1)

    def test_global_shortcuts(self) -> None:
        host = FakeHost()
        self.assertTrue(handle_global_shortcuts(host, FakeEvent("colon", ":")))
        self.assertIn("enter_cmd", host.calls)

        host = FakeHost()
        self.assertTrue(handle_global_shortcuts(host, FakeEvent("1", "1")))
        self.assertIn("focus:AAPL", host.calls)

        host = FakeHost()
        self.assertTrue(handle_global_shortcuts(host, FakeEvent("?", "?")))
        self.assertIn("help", host.calls)


if __name__ == "__main__":
    unittest.main()
