from __future__ import annotations

import importlib.util
import unittest

if importlib.util.find_spec("textual") is None:  # pragma: no cover - env dependent
    raise unittest.SkipTest("textual not installed")

from app.command_ui import autocomplete_command, enter_command_mode, exit_command_mode


class FakeInput:
    def __init__(self) -> None:
        self.display = False
        self.value = ""
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class FakeTable:
    def __init__(self) -> None:
        self.focused = False

    def focus(self) -> None:
        self.focused = True


class FakeHost:
    def __init__(self) -> None:
        self.command_mode = False
        self.command_buffer = ""
        self.market_groups = [{"name": "Tech", "symbols": [{"symbol": "AAPL", "type": "stock"}]}]
        self.main_group_items = [("Tech", [("AAPL", "stock")])]
        self._tab_cycle_key = None
        self._tab_cycle_index = -1
        self.logs: list[str] = []
        self.render_calls = 0
        self.input = FakeInput()
        self.table = FakeTable()

    def query_one(self, selector, _cls):
        if selector == "#command_input":
            return self.input
        if selector == "#crypto_quotes":
            return self.table
        raise AssertionError(selector)

    def _render_status_line(self) -> None:
        self.render_calls += 1

    def _ui_palette(self):
        return {"warn": "yellow"}

    def _log(self, message: str) -> None:
        self.logs.append(message)


class CommandUiTests(unittest.TestCase):
    def test_enter_and_exit_command_mode(self) -> None:
        host = FakeHost()
        enter_command_mode(host)
        self.assertTrue(host.command_mode)
        self.assertTrue(host.input.display)
        self.assertEqual(host.input.value, ":")
        self.assertTrue(host.input.focused)

        exit_command_mode(host)
        self.assertFalse(host.command_mode)
        self.assertFalse(host.input.display)
        self.assertEqual(host.input.value, "")
        self.assertTrue(host.table.focused)

    def test_autocomplete_command(self) -> None:
        host = FakeHost()
        enter_command_mode(host)
        host.input.value = ":a"
        autocomplete_command(host)
        self.assertTrue(host.input.value.startswith(":"))
        self.assertGreaterEqual(host.render_calls, 1)


if __name__ == "__main__":
    unittest.main()
