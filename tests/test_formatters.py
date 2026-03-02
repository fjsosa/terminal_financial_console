from __future__ import annotations

import unittest

from app.formatters import format_news_headline, format_volume, headline_inline, ticker_label


class FormattersTests(unittest.TestCase):
    def test_format_volume_uses_m_suffix_for_large_values(self) -> None:
        self.assertEqual(format_volume(150_000_000, width=9), "  150.00M")
        self.assertIn(",", format_volume(12_345, width=10))

    def test_ticker_label_includes_truncated_name(self) -> None:
        label = ticker_label(
            symbol="AAPL",
            symbol_type="stock",
            symbol_names={("AAPL", "stock"): "Apple Incorporated"},
            palette={"text": "white", "muted": "gray", "accent": "cyan"},
            max_name_len=5,
        )
        self.assertEqual(label.plain, "AAPL:Apple")

    def test_headline_inline_adds_fire_for_now(self) -> None:
        line = headline_inline("reuters.com", "now", "Bitcoin jumps 10 percent", 80)
        self.assertIn("🔥", line)
        self.assertIn("[reuters.com: now", line)

    def test_format_news_headline_returns_multiline_text(self) -> None:
        text = format_news_headline(
            source="reuters.com",
            age="now",
            title="Bitcoin jumps again as market momentum continues",
            line_len=20,
            news_palette={
                "bracket": "gray",
                "source": "cyan",
                "age_now": "green",
                "age_recent": "yellow",
                "age_old": "white",
                "fire": "red",
            },
            body_color="white",
        )
        self.assertIn("reuters.com", text.plain)
        self.assertEqual(text.plain.count("\n"), 2)


if __name__ == "__main__":
    unittest.main()
