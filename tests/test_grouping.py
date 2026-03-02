from __future__ import annotations

import unittest

from app.grouping import (
    advance_symbol_across_groups,
    build_main_groups,
    build_symbol_groups,
    flatten_group_items,
)


class GroupingTests(unittest.TestCase):
    def test_build_symbol_groups_normalizes_and_deduplicates(self) -> None:
        groups = build_symbol_groups(
            [
                {
                    "name": "Mixed",
                    "symbols": [
                        {"symbol": "btcusdt", "type": ""},
                        {"symbol": "BTCUSDT", "type": "crypto"},
                        {"symbol": "AAPL", "type": ""},
                    ],
                }
            ]
        )
        self.assertEqual(groups[0][0], "Mixed")
        self.assertEqual(groups[0][1], [("BTCUSDT", "crypto"), ("AAPL", "stock")])

    def test_build_symbol_groups_fallback(self) -> None:
        groups = build_symbol_groups([], fallback_name="MAIN", fallback_items=[("BTCUSDT", "crypto")])
        self.assertEqual(groups, [("MAIN", [("BTCUSDT", "crypto")])])

    def test_build_main_groups(self) -> None:
        groups = build_main_groups([], crypto_symbols=["BTCUSDT"], stock_symbols=["AAPL"])
        self.assertEqual(groups, [("MAIN", [("BTCUSDT", "crypto"), ("AAPL", "stock")])])

    def test_flatten_group_items(self) -> None:
        items = flatten_group_items(
            [
                ("A", [("BTCUSDT", "crypto"), ("AAPL", "stock")]),
                ("B", [("AAPL", "stock"), ("MSFT", "stock")]),
            ]
        )
        self.assertEqual(items, [("BTCUSDT", "crypto"), ("AAPL", "stock"), ("MSFT", "stock")])

    def test_advance_symbol_across_groups_wraps(self) -> None:
        groups = [
            ("A", [("BTCUSDT", "crypto"), ("ETHUSDT", "crypto")]),
            ("B", [("AAPL", "stock")]),
        ]
        self.assertEqual(
            advance_symbol_across_groups(groups, symbol="ETHUSDT", symbol_type="crypto", step=1),
            ("AAPL", "stock"),
        )
        self.assertEqual(
            advance_symbol_across_groups(groups, symbol="BTCUSDT", symbol_type="crypto", step=-1),
            ("AAPL", "stock"),
        )


if __name__ == "__main__":
    unittest.main()
