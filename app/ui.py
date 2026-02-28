from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, RichLog, Static

from .config import DEFAULT_SYMBOLS, MAX_EVENTS, MAX_POINTS
from .feed import BinanceTickerFeed
from .models import Quote

SPARKS = "▁▂▃▄▅▆▇█"


@dataclass(slots=True)
class SymbolState:
    symbol: str
    price: float = 0.0
    change_percent: float = 0.0
    volume: float = 0.0
    points: deque[float] | None = None
    last_update_ms: int = 0

    def __post_init__(self) -> None:
        if self.points is None:
            self.points = deque(maxlen=MAX_POINTS)


class NeonQuotesApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "Neon Quotes Terminal"
    SUB_TITLE = "Real-time market feed"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reset", "Reset"),
        Binding("1", "focus_symbol('BTCUSDT')", "BTC"),
        Binding("2", "focus_symbol('ETHUSDT')", "ETH"),
        Binding("3", "focus_symbol('SOLUSDT')", "SOL"),
    ]

    heartbeat = reactive(False)
    status_text = reactive("CONNECTING")
    ticker_offset = reactive(0)

    def __init__(self, symbols: Iterable[str] | None = None) -> None:
        super().__init__()
        self.symbols = list(symbols or DEFAULT_SYMBOLS)
        self.feed = BinanceTickerFeed(self.symbols)
        self.symbol_data = {symbol: SymbolState(symbol=symbol) for symbol in self.symbols}
        self.feed_task: asyncio.Task[None] | None = None
        self.last_tick_ms = 0
        self.focused_symbol: str | None = None
        self.row_keys: dict[str, Any] = {}
        self.col_keys: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="main"):
            yield DataTable(id="quotes")
            yield RichLog(id="events", highlight=True, wrap=False, markup=True)
        yield Static(id="ticker")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#quotes", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        col_symbol = table.add_column("Symbol")
        col_price = table.add_column("Price", width=15)
        col_change = table.add_column("24h %", width=10)
        col_volume = table.add_column("Volume", width=22)
        col_spark = table.add_column("Spark")
        self.col_keys = {
            "symbol": col_symbol,
            "price": col_price,
            "change": col_change,
            "volume": col_volume,
            "spark": col_spark,
        }
        for symbol in self.symbols:
            row_key = table.add_row(symbol, "-", "-", "-", "", key=symbol)
            self.row_keys[symbol] = row_key

        events_log = self.query_one("#events", RichLog)
        events_log.max_lines = MAX_EVENTS
        self._log("Booting market stream...")

        self.set_interval(0.5, self._update_clock)
        self.set_interval(1.0, self._animate_ticker)

        self.feed_task = asyncio.create_task(self._consume_feed())

    async def on_unmount(self) -> None:
        if self.feed_task:
            self.feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.feed_task

    def _update_clock(self) -> None:
        self.heartbeat = not self.heartbeat
        age_ms = int(time.time() * 1000) - self.last_tick_ms if self.last_tick_ms else 0
        conn_color = "green" if age_ms < 3000 else "yellow" if age_ms < 10000 else "red"
        pulse = "●" if self.heartbeat else "○"
        now = datetime.now().strftime("%H:%M:%S")
        header = (
            f"[bold #00ffae]NEON MARKET TERM[/]  "
            f"[#8ef9f3]{now}[/]  "
            f"[{conn_color}]LINK {pulse} {self.status_text}[/]  "
            f"[#ffcf5c]latency~{age_ms}ms[/]"
        )
        self.query_one("#header", Static).update(header)

    def _animate_ticker(self) -> None:
        chunks: list[Text] = []
        for symbol in self.symbols:
            state = self.symbol_data[symbol]
            if state.price <= 0:
                continue
            arrow = "▲" if state.change_percent >= 0 else "▼"
            color = "#00ffae" if state.change_percent >= 0 else "#ff5e7a"
            chunk = Text()
            chunk.append(f"{symbol} ", style="#99e2ff")
            chunk.append(f"{arrow} ", style=color)
            chunk.append(f"{state.price:,.4f} ", style="#e9feff")
            chunk.append(f"({state.change_percent:+.2f}%)", style=f"bold {color}")
            chunks.append(chunk)

        if not chunks:
            self.query_one("#ticker", Static).update(Text("Waiting for first ticks...", style="#557799"))
            return

        sep = Text("   •••   ", style="#2ec4b6")
        offset = self.ticker_offset % len(chunks)
        rotated = chunks[offset:] + chunks[:offset]
        ticker = Text()
        for idx, chunk in enumerate(rotated):
            if idx:
                ticker.append_text(sep)
            ticker.append_text(chunk)

        self.query_one("#ticker", Static).update(ticker)
        self.ticker_offset += 1

    async def _consume_feed(self) -> None:
        self.status_text = "STREAMING"
        self._log("[green]Connected to Binance stream[/]")
        while True:
            try:
                async for quote in self.feed.stream():
                    self._apply_quote(quote)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status_text = "RECONNECTING"
                self._log(f"[yellow]Stream warning:[/] {exc!r}")
                await asyncio.sleep(2)
                self.status_text = "STREAMING"

    def _apply_quote(self, quote: Quote) -> None:
        self.last_tick_ms = quote.event_time_ms
        state = self.symbol_data[quote.symbol]
        state.price = quote.price
        state.change_percent = quote.change_percent
        state.volume = quote.volume
        state.last_update_ms = quote.event_time_ms
        assert state.points is not None
        state.points.append(quote.price)
        self._refresh_row(state)

    def _refresh_row(self, state: SymbolState) -> None:
        table = self.query_one("#quotes", DataTable)
        row_key = self.row_keys.get(state.symbol)
        if row_key is None or not self.col_keys:
            return
        color = "#00ffae" if state.change_percent >= 0 else "#ff5e7a"
        price = Text(f"{state.price:>15,.4f}", style=color)
        change = Text(f"{state.change_percent:>+9.2f}%", style=f"bold {color}")
        volume = f"{state.volume:>22,.2f}"
        spark = self._sparkline(state.points or deque())
        table.update_cell(row_key, self.col_keys["price"], price)
        table.update_cell(row_key, self.col_keys["change"], change)
        table.update_cell(row_key, self.col_keys["volume"], volume)
        table.update_cell(row_key, self.col_keys["spark"], spark)

    def _sparkline(self, values: deque[float]) -> Text:
        if not values:
            return Text("·", style="#446")
        lo = min(values)
        hi = max(values)
        span = hi - lo or 1.0
        points = []
        for value in values:
            idx = int((value - lo) / span * (len(SPARKS) - 1))
            points.append(SPARKS[idx])
        trend_color = "#00ffae" if values[-1] >= values[0] else "#ff5e7a"
        return Text("".join(points), style=trend_color)

    def _log(self, message: str) -> None:
        self.query_one("#events", RichLog).write(message)

    def action_reset(self) -> None:
        for symbol in self.symbols:
            self.symbol_data[symbol] = SymbolState(symbol=symbol)
            self._refresh_row(self.symbol_data[symbol])
        self._log("[cyan]Local buffers reset[/]")

    def action_focus_symbol(self, symbol: str) -> None:
        if symbol not in self.symbol_data:
            return
        self.focused_symbol = symbol
        state = self.symbol_data[symbol]
        self._log(
            f"[bold #99e2ff]{symbol}[/] "
            f"price={state.price:,.4f} change={state.change_percent:+.2f}% volume={state.volume:,.2f}"
        )
        table = self.query_one("#quotes", DataTable)
        row_index = self.symbols.index(symbol)
        table.move_cursor(row=row_index)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "a":
            self._log("[#ffcf5c]Tip:[/] 1/2/3 focus symbol, r reset, q exit")


def run_app(symbols: Iterable[str] | None = None) -> None:
    NeonQuotesApp(symbols=symbols).run()
