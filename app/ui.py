from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable
from zoneinfo import ZoneInfo

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, RichLog, Static

from .config import (
    DEFAULT_CRYPTO_SYMBOLS,
    DEFAULT_STOCK_SYMBOLS,
    INITIAL_CANDLE_LIMIT,
    INITIAL_HISTORY_POINTS,
    MAX_EVENTS,
    MAX_POINTS,
    NEWS_GROUP_ROTATE_SECONDS,
    NEWS_GROUP_SIZE,
    NEWS_MAX_ITEMS,
    NEWS_REFRESH_SECONDS,
    STOCK_GROUP_ROTATE_SECONDS,
    STOCKS_REFRESH_SECONDS,
)
from .feed import BinanceTickerFeed
from .models import Quote
from .news import NewsItem, fetch_all_news
from .stocks import (
    StockQuote,
    fetch_stock_candles_timeframe,
    fetch_stock_history,
    fetch_stock_quotes,
)

SPARKS = "▁▂▃▄▅▆▇█"
FIFTEEN_MIN_MS = 15 * 60 * 1000
CANDLE_BUFFER_MAX = 1000
TIMEFRAMES = ("15m", "1h", "1d", "1w", "1mo")
ALERTS_TABLE_SIZE = 15

try:
    import plotext as plt
except Exception:  # pragma: no cover - optional backend
    plt = None


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


@dataclass(slots=True)
class StockState:
    symbol: str
    price: float = 0.0
    change_percent: float = 0.0
    volume: float = 0.0
    points: deque[float] | None = None
    last_update_ms: int = 0

    def __post_init__(self) -> None:
        if self.points is None:
            self.points = deque(maxlen=MAX_POINTS)


@dataclass(slots=True)
class Candle:
    bucket_ms: int
    open: float
    high: float
    low: float
    close: float


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
        chart_builder: Callable[[str, int], Text],
        ensure_history: Callable[[str, int], Awaitable[None]],
    ) -> None:
        super().__init__()
        self.symbol = symbol
        self.chart_builder = chart_builder
        self.ensure_history = ensure_history
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
        # One glyph per candle, keeping a right/left safety margin.
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
            # Don't break modal rendering when remote history refresh fails.
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
        self.phase = "Initializing subsystems"
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
        self.phase = "Market core online"
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
        status = "RUNNING" if self.active else "READY"
        txt = Text()
        txt.append("NEON MARKET OS // BOOT SEQUENCE\n", style="bold #99e2ff")
        txt.append("────────────────────────────────────────────\n", style="#284257")
        txt.append(f"{spinner[self.frame % len(spinner)]} ", style="#ffcf5c")
        txt.append(f"{self.phase}\n", style="#d7f2ff")
        txt.append(f"status: {status}\n", style="#8ad9ff")
        txt.append(f"progress: {self.done}/{self.total}  {pct}%\n", style="#8ad9ff")
        txt.append(bar + "\n\n", style="#2ec4b6")
        txt.append("telemetry stream: ", style="#6f8aa8")
        txt.append(pulse + "\n", style="#00ffae")
        txt.append("loading historical candles and trend buffers...\n", style="#6f8aa8")
        txt.append("booting market interfaces [crypto, stocks, news]\n", style="#6f8aa8")
        self.query_one("#boot_box", Static).update(txt)


class CommandInput(Input):
    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            app = self.app
            if isinstance(app, NeonQuotesApp):
                app.action_exit_command_mode()
                event.stop()
                return
        # Let Input handle all other keys through its own internal bindings.


class NeonQuotesApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "Neon Quotes Terminal"
    SUB_TITLE = "Real-time market feed"

    BINDINGS = [
        Binding("q", "quick_quit", "Quit", priority=True),
        Binding("r", "quick_reset", "Reset", priority=True),
        Binding("n", "quick_news", "News", priority=True),
        Binding("enter", "open_chart", "Chart"),
        Binding("colon", "enter_command_mode", show=False, priority=True, system=True),
        Binding("f2", "enter_command_mode", show=False, priority=True, system=True),
        Binding("ctrl+g", "enter_command_mode", show=False, priority=True, system=True),
        Binding("escape", "exit_command_mode", show=False, priority=True, system=True),
        Binding("a", "show_help_tip", "Help", priority=True),
    ]

    heartbeat = reactive(False)
    status_text = reactive("CONNECTING")
    ticker_offset = reactive(0)

    def _build_main_groups(self) -> list[tuple[str, list[tuple[str, str]]]]:
        groups: list[tuple[str, list[tuple[str, str]]]] = []
        for group in self.market_groups:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name") or "MAIN").strip() or "MAIN"
            raw_items = group.get("symbols")
            if not isinstance(raw_items, list):
                continue
            symbols: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").strip().upper()
                symbol_type = str(item.get("type") or "").strip().lower()
                if symbol_type not in {"crypto", "stock"}:
                    symbol_type = "crypto" if symbol.endswith("USDT") else "stock"
                if not symbol:
                    continue
                key = (symbol, symbol_type)
                if key in seen:
                    continue
                seen.add(key)
                symbols.append(key)
            if symbols:
                groups.append((name, symbols))

        if groups:
            return groups
        fallback_symbols: list[tuple[str, str]] = []
        for symbol in self.crypto_symbols:
            fallback_symbols.append((symbol, "crypto"))
        for symbol in self.stock_symbols:
            fallback_symbols.append((symbol, "stock"))
        if fallback_symbols:
            return [("MAIN", fallback_symbols)]
        if self.stock_symbols:
            return [("MAIN", [(symbol, "stock") for symbol in self.stock_symbols])]
        return []

    def __init__(
        self,
        crypto_symbols: Iterable[str] | None = None,
        stock_symbols: Iterable[str] | None = None,
        timezone: str = "",
        groups: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.crypto_symbols = list(crypto_symbols or DEFAULT_CRYPTO_SYMBOLS)
        self.stock_symbols = [symbol.upper() for symbol in (stock_symbols or DEFAULT_STOCK_SYMBOLS)]
        self.market_groups = list(groups or [])
        self.timezone = timezone.strip()
        self.feed = BinanceTickerFeed(self.crypto_symbols)
        self.symbol_data = {symbol: SymbolState(symbol=symbol) for symbol in self.crypto_symbols}
        self.stock_data = {symbol: StockState(symbol=symbol) for symbol in self.stock_symbols}
        self.feed_task: asyncio.Task[None] | None = None
        self.last_tick_ms = 0
        self.focused_symbol: str | None = None
        self.main_row_keys: list[Any] = []
        self.main_col_keys: dict[str, Any] = {}
        self.main_group_items: list[tuple[str, list[tuple[str, str]]]] = self._build_main_groups()
        self.main_group_index = 0
        self.main_visible_items: list[tuple[str, str]] = []
        self.main_row_item_by_index: dict[int, tuple[str, str]] = {}
        self.alerts_row_keys: list[Any] = []
        self.alerts_col_keys: dict[str, Any] = {}
        self.alerts_row_item_by_index: dict[int, tuple[str, str]] = {}
        self.news_row_keys: list[Any] = []
        self.news_col_keys: dict[str, Any] = {}
        self.news_last_update = "never"
        self.news_groups: list[tuple[str, list[NewsItem]]] = []
        self.news_group_index = 0
        self.news_row_links: dict[int, str] = {}
        self.stocks_last_update = "never"
        self.local_tz = self._resolve_timezone()
        self.candles: dict[str, deque[Candle]] = {
            symbol: deque(maxlen=CANDLE_BUFFER_MAX) for symbol in self.crypto_symbols
        }
        self.stock_candles: dict[str, deque[Candle]] = {
            symbol: deque(maxlen=CANDLE_BUFFER_MAX) for symbol in self.stock_symbols
        }
        self.crypto_candles_by_tf: dict[str, dict[str, deque[Candle]]] = {
            tf: {symbol: deque(maxlen=CANDLE_BUFFER_MAX) for symbol in self.crypto_symbols}
            for tf in TIMEFRAMES
            if tf != "15m"
        }
        self.stock_candles_by_tf: dict[str, dict[str, deque[Candle]]] = {
            tf: {symbol: deque(maxlen=CANDLE_BUFFER_MAX) for symbol in self.stock_symbols}
            for tf in TIMEFRAMES
            if tf != "15m"
        }
        self.boot_modal: BootModal | None = None
        self.startup_task: asyncio.Task[None] | None = None
        self.command_mode = False
        self.command_buffer = ""
        self.status_hint = ":|f2 Cmd | q quit | r reset | n news | enter chart"

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="main"):
            with Vertical(id="markets"):
                yield DataTable(id="crypto_quotes")
                yield DataTable(id="stock_quotes")
            with Vertical(id="side"):
                yield RichLog(id="events", highlight=True, wrap=False, markup=True)
                yield Static(id="news_header")
                yield DataTable(id="news_table")
        yield Static(id="ticker")
        yield Static(id="status_line")
        yield CommandInput(placeholder=":q | :r | :n | :help", id="command_input")

    async def on_mount(self) -> None:
        main_table = self.query_one("#crypto_quotes", DataTable)
        main_table.cursor_type = "row"
        main_table.zebra_stripes = True
        col_symbol = main_table.add_column("Ticker")
        col_type = main_table.add_column("Type", width=8)
        col_price = main_table.add_column("Price", width=15)
        col_change = main_table.add_column("24h %", width=10)
        col_volume = main_table.add_column("Volume", width=22)
        col_spark = main_table.add_column("Spark")
        self.main_col_keys = {
            "symbol": col_symbol,
            "type": col_type,
            "price": col_price,
            "change": col_change,
            "volume": col_volume,
            "spark": col_spark,
        }
        self.main_row_keys.clear()
        main_rows = max(1, max((len(items) for _, items in self.main_group_items), default=1))
        for i in range(main_rows):
            row_key = main_table.add_row("-", "-", "-", "-", "-", "", key=f"main_{i}")
            self.main_row_keys.append(row_key)
        self._update_main_group_panel()

        alerts_table = self.query_one("#stock_quotes", DataTable)
        alerts_table.cursor_type = "row"
        alerts_table.zebra_stripes = True
        a_rank = alerts_table.add_column("#", width=3)
        a_symbol = alerts_table.add_column("Ticker")
        a_type = alerts_table.add_column("Type", width=8)
        a_change = alerts_table.add_column("24h %", width=10)
        a_price = alerts_table.add_column("Price", width=15)
        a_volume = alerts_table.add_column("Volume", width=22)
        self.alerts_col_keys = {
            "rank": a_rank,
            "symbol": a_symbol,
            "type": a_type,
            "change": a_change,
            "price": a_price,
            "volume": a_volume,
        }
        self.alerts_row_keys.clear()
        for i in range(ALERTS_TABLE_SIZE):
            row_key = alerts_table.add_row(
                f"{i + 1}",
                "-",
                "-",
                "-",
                "-",
                "-",
                key=f"alert_{i}",
            )
            self.alerts_row_keys.append(row_key)
        self._update_alerts_panel()

        news_table = self.query_one("#news_table", DataTable)
        news_table.cursor_type = "row"
        news_table.zebra_stripes = True
        n_idx = news_table.add_column("#", width=3)
        n_age = news_table.add_column("Age", width=8)
        n_title = news_table.add_column("Headline", width=58)
        n_source = news_table.add_column("Source", width=20)
        self.news_col_keys = {
            "idx": n_idx,
            "age": n_age,
            "title": n_title,
            "source": n_source,
        }
        self.news_row_keys.clear()
        for i in range(NEWS_GROUP_SIZE):
            row_key = news_table.add_row(
                "-",
                "-",
                "Loading headlines...\nPlease wait",
                "-",
                key=f"news_{i}",
                height=2,
            )
            self.news_row_keys.append(row_key)

        events_log = self.query_one("#events", RichLog)
        events_log.max_lines = MAX_EVENTS
        self._log("Booting market stream...")
        self.query_one("#news_header", Static).update(
            Text("NEWS // finviz.com (refresh 10m)", style="#7aa3c5")
        )
        command_input = self.query_one("#command_input", Input)
        command_input.value = ""
        command_input.display = False
        self._render_status_line()

        self.set_interval(0.5, self._update_clock)
        self.set_interval(0.15, self._animate_ticker)
        self.set_interval(NEWS_REFRESH_SECONDS, self._schedule_news_refresh)
        self.set_interval(NEWS_GROUP_ROTATE_SECONDS, self._rotate_news_group)
        self.set_interval(STOCK_GROUP_ROTATE_SECONDS, self._rotate_main_group)
        self.set_interval(STOCKS_REFRESH_SECONDS, self._schedule_stock_refresh)
        self.startup_task = asyncio.create_task(self._startup_sequence())

    async def on_unmount(self) -> None:
        if self.startup_task:
            self.startup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.startup_task
        if self.feed_task:
            self.feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.feed_task

    async def _startup_sequence(self) -> None:
        try:
            # Let first frame render before opening boot modal.
            await asyncio.sleep(0)
            await self._show_boot_modal()
            await self._preload_history()
            await self._preload_stock_history()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._log(f"[yellow]Startup warning:[/] {exc!r}")
        finally:
            await self._hide_boot_modal()
            if self.feed_task is None and self.crypto_symbols:
                self.feed_task = asyncio.create_task(self._consume_feed())
            elif not self.crypto_symbols:
                self.status_text = "STOCKS ONLY"
            self._schedule_news_refresh()
            self._schedule_stock_refresh()

    def _update_clock(self) -> None:
        self.heartbeat = not self.heartbeat
        age_ms = int(time.time() * 1000) - self.last_tick_ms if self.last_tick_ms else 0
        conn_color = "green" if age_ms < 3000 else "yellow" if age_ms < 10000 else "red"
        pulse = "●" if self.heartbeat else "○"
        now = datetime.now(self.local_tz).strftime("%H:%M:%S")
        header = (
            f"[bold #00ffae]NEON MARKET TERM[/]  "
            f"[#8ef9f3]{now}[/]  "
            f"[{conn_color}]LINK {pulse} {self.status_text}[/]  "
            f"[#ffcf5c]latency~{age_ms}ms[/]"
        )
        self.query_one("#header", Static).update(header)
        self._render_status_line()

    def _animate_ticker(self) -> None:
        chunks: list[str] = []

        for symbol in self.crypto_symbols:
            state = self.symbol_data[symbol]
            if state.price <= 0:
                continue
            arrow = "▲" if state.change_percent >= 0 else "▼"
            chunks.append(f"C:{symbol} {arrow} {state.price:,.4f} ({state.change_percent:+.2f}%)")

        for symbol in self.stock_symbols:
            state = self.stock_data[symbol]
            if state.price <= 0:
                continue
            arrow = "▲" if state.change_percent >= 0 else "▼"
            chunks.append(f"S:{symbol} {arrow} {state.price:,.4f} ({state.change_percent:+.2f}%)")

        if not chunks:
            self.query_one("#ticker", Static).update("Waiting for market data...")
            return

        line = "   |   ".join(chunks)
        scroll = f"{line}   ||   {line}   ||   "
        if not scroll:
            return
        width = max(40, self.size.width - 6)
        start = self.ticker_offset % len(scroll)
        visible = (scroll + scroll)[start : start + width]
        ticker_text = Text(visible, style="#d7f2ff")
        for idx, ch in enumerate(visible):
            if ch == "▲":
                ticker_text.stylize("#00ffae", idx, idx + 1)
            elif ch == "▼":
                ticker_text.stylize("#ff5e7a", idx, idx + 1)
        self.query_one("#ticker", Static).update(ticker_text)
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

    def _schedule_news_refresh(self) -> None:
        asyncio.create_task(self._refresh_news())

    def action_refresh_news(self) -> None:
        self._log("[#2ec4b6]NEWS[/] manual refresh requested")
        self._schedule_news_refresh()

    def action_quick_quit(self) -> None:
        if isinstance(self.screen, ChartModal):
            self.screen.dismiss(None)
            return
        if not self.command_mode:
            self.exit()

    def action_quick_reset(self) -> None:
        if not self.command_mode:
            self.action_reset()

    def action_quick_news(self) -> None:
        if not self.command_mode:
            self.action_refresh_news()

    def action_enter_command_mode(self) -> None:
        if not self.command_mode:
            self._enter_command_mode()

    def action_exit_command_mode(self) -> None:
        if isinstance(self.screen, ChartModal):
            self.screen.dismiss(None)
            return
        if self.command_mode:
            self._exit_command_mode()

    def action_show_help_tip(self) -> None:
        self._log(
            "[#ffcf5c]Tip:[/] Enter chart on focused table; ':' command mode; commands: :q :r :n :help"
        )

    def action_open_chart(self) -> None:
        if isinstance(self.screen, ChartModal):
            self.screen.dismiss(None)
            return
        news_table = self.query_one("#news_table", DataTable)
        alerts_table = self.query_one("#stock_quotes", DataTable)
        main_table = self.query_one("#crypto_quotes", DataTable)
        if news_table.has_focus:
            row = news_table.cursor_row
            if row is not None:
                self._copy_news_link(int(row))
            return
        if alerts_table.has_focus:
            row = alerts_table.cursor_row
            if row is not None:
                self._open_alert_chart_for_row(int(row))
            return
        row = main_table.cursor_row
        if row is not None:
            self._open_main_chart_for_row(int(row))

    def _open_chart_for_symbol(self, symbol: str, symbol_type: str) -> None:
        if symbol_type == "stock":
            if symbol not in self.stock_data:
                self.stock_data[symbol] = StockState(symbol=symbol)
                self.stock_candles[symbol] = deque(maxlen=CANDLE_BUFFER_MAX)
                for tf in self.stock_candles_by_tf:
                    self.stock_candles_by_tf[tf].setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
            self.push_screen(
                ChartModal(
                    symbol=symbol,
                    chart_builder=lambda tf, candles: self._build_stock_chart_text(
                        self.stock_data[symbol], tf, candles
                    ),
                    ensure_history=lambda tf, candles: self._ensure_stock_chart_history(
                        symbol, tf, candles
                    ),
                )
            )
            return
        if symbol not in self.symbol_data:
            self.symbol_data[symbol] = SymbolState(symbol=symbol)
            self.candles[symbol] = deque(maxlen=CANDLE_BUFFER_MAX)
            for tf in self.crypto_candles_by_tf:
                self.crypto_candles_by_tf[tf].setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
        self.push_screen(
            ChartModal(
                symbol=symbol,
                chart_builder=lambda tf, candles: self._build_chart_text(
                    self.symbol_data[symbol], tf, candles
                ),
                ensure_history=lambda tf, candles: self._ensure_crypto_chart_history(
                    symbol, tf, candles
                ),
            )
        )

    def _open_main_chart_for_row(self, row_index: int) -> None:
        item = self.main_row_item_by_index.get(row_index)
        if not item:
            return
        symbol, symbol_type = item
        self._open_chart_for_symbol(symbol, symbol_type)

    def _open_alert_chart_for_row(self, row_index: int) -> None:
        item = self.alerts_row_item_by_index.get(row_index)
        if not item:
            return
        symbol, symbol_type = item
        self._open_chart_for_symbol(symbol, symbol_type)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "crypto_quotes":
            self._open_main_chart_for_row(event.cursor_row)
            return
        if event.data_table.id == "stock_quotes":
            self._open_alert_chart_for_row(event.cursor_row)
            return
        if event.data_table.id == "news_table":
            self._copy_news_link(event.cursor_row)

    async def _refresh_news(self) -> None:
        try:
            by_category = await asyncio.to_thread(fetch_all_news, NEWS_MAX_ITEMS)
            self.news_groups = self._build_news_groups(by_category)
            self.news_last_update = datetime.now(self.local_tz).strftime("%H:%M")
            self.news_group_index = 0
            self._update_news_panel()
            total = sum(len(items) for items in by_category.values())
            self._log(f"[#2ec4b6]NEWS[/] refreshed {total} headlines across {len(by_category)} feeds")
        except Exception as exc:
            self._log(f"[yellow]News warning:[/] {exc!r}")

    def _build_news_groups(self, by_category: dict[str, list[NewsItem]]) -> list[tuple[str, list[NewsItem]]]:
        groups: list[tuple[str, list[NewsItem]]] = []
        for category, items in by_category.items():
            for i in range(0, len(items), NEWS_GROUP_SIZE):
                chunk = items[i : i + NEWS_GROUP_SIZE]
                if chunk:
                    groups.append((category, chunk))
        return groups

    def _rotate_news_group(self) -> None:
        if not self.news_groups:
            return
        self.news_group_index = (self.news_group_index + 1) % len(self.news_groups)
        self._update_news_panel()

    def _rotate_main_group(self) -> None:
        if not self.main_group_items:
            return
        self.main_group_index = (self.main_group_index + 1) % len(self.main_group_items)
        self._update_main_group_panel()
        self._schedule_stock_refresh()

    def _update_main_group_panel(self) -> None:
        table = self.query_one("#crypto_quotes", DataTable)
        if not self.main_group_items:
            self.main_visible_items = []
            self.main_row_item_by_index.clear()
            with contextlib.suppress(Exception):
                table.border_title = " MAIN TABLE "
            for i, row_key in enumerate(self.main_row_keys):
                table.update_cell(row_key, self.main_col_keys["symbol"], "-" if i == 0 else "")
                table.update_cell(row_key, self.main_col_keys["type"], "-")
                table.update_cell(row_key, self.main_col_keys["price"], "-")
                table.update_cell(row_key, self.main_col_keys["change"], "-")
                table.update_cell(row_key, self.main_col_keys["volume"], "-")
                table.update_cell(row_key, self.main_col_keys["spark"], "")
            return

        group_name, items = self.main_group_items[self.main_group_index]
        self.main_visible_items = items
        self.main_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" MAIN TABLE // {group_name} "
                f"[group {self.main_group_index + 1}/{len(self.main_group_items)}] "
                f"[updated {self.stocks_last_update}] "
            )

        for i, row_key in enumerate(self.main_row_keys):
            if i < len(items):
                symbol, symbol_type = items[i]
                self.main_row_item_by_index[i] = (symbol, symbol_type)
                self._refresh_main_row(symbol, symbol_type)
                continue

            table.update_cell(row_key, self.main_col_keys["symbol"], "")
            table.update_cell(row_key, self.main_col_keys["type"], "")
            table.update_cell(row_key, self.main_col_keys["price"], "")
            table.update_cell(row_key, self.main_col_keys["change"], "")
            table.update_cell(row_key, self.main_col_keys["volume"], "")
            table.update_cell(row_key, self.main_col_keys["spark"], "")

    def _update_alerts_panel(self) -> None:
        table = self.query_one("#stock_quotes", DataTable)
        entries: list[tuple[str, str, float, float, float]] = []
        for symbol, state in self.symbol_data.items():
            if state.price <= 0 and state.last_update_ms <= 0:
                continue
            entries.append((symbol, "crypto", state.change_percent, state.price, state.volume))
        for symbol, state in self.stock_data.items():
            if state.price <= 0 and state.last_update_ms <= 0:
                continue
            entries.append((symbol, "stock", state.change_percent, state.price, state.volume))

        entries.sort(key=lambda item: abs(item[2]), reverse=True)
        top = entries[:ALERTS_TABLE_SIZE]
        self.alerts_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" ALERTS TABLE // top {ALERTS_TABLE_SIZE} abs movers "
                f"[updated {self.stocks_last_update}] "
            )

        for i, row_key in enumerate(self.alerts_row_keys):
            table.update_cell(row_key, self.alerts_col_keys["rank"], f"{i + 1}")
            if i >= len(top):
                table.update_cell(row_key, self.alerts_col_keys["symbol"], "")
                table.update_cell(row_key, self.alerts_col_keys["type"], "")
                table.update_cell(row_key, self.alerts_col_keys["change"], "")
                table.update_cell(row_key, self.alerts_col_keys["price"], "")
                table.update_cell(row_key, self.alerts_col_keys["volume"], "")
                continue

            symbol, symbol_type, change_pct, price, volume = top[i]
            self.alerts_row_item_by_index[i] = (symbol, symbol_type)
            color = "#00ffae" if change_pct >= 0 else "#ff5e7a"
            type_label = "CRYPTO" if symbol_type == "crypto" else "STOCK"
            table.update_cell(row_key, self.alerts_col_keys["symbol"], symbol)
            table.update_cell(row_key, self.alerts_col_keys["type"], type_label)
            table.update_cell(
                row_key,
                self.alerts_col_keys["change"],
                Text(f"{change_pct:>+9.2f}%", style=f"bold {color}"),
            )
            table.update_cell(
                row_key,
                self.alerts_col_keys["price"],
                Text(f"{price:>15,.4f}", style=color),
            )
            table.update_cell(row_key, self.alerts_col_keys["volume"], f"{volume:>22,.2f}")

    async def _preload_history(self) -> None:
        if self.boot_modal:
            self.boot_modal.set_total(len(self.crypto_symbols) + len(self.stock_symbols))
            self.boot_modal.set_phase("Syncing crypto history")
        self._log(f"[#2ec4b6]HISTORY[/] loading recent {INITIAL_HISTORY_POINTS} quotes per symbol...")
        for symbol in self.crypto_symbols:
            try:
                closes = await asyncio.to_thread(
                    self.feed.fetch_recent_closes, symbol, INITIAL_HISTORY_POINTS
                )
                candles_raw = await asyncio.to_thread(
                    self.feed.fetch_recent_15m_ohlc, symbol, INITIAL_CANDLE_LIMIT
                )
                self._seed_symbol_history(symbol, closes, candles_raw)
            except Exception as exc:
                self._log(f"[yellow]History warning {symbol}:[/] {exc!r}")
            if self.boot_modal:
                self.boot_modal.increment()
        self._update_main_group_panel()
        self._update_alerts_panel()
        self._log("[#2ec4b6]HISTORY[/] preload complete")

    async def _preload_stock_history(self) -> None:
        if not self.stock_symbols:
            return
        current_group_stocks = [s for s, t in self.main_visible_items if t == "stock"]
        first_group_stocks: list[str] = []
        if self.main_group_items:
            first_group_stocks = [s for s, t in self.main_group_items[0][1] if t == "stock"]
        preload_symbols = current_group_stocks or first_group_stocks or self.stock_symbols[:20]
        if self.boot_modal:
            self.boot_modal.set_phase("Syncing stock history")
            self.boot_modal.set_total(len(self.crypto_symbols) + len(preload_symbols))
        self._log(
            f"[#ff9f43]STOCKS HISTORY[/] loading recent {INITIAL_HISTORY_POINTS} quotes per symbol..."
        )
        for symbol in preload_symbols:
            try:
                closes, candles = await asyncio.to_thread(
                    fetch_stock_history, symbol, INITIAL_HISTORY_POINTS, INITIAL_CANDLE_LIMIT
                )
                self._seed_stock_history(symbol, closes, candles)
            except Exception as exc:
                self._log(f"[yellow]Stock history warning {symbol}:[/] {exc!r}")
            if self.boot_modal:
                self.boot_modal.increment()
        self._update_main_group_panel()
        self._update_alerts_panel()
        self._log("[#ff9f43]STOCKS HISTORY[/] preload complete")

    async def _show_boot_modal(self) -> None:
        self.boot_modal = BootModal()
        self.push_screen(self.boot_modal)
        await asyncio.sleep(0.05)

    async def _hide_boot_modal(self) -> None:
        if not self.boot_modal:
            return
        self.boot_modal.complete()
        await asyncio.sleep(0.45)
        self.boot_modal.dismiss(None)
        self.boot_modal = None

    def _schedule_stock_refresh(self) -> None:
        asyncio.create_task(self._refresh_stocks())

    async def _refresh_stocks(self) -> None:
        if not self.stock_symbols:
            return
        visible_stock_symbols = [s for s, t in self.main_visible_items if t == "stock"]
        symbols_to_refresh = visible_stock_symbols or self.stock_symbols
        if not symbols_to_refresh:
            return
        try:
            quotes = await asyncio.to_thread(fetch_stock_quotes, symbols_to_refresh)
            for quote in quotes:
                self._apply_stock_quote(quote)
            self.stocks_last_update = datetime.now(self.local_tz).strftime("%H:%M")
            self._update_main_group_panel()
            self._update_alerts_panel()
            self._log(
                f"[#2ec4b6]STOCKS[/] refreshed {len(quotes)} symbols "
                f"({len(symbols_to_refresh)} in active group)"
            )
        except Exception as exc:
            self._log(f"[yellow]Stocks warning:[/] {exc!r}")

    async def _ensure_crypto_chart_history(
        self, symbol: str, timeframe: str, target_candles: int
    ) -> None:
        series = self._get_crypto_series(symbol, timeframe)
        if series is None:
            return
        required = min(CANDLE_BUFFER_MAX, max(INITIAL_CANDLE_LIMIT, target_candles + 8))
        if len(series) >= required:
            return

        candles_raw = await asyncio.to_thread(self.feed.fetch_recent_ohlc, symbol, timeframe, required)
        if not candles_raw:
            return
        fresh = deque(maxlen=CANDLE_BUFFER_MAX)
        for open_ts, open_p, high_p, low_p, close_p in candles_raw:
            fresh.append(
                Candle(
                    bucket_ms=open_ts,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                )
            )
        if timeframe == "15m":
            self.candles[symbol] = fresh
            return
        self.crypto_candles_by_tf[timeframe][symbol] = fresh

    async def _ensure_stock_chart_history(
        self, symbol: str, timeframe: str, target_candles: int
    ) -> None:
        series = self._get_stock_series(symbol, timeframe)
        if series is None:
            return
        required = min(CANDLE_BUFFER_MAX, max(INITIAL_CANDLE_LIMIT, target_candles + 8))
        if len(series) >= required:
            return

        candles_raw = await asyncio.to_thread(fetch_stock_candles_timeframe, symbol, timeframe, required)
        if not candles_raw:
            return
        fresh = deque(maxlen=CANDLE_BUFFER_MAX)
        for open_ts, open_p, high_p, low_p, close_p in candles_raw:
            fresh.append(
                Candle(
                    bucket_ms=open_ts,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                )
            )
        if timeframe == "15m":
            self.stock_candles[symbol] = fresh
            return
        self.stock_candles_by_tf[timeframe][symbol] = fresh

    def _get_crypto_series(self, symbol: str, timeframe: str) -> deque[Candle] | None:
        if timeframe == "15m":
            return self.candles.get(symbol)
        by_tf = self.crypto_candles_by_tf.get(timeframe, {})
        return by_tf.get(symbol)

    def _get_stock_series(self, symbol: str, timeframe: str) -> deque[Candle] | None:
        if timeframe == "15m":
            return self.stock_candles.get(symbol)
        by_tf = self.stock_candles_by_tf.get(timeframe, {})
        return by_tf.get(symbol)

    def _seed_symbol_history(
        self,
        symbol: str,
        closes: list[tuple[int, float]],
        candles_raw: list[tuple[int, float, float, float, float]],
    ) -> None:
        state = self.symbol_data[symbol]
        assert state.points is not None
        state.points.clear()
        for _, close_price in closes[-MAX_POINTS:]:
            state.points.append(close_price)
        if closes:
            last_ts, last_close = closes[-1]
            state.last_update_ms = last_ts
            state.price = last_close

        series = self.candles[symbol]
        series.clear()
        for open_ts, open_p, high_p, low_p, close_p in candles_raw:
            series.append(
                Candle(
                    bucket_ms=open_ts,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                )
            )

        self._refresh_main_row(symbol, "crypto")

    def _seed_stock_history(
        self,
        symbol: str,
        closes: list[tuple[int, float]],
        candles_raw: list[tuple[int, float, float, float, float]],
    ) -> None:
        state = self.stock_data[symbol]
        assert state.points is not None
        state.points.clear()
        for _, close_price in closes[-MAX_POINTS:]:
            state.points.append(close_price)
        if closes:
            last_ts, last_close = closes[-1]
            state.last_update_ms = last_ts
            state.price = last_close

        series = self.stock_candles[symbol]
        series.clear()
        for open_ts, open_p, high_p, low_p, close_p in candles_raw:
            series.append(
                Candle(
                    bucket_ms=open_ts,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                )
            )
        self._refresh_main_row(symbol, "stock")

    def _resolve_timezone(self) -> ZoneInfo | None:
        if self.timezone:
            try:
                return ZoneInfo(self.timezone)
            except Exception:
                pass
        return datetime.now().astimezone().tzinfo

    def _update_news_panel(self) -> None:
        header = self.query_one("#news_header", Static)
        table = self.query_one("#news_table", DataTable)

        if not self.news_groups:
            header.update(Text("NEWS // finviz.com (refresh 10m)", style="#7aa3c5"))
            self.news_row_links.clear()
            for i in range(NEWS_GROUP_SIZE):
                row_key = self.news_row_keys[i]
                table.update_cell(row_key, self.news_col_keys["idx"], f"{i + 1}")
                table.update_cell(row_key, self.news_col_keys["age"], "-")
                table.update_cell(
                    row_key, self.news_col_keys["title"], "No headlines available\nTry refresh [n]"
                )
                table.update_cell(row_key, self.news_col_keys["source"], "-")
            return

        category, items = self.news_groups[self.news_group_index]
        title_style = "#2ec4b6" if "CRYPTO" in category else "#ff9f43" if "STOCK" in category else "#8ad9ff"
        header_txt = Text()
        header_txt.append(f"{category} // ", style=f"bold {title_style}")
        header_txt.append("finviz.com", style="#8ad9ff")
        header_txt.append(f" (refresh {NEWS_REFRESH_SECONDS // 60}m) ", style="#6f8aa8")
        header_txt.append(
            f"[group {self.news_group_index + 1}/{len(self.news_groups)} | updated {self.news_last_update}]",
            style="#6f8aa8",
        )
        header.update(header_txt)

        self.news_row_links.clear()
        for i in range(NEWS_GROUP_SIZE):
            row_key = self.news_row_keys[i]
            if i < len(items):
                item = items[i]
                self.news_row_links[i] = item.url
                table.update_cell(row_key, self.news_col_keys["idx"], f"{i + 1}")
                table.update_cell(row_key, self.news_col_keys["age"], item.age[:7])
                table.update_cell(
                    row_key,
                    self.news_col_keys["title"],
                    self._format_headline_two_lines(item.title, line_len=54),
                )
                table.update_cell(row_key, self.news_col_keys["source"], item.source[:12])
            else:
                table.update_cell(row_key, self.news_col_keys["idx"], f"{i + 1}")
                table.update_cell(row_key, self.news_col_keys["age"], "-")
                table.update_cell(row_key, self.news_col_keys["title"], "\n")
                table.update_cell(row_key, self.news_col_keys["source"], "")

    def _format_headline_two_lines(self, title: str, line_len: int = 54) -> str:
        words = title.split()
        if not words:
            return "\n"

        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= line_len:
                current = candidate
                continue
            lines.append(current or word[:line_len])
            current = word if len(word) <= line_len else word[:line_len]
            if len(lines) == 2:
                break

        if len(lines) < 2 and current:
            lines.append(current)

        if len(lines) == 1:
            lines.append("")

        # Truncate to exactly two lines and append ellipsis if needed.
        rendered = lines[:2]
        consumed = " ".join(rendered).strip()
        if len(consumed) < len(title):
            rendered[1] = (rendered[1][: max(0, line_len - 1)] + "…").strip()
        return f"{rendered[0]}\n{rendered[1]}"

    def _copy_news_link(self, row_index: int) -> None:
        link = self.news_row_links.get(row_index)
        if not link:
            self._log("[yellow]NEWS[/] selected row has no link")
            return
        if self._copy_to_clipboard(link):
            self._log(f"[#2ec4b6]NEWS[/] link copied to clipboard: {link}")
        else:
            self._log(f"[yellow]NEWS[/] could not access clipboard, link: {link}")

    def _copy_to_clipboard(self, text: str) -> bool:
        try:
            if sys.platform.startswith("darwin") and shutil.which("pbcopy"):
                subprocess.run(["pbcopy"], input=text, text=True, check=True)
                return True
            if sys.platform.startswith("win"):
                subprocess.run(["clip"], input=text, text=True, check=True, shell=True)
                return True
            if shutil.which("clip.exe"):
                subprocess.run(["clip.exe"], input=text, text=True, check=True)
                return True
            if shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text, text=True, check=True)
                return True
            if shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
                return True
            if shutil.which("xsel"):
                subprocess.run(["xsel", "--clipboard", "--input"], input=text, text=True, check=True)
                return True
        except Exception:
            return False
        return False

    def _enter_command_mode(self) -> None:
        self.command_mode = True
        self.command_buffer = ""
        self._log("[#ffcf5c]COMMAND[/] mode enabled")
        command_input = self.query_one("#command_input", Input)
        command_input.display = True
        command_input.value = ":"
        command_input.focus()
        self._render_status_line()

    def _exit_command_mode(self) -> None:
        self.command_mode = False
        self.command_buffer = ""
        self._log("[#ffcf5c]COMMAND[/] mode disabled")
        command_input = self.query_one("#command_input", Input)
        command_input.value = ""
        command_input.display = False
        self.query_one("#crypto_quotes", DataTable).focus()
        self._render_status_line()

    def _render_status_line(self) -> None:
        line = self.query_one("#status_line", Static)

        if self.command_mode:
            left = f":{self.command_buffer}█ | [Enter] run | [Esc] normal | q quit | r reset | n news | help"
            right = "status: enter command"
            right_style = "#ffcf5c"
        else:
            left = ": [f2] Cmd | q quit | r reset | n news | [enter] chart"
            right = "status: normal"
            right_style = "#00ffae"

        total_width = max(40, self.size.width - 2)
        max_left = max(1, total_width - len(right) - 1)
        if len(left) > max_left:
            left = left[:max_left] if max_left <= 1 else (left[: max_left - 1] + "…")
        spaces = max(1, total_width - len(left) - len(right))
        txt = Text()
        txt.append(left, style="#d7f2ff")
        txt.append(" " * spaces, style="#6f8aa8")
        txt.append(right, style=f"bold {right_style}")
        line.update(txt)

    def _execute_command(self, command: str) -> None:
        cmd = command.strip().lower()
        if not cmd:
            return
        if cmd == "q":
            self.exit()
            return
        if cmd == "r":
            self.action_reset()
            return
        if cmd == "n":
            self.action_refresh_news()
            return
        if cmd == "help":
            self._log("[#ffcf5c]Commands:[/] :q :r :n :help")
            return
        self._log(f"[yellow]Command unknown:[/] :{cmd}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command_input":
            return
        raw = (event.value or "").strip()
        if raw.startswith(":"):
            raw = raw[1:].strip()
        if not raw:
            event.input.value = ""
            self._exit_command_mode()
            return
        self._execute_command(raw)
        event.input.value = ""
        self._exit_command_mode()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command_input":
            return
        value = event.value or ""
        if value.startswith(":"):
            value = value[1:]
        self.command_buffer = value
        if self.command_mode:
            self._render_status_line()

    def _apply_quote(self, quote: Quote) -> None:
        self.last_tick_ms = quote.event_time_ms
        state = self.symbol_data[quote.symbol]
        state.price = quote.price
        state.change_percent = quote.change_percent
        state.volume = quote.volume
        state.last_update_ms = quote.event_time_ms
        assert state.points is not None
        state.points.append(quote.price)
        self._update_candles(quote.symbol, quote.price, quote.event_time_ms)
        self._refresh_main_row(quote.symbol, "crypto")
        self._update_alerts_panel()

    def _update_candles(self, symbol: str, price: float, event_time_ms: int) -> None:
        series = self.candles[symbol]
        bucket = (event_time_ms // FIFTEEN_MIN_MS) * FIFTEEN_MIN_MS
        if not series or series[-1].bucket_ms != bucket:
            series.append(Candle(bucket_ms=bucket, open=price, high=price, low=price, close=price))
            return

        candle = series[-1]
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price

    def _refresh_main_row(self, symbol: str, symbol_type: str) -> None:
        table = self.query_one("#crypto_quotes", DataTable)
        row_index = None
        for idx, item in self.main_row_item_by_index.items():
            if item == (symbol, symbol_type):
                row_index = idx
                break
        if row_index is None or not self.main_col_keys or row_index >= len(self.main_row_keys):
            return
        row_key = self.main_row_keys[row_index]

        if symbol_type == "crypto":
            state = self.symbol_data.get(symbol)
            if state is None:
                return
            color = "#00ffae" if state.change_percent >= 0 else "#ff5e7a"
            price = Text(f"{state.price:>15,.4f}", style=color)
            change = Text(f"{state.change_percent:>+9.2f}%", style=f"bold {color}")
            volume = f"{state.volume:>22,.2f}"
            spark = self._sparkline(state.points or deque())
            type_label = "CRYPTO"
        else:
            state = self.stock_data.get(symbol)
            if state is None:
                state = StockState(symbol=symbol)
                self.stock_data[symbol] = state
            color = "#00ffae" if state.change_percent >= 0 else "#ff5e7a"
            price = Text(f"{state.price:>15,.4f}", style=color)
            change = Text(f"{state.change_percent:>+9.2f}%", style=f"bold {color}")
            volume = f"{state.volume:>22,.0f}"
            spark = self._sparkline(state.points or deque())
            type_label = "STOCK"

        table.update_cell(row_key, self.main_col_keys["symbol"], symbol)
        table.update_cell(row_key, self.main_col_keys["type"], type_label)
        table.update_cell(row_key, self.main_col_keys["price"], price)
        table.update_cell(row_key, self.main_col_keys["change"], change)
        table.update_cell(row_key, self.main_col_keys["volume"], volume)
        table.update_cell(row_key, self.main_col_keys["spark"], spark)

    def _apply_stock_quote(self, quote: StockQuote) -> None:
        state = self.stock_data.get(quote.symbol)
        if state is None:
            return
        state.price = quote.price
        state.change_percent = quote.change_percent
        state.volume = quote.volume
        state.last_update_ms = quote.event_time_ms
        assert state.points is not None
        state.points.append(quote.price)
        self._update_stock_candles(quote.symbol, quote.price, quote.event_time_ms)
        self._refresh_main_row(quote.symbol, "stock")
        self._update_alerts_panel()

    def _update_stock_candles(self, symbol: str, price: float, event_time_ms: int) -> None:
        series = self.stock_candles[symbol]
        bucket = (event_time_ms // FIFTEEN_MIN_MS) * FIFTEEN_MIN_MS
        if not series or series[-1].bucket_ms != bucket:
            series.append(
                Candle(bucket_ms=bucket, open=price, high=price, low=price, close=price)
            )
            return

        candle = series[-1]
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price

    def _refresh_row(self, state: SymbolState) -> None:
        self._refresh_main_row(state.symbol, "crypto")

    def _refresh_stock_row(self, state: StockState) -> None:
        self._refresh_main_row(state.symbol, "stock")

    def _sparkline(self, values: deque[float]) -> Text:
        if not values:
            return Text("·", style="#446")
        sampled = self._compress_series(list(values), target=24)
        lo = min(sampled)
        hi = max(sampled)
        span = hi - lo or 1.0
        points = []
        for value in sampled:
            idx = int((value - lo) / span * (len(SPARKS) - 1))
            points.append(SPARKS[idx])
        trend_color = "#00ffae" if sampled[-1] >= sampled[0] else "#ff5e7a"
        return Text("".join(points), style=trend_color)

    def _build_chart_text(
        self, state: SymbolState, timeframe: str = "15m", target_candles: int = 96
    ) -> Text:
        candles = list(self._get_crypto_series(state.symbol, timeframe) or deque())
        if timeframe != "15m" and not candles:
            candles = self._resample_candles(list(self.candles.get(state.symbol, deque())), timeframe)
        return self._build_chart_from_series(
            symbol=state.symbol,
            market_label="CRYPTO",
            price=state.price,
            change_percent=state.change_percent,
            volume=state.volume,
            values=list(state.points or []),
            candles=candles,
            timeframe=timeframe,
            target_candles=target_candles,
        )

    def _build_stock_chart_text(
        self, state: StockState, timeframe: str = "15m", target_candles: int = 96
    ) -> Text:
        candles = list(self._get_stock_series(state.symbol, timeframe) or deque())
        if timeframe != "15m" and not candles:
            candles = self._resample_candles(list(self.stock_candles.get(state.symbol, deque())), timeframe)
        return self._build_chart_from_series(
            symbol=state.symbol,
            market_label="STOCK",
            price=state.price,
            change_percent=state.change_percent,
            volume=state.volume,
            values=list(state.points or []),
            candles=candles,
            timeframe=timeframe,
            target_candles=target_candles,
        )

    def _build_chart_from_series(
        self,
        *,
        symbol: str,
        market_label: str,
        price: float,
        change_percent: float,
        volume: float,
        values: list[float],
        candles: list[Candle],
        timeframe: str,
        target_candles: int,
    ) -> Text:
        color = "#00ffae" if change_percent >= 0 else "#ff5e7a"
        visible_candles = max(24, target_candles)

        chart = Text()
        chart.append(f"{symbol} // {market_label} SNAPSHOT\n", style="bold #99e2ff")
        chart.append(
            f"price: {price:,.4f}   change: {change_percent:+.2f}%   volume: {volume:,.2f}\n",
            style=f"bold {color}",
        )
        chart.append(
            f"timeframe: {timeframe.upper()}   toggle: [t] 15m/1h/1d/1w/1mo   close: [Esc]/[Enter]/[q]\n\n",
            style="#6f8aa8",
        )

        if len(candles) >= 2:
            chart.append("Chart 1: Candlestick view\n", style="bold #2ec4b6")
            chart.append(
                f"{timeframe.upper()} OHLC candles  |  showing latest {min(len(candles), visible_candles)}\n",
                style="#7fd7cb",
            )
            chart.append_text(
                self._render_candlestick_chart(candles, width=visible_candles, height=16)
            )
            chart.append("\n")

        if len(values) >= 2:
            lo = min(values)
            hi = max(values)
            chart.append("Chart 2: Live updates\n", style="bold #58b6ff")
            chart.append(
                f"tick trend min: {lo:,.4f}   max: {hi:,.4f}   points: {len(values)}\n",
                style="#8ad9ff",
            )
            plotext_text = self._render_plotext_xy(values, symbol)
            if plotext_text and plotext_text.count("\n") >= 8:
                chart.append(plotext_text, style="#d7f2ff")
            else:
                chart.append_text(self._render_xy_ascii(values, width=108, height=22, color=color))
            chart.append("\n")
        else:
            chart.append("Waiting for more ticks to draw chart...\n", style="#7aa3c5")
        return chart

    def _resample_candles(self, candles: list[Candle], timeframe: str) -> list[Candle]:
        if timeframe == "15m":
            return candles
        if not candles:
            return []

        bucket_by_tf = {
            "1h": 60 * 60 * 1000,
            "1d": 24 * 60 * 60 * 1000,
            "1w": 7 * 24 * 60 * 60 * 1000,
            "1mo": 30 * 24 * 60 * 60 * 1000,
        }
        bucket_ms = bucket_by_tf.get(timeframe)
        if bucket_ms is None:
            return candles

        out: list[Candle] = []
        current: Candle | None = None

        for candle in candles:
            bucket = (candle.bucket_ms // bucket_ms) * bucket_ms
            if current is None or current.bucket_ms != bucket:
                if current is not None:
                    out.append(current)
                current = Candle(
                    bucket_ms=bucket,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                )
                continue
            current.high = max(current.high, candle.high)
            current.low = min(current.low, candle.low)
            current.close = candle.close

        if current is not None:
            out.append(current)
        return out

    def _render_plotext_xy(self, values: list[float], symbol: str) -> str:
        if plt is None:
            return ""
        try:
            series = values[-240:]
            x = list(range(len(series)))
            clear_fn = getattr(plt, "clear_figure", None) or getattr(plt, "clf", None)
            if clear_fn:
                clear_fn()

            plot_size_fn = getattr(plt, "plot_size", None) or getattr(plt, "plotsize", None)
            if plot_size_fn:
                plot_size_fn(120, 28)

            title_fn = getattr(plt, "title", None)
            if title_fn:
                title_fn(f"{symbol} XY trend")

            xlabel_fn = getattr(plt, "xlabel", None)
            if xlabel_fn:
                xlabel_fn("ticks")

            ylabel_fn = getattr(plt, "ylabel", None)
            if ylabel_fn:
                ylabel_fn("price")

            grid_fn = getattr(plt, "grid", None)
            if grid_fn:
                try:
                    grid_fn(True, True)
                except Exception:
                    pass

            plot_fn = getattr(plt, "plot", None)
            if plot_fn:
                try:
                    plot_fn(x, series, color="cyan", marker="braille")
                except Exception:
                    plot_fn(x, series)

            build_fn = getattr(plt, "build", None)
            if not build_fn:
                return ""
            out = build_fn()
            if clear_fn:
                clear_fn()
            return out if isinstance(out, str) else str(out)
        except Exception:
            return ""

    def _render_xy_ascii(self, values: list[float], width: int, height: int, color: str) -> Text:
        series = values[-max(width * 2, width):]
        if len(series) > width:
            step = len(series) / width
            sampled = [series[int(i * step)] for i in range(width)]
        else:
            sampled = series[:]
            if len(sampled) < width:
                sampled = [sampled[0]] * (width - len(sampled)) + sampled

        lo = min(sampled)
        hi = max(sampled)
        span = hi - lo or 1.0

        def y(value: float) -> int:
            return int((value - lo) / span * (height - 1))

        grid = [[" " for _ in range(width)] for _ in range(height)]

        # Draw polyline with vertical connectors for continuity.
        prev_y = y(sampled[0])
        grid[height - 1 - prev_y][0] = "●"
        for x in range(1, width):
            cur_y = y(sampled[x])
            y0 = min(prev_y, cur_y)
            y1 = max(prev_y, cur_y)
            for yy in range(y0, y1 + 1):
                ch = "●" if yy == cur_y else "│"
                grid[height - 1 - yy][x] = ch
            prev_y = cur_y

        text = Text()
        text.append(f"{hi:,.4f} ┤", style="#8ad9ff")
        text.append("\n")
        for row in grid:
            text.append("      │", style="#284257")
            text.append("".join(row), style=color)
            text.append("\n")
        text.append(f"{lo:,.4f} ┼", style="#8ad9ff")
        text.append("─" * width, style="#284257")
        text.append("\n")
        text.append("       oldest", style="#6f8aa8")
        text.append(" " * (max(1, width - 13)))
        text.append("latest", style="#6f8aa8")
        text.append("\n")
        return text

    def _compress_series(self, values: list[float], target: int) -> list[float]:
        if len(values) <= target:
            return values
        step = len(values) / target
        out: list[float] = []
        for i in range(target):
            idx = int(i * step)
            out.append(values[idx])
        return out

    def _render_candlestick_chart(self, candles: list[Candle], width: int, height: int) -> Text:
        if len(candles) > width:
            sampled = candles[-width:]
        else:
            sampled = candles

        lo = min(c.low for c in sampled)
        hi = max(c.high for c in sampled)
        span = hi - lo or 1.0

        def scale(price: float) -> int:
            return int((price - lo) / span * (height - 1))

        text = Text()
        for row in range(height - 1, -1, -1):
            for candle in sampled:
                y_low = scale(candle.low)
                y_high = scale(candle.high)
                y_open = scale(candle.open)
                y_close = scale(candle.close)
                body_min = min(y_open, y_close)
                body_max = max(y_open, y_close)
                up = candle.close >= candle.open
                c_color = "#00ffae" if up else "#ff5e7a"

                if body_min <= row <= body_max:
                    text.append("█", style=c_color)
                elif y_low <= row <= y_high:
                    text.append("│", style=c_color)
                else:
                    text.append(" ")
            text.append("\n")

        text.append(f"high {hi:,.4f}\n", style="#8ad9ff")
        text.append(f"low  {lo:,.4f}\n", style="#8ad9ff")
        return text

    def _log(self, message: str) -> None:
        self.query_one("#events", RichLog).write(message)

    def action_reset(self) -> None:
        for symbol in self.crypto_symbols:
            self.symbol_data[symbol] = SymbolState(symbol=symbol)
            self._refresh_main_row(symbol, "crypto")
            for tf in self.crypto_candles_by_tf:
                self.crypto_candles_by_tf[tf][symbol].clear()
        for symbol in self.stock_symbols:
            self.stock_data[symbol] = StockState(symbol=symbol)
            self.stock_candles[symbol].clear()
            for tf in self.stock_candles_by_tf:
                self.stock_candles_by_tf[tf][symbol].clear()
            self._refresh_main_row(symbol, "stock")
        self._update_main_group_panel()
        self._update_alerts_panel()
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
        table = self.query_one("#crypto_quotes", DataTable)
        for row_index, item in self.main_row_item_by_index.items():
            if item == (symbol, "crypto"):
                table.move_cursor(row=row_index)
                break

    async def on_key(self, event: events.Key) -> None:
        if isinstance(self.screen, ChartModal):
            if event.key in {"escape", "enter", "q"}:
                self.screen.dismiss(None)
                event.stop()
                return
            # While chart modal is open, global shortcuts must not affect the app.
            return

        if self.command_mode:
            if event.key == "escape":
                self._exit_command_mode()
                event.stop()
                return
            # Let Input widget handle typing/submission in command mode.
            return

        if event.character == ":" or event.key in {":", "colon"}:
            self._enter_command_mode()
            event.stop()
            return
        if event.key == "q":
            self.exit()
            return
        if event.key == "r":
            self.action_reset()
            return
        if event.key == "n":
            self.action_refresh_news()
            return
        if event.key == "1":
            self.action_focus_symbol("BTCUSDT")
            return
        if event.key == "2":
            self.action_focus_symbol("ETHUSDT")
            return
        if event.key == "3":
            self.action_focus_symbol("SOLUSDT")
            return
        if event.key == "a":
            self.action_show_help_tip()


def run_app(
    crypto_symbols: Iterable[str] | None = None,
    stock_symbols: Iterable[str] | None = None,
    timezone: str = "",
    groups: Iterable[dict[str, Any]] | None = None,
) -> None:
    NeonQuotesApp(
        crypto_symbols=crypto_symbols,
        stock_symbols=stock_symbols,
        timezone=timezone,
        groups=groups,
    ).run()
