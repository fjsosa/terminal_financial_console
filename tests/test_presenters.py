from __future__ import annotations

import unittest

from app.presenters import build_header_markup, build_status_line_text


class PresentersTests(unittest.TestCase):
    def test_build_header_markup(self) -> None:
        palette = {"ok": "green", "muted": "gray", "brand": "cyan", "accent": "blue", "warn": "yellow"}
        out = build_header_markup(
            palette=palette,
            app_version="0.0.2",
            config_name="Test Config",
            now_text="2026-03-02 10:00",
            status_text="STREAMING",
            age_ms=1200,
            heartbeat=True,
        )
        self.assertIn("NEON MARKET TERM v0.0.2", out)
        self.assertIn("Test Config", out)
        self.assertIn("latency~1200ms", out)

    def test_build_status_line_text_modes(self) -> None:
        palette = {"text": "white", "muted": "gray", "warn": "yellow", "ok": "green"}
        normal = build_status_line_text(
            palette=palette,
            command_mode=False,
            command_buffer="",
            width=120,
        )
        command = build_status_line_text(
            palette=palette,
            command_mode=True,
            command_buffer="add",
            width=120,
        )
        self.assertIn("status: normal", normal.plain)
        self.assertIn("status: enter command", command.plain)
        self.assertIn(":add", command.plain)


if __name__ == "__main__":
    unittest.main()
