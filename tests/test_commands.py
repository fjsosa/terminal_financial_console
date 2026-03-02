from __future__ import annotations

import unittest
from typing import Any

from app.commands import cmd_add_symbol, cmd_del_symbol, cmd_edit_symbol, cmd_move_symbol, execute_command


class FakeHost:
    def __init__(self) -> None:
        self.market_groups: list[dict[str, Any]] = [
            {"name": "Tech", "symbols": [{"symbol": "AAPL", "type": "stock", "name": "Apple"}]},
            {"name": "Crypto", "symbols": [{"symbol": "BTCUSDT", "type": "crypto"}]},
        ]
        self.main_group_items = [
            ("Tech", [("AAPL", "stock")]),
            ("Crypto", [("BTCUSDT", "crypto")]),
        ]
        self.symbol_names: dict[tuple[str, str], str] = {("AAPL", "stock"): "Apple"}
        self.quick_actions = {"1": "AAPL", "2": "", "3": ""}
        self.logs: list[str] = []
        self.persist_ok = True
        self.persist_calls = 0
        self.applied_calls = 0
        self.exited = False
        self.news_refreshed = False
        self.calendar_opened = False
        self.help_opened = False

    def _normalize_symbol_type(self, symbol: str, symbol_type: str) -> str:
        st = (symbol_type or "").strip().lower()
        if st in {"crypto", "stock"}:
            return st
        return "crypto" if symbol.upper().endswith("USDT") else "stock"

    def _find_group_index(self, group_name: str) -> int | None:
        wanted = group_name.strip().casefold()
        for idx, g in enumerate(self.market_groups):
            if str(g.get("name") or "").strip().casefold() == wanted:
                return idx
        return None

    def _find_symbol_entry(self, symbol: str):
        needle = symbol.strip().upper()
        for gi, g in enumerate(self.market_groups):
            symbols = g.get("symbols", [])
            for si, item in enumerate(symbols):
                if str(item.get("symbol") or "").strip().upper() == needle:
                    return gi, si, item
        return None

    def _apply_market_groups_change(self, resolve_missing_names: bool = False) -> None:
        self.applied_calls += 1

    def _persist_config(self) -> bool:
        self.persist_calls += 1
        return self.persist_ok

    def _clear_quick_actions_for_symbol(self, symbol: str) -> None:
        up = symbol.upper()
        for k, v in list(self.quick_actions.items()):
            if v.upper() == up:
                self.quick_actions[k] = ""

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def action_reset(self) -> None:
        pass

    def action_refresh_news(self) -> None:
        self.news_refreshed = True

    def action_open_calendar(self) -> None:
        self.calendar_opened = True

    def action_show_help_tip(self) -> None:
        self.help_opened = True

    def exit(self) -> None:
        self.exited = True


class CommandsTests(unittest.TestCase):
    def test_cmd_add_symbol_success(self) -> None:
        host = FakeHost()
        cmd_add_symbol(host, ["add", "MSFT", "stock", "Tech", "Microsoft"])
        self.assertTrue(any(i.get("symbol") == "MSFT" for i in host.market_groups[0]["symbols"]))
        self.assertEqual(host.persist_calls, 1)
        self.assertEqual(host.applied_calls, 1)

    def test_cmd_del_symbol_clears_quick_actions(self) -> None:
        host = FakeHost()
        cmd_del_symbol(host, ["del", "AAPL"])
        self.assertEqual(host.quick_actions["1"], "")
        self.assertEqual(host.persist_calls, 1)

    def test_cmd_move_symbol(self) -> None:
        host = FakeHost()
        cmd_move_symbol(host, ["mv", "AAPL", "Crypto"])
        crypto_group = next(g for g in host.market_groups if g.get("name") == "Crypto")
        crypto_symbols = [x["symbol"] for x in crypto_group["symbols"]]
        self.assertIn("AAPL", crypto_symbols)
        self.assertEqual(host.persist_calls, 1)

    def test_cmd_edit_symbol_changes_name(self) -> None:
        host = FakeHost()
        cmd_edit_symbol(host, ["edit", "AAPL", "name=Apple Inc"])
        self.assertEqual(host.symbol_names[("AAPL", "stock")], "Apple Inc")
        self.assertEqual(host.persist_calls, 1)

    def test_execute_command_dispatch(self) -> None:
        host = FakeHost()
        execute_command(host, "q")
        self.assertTrue(host.exited)

        host = FakeHost()
        execute_command(host, "c calendar")
        self.assertTrue(host.calendar_opened)

        host = FakeHost()
        execute_command(host, "?")
        self.assertTrue(host.help_opened)


if __name__ == "__main__":
    unittest.main()
