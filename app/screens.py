from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from .i18n import tr

TIMEFRAMES = ("15m", "1h", "1d", "1w", "1mo")


class ChartModal(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close_modal", show=False),
        Binding("enter", "close_modal", show=False),
        Binding("q", "close_modal", show=False),
        Binding("t", "toggle_timeframe", show=False),
    ]

    DEFAULT_CSS = """
    ChartModal {
        align: center middle;
        background: rgba(1, 5, 9, 0.85);
    }
    #chart_scroll {
        width: 96%;
        height: 92%;
        border: round #2ec4b6;
        background: #060d15;
        padding: 1 2;
    }
    #chart_box {
        width: 1fr;
    }
    """

    def __init__(
        self,
        symbol: str,
        symbol_type: str,
        chart_builder: Callable[[str, int], Text],
        ensure_history: Callable[[str, int], Awaitable[None]],
        navigate_symbol: Callable[[int], tuple[str, str] | None] | None = None,
    ) -> None:
        super().__init__()
        self.symbol = symbol
        self.symbol_type = symbol_type
        self.chart_builder = chart_builder
        self.ensure_history = ensure_history
        self.navigate_symbol = navigate_symbol
        self.timeframe = TIMEFRAMES[0]
        self._ensure_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chart_scroll"):
            yield Static("Loading chart...", id="chart_box")

    async def on_mount(self) -> None:
        self._refresh_chart()
        self.query_one("#chart_scroll", VerticalScroll).focus()
        self.set_interval(1.0, self._refresh_chart)
        self._schedule_ensure_history()

    async def on_resize(self, event: events.Resize) -> None:
        del event
        self._schedule_ensure_history()

    def _target_candle_count(self) -> int:
        scroller = self.query_one("#chart_scroll", VerticalScroll)
        return max(24, scroller.size.width - 10)

    def _schedule_ensure_history(self) -> None:
        if self._ensure_task and not self._ensure_task.done():
            self._ensure_task.cancel()
        self._ensure_task = asyncio.create_task(self._ensure_history_and_refresh())

    async def _ensure_history_and_refresh(self) -> None:
        try:
            await self.ensure_history(self.timeframe, self._target_candle_count())
        except asyncio.CancelledError:
            return
        except Exception:
            pass
        self._refresh_chart()

    def _refresh_chart(self) -> None:
        target_candles = self._target_candle_count()
        self.query_one("#chart_box", Static).update(self.chart_builder(self.timeframe, target_candles))

    def action_close_modal(self) -> None:
        self.dismiss(None)

    def action_toggle_timeframe(self) -> None:
        index = TIMEFRAMES.index(self.timeframe)
        self.timeframe = TIMEFRAMES[(index + 1) % len(TIMEFRAMES)]
        self._schedule_ensure_history()

    async def on_key(self, event: events.Key) -> None:
        scroller = self.query_one("#chart_scroll", VerticalScroll)
        if event.key in {"down", "j"}:
            scroller.scroll_down(animate=False)
            event.stop()
            return
        if event.key in {"up", "k"}:
            scroller.scroll_up(animate=False)
            event.stop()
            return
        if event.key == "pagedown":
            scroller.scroll_page_down(animate=False)
            event.stop()
            return
        if event.key == "pageup":
            scroller.scroll_page_up(animate=False)
            event.stop()
            return
        if event.key == "home":
            scroller.scroll_home(animate=False)
            event.stop()
            return
        if event.key == "end":
            scroller.scroll_end(animate=False)
            event.stop()
            return
        if event.key in {"left", "comma"} or event.character in {"<", ","}:
            if self.navigate_symbol:
                nxt = self.navigate_symbol(-1)
                if nxt:
                    self.symbol, self.symbol_type = nxt
                    self._schedule_ensure_history()
                    event.stop()
            return
        if event.key in {"right", "full_stop", "period"} or event.character in {">", "."}:
            if self.navigate_symbol:
                nxt = self.navigate_symbol(1)
                if nxt:
                    self.symbol, self.symbol_type = nxt
                    self._schedule_ensure_history()
                    event.stop()

    async def on_unmount(self) -> None:
        if self._ensure_task and not self._ensure_task.done():
            self._ensure_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ensure_task


