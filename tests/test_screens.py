from __future__ import annotations

import importlib.util
import unittest

if importlib.util.find_spec("textual") is None:  # pragma: no cover - env dependent
    raise unittest.SkipTest("textual not installed")

from app.screens import ChartModal, CommandInput, ReadmeModal, TIMEFRAMES


class FakeEvent:
    def __init__(self, key: str) -> None:
        self.key = key
        self.character = key if len(key) == 1 else None
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeApp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def action_exit_command_mode(self) -> None:
        self.calls.append("exit")

    def autocomplete_command_input(self) -> None:
        self.calls.append("autocomplete")


class TestableCommandInput(CommandInput):
    def __init__(self, fake_app: FakeApp) -> None:
        super().__init__()
        self._fake_app = fake_app

    @property
    def app(self):
        return self._fake_app


class ScreensTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_input_escape_and_tab(self):
        app = FakeApp()
        widget = TestableCommandInput(app)

        ev = FakeEvent("escape")
        await widget.on_key(ev)
        self.assertIn("exit", app.calls)
        self.assertTrue(ev.stopped)

        ev = FakeEvent("tab")
        await widget.on_key(ev)
        self.assertIn("autocomplete", app.calls)
        self.assertTrue(ev.stopped)

    def test_chart_modal_toggle_timeframe(self):
        modal = ChartModal(
            symbol="BTCUSDT",
            symbol_type="crypto",
            chart_builder=lambda _tf, _n: "ok",
            ensure_history=lambda _tf, _n: None,
        )
        calls = {"scheduled": 0}
        modal._schedule_ensure_history = lambda: calls.__setitem__("scheduled", calls["scheduled"] + 1)
        first = modal.timeframe
        modal.action_toggle_timeframe()
        self.assertNotEqual(modal.timeframe, first)
        self.assertIn(modal.timeframe, TIMEFRAMES)
        self.assertEqual(calls["scheduled"], 1)

    def test_readme_modal_stores_text(self):
        modal = ReadmeModal("hello")
        self.assertEqual(modal.readme_text, "hello")


if __name__ == "__main__":
    unittest.main()
