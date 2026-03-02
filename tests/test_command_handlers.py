from __future__ import annotations

import unittest
from typing import Any

from app.command_handlers import RuntimeConfigCommands


class FakeHost:
    def __init__(self) -> None:
        self.market_groups: list[dict[str, Any]] = [
            {"name": "Tech", "symbols": [{"symbol": "AAPL", "type": "stock", "name": "Apple"}]},
            {"name": "Crypto", "symbols": [{"symbol": "BTCUSDT", "type": "crypto"}]},
        ]
        self.symbol_names: dict[tuple[str, str], str] = {("AAPL", "stock"): "Apple"}
        self.quick_actions = {"1": "AAPL", "2": "", "3": ""}
        self.logs: list[str] = []
        self.persist_ok = True
        self.persist_calls = 0
        self.applied_calls = 0

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


class RuntimeConfigCommandsTests(unittest.TestCase):
    def test_add_symbol_success(self) -> None:
        host = FakeHost()
        RuntimeConfigCommands(host).add_symbol(["add", "MSFT", "stock", "Tech", "Microsoft"])
        self.assertTrue(any(i.get("symbol") == "MSFT" for i in host.market_groups[0]["symbols"]))
        self.assertEqual(host.persist_calls, 1)
        self.assertEqual(host.applied_calls, 1)

    def test_delete_symbol_clears_quick_action(self) -> None:
        host = FakeHost()
        RuntimeConfigCommands(host).delete_symbol(["del", "AAPL"])
        self.assertEqual(host.quick_actions["1"], "")
        self.assertEqual(host.persist_calls, 1)

    def test_move_symbol_changes_group(self) -> None:
        host = FakeHost()
        RuntimeConfigCommands(host).move_symbol(["mv", "AAPL", "Crypto"])
        crypto_group = next(g for g in host.market_groups if g.get("name") == "Crypto")
        self.assertIn("AAPL", [i.get("symbol") for i in crypto_group["symbols"]])
        self.assertEqual(host.persist_calls, 1)

    def test_edit_symbol_name(self) -> None:
        host = FakeHost()
        RuntimeConfigCommands(host).edit_symbol(["edit", "AAPL", "name=Apple Inc"])
        self.assertEqual(host.symbol_names[("AAPL", "stock")], "Apple Inc")
        self.assertEqual(host.persist_calls, 1)

    def test_edit_invalid_token_logs_error(self) -> None:
        host = FakeHost()
        RuntimeConfigCommands(host).edit_symbol(["edit", "AAPL", "invalid"])
        self.assertTrue(any("invalid token" in msg for msg in host.logs))
        self.assertEqual(host.persist_calls, 0)


if __name__ == "__main__":
    unittest.main()
