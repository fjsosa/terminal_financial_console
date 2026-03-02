from __future__ import annotations

import unittest

from app.command_completion import autocomplete, quote_token


class CommandCompletionTests(unittest.TestCase):
    def test_quote_token_wraps_values_with_spaces(self) -> None:
        self.assertEqual(quote_token("Group One"), '"Group One"')
        self.assertEqual(quote_token("GROUP"), "GROUP")

    def test_autocomplete_cycles_commands_with_tab(self) -> None:
        first = autocomplete(
            raw_value=":",
            market_groups=[],
            main_group_items=[],
            tab_cycle_key=None,
            tab_cycle_index=-1,
        )
        self.assertEqual(first.value, ":q")
        self.assertIsNotNone(first.tab_cycle_key)

        second = autocomplete(
            raw_value=":",
            market_groups=[],
            main_group_items=[],
            tab_cycle_key=first.tab_cycle_key,
            tab_cycle_index=first.tab_cycle_index,
        )
        self.assertEqual(second.value, ":r")

    def test_autocomplete_proposes_group_for_add(self) -> None:
        result = autocomplete(
            raw_value=":add AAPL stock ",
            market_groups=[{"name": "Tech Group"}],
            main_group_items=[],
            tab_cycle_key=None,
            tab_cycle_index=-1,
        )
        self.assertEqual(result.value, ':add AAPL stock "Tech Group" ')

    def test_autocomplete_no_candidates(self) -> None:
        result = autocomplete(
            raw_value=":xyz",
            market_groups=[],
            main_group_items=[],
            tab_cycle_key=None,
            tab_cycle_index=-1,
        )
        self.assertTrue(result.no_candidates)
        self.assertIsNone(result.value)


if __name__ == "__main__":
    unittest.main()