class BootModal(ModalScreen[None]):
    DEFAULT_CSS = """
    BootModal {
        align: center middle;
        background: rgba(2, 6, 10, 0.88);
    }
    #boot_box {
        width: 76;
        height: 22;
        border: round #2ec4b6;
        background: #06101a;
        padding: 1 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.phase = tr("Initializing subsystems")
        self.done = 0
        self.total = 1
        self.frame = 0
        self.active = True

    def compose(self) -> ComposeResult:
        yield Static("", id="boot_box")

    async def on_mount(self) -> None:
        self._draw()
        self.set_interval(0.14, self._animate)

    def set_total(self, total: int) -> None:
        self.total = max(1, total)
        self._draw()

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self._draw()

    def increment(self) -> None:
        self.done = min(self.total, self.done + 1)
        self._draw()

    def complete(self) -> None:
        self.done = self.total
        self.phase = tr("Market core online")
        self.active = False
        self._draw()

    def _animate(self) -> None:
        self.frame += 1
        self._draw()

    def _draw(self) -> None:
        spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        pulse = "█" * ((self.frame % 12) + 1)
        pct = int((self.done / self.total) * 100)
        bar_width = 40
        filled = int((self.done / self.total) * bar_width)
        bar = f"[{'#' * filled}{'.' * (bar_width - filled)}]"
        status = tr("RUNNING") if self.active else tr("READY")
        txt = Text()
        txt.append(f"{tr('NEON MARKET OS // BOOT SEQUENCE')}\n", style="bold #99e2ff")
        txt.append("────────────────────────────────────────────\n", style="#284257")
        txt.append(f"{spinner[self.frame % len(spinner)]} ", style="#ffcf5c")
        txt.append(f"{self.phase}\n", style="#d7f2ff")
        txt.append(f"status: {status}\n", style="#8ad9ff")
        txt.append(f"progress: {self.done}/{self.total}  {pct}%\n", style="#8ad9ff")
        txt.append(bar + "\n\n", style="#2ec4b6")
        txt.append("telemetry stream: ", style="#6f8aa8")
        txt.append(pulse + "\n", style="#00ffae")
        txt.append(f"{tr('loading historical candles and trend buffers...')}\n", style="#6f8aa8")
        txt.append(f"{tr('booting market interfaces [crypto, stocks, news]')}\n", style="#6f8aa8")
        self.query_one("#boot_box", Static).update(txt)


class ReadmeModal(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close_modal", show=False),
        Binding("enter", "close_modal", show=False),
        Binding("q", "close_modal", show=False),
    ]

    DEFAULT_CSS = """
    ReadmeModal {
        align: center middle;
        background: rgba(1, 5, 9, 0.85);
    }
    #help_scroll {
        width: 96%;
        height: 92%;
        border: round #2ec4b6;
        background: #060d15;
        padding: 1 2;
    }
    #help_box {
        width: 1fr;
    }
    """

    def __init__(self, readme_text: str) -> None:
        super().__init__()
        self.readme_text = readme_text

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help_scroll"):
            yield Static(self.readme_text, id="help_box")

    async def on_mount(self) -> None:
        self.query_one("#help_scroll", VerticalScroll).focus()

    def action_close_modal(self) -> None:
        self.dismiss(None)

    async def on_key(self, event: events.Key) -> None:
        if event.key in {"escape", "enter", "q"}:
            self.dismiss(None)
            event.stop()
            return
        scroller = self.query_one("#help_scroll", VerticalScroll)
        if event.key in {"down", "j"}:
            scroller.scroll_down(animate=False)
            event.stop()
            return
        if event.key in {"up", "k"}:
            scroller.scroll_up(animate=False)
            event.stop()
            return
        if event.key == "pagedown":
            scroller.scroll_page_down(animate=False)
            event.stop()
            return
        if event.key == "pageup":
            scroller.scroll_page_up(animate=False)
            event.stop()
            return
        if event.key == "home":
            scroller.scroll_home(animate=False)
            event.stop()
            return
        if event.key == "end":
            scroller.scroll_end(animate=False)
            event.stop()
            return


class CalendarModal(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close_modal", show=False),
        Binding("q", "close_modal", show=False),
    ]

    DEFAULT_CSS = """
    CalendarModal {
        align: center middle;
        background: rgba(1, 5, 9, 0.85);
    }
    #calendar_scroll {
        width: 96%;
        height: 92%;
        border: round #2ec4b6;
        background: #060d15;
        padding: 1 2;
    }
    #calendar_box {
        width: 1fr;
    }
    """

    def __init__(self, renderer: Callable[[], Text]) -> None:
        super().__init__()
        self.renderer = renderer

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="calendar_scroll"):
            yield Static("", id="calendar_box")

    async def on_mount(self) -> None:
        self.query_one("#calendar_scroll", VerticalScroll).focus()
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        self.query_one("#calendar_box", Static).update(self.renderer())

    def action_close_modal(self) -> None:
        self.dismiss(None)

    async def on_key(self, event: events.Key) -> None:
        if event.key in {"escape", "q"}:
            self.dismiss(None)
            event.stop()
            return
        scroller = self.query_one("#calendar_scroll", VerticalScroll)
        if event.key in {"down", "j"}:
            scroller.scroll_down(animate=False)
            event.stop()
            return
        if event.key in {"up", "k"}:
            scroller.scroll_up(animate=False)
            event.stop()
            return
        if event.key == "pagedown":
            scroller.scroll_page_down(animate=False)
            event.stop()
            return
        if event.key == "pageup":
            scroller.scroll_page_up(animate=False)
            event.stop()
            return
        if event.key == "home":
            scroller.scroll_home(animate=False)
            event.stop()
            return
        if event.key == "end":
            scroller.scroll_end(animate=False)
            event.stop()
            return


class CommandInput(Input):
    async def on_key(self, event: events.Key) -> None:
        app = self.app
        if event.key == "escape" and hasattr(app, "action_exit_command_mode"):
            app.action_exit_command_mode()
            event.stop()
            return
        if event.key == "tab" and hasattr(app, "autocomplete_command_input"):
            app.autocomplete_command_input()
            event.stop()
            return
