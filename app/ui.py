from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    CACHE_TTL_SECONDS,
    CALENDAR_HORIZON_DAYS,
    CALENDAR_REFRESH_SECONDS,
    CALENDAR_SOON_HOURS,
    CHART_HISTORY_POINTS,
    DEFAULT_CRYPTO_SYMBOLS,
    DEFAULT_STOCK_SYMBOLS,
    INITIAL_CANDLE_LIMIT,
    INITIAL_HISTORY_POINTS,
    MAX_EVENTS,
    MAX_POINTS,
    NAME_CACHE_TTL_SECONDS,
    NEWS_GROUP_ROTATE_SECONDS,
    NEWS_GROUP_SIZE,
    NEWS_MAX_ITEMS,
    NEWS_REFRESH_SECONDS,
    STARTUP_IO_CONCURRENCY,
    STOCK_GROUP_ROTATE_SECONDS,
    STOCKS_REFRESH_SECONDS,
)
from .calendar import CalendarEvent, fetch_calendar_events
from .cache import load_names_cache, load_symbol_history_cache, save_names_cache, save_symbol_history_cache
from .cache import append_app_log_line
from .feed import BinanceTickerFeed
from .i18n import format_time_local, set_language, tr
from .models import Quote
from .news import NewsItem, fetch_all_news
from .stocks import (
    StockQuote,
    fetch_stock_candles_timeframe,
    fetch_stock_history,
    fetch_stock_quotes,
)
from .symbol_names import resolve_symbol_names, update_config_group_names
from .version import get_app_version

SPARKS = "▁▂▃▄▅▆▇█"
FIFTEEN_MIN_MS = 15 * 60 * 1000
CANDLE_BUFFER_MAX = 1000
TIMEFRAMES = ("15m", "1h", "1d", "1w", "1mo")
ALERTS_TABLE_SIZE = 15
STOCK_TREND_UP_COLOR = "#00ffae"
STOCK_TREND_DOWN_COLOR = "#ff5e7a"
TICKER_MODE_SECONDS = 60
NEWS_MODE_SECONDS = 180
CALENDAR_MODE_SECONDS = 60
NEWS_TICKER_LIMIT = 10
NEWS_TICKER_HEADLINE_MAX = 110

AGE_TOKEN_RE = re.compile(
    r"^(?P<num>\d+)\s*(?P<unit>min|mins|minute|minutes|hour|hours|day|days)$",
    re.IGNORECASE,
)

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
        if event.key == "escape":
            app = self.app
            if isinstance(app, NeonQuotesApp):
                app.action_exit_command_mode()
                event.stop()
                return
        if event.key == "tab":
            app = self.app
            if isinstance(app, NeonQuotesApp):
                app.autocomplete_command_input()
                event.stop()
                return
        # Let Input handle all other keys through its own internal bindings.


class NeonQuotesApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "Neon Quotes Terminal"
    SUB_TITLE = "Real-time market feed"

    BINDINGS = [
        Binding("q", "quick_quit", "Quit", priority=True),
        Binding("enter", "open_chart", "Chart"),
        Binding("colon", "enter_command_mode", show=False, priority=True, system=True),
        Binding("f2", "enter_command_mode", show=False, priority=True, system=True),
        Binding("ctrl+g", "enter_command_mode", show=False, priority=True, system=True),
        Binding("escape", "exit_command_mode", show=False, priority=True, system=True),
    ]

    heartbeat = reactive(False)
    status_text = reactive("CONNECTING")
    ticker_offset = reactive(0)

    def _build_symbol_groups(
        self,
        source_groups: Iterable[dict[str, Any]],
        fallback_name: str = "MAIN",
        fallback_items: Iterable[tuple[str, str]] | None = None,
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        groups: list[tuple[str, list[tuple[str, str]]]] = []
        for group in source_groups:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name") or fallback_name).strip() or fallback_name
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
        fallback_symbols = list(fallback_items or [])
        if fallback_symbols:
            return [(fallback_name, fallback_symbols)]
        return []

    def _build_main_groups(self) -> list[tuple[str, list[tuple[str, str]]]]:
        fallback_symbols: list[tuple[str, str]] = []
        for symbol in self.crypto_symbols:
            fallback_symbols.append((symbol, "crypto"))
        for symbol in self.stock_symbols:
            fallback_symbols.append((symbol, "stock"))
        return self._build_symbol_groups(
            self.market_groups,
            fallback_name="MAIN",
            fallback_items=fallback_symbols,
        )

    def __init__(
        self,
        crypto_symbols: Iterable[str] | None = None,
        stock_symbols: Iterable[str] | None = None,
        timezone: str = "",
        language: str = "es",
        config_name: str = "",
        calendars: Iterable[dict[str, Any]] | None = None,
        groups: Iterable[dict[str, Any]] | None = None,
        indicator_groups: Iterable[dict[str, Any]] | None = None,
        quick_actions: dict[str, str] | None = None,
        symbol_names: dict[tuple[str, str], str] | None = None,
        config_path: str = "config.yml",
        symbols_from_config: bool = True,
    ) -> None:
        super().__init__()
        self.crypto_symbols = list(crypto_symbols or DEFAULT_CRYPTO_SYMBOLS)
        self.stock_symbols = [symbol.upper() for symbol in (stock_symbols or DEFAULT_STOCK_SYMBOLS)]
        self.market_groups = list(groups or [])
        self.indicator_groups = list(indicator_groups or [])
        self.symbol_names = dict(symbol_names or {})
        self.quick_actions = {
            "1": "BTCUSDT",
            "2": "ETHUSDT",
            "3": "SOLUSDT",
        }
        if quick_actions:
            for key in ("1", "2", "3"):
                symbol = str(quick_actions.get(key) or "").strip().upper()
                if symbol:
                    self.quick_actions[key] = symbol
        self.config_path = config_path
        self.symbols_from_config = symbols_from_config
        self.timezone = timezone.strip()
        self.language = (language or "es").strip().lower()
        self.config_name = (config_name or "").strip()
        self.app_version = get_app_version()
        self.calendars = list(calendars or [])
        set_language(self.language)
        self.feed = BinanceTickerFeed([])
        self.symbol_data = {symbol: SymbolState(symbol=symbol) for symbol in self.crypto_symbols}
        self.stock_data = {symbol: StockState(symbol=symbol) for symbol in self.stock_symbols}
        self.indicator_group_items: list[tuple[str, list[tuple[str, str]]]] = self._build_symbol_groups(
            self.indicator_groups,
            fallback_name="INDICATORS",
        )
        self.indicator_symbols = sorted(
            {symbol for _, items in self.indicator_group_items for symbol, _ in items}
        )
        self.indicator_data = {symbol: StockState(symbol=symbol) for symbol in self.indicator_symbols}
        self.feed_task: asyncio.Task[None] | None = None
        self.last_tick_ms = 0
        self.focused_symbol: str | None = None
        self.main_row_keys: list[Any] = []
        self.main_col_keys: dict[str, Any] = {}
        self.main_group_items: list[tuple[str, list[tuple[str, str]]]] = self._build_main_groups()
        self.main_group_index = 0
        self.main_visible_items: list[tuple[str, str]] = []
        self.main_row_item_by_index: dict[int, tuple[str, str]] = {}
        self.indicator_row_keys: list[Any] = []
        self.indicator_col_keys: dict[str, Any] = {}
        self.indicator_group_index = 0
        self.indicator_visible_items: list[tuple[str, str]] = []
        self.indicator_row_item_by_index: dict[int, tuple[str, str]] = {}
        self.alerts_row_keys: list[Any] = []
        self.alerts_col_keys: dict[str, Any] = {}
        self.alerts_row_item_by_index: dict[int, tuple[str, str]] = {}
        self.news_row_keys: list[Any] = []
        self.news_col_keys: dict[str, Any] = {}
        self.news_last_update = "never"
        self.news_groups: list[tuple[str, list[NewsItem]]] = []
        self.news_latest_items: list[NewsItem] = []
        self.news_group_index = 0
        self.news_row_links: dict[int, str] = {}
        self.ticker_modes: list[tuple[str, int]] = [
            ("quotes", max(1, TICKER_MODE_SECONDS // TICKER_MODE_SECONDS)),
            ("news", max(1, NEWS_MODE_SECONDS // TICKER_MODE_SECONDS)),
            ("calendar", max(1, CALENDAR_MODE_SECONDS // TICKER_MODE_SECONDS)),
        ]
        self.ticker_mode_index = 0
        self.ticker_mode = self.ticker_modes[0][0]
        self.ticker_mode_ticks_remaining = self.ticker_modes[0][1]
        self.main_rotation_pause_until = 0.0
        self.indicator_rotation_pause_until = 0.0
        self.news_rotation_pause_until = 0.0
        self.stocks_last_update = "never"
        self.indicators_last_update = "never"
        self.calendar_last_update = "never"
        self.calendar_events: list[CalendarEvent] = []
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
        self.lazy_history_task: asyncio.Task[None] | None = None
        self.name_resolve_task: asyncio.Task[None] | None = None
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self.is_shutting_down = False
        self.command_mode = False
        self.command_buffer = ""
        self._tab_cycle_key: tuple[Any, ...] | None = None
        self._tab_cycle_index: int = -1
        self.status_hint = (
            f":|f2 {tr('Cmd')} | q {tr('quit')} | [enter] {tr('chart')} | "
            f"? {tr('help')} | ⌃P palette"
        )

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="main"):
            with Vertical(id="markets"):
                yield DataTable(id="crypto_quotes")
                yield DataTable(id="stock_quotes")
                yield RichLog(id="events", highlight=True, wrap=False, markup=True)
            with Vertical(id="side"):
                yield DataTable(id="indicators_table")
                yield Static(id="news_header")
                yield DataTable(id="news_table")
        yield Static(id="ticker")
        yield Static(id="status_line")
        yield CommandInput(
            placeholder=":q | :r | :n | :c calendar | :? | :add | :del | :mv | :edit",
            id="command_input",
        )

    async def on_mount(self) -> None:
        main_table = self.query_one("#crypto_quotes", DataTable)
        main_table.cursor_type = "row"
        main_table.zebra_stripes = True
        col_symbol = main_table.add_column(tr("Ticker"), width=25)
        col_type = main_table.add_column(tr("Type"), width=4)
        col_price = main_table.add_column(tr("Price"), width=13)
        col_change = main_table.add_column("24h %", width=9)
        col_volume = main_table.add_column(tr("Volume"), width=17)
        col_spark = main_table.add_column(tr("Spark"))
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
        a_symbol = alerts_table.add_column(tr("Ticker"), width=25)
        a_type = alerts_table.add_column(tr("Type"), width=4)
        a_change = alerts_table.add_column("24h %", width=9)
        a_price = alerts_table.add_column(tr("Price"), width=13)
        a_volume = alerts_table.add_column(tr("Volume"), width=17)
        self.alerts_col_keys = {
            "symbol": a_symbol,
            "type": a_type,
            "change": a_change,
            "price": a_price,
            "volume": a_volume,
        }
        self.alerts_row_keys.clear()
        for i in range(ALERTS_TABLE_SIZE):
            row_key = alerts_table.add_row(
                "-",
                "-",
                "-",
                "-",
                "-",
                key=f"alert_{i}",
            )
            self.alerts_row_keys.append(row_key)
        self._update_alerts_panel()

        indicators_table = self.query_one("#indicators_table", DataTable)
        indicators_table.cursor_type = "row"
        indicators_table.zebra_stripes = True
        i_symbol = indicators_table.add_column(tr("Indicator"), width=30)
        i_change = indicators_table.add_column("24h %", width=9)
        i_price = indicators_table.add_column(tr("Price"), width=13)
        self.indicator_col_keys = {
            "symbol": i_symbol,
            "change": i_change,
            "price": i_price,
        }
        self.indicator_row_keys.clear()
        indicator_rows = max(1, max((len(items) for _, items in self.indicator_group_items), default=1))
        for i in range(indicator_rows):
            row_key = indicators_table.add_row("-", "-", "-", key=f"indicator_{i}")
            self.indicator_row_keys.append(row_key)
        self._update_indicators_panel()

        news_table = self.query_one("#news_table", DataTable)
        news_table.cursor_type = "row"
        news_table.zebra_stripes = True
        news_table.show_horizontal_scrollbar = False
        n_title = news_table.add_column(tr("Headline"), width=82)
        self.news_col_keys = {
            "title": n_title,
        }
        self.news_row_keys.clear()
        for i in range(NEWS_GROUP_SIZE):
            row_key = news_table.add_row(
                tr("Loading headlines...\nPlease wait\n"),
                key=f"news_{i}",
                height=3,
            )
            self.news_row_keys.append(row_key)

        events_log = self.query_one("#events", RichLog)
        events_log.max_lines = MAX_EVENTS
        self._log(tr("Booting market stream..."))
        self._load_cached_symbol_names()
        self._log("[#6f8aa8]NAMES[/] resolving symbol names in background...")
        self.name_resolve_task = asyncio.create_task(self._resolve_names_background())
        self.query_one("#news_header", Static).update(
            Text("NEWS // finviz.com (refresh 10m)", style=self._ui_palette()["accent"])
        )
        command_input = self.query_one("#command_input", Input)
        command_input.value = ""
        command_input.display = False
        self._render_status_line()
        self.watch(self.app, "theme", self._on_app_theme_changed, init=False)

        self.set_interval(0.5, self._update_clock)
        self.set_interval(0.15, self._animate_ticker)
        self.set_interval(TICKER_MODE_SECONDS, self._rotate_ticker_mode)
        self.set_interval(NEWS_REFRESH_SECONDS, self._schedule_news_refresh)
        self.set_interval(CALENDAR_REFRESH_SECONDS, self._schedule_calendar_refresh)
        self.set_interval(NEWS_GROUP_ROTATE_SECONDS, self._rotate_news_group)
        self.set_interval(STOCK_GROUP_ROTATE_SECONDS, self._rotate_main_group)
        self.set_interval(STOCK_GROUP_ROTATE_SECONDS, self._rotate_indicator_group)
        self.set_interval(STOCKS_REFRESH_SECONDS, self._schedule_stock_refresh)
        self.set_interval(STOCKS_REFRESH_SECONDS, self._schedule_indicator_refresh)
        self.startup_task = asyncio.create_task(self._startup_sequence())

    def _on_app_theme_changed(self, *_args: Any) -> None:
        # Re-render news metadata colors when theme changes from command palette.
        self._update_news_panel()
        self._update_main_group_panel()
        self._update_indicators_panel()
        self._update_alerts_panel()
        self._render_status_line()
        self._update_clock()

    def _ui_palette(self) -> dict[str, str]:
        theme = self.app.current_theme
        return {
            "brand": theme.primary or "#99e2ff",
            "accent": theme.accent or theme.primary or "#8ad9ff",
            "muted": theme.secondary or theme.primary or "#6f8aa8",
            "text": theme.foreground or "#d7f2ff",
            "ok": theme.success or theme.primary or "#00ffae",
            "warn": theme.warning or theme.primary or "#ffcf5c",
            "err": theme.error or theme.primary or "#ff5e7a",
        }

    def _trend_color(self, is_up: bool, symbol_type: str | None = None) -> str:
        if symbol_type == "stock":
            return STOCK_TREND_UP_COLOR if is_up else STOCK_TREND_DOWN_COLOR
        palette = self._ui_palette()
        return palette["ok"] if is_up else palette["err"]

    async def on_unmount(self) -> None:
        self.is_shutting_down = True
        for task in list(self.background_tasks):
            task.cancel()
        for task in list(self.background_tasks):
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(task, timeout=0.2)
        if self.startup_task:
            self.startup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.startup_task, timeout=0.2)
        if self.lazy_history_task:
            self.lazy_history_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.lazy_history_task, timeout=0.2)
        if self.name_resolve_task:
            self.name_resolve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.name_resolve_task, timeout=0.2)
        if self.feed_task:
            self.feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.feed_task, timeout=0.2)

    def _spawn_background(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        return task

    def _load_cached_symbol_names(self) -> None:
        cached = load_names_cache(NAME_CACHE_TTL_SECONDS)
        if not cached:
            self._log("[#6f8aa8]NAMES[/] no fresh local cache")
            return
        self.symbol_names.update(cached)
        self._log(f"[#2ec4b6]NAMES[/] loaded {len(cached)} cached names")

    async def _resolve_names_background(self) -> None:
        try:
            groups, indicator_groups, names, stats = await asyncio.to_thread(
                resolve_symbol_names,
                self.market_groups,
                self.indicator_groups,
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._log(f"[yellow]Names warning:[/] {exc!r}")
            return

        self.market_groups = groups
        self.indicator_groups = indicator_groups
        self.indicator_group_items = self._build_symbol_groups(
            self.indicator_groups,
            fallback_name="INDICATORS",
        )
        self.indicator_symbols = sorted(
            {symbol for _, items in self.indicator_group_items for symbol, _ in items}
        )
        for symbol in self.indicator_symbols:
            self.indicator_data.setdefault(symbol, StockState(symbol=symbol))
        for symbol in list(self.indicator_data):
            if symbol not in self.indicator_symbols:
                self.indicator_data.pop(symbol, None)
        self.symbol_names.update(names)
        save_names_cache(self.symbol_names)
        self._log(
            f"[#2ec4b6]NAMES[/] stocks={stats['stocks_total']} "
            f"(missing={stats['stocks_missing_name']}, resolved={stats['stocks_resolved_remote']})"
        )
        self._log(
            f"[#2ec4b6]NAMES[/] crypto={stats['crypto_total']} "
            f"(missing={stats['crypto_missing_name']}, resolved={stats['crypto_resolved_remote']})"
        )

        if self.symbols_from_config:
            updated = await asyncio.to_thread(
                update_config_group_names,
                self.config_path,
                groups,
                indicator_groups,
            )
            if updated:
                self._log("[#2ec4b6]CONFIG[/] symbol names persisted to config.yml")
            else:
                self._log("[#6f8aa8]CONFIG[/] no symbol name changes to persist")
        else:
            self._log("[#6f8aa8]CONFIG[/] symbols from CLI/env, names kept in memory")

        self._update_main_group_panel()
        self._update_indicators_panel()
        self._update_alerts_panel()

    async def _startup_sequence(self) -> None:
        try:
            # Let first frame render before opening boot modal.
            await asyncio.sleep(0)
            await self._show_boot_modal()
            await self._preload_visible_group_history()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._log(f"[yellow]Startup warning:[/] {exc!r}")
        finally:
            if self.is_shutting_down:
                return
            await self._hide_boot_modal()
            await self._refresh_crypto_stream_for_visible_group()
            self.lazy_history_task = self._spawn_background(self._load_remaining_history_in_background())
            self._schedule_news_refresh()
            self._schedule_calendar_refresh()
            self._schedule_stock_refresh()
            self._schedule_indicator_refresh()

    def _update_clock(self) -> None:
        palette = self._ui_palette()
        self.heartbeat = not self.heartbeat
        age_ms = int(time.time() * 1000) - self.last_tick_ms if self.last_tick_ms else 0
        conn_color = "green" if age_ms < 3000 else "yellow" if age_ms < 10000 else "red"
        pulse = "●" if self.heartbeat else "○"
        now = format_time_local(datetime.now(self.local_tz), tzinfo=self.local_tz)
        config_name = self.config_name or "default"
        header = (
            f"[bold {palette['ok']}]NEON MARKET TERM v{self.app_version}[/] "
            f"[{palette['muted']}]|[/] "
            f"[{palette['brand']}]{config_name}[/] "
            f"[{palette['muted']}]|[/] "
            f"[{palette['accent']}]{now}[/]  "
            f"[{conn_color}]LINK {pulse} {self.status_text}[/]  "
            f"[{palette['warn']}]latency~{age_ms}ms[/]"
        )
        self.query_one("#header", Static).update(header)
        self._render_status_line()

    def _rotate_ticker_mode(self) -> None:
        if self.is_shutting_down:
            return
        available_modes: list[tuple[str, int]] = []
        for mode, ticks in self.ticker_modes:
            if mode == "calendar" and not self._calendar_events_for_ticker():
                continue
            available_modes.append((mode, ticks))
        if not available_modes:
            available_modes = [("quotes", 1)]

        # If current mode is no longer available, snap to first available mode.
        available_names = [name for name, _ in available_modes]
        if self.ticker_mode not in available_names:
            self.ticker_mode_index = 0
            self.ticker_mode, ticks = available_modes[0]
            self.ticker_mode_ticks_remaining = max(1, ticks)
            self.ticker_offset = 0
            return

        if self.ticker_mode_ticks_remaining > 1:
            self.ticker_mode_ticks_remaining -= 1
        else:
            current_pos = available_names.index(self.ticker_mode)
            next_pos = (current_pos + 1) % len(available_modes)
            self.ticker_mode_index = next_pos
            self.ticker_mode, ticks = available_modes[next_pos]
            self.ticker_mode_ticks_remaining = max(1, ticks)
        self.ticker_offset = 0

    def _alerts_items_for_ticker(self) -> list[tuple[str, str]]:
        if not self.alerts_row_item_by_index:
            return []
        return [self.alerts_row_item_by_index[i] for i in sorted(self.alerts_row_item_by_index)]

    def _news_age_minutes(self, age: str) -> int:
        value = (age or "").strip().lower()
        if not value:
            return 999999
        if value == "now":
            return 0
        match = AGE_TOKEN_RE.match(value)
        if match:
            num = int(match.group("num"))
            unit = match.group("unit")
            if unit.startswith("min"):
                return num
            if unit.startswith("hour"):
                return num * 60
            if unit.startswith("day"):
                return num * 1440
        # Date tokens (e.g. "Mar-01") are older than relative "now/min/hour/day".
        if "-" in value and len(value) >= 6:
            return 200000
        return 300000

    def _headline_inline(self, item: NewsItem) -> str:
        source = (item.source or "source").strip()[:16]
        age = (item.age or "-").strip()[:10]
        if age.lower() == "now":
            age = f"{age} 🔥"
        title = " ".join((item.title or "").split())
        if len(title) > NEWS_TICKER_HEADLINE_MAX:
            title = title[: NEWS_TICKER_HEADLINE_MAX - 1].rstrip() + "…"
        return f"[{source}: {age}] {title}"

    def _format_hhmmss(self, delta_seconds: int) -> str:
        total = max(0, int(delta_seconds))
        hh = total // 3600
        mm = (total % 3600) // 60
        ss = total % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def _calendar_status_label(self, event: CalendarEvent) -> tuple[str, str]:
        now_utc = datetime.now(tz=UTC)
        if event.start_utc <= now_utc <= event.end_utc:
            return tr("LIVE ALERT"), "live"
        if now_utc > event.end_utc:
            return tr("FINISHED"), "done"
        delta = event.start_utc - now_utc
        if delta.total_seconds() <= CALENDAR_SOON_HOURS * 3600:
            return tr("event starts in {time}").format(
                time=self._format_hhmmss(int(delta.total_seconds()))
            ), "soon"
        return tr("SCHEDULED"), "scheduled"

    def _calendar_events_for_ticker(self) -> list[CalendarEvent]:
        if not self.calendar_events:
            return []
        now_local = datetime.now(self.local_tz)
        today = now_local.date()
        out: list[CalendarEvent] = []
        for event in self.calendar_events:
            start_local = event.start_utc.astimezone(self.local_tz)
            if start_local.date() != today:
                continue
            impact = (event.impact or "").strip().lower()
            if impact not in {"high", "alto", "3", "3.0"}:
                continue
            out.append(event)
        out.sort(key=lambda e: e.start_utc)
        return out

    def _build_calendar_text(self) -> Text:
        palette = self._ui_palette()
        txt = Text()
        now_local = datetime.now(self.local_tz)
        txt.append(f"{tr('ECONOMIC CALENDAR')}\n", style=f"bold {palette['brand']}")
        txt.append(
            (
                f"{tr('updated')} {self.calendar_last_update} | "
                f"{tr('horizon')} {CALENDAR_HORIZON_DAYS}d | "
                f"{tr('now')} {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            ),
            style=palette["muted"],
        )
        if not self.calendars:
            txt.append(f"{tr('No calendars configured in config.yml.')}\n", style=palette["warn"])
            txt.append(
                tr("Add a 'calendars' section with one or more entries.") + "\n",
                style=palette["muted"],
            )
            return txt
        if not self.calendar_events:
            txt.append(
                f"{tr('Calendars configured: {count}. No events available from source.').format(count=len(self.calendars))}\n",
                style=palette["warn"],
            )
            txt.append(
                f"{tr('Check internet connectivity, source availability, and region filters.')}\n",
                style=palette["muted"],
            )
            return txt

        for event in self.calendar_events:
            start_local = event.start_utc.astimezone(self.local_tz)
            end_local = event.end_utc.astimezone(self.local_tz)
            status, kind = self._calendar_status_label(event)
            status_color = palette["muted"]
            if kind == "live":
                status_color = palette["err"]
            elif kind == "done":
                status_color = palette["muted"]
            elif kind == "soon":
                status_color = palette["warn"]
            txt.append(
                f"[{event.calendar_name}] {start_local.strftime('%Y-%m-%d %H:%M')} - {end_local.strftime('%H:%M')} ",
                style=palette["accent"],
            )
            txt.append(f"{event.title}\n", style=palette["text"])
            txt.append(
                f"  {event.country}/{event.region}  impact={event.impact or '-'}  ",
                style=palette["muted"],
            )
            txt.append(f"{status}\n\n", style=f"bold {status_color}")
        return txt

    def _animate_ticker(self) -> None:
        chunks: list[str] = []
        mode = self.ticker_mode
        if mode == "quotes":
            for symbol, symbol_type in self._alerts_items_for_ticker():
                if symbol_type == "crypto":
                    state = self.symbol_data.get(symbol)
                else:
                    state = self.stock_data.get(symbol)
                if state is None or state.price <= 0:
                    continue
                arrow = "▲" if state.change_percent >= 0 else "▼"
                prefix = "C" if symbol_type == "crypto" else "S"
                chunks.append(f"{prefix}:{symbol} {arrow} {state.price:,.2f} ({state.change_percent:+.2f}%)")
        elif mode == "news":
            for idx, item in enumerate(self.news_latest_items[:NEWS_TICKER_LIMIT]):
                chunks.append(self._headline_inline(item))
                if idx < min(len(self.news_latest_items), NEWS_TICKER_LIMIT) - 1:
                    chunks.append("BREAKING NEWS")
        else:
            calendar_events = self._calendar_events_for_ticker()[:12]
            for idx, event in enumerate(calendar_events):
                status, _kind = self._calendar_status_label(event)
                title = " ".join(event.title.split())
                if len(title) > 60:
                    title = title[:59].rstrip() + "…"
                chunks.append(f"[{event.calendar_name}] {title} ({status})")
                if (idx + 1) % 2 == 0 and idx < len(calendar_events) - 1:
                    chunks.append(tr("TODAY EVENTS"))

        if not chunks:
            self.query_one("#ticker", Static).update(tr("Waiting for market data..."))
            return

        separator = " | " if mode == "calendar" else "   |   "
        line = separator.join(chunks)
        scroll = f"{line}   ||   {line}   ||   "
        if not scroll:
            return
        width = max(40, self.size.width - 6)
        start = self.ticker_offset % len(scroll)
        visible = (scroll + scroll)[start : start + width]
        palette = self._ui_palette()
        ticker_text = Text(visible, style=palette["text"])
        if mode == "quotes":
            for idx, ch in enumerate(visible):
                if ch == "▲":
                    ticker_text.stylize(palette["ok"], idx, idx + 1)
                elif ch == "▼":
                    ticker_text.stylize(palette["err"], idx, idx + 1)
        elif mode == "news":
            alert_style = palette["warn"] if self.heartbeat else palette["err"]
            token = "BREAKING NEWS"
            start = 0
            while True:
                pos = visible.find(token, start)
                if pos < 0:
                    break
                ticker_text.stylize(f"bold {alert_style}", pos, pos + len(token))
                start = pos + len(token)
        else:
            token = tr("LIVE ALERT")
            start = 0
            while True:
                pos = visible.find(token, start)
                if pos < 0:
                    break
                ticker_text.stylize(f"bold {palette['err']}", pos, pos + len(token))
                start = pos + len(token)
            alert_token = tr("TODAY EVENTS")
            start = 0
            blink_style = palette["warn"] if self.heartbeat else palette["err"]
            while True:
                pos = visible.find(alert_token, start)
                if pos < 0:
                    break
                ticker_text.stylize(f"bold {blink_style}", pos, pos + len(alert_token))
                start = pos + len(alert_token)
            # Highlight only the [CALENDAR_NAME] prefix with palette accent.
            name_token_re = re.compile(r"\[[^\]]+\]")
            for match in name_token_re.finditer(visible):
                ticker_text.stylize(f"bold {palette['accent']}", match.start(), match.end())
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
        if self.is_shutting_down:
            return
        self._spawn_background(self._refresh_news())

    def _schedule_calendar_refresh(self) -> None:
        if self.is_shutting_down:
            return
        self._spawn_background(self._refresh_calendar())

    async def _refresh_calendar(self) -> None:
        if not self.calendars:
            self._log(
                f"[{self._ui_palette()['warn']}]CALENDAR[/] "
                f"{tr('no calendars configured in config.yml')}"
            )
            return
        try:
            events = await asyncio.to_thread(
                fetch_calendar_events,
                self.calendars,
                CALENDAR_HORIZON_DAYS,
            )
            self.calendar_events = events
            self.calendar_last_update = datetime.now(self.local_tz).strftime("%H:%M")
            self._log(
                f"[{self._ui_palette()['accent']}]CALENDAR[/] refreshed {len(events)} events "
                f"from {len(self.calendars)} calendars (next {CALENDAR_HORIZON_DAYS}d)"
            )
        except Exception as exc:
            self._log(f"[{self._ui_palette()['warn']}]Calendar warning:[/] {exc!r}")

    def action_open_calendar(self) -> None:
        # Defer screen push to next refresh cycle to avoid collisions with
        # command-input submit/enter handling in the same event loop tick.
        self._log(
            f"[{self._ui_palette()['accent']}]CALENDAR[/] "
            f"{tr('opening calendar modal')}"
        )
        self.call_after_refresh(lambda: self.push_screen(CalendarModal(self._build_calendar_text)))

    def action_refresh_news(self) -> None:
        self._log("[#2ec4b6]NEWS[/] manual refresh requested")
        self._schedule_news_refresh()

    def action_quick_quit(self) -> None:
        if isinstance(self.screen, (ChartModal, ReadmeModal, CalendarModal)):
            self.screen.dismiss(None)
            return
        if not self.command_mode:
            self.exit()

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
        self.push_screen(ReadmeModal(self._load_readme_text()))

    def _load_readme_text(self) -> str:
        readme_path = Path(__file__).resolve().parent.parent / "README.md"
        header = (
            "README // Neon Quotes Terminal\n"
            "Scroll: ↑/↓ PgUp/PgDn Home/End | Close: Esc/Enter/q\n\n"
        )
        try:
            content = readme_path.read_text(encoding="utf-8")
        except Exception as exc:
            return header + f"Could not load README.md: {exc!r}\n"
        return header + content

    def action_open_chart(self) -> None:
        if isinstance(self.screen, ChartModal):
            self.screen.dismiss(None)
            return
        news_table = self.query_one("#news_table", DataTable)
        indicators_table = self.query_one("#indicators_table", DataTable)
        alerts_table = self.query_one("#stock_quotes", DataTable)
        main_table = self.query_one("#crypto_quotes", DataTable)
        if news_table.has_focus:
            row = news_table.cursor_row
            if row is not None:
                self._copy_news_link(int(row))
            return
        if indicators_table.has_focus:
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
        current = {"symbol": symbol, "type": symbol_type}

        def chart_builder(tf: str, candles: int) -> Text:
            return self._build_chart_for_item(current["symbol"], current["type"], tf, candles)

        async def ensure_history(tf: str, candles: int) -> None:
            await self._ensure_chart_history_for_item(current["symbol"], current["type"], tf, candles)

        def navigate(step: int) -> tuple[str, str] | None:
            nxt = self._advance_symbol_across_groups(current["symbol"], current["type"], step)
            if not nxt:
                return None
            current["symbol"], current["type"] = nxt
            return nxt

        if symbol_type == "stock":
            if symbol not in self.stock_data:
                self.stock_data[symbol] = StockState(symbol=symbol)
                self.stock_candles[symbol] = deque(maxlen=CANDLE_BUFFER_MAX)
                for tf in self.stock_candles_by_tf:
                    self.stock_candles_by_tf[tf].setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
            self.push_screen(
                ChartModal(
                    symbol=symbol,
                    symbol_type=symbol_type,
                    chart_builder=chart_builder,
                    ensure_history=ensure_history,
                    navigate_symbol=navigate,
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
                symbol_type=symbol_type,
                chart_builder=chart_builder,
                ensure_history=ensure_history,
                navigate_symbol=navigate,
            )
        )

    def _build_chart_for_item(
        self, symbol: str, symbol_type: str, timeframe: str, target_candles: int
    ) -> Text:
        if symbol_type == "stock":
            state = self.stock_data.get(symbol)
            if state is None:
                state = StockState(symbol=symbol)
                self.stock_data[symbol] = state
            return self._build_stock_chart_text(state, timeframe, target_candles)
        state = self.symbol_data.get(symbol)
        if state is None:
            state = SymbolState(symbol=symbol)
            self.symbol_data[symbol] = state
        return self._build_chart_text(state, timeframe, target_candles)

    async def _ensure_chart_history_for_item(
        self, symbol: str, symbol_type: str, timeframe: str, target_candles: int
    ) -> None:
        if symbol_type == "stock":
            await self._ensure_stock_chart_history(symbol, timeframe, target_candles)
            return
        await self._ensure_crypto_chart_history(symbol, timeframe, target_candles)

    def _flatten_group_items(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for _, items in self.main_group_items:
            for item in items:
                if item in seen:
                    continue
                seen.add(item)
                out.append(item)
        return out

    def _advance_symbol_across_groups(
        self, symbol: str, symbol_type: str, step: int
    ) -> tuple[str, str] | None:
        ordered = self._flatten_group_items()
        if not ordered:
            return None
        current = (symbol, symbol_type)
        try:
            idx = ordered.index(current)
        except ValueError:
            idx = 0
        nxt = ordered[(idx + step) % len(ordered)]

        for i, (_, items) in enumerate(self.main_group_items):
            if nxt in items:
                self.main_group_index = i
                self._pause_group_rotation("crypto_quotes", 60)
                self._update_main_group_panel()
                break
        return nxt

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
        if event.data_table.id == "indicators_table":
            return
        if event.data_table.id == "news_table":
            self._copy_news_link(event.cursor_row)

    async def _refresh_news(self) -> None:
        try:
            by_category = await asyncio.to_thread(fetch_all_news, NEWS_MAX_ITEMS)
            self.news_groups = self._build_news_groups(by_category)
            flat_items: list[NewsItem] = []
            for items in by_category.values():
                flat_items.extend(items)
            flat_items.sort(key=lambda item: self._news_age_minutes(item.age))
            self.news_latest_items = flat_items[:NEWS_TICKER_LIMIT]
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
        if time.time() < self.news_rotation_pause_until:
            return
        self.news_group_index = (self.news_group_index + 1) % len(self.news_groups)
        self._update_news_panel()

    def _rotate_main_group(self) -> None:
        if self.is_shutting_down:
            return
        if not self.main_group_items:
            return
        if time.time() < self.main_rotation_pause_until:
            return
        self.main_group_index = (self.main_group_index + 1) % len(self.main_group_items)
        self._update_main_group_panel()
        self._schedule_stock_refresh()
        self._spawn_background(self._refresh_crypto_stream_for_visible_group())
        if self.lazy_history_task and not self.lazy_history_task.done():
            self.lazy_history_task.cancel()
        self.lazy_history_task = self._spawn_background(self._load_remaining_history_in_background())

    def _rotate_indicator_group(self) -> None:
        if self.is_shutting_down:
            return
        if not self.indicator_group_items:
            return
        if time.time() < self.indicator_rotation_pause_until:
            return
        self.indicator_group_index = (self.indicator_group_index + 1) % len(self.indicator_group_items)
        self._update_indicators_panel()
        self._schedule_indicator_refresh()

    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None:
        until = time.time() + seconds
        if table_id == "crypto_quotes":
            self.main_rotation_pause_until = until
            return
        if table_id == "indicators_table":
            self.indicator_rotation_pause_until = until
            return
        if table_id == "news_table":
            self.news_rotation_pause_until = until

    def _cycle_main_group(self, step: int) -> None:
        if self.is_shutting_down:
            return
        if not self.main_group_items:
            return
        self.main_group_index = (self.main_group_index + step) % len(self.main_group_items)
        self._pause_group_rotation("crypto_quotes", 60)
        self._update_main_group_panel()
        self._schedule_stock_refresh()
        self._spawn_background(self._refresh_crypto_stream_for_visible_group())

    def _cycle_news_group(self, step: int) -> None:
        if not self.news_groups:
            return
        self.news_group_index = (self.news_group_index + step) % len(self.news_groups)
        self._pause_group_rotation("news_table", 60)
        self._update_news_panel()

    def _cycle_indicator_group(self, step: int) -> None:
        if not self.indicator_group_items:
            return
        self.indicator_group_index = (self.indicator_group_index + step) % len(self.indicator_group_items)
        self._pause_group_rotation("indicators_table", 60)
        self._update_indicators_panel()
        self._schedule_indicator_refresh()

    async def _refresh_crypto_stream_for_visible_group(self) -> None:
        desired = [s for s, t in self.main_visible_items if t == "crypto"]
        desired = [s.upper() for s in desired if s]
        current = [s.upper() for s in self.feed.symbols]
        if desired == current and self.feed_task is not None:
            return

        if self.feed_task:
            self.feed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.feed_task
            self.feed_task = None

        if not desired:
            self.status_text = "STOCKS ONLY"
            return

        self.feed = BinanceTickerFeed(desired)
        self.feed_task = asyncio.create_task(self._consume_feed())

    def _update_main_group_panel(self) -> None:
        table = self.query_one("#crypto_quotes", DataTable)
        if not self.main_group_items:
            self.main_visible_items = []
            self.main_row_item_by_index.clear()
            with contextlib.suppress(Exception):
                table.border_title = (
                    f" [{tr('group')} 0/0] "
                    f"[{tr('updated')} {self.stocks_last_update}] "
                )
            for i, row_key in enumerate(self.main_row_keys):
                table.update_cell(row_key, self.main_col_keys["symbol"], "-" if i == 0 else "")
                table.update_cell(row_key, self.main_col_keys["type"], "-")
                table.update_cell(row_key, self.main_col_keys["price"], "-")
                table.update_cell(row_key, self.main_col_keys["change"], "-")
                table.update_cell(row_key, self.main_col_keys["volume"], "-")
                table.update_cell(row_key, self.main_col_keys["spark"], "")
            return

        group_name, items = self.main_group_items[self.main_group_index]
        sorted_items = sorted(
            items,
            key=lambda item: self._get_change_percent(item[0], item[1]),
            reverse=True,
        )
        self.main_visible_items = sorted_items
        self.main_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" {group_name.upper()} "
                f"[{tr('group')} {self.main_group_index + 1}/{len(self.main_group_items)}] "
                f"[{tr('updated')} {self.stocks_last_update}] "
            )

        for i, row_key in enumerate(self.main_row_keys):
            if i < len(sorted_items):
                symbol, symbol_type = sorted_items[i]
                self.main_row_item_by_index[i] = (symbol, symbol_type)
                self._refresh_main_row(symbol, symbol_type)
                continue

            table.update_cell(row_key, self.main_col_keys["symbol"], "")
            table.update_cell(row_key, self.main_col_keys["type"], "")
            table.update_cell(row_key, self.main_col_keys["price"], "")
            table.update_cell(row_key, self.main_col_keys["change"], "")
            table.update_cell(row_key, self.main_col_keys["volume"], "")
            table.update_cell(row_key, self.main_col_keys["spark"], "")

    def _update_indicators_panel(self) -> None:
        table = self.query_one("#indicators_table", DataTable)
        if not self.indicator_group_items:
            self.indicator_visible_items = []
            self.indicator_row_item_by_index.clear()
            with contextlib.suppress(Exception):
                table.border_title = (
                    f" {tr('INDICATORS')} "
                    f"[{tr('group')} 0/0] "
                    f"[{tr('updated')} {self.indicators_last_update}] "
                )
            for i, row_key in enumerate(self.indicator_row_keys):
                table.update_cell(row_key, self.indicator_col_keys["symbol"], "-" if i == 0 else "")
                table.update_cell(row_key, self.indicator_col_keys["change"], "-")
                table.update_cell(row_key, self.indicator_col_keys["price"], "-")
            return

        group_name, items = self.indicator_group_items[self.indicator_group_index]
        sorted_items = sorted(
            items,
            key=lambda item: self.indicator_data.get(item[0], StockState(symbol=item[0])).change_percent,
            reverse=True,
        )
        self.indicator_visible_items = sorted_items
        self.indicator_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" {group_name.upper()} "
                f"[{tr('group')} {self.indicator_group_index + 1}/{len(self.indicator_group_items)}] "
                f"[{tr('updated')} {self.indicators_last_update}] "
            )

        for i, row_key in enumerate(self.indicator_row_keys):
            if i >= len(sorted_items):
                table.update_cell(row_key, self.indicator_col_keys["symbol"], "")
                table.update_cell(row_key, self.indicator_col_keys["change"], "")
                table.update_cell(row_key, self.indicator_col_keys["price"], "")
                continue

            symbol, symbol_type = sorted_items[i]
            self.indicator_row_item_by_index[i] = (symbol, symbol_type)
            state = self.indicator_data.get(symbol)
            if state is None:
                state = StockState(symbol=symbol)
                self.indicator_data[symbol] = state
            color = self._trend_color(state.change_percent >= 0, symbol_type="stock")
            table.update_cell(
                row_key,
                self.indicator_col_keys["symbol"],
                self._ticker_label(symbol, symbol_type, max_name_len=25),
            )
            table.update_cell(
                row_key,
                self.indicator_col_keys["change"],
                Text(f"{state.change_percent:>+8.2f}%", style=f"bold {color}"),
            )
            table.update_cell(
                row_key,
                self.indicator_col_keys["price"],
                Text(f"{state.price:>13,.2f}", style=color),
            )

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

        entries.sort(key=lambda item: item[2], reverse=True)
        top = entries[:ALERTS_TABLE_SIZE]
        self.alerts_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" {tr('ALERTAS')} "
                f"[{tr('updated')} {self.stocks_last_update}] "
            )

        for i, row_key in enumerate(self.alerts_row_keys):
            if i >= len(top):
                table.update_cell(row_key, self.alerts_col_keys["symbol"], "")
                table.update_cell(row_key, self.alerts_col_keys["type"], "")
                table.update_cell(row_key, self.alerts_col_keys["change"], "")
                table.update_cell(row_key, self.alerts_col_keys["price"], "")
                table.update_cell(row_key, self.alerts_col_keys["volume"], "")
                continue

            symbol, symbol_type, change_pct, price, volume = top[i]
            self.alerts_row_item_by_index[i] = (symbol, symbol_type)
            color = self._trend_color(change_pct >= 0, symbol_type=symbol_type)
            type_label = "CRT" if symbol_type == "crypto" else "STK"
            table.update_cell(row_key, self.alerts_col_keys["symbol"], self._ticker_label(symbol, symbol_type))
            table.update_cell(row_key, self.alerts_col_keys["type"], type_label)
            table.update_cell(
                row_key,
                self.alerts_col_keys["change"],
                Text(f"{change_pct:>+8.2f}%", style=f"bold {color}"),
            )
            table.update_cell(
                row_key,
                self.alerts_col_keys["price"],
                Text(f"{price:>13,.2f}", style=color),
            )
            table.update_cell(row_key, self.alerts_col_keys["volume"], self._format_volume(volume, 17))

    def _get_change_percent(self, symbol: str, symbol_type: str) -> float:
        if symbol_type == "crypto":
            state = self.symbol_data.get(symbol)
            return state.change_percent if state is not None else -9999.0
        state = self.stock_data.get(symbol)
        return state.change_percent if state is not None else -9999.0

    def _current_visible_symbols(self) -> tuple[list[str], list[str]]:
        visible_crypto = [s for s, t in self.main_visible_items if t == "crypto"]
        visible_stock = [s for s, t in self.main_visible_items if t == "stock"]
        return visible_crypto, visible_stock

    async def _preload_visible_group_history(self) -> None:
        visible_crypto, visible_stock = self._current_visible_symbols()
        visible_crypto = visible_crypto or self.crypto_symbols[:10]
        visible_stock = visible_stock or self.stock_symbols[:10]
        total = len(visible_crypto) + len(visible_stock)
        if self.boot_modal:
            self.boot_modal.set_total(max(1, total))
            self.boot_modal.set_phase(tr("Syncing crypto history"))

        # 1) Instant load from cache when available.
        cache_hits = 0
        for symbol in visible_crypto:
            cached = load_symbol_history_cache(symbol, "crypto", CACHE_TTL_SECONDS)
            if not cached:
                continue
            closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
            candles = [
                (int(ts), float(o), float(h), float(l), float(c))
                for ts, o, h, l, c in cached.get("candles", [])
            ]
            self._seed_symbol_history(symbol, closes[-INITIAL_HISTORY_POINTS:], candles[-INITIAL_CANDLE_LIMIT:])
            cache_hits += 1
        for symbol in visible_stock:
            cached = load_symbol_history_cache(symbol, "stock", CACHE_TTL_SECONDS)
            if not cached:
                continue
            closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
            candles = [
                (int(ts), float(o), float(h), float(l), float(c))
                for ts, o, h, l, c in cached.get("candles", [])
            ]
            self._seed_stock_history(symbol, closes[-INITIAL_HISTORY_POINTS:], candles[-INITIAL_CANDLE_LIMIT:])
            cache_hits += 1

        if cache_hits:
            self._log(f"[#2ec4b6]CACHE[/] loaded {cache_hits} symbol histories")

        # 2) Remote refresh for visible symbols with concurrency limit.
        sem = asyncio.Semaphore(STARTUP_IO_CONCURRENCY)

        async def fetch_crypto(symbol: str) -> None:
            async with sem:
                try:
                    closes = await asyncio.to_thread(
                        self.feed.fetch_recent_closes, symbol, INITIAL_HISTORY_POINTS
                    )
                    candles = await asyncio.to_thread(
                        self.feed.fetch_recent_15m_ohlc, symbol, INITIAL_CANDLE_LIMIT
                    )
                    self._seed_symbol_history(symbol, closes, candles)
                    await asyncio.to_thread(
                        save_symbol_history_cache,
                        symbol,
                        "crypto",
                        closes=closes,
                        candles=candles,
                    )
                except Exception as exc:
                    self._log(f"[yellow]History warning {symbol}:[/] {exc!r}")
                finally:
                    if self.boot_modal:
                        self.boot_modal.increment()

        async def fetch_stock(symbol: str) -> None:
            async with sem:
                try:
                    closes, candles = await asyncio.to_thread(
                        fetch_stock_history,
                        symbol,
                        INITIAL_HISTORY_POINTS,
                        INITIAL_CANDLE_LIMIT,
                    )
                    self._seed_stock_history(symbol, closes, candles)
                    await asyncio.to_thread(
                        save_symbol_history_cache,
                        symbol,
                        "stock",
                        closes=closes,
                        candles=candles,
                    )
                except Exception as exc:
                    self._log(f"[yellow]Stock history warning {symbol}:[/] {exc!r}")
                finally:
                    if self.boot_modal:
                        self.boot_modal.increment()

        tasks = [asyncio.create_task(fetch_crypto(s)) for s in visible_crypto]
        tasks.extend(asyncio.create_task(fetch_stock(s)) for s in visible_stock)
        if tasks:
            await asyncio.gather(*tasks)
        self._update_main_group_panel()
        self._update_alerts_panel()
        self._log("[#2ec4b6]HISTORY[/] visible group preload complete")

    async def _load_remaining_history_in_background(self) -> None:
        # Lazy fill for symbols outside the visible window.
        visible_crypto, visible_stock = self._current_visible_symbols()
        remaining_crypto = [s for s in self.crypto_symbols if s not in set(visible_crypto)]
        remaining_stock = [s for s in self.stock_symbols if s not in set(visible_stock)]
        if not remaining_crypto and not remaining_stock:
            return

        self._log(
            f"[#6f8aa8]HISTORY[/] lazy background load started "
            f"(crypto={len(remaining_crypto)} stock={len(remaining_stock)})"
        )
        sem = asyncio.Semaphore(STARTUP_IO_CONCURRENCY)

        async def fill_crypto(symbol: str) -> None:
            cached = load_symbol_history_cache(symbol, "crypto", CACHE_TTL_SECONDS)
            if cached:
                closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
                candles = [
                    (int(ts), float(o), float(h), float(l), float(c))
                    for ts, o, h, l, c in cached.get("candles", [])
                ]
                self._seed_symbol_history(symbol, closes[-INITIAL_HISTORY_POINTS:], candles[-INITIAL_CANDLE_LIMIT:])
                return
            async with sem:
                try:
                    closes = await asyncio.to_thread(
                        self.feed.fetch_recent_closes, symbol, INITIAL_HISTORY_POINTS
                    )
                    candles = await asyncio.to_thread(
                        self.feed.fetch_recent_15m_ohlc, symbol, INITIAL_CANDLE_LIMIT
                    )
                    self._seed_symbol_history(symbol, closes, candles)
                    await asyncio.to_thread(
                        save_symbol_history_cache,
                        symbol,
                        "crypto",
                        closes=closes,
                        candles=candles,
                    )
                except Exception:
                    return

        async def fill_stock(symbol: str) -> None:
            cached = load_symbol_history_cache(symbol, "stock", CACHE_TTL_SECONDS)
            if cached:
                closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
                candles = [
                    (int(ts), float(o), float(h), float(l), float(c))
                    for ts, o, h, l, c in cached.get("candles", [])
                ]
                self._seed_stock_history(symbol, closes[-INITIAL_HISTORY_POINTS:], candles[-INITIAL_CANDLE_LIMIT:])
                return
            async with sem:
                try:
                    closes, candles = await asyncio.to_thread(
                        fetch_stock_history,
                        symbol,
                        INITIAL_HISTORY_POINTS,
                        INITIAL_CANDLE_LIMIT,
                    )
                    self._seed_stock_history(symbol, closes, candles)
                    await asyncio.to_thread(
                        save_symbol_history_cache,
                        symbol,
                        "stock",
                        closes=closes,
                        candles=candles,
                    )
                except Exception:
                    return

        tasks = [asyncio.create_task(fill_crypto(s)) for s in remaining_crypto]
        tasks.extend(asyncio.create_task(fill_stock(s)) for s in remaining_stock)
        if tasks:
            await asyncio.gather(*tasks)
        self._log("[#6f8aa8]HISTORY[/] lazy background load completed")

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
        if self.is_shutting_down:
            return
        self._spawn_background(self._refresh_stocks())

    def _schedule_indicator_refresh(self) -> None:
        if self.is_shutting_down:
            return
        self._spawn_background(self._refresh_indicators())

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

    async def _refresh_indicators(self) -> None:
        if not self.indicator_symbols:
            return
        visible_symbols = [s for s, _ in self.indicator_visible_items]
        symbols_to_refresh = visible_symbols or self.indicator_symbols
        if not symbols_to_refresh:
            return
        try:
            quotes = await asyncio.to_thread(fetch_stock_quotes, symbols_to_refresh)
            for quote in quotes:
                state = self.indicator_data.get(quote.symbol)
                if state is None:
                    state = StockState(symbol=quote.symbol)
                    self.indicator_data[quote.symbol] = state
                state.price = quote.price
                state.change_percent = quote.change_percent
                state.volume = quote.volume
                state.last_update_ms = quote.event_time_ms
            self.indicators_last_update = datetime.now(self.local_tz).strftime("%H:%M")
            self._update_indicators_panel()
            self._log(
                f"[#2ec4b6]{tr('INDICATORS')}[/] refreshed {len(quotes)} symbols "
                f"({len(symbols_to_refresh)} in active group)"
            )
        except Exception as exc:
            self._log(f"[yellow]{tr('INDICATORS')} warning:[/] {exc!r}")

    async def _ensure_crypto_chart_history(
        self, symbol: str, timeframe: str, target_candles: int
    ) -> None:
        series = self._get_crypto_series(symbol, timeframe)
        if series is None:
            return
        required = min(CANDLE_BUFFER_MAX, max(CHART_HISTORY_POINTS, target_candles + 24))
        if len(series) >= required:
            # Ensure line chart has enough points as well.
            state = self.symbol_data.get(symbol)
            if state is not None and state.points is not None and len(state.points) >= CHART_HISTORY_POINTS:
                return

        candles_raw = await asyncio.to_thread(self.feed.fetch_recent_ohlc, symbol, timeframe, required)
        if candles_raw:
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
            else:
                self.crypto_candles_by_tf[timeframe][symbol] = fresh

        if timeframe == "15m":
            closes = await asyncio.to_thread(self.feed.fetch_recent_closes, symbol, CHART_HISTORY_POINTS)
            if closes:
                state = self.symbol_data.get(symbol)
                if state is not None and state.points is not None:
                    state.points.clear()
                    for _, close_price in closes[-MAX_POINTS:]:
                        state.points.append(close_price)
                candles_for_cache = [
                    (c.bucket_ms, c.open, c.high, c.low, c.close)
                    for c in list(self.candles.get(symbol, deque()))[-CHART_HISTORY_POINTS:]
                ]
                await asyncio.to_thread(
                    save_symbol_history_cache,
                    symbol,
                    "crypto",
                    closes=closes[-CHART_HISTORY_POINTS:],
                    candles=candles_for_cache,
                )

    async def _ensure_stock_chart_history(
        self, symbol: str, timeframe: str, target_candles: int
    ) -> None:
        series = self._get_stock_series(symbol, timeframe)
        if series is None:
            return
        required = min(CANDLE_BUFFER_MAX, max(CHART_HISTORY_POINTS, target_candles + 24))
        if len(series) >= required:
            state = self.stock_data.get(symbol)
            if state is not None and state.points is not None and len(state.points) >= CHART_HISTORY_POINTS:
                return

        candles_raw = await asyncio.to_thread(fetch_stock_candles_timeframe, symbol, timeframe, required)
        if candles_raw:
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
            else:
                self.stock_candles_by_tf[timeframe][symbol] = fresh

        if timeframe == "15m":
            closes, _ = await asyncio.to_thread(
                fetch_stock_history, symbol, CHART_HISTORY_POINTS, INITIAL_CANDLE_LIMIT
            )
            if closes:
                state = self.stock_data.get(symbol)
                if state is not None and state.points is not None:
                    state.points.clear()
                    for _, close_price in closes[-MAX_POINTS:]:
                        state.points.append(close_price)
                candles_for_cache = [
                    (c.bucket_ms, c.open, c.high, c.low, c.close)
                    for c in list(self.stock_candles.get(symbol, deque()))[-CHART_HISTORY_POINTS:]
                ]
                await asyncio.to_thread(
                    save_symbol_history_cache,
                    symbol,
                    "stock",
                    closes=closes[-CHART_HISTORY_POINTS:],
                    candles=candles_for_cache,
                )

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
            header.update(Text("NEWS // finviz.com (refresh 10m)", style=self._ui_palette()["accent"]))
            self.news_row_links.clear()
            for i in range(NEWS_GROUP_SIZE):
                row_key = self.news_row_keys[i]
                table.update_cell(
                    row_key,
                    self.news_col_keys["title"],
                    Text(tr("No headlines available\nTry refresh [n]\n")),
                )
            return

        category, items = self.news_groups[self.news_group_index]
        palette = self._ui_palette()
        title_style = palette["ok"] if "CRYPTO" in category else palette["warn"] if "STOCK" in category else palette["accent"]
        header_txt = Text()
        header_txt.append(f"{category} // ", style=f"bold {title_style}")
        header_txt.append("finviz.com", style=palette["accent"])
        header_txt.append(f" (refresh {NEWS_REFRESH_SECONDS // 60}m) ", style=palette["muted"])
        header_txt.append(
            f"[group {self.news_group_index + 1}/{len(self.news_groups)} | updated {self.news_last_update}]",
            style=palette["muted"],
        )
        header.update(header_txt)

        self.news_row_links.clear()
        for i in range(NEWS_GROUP_SIZE):
            row_key = self.news_row_keys[i]
            if i < len(items):
                item = items[i]
                self.news_row_links[i] = item.url
                source = (item.source or "source").strip()
                age = (item.age or "-").strip()
                table.update_cell(
                    row_key,
                    self.news_col_keys["title"],
                    self._format_news_headline(
                        source=source,
                        age=age,
                        title=item.title,
                        line_len=72,
                    ),
                )
            else:
                table.update_cell(row_key, self.news_col_keys["title"], Text("\n\n"))

    def _format_news_headline(self, source: str, age: str, title: str, line_len: int = 86) -> Text:
        palette = self._news_palette()
        clean_source = (source.strip() or "source")[:20]
        clean_age = (age.strip() or "-")[:12]
        age_lower = clean_age.lower()
        show_fire = age_lower == "now"
        words = (title or "").split() or ["-"]
        per_line = max(12, line_len)

        body_lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= per_line:
                current = candidate
                continue
            body_lines.append(current or word[:per_line])
            current = word if len(word) <= per_line else word[:per_line]
        if current:
            body_lines.append(current)

        while len(body_lines) < 2:
            body_lines.append("")
        if len(body_lines) > 2:
            body_lines = body_lines[:2]
            body_lines[1] = (body_lines[1][: max(0, per_line - 1)] + "…").rstrip()

        age_style = palette["age_old"]
        if "now" in age_lower:
            age_style = palette["age_now"]
        elif "min" in age_lower or "hour" in age_lower:
            age_style = palette["age_recent"]

        text = Text()
        text.append("[", style=palette["bracket"])
        text.append(clean_source, style=palette["source"])
        text.append(": ", style=palette["bracket"])
        text.append(clean_age, style=age_style)
        if show_fire:
            text.append(" ", style=palette["bracket"])
            text.append("🔥", style=palette["fire"])
        text.append("]", style=palette["bracket"])
        body_color = self._ui_palette()["text"]
        text.append("\n", style=body_color)
        text.append(body_lines[0], style=body_color)
        text.append("\n", style=body_color)
        text.append(body_lines[1], style=body_color)
        return text

    def _news_palette(self) -> dict[str, str]:
        theme = self.app.current_theme
        return {
            "bracket": theme.secondary or theme.primary or "#6f8aa8",
            "source": theme.accent or theme.primary or "#8ad9ff",
            "age_now": theme.success or theme.primary or "#00ffae",
            "age_recent": theme.warning or theme.primary or "#ffcf5c",
            "age_old": theme.foreground or theme.primary or "#7aa3c5",
            "fire": theme.error or theme.warning or theme.primary or "#ff7a00",
        }

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
        self._tab_cycle_key = None
        self._tab_cycle_index = -1
        self._log(f"[{self._ui_palette()['warn']}]COMMAND[/] {tr('COMMAND mode enabled')}")
        command_input = self.query_one("#command_input", Input)
        command_input.display = True
        command_input.value = ":"
        command_input.focus()
        self._render_status_line()

    def _exit_command_mode(self) -> None:
        self.command_mode = False
        self.command_buffer = ""
        self._tab_cycle_key = None
        self._tab_cycle_index = -1
        self._log(f"[{self._ui_palette()['warn']}]COMMAND[/] {tr('COMMAND mode disabled')}")
        command_input = self.query_one("#command_input", Input)
        command_input.value = ""
        command_input.display = False
        self.query_one("#crypto_quotes", DataTable).focus()
        self._render_status_line()

    def _render_status_line(self) -> None:
        palette = self._ui_palette()
        line = self.query_one("#status_line", Static)

        if self.command_mode:
            left = (
                f":{self.command_buffer}█ | [Enter] {tr('run')} | [Esc] {tr('normal')} | "
                f"q {tr('quit')} | r {tr('reset')} | n {tr('news')} | ? {tr('help')} | "
                "c calendar | add/del/mv/edit"
            )
            right = tr("status: enter command")
            right_style = palette["warn"]
        else:
            left = (
                f":|f2 {tr('Cmd')} | q {tr('quit')} | [enter] {tr('chart')} | "
                f"? {tr('help')} | ⌃P palette | < {tr('previous group')} | > {tr('next group')}"
            )
            right = tr("status: normal")
            right_style = palette["ok"]

        total_width = max(40, self.size.width - 2)
        max_left = max(1, total_width - len(right) - 1)
        if len(left) > max_left:
            left = left[:max_left] if max_left <= 1 else (left[: max_left - 1] + "…")
        spaces = max(1, total_width - len(left) - len(right))
        txt = Text()
        txt.append(left, style=palette["text"])
        txt.append(" " * spaces, style=palette["muted"])
        txt.append(right, style=f"bold {right_style}")
        line.update(txt)

    @staticmethod
    def _quote_token(value: str) -> str:
        if not value:
            return value
        if any(ch.isspace() for ch in value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value

    @staticmethod
    def _token_starts_with(candidate: str, partial: str) -> bool:
        raw = candidate.strip()
        normalized = raw.strip('"').strip("'")
        probe = (partial or "").strip()
        if not probe:
            return True
        cf = probe.casefold()
        return raw.casefold().startswith(cf) or normalized.casefold().startswith(cf)

    @staticmethod
    def _token_equals(candidate: str, partial: str) -> bool:
        raw = candidate.strip()
        normalized = raw.strip('"').strip("'")
        probe = (partial or "").strip()
        if not probe:
            return False
        cf = probe.casefold()
        return raw.casefold() == cf or normalized.casefold() == cf

    def _command_slot_candidates(self, committed: list[str]) -> list[str]:
        commands = ["q", "r", "n", "c", "calendar", "?", "add", "del", "mv", "edit"]
        if not committed:
            return commands
        cmd = committed[0].lower()
        target_index = len(committed)
        if cmd == "c" and target_index == 1:
            return ["calendar"]
        if cmd in {"del", "mv", "edit"} and target_index == 1:
            return self._all_configured_symbols()
        if cmd == "add" and target_index == 2:
            return ["crypto", "stock"]
        if cmd in {"add", "mv"} and target_index == 2 + (1 if cmd == "add" else 0):
            groups = [self._quote_token(str(g.get("name") or "").strip()) for g in self.market_groups]
            return [g for g in groups if g]
        if cmd == "edit" and target_index >= 2:
            return ["group=", "type=", "name="]
        return []

    def _all_configured_symbols(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for _, items in self.main_group_items:
            for symbol, _ in items:
                if symbol not in seen:
                    seen.add(symbol)
                    out.append(symbol)
        return out

    def _command_completion_candidates(
        self,
        committed: list[str],
        current_partial: str,
    ) -> list[str]:
        slot = self._command_slot_candidates(committed)
        return [value for value in slot if self._token_starts_with(value, current_partial)]

    def autocomplete_command_input(self) -> None:
        if not self.command_mode:
            return
        command_input = self.query_one("#command_input", Input)
        raw_value = command_input.value or ""
        if raw_value.startswith(":"):
            raw_value = raw_value[1:]
        ends_space = bool(raw_value) and raw_value[-1].isspace()
        try:
            tokens = shlex.split(raw_value)
        except ValueError:
            tokens = raw_value.split()
        current_partial = ""
        committed = list(tokens)
        if not ends_space and tokens:
            current_partial = tokens[-1]
            committed = tokens[:-1]

        slot_candidates = self._command_slot_candidates(committed)
        filtered_candidates = [c for c in slot_candidates if self._token_starts_with(c, current_partial)]
        if (
            len(slot_candidates) > 1
            and current_partial
            and any(self._token_equals(c, current_partial) for c in slot_candidates)
        ):
            candidates = slot_candidates
        else:
            candidates = filtered_candidates

        if not candidates:
            self._log("[#6f8aa8]COMMAND[/] no completion candidates")
            self._tab_cycle_key = None
            self._tab_cycle_index = -1
            return

        next_token = ""
        add_trailing_space = False
        if len(candidates) == 1:
            next_token = candidates[0]
            add_trailing_space = True
            self._tab_cycle_key = None
            self._tab_cycle_index = -1
        else:
            cycle_key = (tuple(committed), tuple(candidates))
            if self._tab_cycle_key == cycle_key:
                idx = (self._tab_cycle_index + 1) % len(candidates)
            else:
                idx = 0
                for i, cand in enumerate(candidates):
                    if self._token_equals(cand, current_partial):
                        idx = (i + 1) % len(candidates)
                        break
            self._tab_cycle_key = cycle_key
            self._tab_cycle_index = idx
            next_token = candidates[idx]
            preview = ", ".join(candidates[:8])
            if len(candidates) > 8:
                preview += ", …"
            self._log(f"[#6f8aa8]COMMAND[/] suggestions: {preview}")

        rebuilt = list(committed)
        rebuilt.append(next_token)
        suffix = " " if add_trailing_space else ""
        command_input.value = ":" + " ".join(rebuilt) + suffix
        self.command_buffer = command_input.value[1:]
        self._render_status_line()

    @staticmethod
    def _normalize_symbol_type(symbol: str, symbol_type: str) -> str:
        st = (symbol_type or "").strip().lower()
        if st in {"crypto", "stock"}:
            return st
        return "crypto" if symbol.upper().endswith("USDT") else "stock"

    def _find_group_index(self, group_name: str) -> int | None:
        wanted = (group_name or "").strip().casefold()
        if not wanted:
            return None
        for idx, group in enumerate(self.market_groups):
            name = str(group.get("name") or "").strip().casefold()
            if name == wanted:
                return idx
        return None

    def _find_symbol_entry(self, symbol: str) -> tuple[int, int, dict[str, Any]] | None:
        needle = (symbol or "").strip().upper()
        if not needle:
            return None
        for group_idx, group in enumerate(self.market_groups):
            symbols = group.get("symbols")
            if not isinstance(symbols, list):
                continue
            for item_idx, item in enumerate(symbols):
                if not isinstance(item, dict):
                    continue
                value = str(item.get("symbol") or "").strip().upper()
                if value == needle:
                    return group_idx, item_idx, item
        return None

    def _yaml_quote(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _serialize_config_yaml(self) -> str:
        lines: list[str] = []
        lines.append(f"config_name: {self._yaml_quote(self.config_name)}")
        lines.append(f"timezone: {self._yaml_quote(self.timezone)}")
        lines.append(f"language: {self._yaml_quote(self.language)}")
        lines.append("quick_actions:")
        for key in ("1", "2", "3"):
            value = str(self.quick_actions.get(key) or "").strip()
            lines.append(f"  {self._yaml_quote(key)}: {self._yaml_quote(value)}")

        lines.append("calendars:")
        for item in self.calendars:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            source = str(item.get("source") or "forexfactory").strip().lower()
            region = str(item.get("region") or "GLOBAL").strip()
            enabled = bool(item.get("enabled", True))
            duration = int(item.get("default_duration_min") or 60)
            if duration <= 0:
                duration = 60
            lines.append(f"- name: {self._yaml_quote(name)}")
            lines.append(f"  source: {self._yaml_quote(source)}")
            lines.append(f"  region: {self._yaml_quote(region)}")
            lines.append(f"  enabled: {'true' if enabled else 'false'}")
            lines.append(f"  default_duration_min: {duration}")

        lines.append("indicator_groups:")
        for group in self.indicator_groups:
            name = str(group.get("name") or "").strip()
            lines.append(f"- name: {self._yaml_quote(name)}")
            lines.append("  symbols:")
            for item in group.get("symbols", []):
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").strip().upper()
                symbol_type = self._normalize_symbol_type(symbol, str(item.get("type") or "stock"))
                if not symbol:
                    continue
                lines.append(f"  - symbol: {self._yaml_quote(symbol)}")
                lines.append(f"    type: {self._yaml_quote(symbol_type)}")
                name_value = str(item.get("name") or "").strip()
                if name_value:
                    lines.append(f"    name: {self._yaml_quote(name_value)}")

        lines.append("groups:")
        for group in self.market_groups:
            name = str(group.get("name") or "").strip()
            lines.append(f"- name: {self._yaml_quote(name)}")
            lines.append("  symbols:")
            for item in group.get("symbols", []):
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").strip().upper()
                symbol_type = self._normalize_symbol_type(symbol, str(item.get("type") or "stock"))
                if not symbol:
                    continue
                lines.append(f"  - symbol: {self._yaml_quote(symbol)}")
                lines.append(f"    type: {self._yaml_quote(symbol_type)}")
                name_value = str(item.get("name") or "").strip()
                if name_value:
                    lines.append(f"    name: {self._yaml_quote(name_value)}")
        return "\n".join(lines) + "\n"

    def _persist_config(self) -> bool:
        path = Path(self.config_path)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        payload = self._serialize_config_yaml()
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)
            return True
        except Exception:
            with contextlib.suppress(Exception):
                if tmp_path.exists():
                    tmp_path.unlink()
            return False

    def _ensure_main_row_capacity(self, required_rows: int) -> None:
        table = self.query_one("#crypto_quotes", DataTable)
        while len(self.main_row_keys) < required_rows:
            idx = len(self.main_row_keys)
            row_key = table.add_row("-", "-", "-", "-", "-", "", key=f"main_{idx}")
            self.main_row_keys.append(row_key)

    def _sync_market_data_structures(self) -> None:
        crypto_symbols: list[str] = []
        stock_symbols: list[str] = []
        seen_crypto: set[str] = set()
        seen_stock: set[str] = set()
        for _, items in self.main_group_items:
            for symbol, symbol_type in items:
                if symbol_type == "crypto":
                    if symbol not in seen_crypto:
                        seen_crypto.add(symbol)
                        crypto_symbols.append(symbol)
                else:
                    if symbol not in seen_stock:
                        seen_stock.add(symbol)
                        stock_symbols.append(symbol)

        self.crypto_symbols = crypto_symbols
        self.stock_symbols = stock_symbols

        for symbol in self.crypto_symbols:
            self.symbol_data.setdefault(symbol, SymbolState(symbol=symbol))
            self.candles.setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
            for tf in self.crypto_candles_by_tf:
                self.crypto_candles_by_tf[tf].setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
        for symbol in list(self.symbol_data):
            if symbol not in seen_crypto:
                self.symbol_data.pop(symbol, None)
                self.candles.pop(symbol, None)
                for tf in self.crypto_candles_by_tf:
                    self.crypto_candles_by_tf[tf].pop(symbol, None)

        for symbol in self.stock_symbols:
            self.stock_data.setdefault(symbol, StockState(symbol=symbol))
            self.stock_candles.setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
            for tf in self.stock_candles_by_tf:
                self.stock_candles_by_tf[tf].setdefault(symbol, deque(maxlen=CANDLE_BUFFER_MAX))
        for symbol in list(self.stock_data):
            if symbol not in seen_stock:
                self.stock_data.pop(symbol, None)
                self.stock_candles.pop(symbol, None)
                for tf in self.stock_candles_by_tf:
                    self.stock_candles_by_tf[tf].pop(symbol, None)

    def _apply_market_groups_change(self, resolve_missing_names: bool = False) -> None:
        self.main_group_items = self._build_main_groups()
        self._sync_market_data_structures()
        if self.main_group_items:
            self.main_group_index %= len(self.main_group_items)
            required = max(1, max(len(items) for _, items in self.main_group_items))
        else:
            self.main_group_index = 0
            required = 1
        self._ensure_main_row_capacity(required)
        self._update_main_group_panel()
        self._update_alerts_panel()
        self._spawn_background(self._refresh_crypto_stream_for_visible_group())
        self._schedule_stock_refresh()
        if resolve_missing_names:
            if self.name_resolve_task and not self.name_resolve_task.done():
                self.name_resolve_task.cancel()
            self.name_resolve_task = self._spawn_background(self._resolve_names_background())

    def _clear_quick_actions_for_symbol(self, symbol: str) -> None:
        removed: list[str] = []
        for key in ("1", "2", "3"):
            if self.quick_actions.get(key, "").upper() == symbol.upper():
                self.quick_actions[key] = ""
                removed.append(key)
        if removed:
            self._log(
                f"[#ffcf5c]CONFIG[/] quick actions cleared for {symbol}: "
                f"{', '.join(removed)}"
            )

    def _cmd_add_symbol(self, tokens: list[str]) -> None:
        if len(tokens) < 4:
            self._log("[yellow]Usage:[/] :add <symbol> <crypto|stock> <group> [name]")
            return
        symbol = tokens[1].strip().upper()
        symbol_type = self._normalize_symbol_type(symbol, tokens[2])
        group_name = tokens[3].strip()
        name = " ".join(tokens[4:]).strip()
        if symbol_type not in {"crypto", "stock"}:
            self._log("[yellow]Add failed:[/] type must be crypto or stock")
            return
        if not symbol or not group_name:
            self._log("[yellow]Add failed:[/] symbol and group are required")
            return
        if self._find_symbol_entry(symbol):
            self._log(f"[yellow]Add failed:[/] symbol already exists: {symbol}")
            return
        group_idx = self._find_group_index(group_name)
        if group_idx is None:
            self._log(f"[yellow]Add failed:[/] group not found: {group_name}")
            return
        item: dict[str, str] = {"symbol": symbol, "type": symbol_type}
        if name:
            item["name"] = name
            self.symbol_names[(symbol, symbol_type)] = name
        symbols = self.market_groups[group_idx].setdefault("symbols", [])
        if not isinstance(symbols, list):
            self._log(f"[yellow]Add failed:[/] invalid group schema: {group_name}")
            return
        symbols.append(item)
        self._apply_market_groups_change(resolve_missing_names=not bool(name))
        if not self._persist_config():
            self._log("[yellow]Add warning:[/] could not persist config.yml")
            return
        self._log(f"[#2ec4b6]CONFIG[/] added {symbol} ({symbol_type}) to group '{group_name}'")

    def _cmd_del_symbol(self, tokens: list[str]) -> None:
        if len(tokens) != 2:
            self._log("[yellow]Usage:[/] :del <symbol>")
            return
        symbol = tokens[1].strip().upper()
        found = self._find_symbol_entry(symbol)
        if not found:
            self._log(f"[yellow]Delete failed:[/] symbol not found: {symbol}")
            return
        group_idx, item_idx, item = found
        group_name = str(self.market_groups[group_idx].get("name") or "")
        symbols = self.market_groups[group_idx].get("symbols")
        if not isinstance(symbols, list):
            self._log("[yellow]Delete failed:[/] invalid group schema")
            return
        item_type = self._normalize_symbol_type(symbol, str(item.get("type") or ""))
        symbols.pop(item_idx)
        if not symbols:
            self.market_groups.pop(group_idx)
            self._log(f"[#6f8aa8]CONFIG[/] removed empty group '{group_name}'")
        self.symbol_names.pop((symbol, item_type), None)
        self._clear_quick_actions_for_symbol(symbol)
        self._apply_market_groups_change(resolve_missing_names=False)
        if not self._persist_config():
            self._log("[yellow]Delete warning:[/] could not persist config.yml")
            return
        self._log(f"[#2ec4b6]CONFIG[/] deleted {symbol} from group '{group_name}'")

    def _cmd_move_symbol(self, tokens: list[str]) -> None:
        if len(tokens) < 3:
            self._log("[yellow]Usage:[/] :mv <symbol> <group>")
            return
        symbol = tokens[1].strip().upper()
        destination_name = " ".join(tokens[2:]).strip()
        found = self._find_symbol_entry(symbol)
        if not found:
            self._log(f"[yellow]Move failed:[/] symbol not found: {symbol}")
            return
        from_group_idx, item_idx, item = found
        to_group_idx = self._find_group_index(destination_name)
        if to_group_idx is None:
            self._log(f"[yellow]Move failed:[/] destination group not found: {destination_name}")
            return
        if to_group_idx == from_group_idx:
            self._log(f"[#6f8aa8]CONFIG[/] {symbol} already in group '{destination_name}'")
            return

        source_name = str(self.market_groups[from_group_idx].get("name") or "")
        symbols_src = self.market_groups[from_group_idx].get("symbols")
        symbols_dst = self.market_groups[to_group_idx].setdefault("symbols", [])
        if not isinstance(symbols_src, list) or not isinstance(symbols_dst, list):
            self._log("[yellow]Move failed:[/] invalid group schema")
            return
        moved = dict(item)
        symbols_src.pop(item_idx)
        symbols_dst.append(moved)
        if not symbols_src:
            if from_group_idx < to_group_idx:
                to_group_idx -= 1
            self.market_groups.pop(from_group_idx)
            self._log(f"[#6f8aa8]CONFIG[/] removed empty group '{source_name}'")
        self._apply_market_groups_change(resolve_missing_names=False)
        if not self._persist_config():
            self._log("[yellow]Move warning:[/] could not persist config.yml")
            return
        self._log(
            f"[#2ec4b6]CONFIG[/] moved {symbol} from '{source_name}' to '{destination_name}'"
        )

    def _cmd_edit_symbol(self, tokens: list[str]) -> None:
        if len(tokens) < 3:
            self._log("[yellow]Usage:[/] :edit <symbol> group=<name> type=<crypto|stock> name=<label>")
            return
        symbol = tokens[1].strip().upper()
        found = self._find_symbol_entry(symbol)
        if not found:
            self._log(f"[yellow]Edit failed:[/] symbol not found: {symbol}")
            return
        group_idx, item_idx, item = found
        updates: dict[str, str] = {}
        for part in tokens[2:]:
            if "=" not in part:
                self._log(f"[yellow]Edit failed:[/] invalid token '{part}', expected key=value")
                return
            key, value = part.split("=", 1)
            k = key.strip().lower()
            v = value.strip()
            if k not in {"group", "type", "name"}:
                self._log(f"[yellow]Edit failed:[/] unsupported field '{k}'")
                return
            updates[k] = v
        destination_group = updates.get("group")
        if destination_group:
            dest_idx = self._find_group_index(destination_group)
            if dest_idx is None:
                self._log(f"[yellow]Edit failed:[/] group not found: {destination_group}")
                return
        new_type = updates.get("type")
        if new_type and self._normalize_symbol_type(symbol, new_type) not in {"crypto", "stock"}:
            self._log("[yellow]Edit failed:[/] type must be crypto or stock")
            return

        resolve_names = False
        if "type" in updates:
            normalized = self._normalize_symbol_type(symbol, updates["type"])
            item["type"] = normalized
        if "name" in updates:
            name_value = updates["name"].strip()
            if name_value:
                item["name"] = name_value
                self.symbol_names[(symbol, self._normalize_symbol_type(symbol, str(item.get('type') or '')))] = name_value
            else:
                item.pop("name", None)
                resolve_names = True

        if destination_group:
            dest_idx = self._find_group_index(destination_group)
            assert dest_idx is not None
            if dest_idx != group_idx:
                src_symbols = self.market_groups[group_idx].get("symbols")
                dst_symbols = self.market_groups[dest_idx].setdefault("symbols", [])
                if not isinstance(src_symbols, list) or not isinstance(dst_symbols, list):
                    self._log("[yellow]Edit failed:[/] invalid group schema")
                    return
                moved = dict(item)
                src_symbols.pop(item_idx)
                dst_symbols.append(moved)
                if not src_symbols:
                    if group_idx < dest_idx:
                        dest_idx -= 1
                    self.market_groups.pop(group_idx)

        self._apply_market_groups_change(resolve_missing_names=resolve_names)
        if not self._persist_config():
            self._log("[yellow]Edit warning:[/] could not persist config.yml")
            return
        self._log(f"[#2ec4b6]CONFIG[/] updated {symbol}")

    def _execute_command(self, command: str) -> None:
        raw = command.strip()
        if not raw:
            return
        try:
            tokens = shlex.split(raw)
        except ValueError as exc:
            self._log(f"[yellow]Command parse error:[/] {exc}")
            return
        if not tokens:
            return

        cmd = tokens[0].lower()
        if cmd == "q":
            self.exit()
            return
        if cmd == "r":
            self.action_reset()
            return
        if cmd == "n":
            self.action_refresh_news()
            return
        if cmd == "c":
            if len(tokens) == 1:
                self.action_open_calendar()
                return
            if len(tokens) >= 2 and tokens[1].strip().lower() == "calendar":
                self.action_open_calendar()
                return
            self._log(f"[yellow]{tr('Usage: :c calendar')}[/]")
            return
        if cmd == "calendar":
            self.action_open_calendar()
            return
        if cmd == "?":
            self.push_screen(ReadmeModal(self._load_readme_text()))
            return
        if cmd == "add":
            self._cmd_add_symbol(tokens)
            return
        if cmd == "del":
            self._cmd_del_symbol(tokens)
            return
        if cmd == "mv":
            self._cmd_move_symbol(tokens)
            return
        if cmd == "edit":
            self._cmd_edit_symbol(tokens)
            return
        self._log(f"[yellow]Command unknown:[/] :{raw}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command_input":
            return
        if not self.command_mode:
            # Enter was already handled by on_key command mode path.
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
        self._tab_cycle_key = None
        self._tab_cycle_index = -1
        self._exit_command_mode()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "command_input":
            return
        value = event.value or ""
        if value.startswith(":"):
            value = value[1:]
        self.command_buffer = value
        self._tab_cycle_key = None
        self._tab_cycle_index = -1
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
        self._update_main_group_panel()
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
            color = self._trend_color(state.change_percent >= 0, symbol_type="crypto")
            price = Text(f"{state.price:>13,.2f}", style=color)
            change = Text(f"{state.change_percent:>+8.2f}%", style=f"bold {color}")
            volume = self._format_volume(state.volume, 17)
            spark = self._sparkline(state.points or deque())
            type_label = "CRT"
        else:
            state = self.stock_data.get(symbol)
            if state is None:
                state = StockState(symbol=symbol)
                self.stock_data[symbol] = state
            color = self._trend_color(state.change_percent >= 0, symbol_type="stock")
            price = Text(f"{state.price:>13,.2f}", style=color)
            change = Text(f"{state.change_percent:>+8.2f}%", style=f"bold {color}")
            volume = self._format_volume(state.volume, 17)
            spark = self._sparkline(state.points or deque())
            type_label = "STK"

        table.update_cell(row_key, self.main_col_keys["symbol"], self._ticker_label(symbol, symbol_type))
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
        self._update_main_group_panel()
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

    def _ticker_label(self, symbol: str, symbol_type: str, max_name_len: int = 20) -> Text:
        name = self.symbol_names.get((symbol, symbol_type), "").strip()
        palette = self._ui_palette()
        label = Text(symbol, style=palette["text"])
        if not name:
            return label
        label.append(":", style=palette["muted"])
        label.append(name[:max_name_len], style=palette["accent"])
        return label

    def _format_volume(self, volume: float, width: int = 17) -> str:
        if abs(volume) >= 100_000_000:
            numeric_width = max(1, width - 1)
            return f"{(volume / 1_000_000):>{numeric_width}.2f}M"
        return f"{volume:>{width},.2f}"

    def _sparkline(self, values: deque[float]) -> Text:
        if not values:
            return Text("·", style=self._ui_palette()["muted"])
        sampled = self._compress_series(list(values), target=24)
        lo = min(sampled)
        hi = max(sampled)
        span = hi - lo or 1.0
        points = []
        for value in sampled:
            idx = int((value - lo) / span * (len(SPARKS) - 1))
            points.append(SPARKS[idx])
        trend_color = self._trend_color(sampled[-1] >= sampled[0], symbol_type=None)
        return Text("".join(points), style=trend_color)

    def _build_chart_text(
        self, state: SymbolState, timeframe: str = "15m", target_candles: int = 96
    ) -> Text:
        candles = list(self._get_crypto_series(state.symbol, timeframe) or deque())
        if timeframe != "15m" and not candles:
            candles = self._resample_candles(list(self.candles.get(state.symbol, deque())), timeframe)
        return self._build_chart_from_series(
            symbol=state.symbol,
            display_name=self.symbol_names.get((state.symbol, "crypto"), ""),
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
            display_name=self.symbol_names.get((state.symbol, "stock"), ""),
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
        display_name: str,
        market_label: str,
        price: float,
        change_percent: float,
        volume: float,
        values: list[float],
        candles: list[Candle],
        timeframe: str,
        target_candles: int,
    ) -> Text:
        symbol_type = "stock" if market_label == "STOCK" else "crypto"
        color = self._trend_color(change_percent >= 0, symbol_type=symbol_type)
        palette = self._ui_palette()
        visible_candles = max(24, target_candles)

        chart = Text()
        if display_name:
            chart.append(f"{symbol} ({display_name}) // {market_label} SNAPSHOT\n", style=f"bold {palette['brand']}")
        else:
            chart.append(f"{symbol} // {market_label} SNAPSHOT\n", style=f"bold {palette['brand']}")
        chart.append(
            f"price: {price:,.4f}   change: {change_percent:+.2f}%   volume: {volume:,.2f}\n",
            style=f"bold {color}",
        )
        chart.append(
            f"timeframe: {timeframe.upper()}   toggle: [t] 15m/1h/1d/1w/1mo   close: [Esc]/[Enter]/[q]\n\n",
            style=palette["muted"],
        )

        if len(candles) >= 2:
            chart.append("Chart 1: Candlestick view\n", style=f"bold {palette['ok']}")
            chart.append(
                f"{timeframe.upper()} OHLC candles  |  showing latest {min(len(candles), visible_candles)}\n",
                style=palette["accent"],
            )
            chart.append_text(
                self._render_candlestick_chart(candles, width=visible_candles, height=16)
            )
            chart.append("\n")

        if len(values) >= 2:
            lo = min(values)
            hi = max(values)
            chart.append("Chart 2: Live updates\n", style=f"bold {palette['brand']}")
            chart.append(
                f"tick trend min: {lo:,.4f}   max: {hi:,.4f}   points: {len(values)}\n",
                style=palette["accent"],
            )
            plotext_text = self._render_plotext_xy(values, symbol)
            if plotext_text and plotext_text.count("\n") >= 8:
                chart.append(plotext_text, style=palette["text"])
            else:
                chart.append_text(self._render_xy_ascii(values, width=108, height=22, color=color))
            chart.append("\n")
        else:
            chart.append("Waiting for more ticks to draw chart...\n", style=palette["accent"])
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
        palette = self._ui_palette()
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
        text.append(f"{hi:,.4f} ┤", style=palette["accent"])
        text.append("\n")
        for row in grid:
            text.append("      │", style=palette["muted"])
            text.append("".join(row), style=color)
            text.append("\n")
        text.append(f"{lo:,.4f} ┼", style=palette["accent"])
        text.append("─" * width, style=palette["muted"])
        text.append("\n")
        text.append("       oldest", style=palette["muted"])
        text.append(" " * (max(1, width - 13)))
        text.append("latest", style=palette["muted"])
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
        palette = self._ui_palette()
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
                c_color = self._trend_color(up, symbol_type=None)

                if body_min <= row <= body_max:
                    text.append("█", style=c_color)
                elif y_low <= row <= y_high:
                    text.append("│", style=c_color)
                else:
                    text.append(" ")
            text.append("\n")

        text.append(f"high {hi:,.4f}\n", style=palette["accent"])
        text.append(f"low  {lo:,.4f}\n", style=palette["accent"])
        return text

    def _log(self, message: str) -> None:
        self.query_one("#events", RichLog).write(message)
        ts = datetime.now(self.local_tz).strftime("%Y-%m-%d %H:%M:%S")
        try:
            append_app_log_line(f"{ts} {message}")
        except Exception:
            pass

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
        for symbol in self.indicator_symbols:
            self.indicator_data[symbol] = StockState(symbol=symbol)
        self._update_main_group_panel()
        self._update_indicators_panel()
        self._update_alerts_panel()
        self._log("[cyan]Local buffers reset[/]")

    def action_focus_symbol(self, symbol: str) -> None:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return

        symbol_type = ""
        in_indicator_groups = False
        if symbol in self.symbol_data:
            symbol_type = "crypto"
        elif symbol in self.stock_data:
            symbol_type = "stock"
        elif symbol in self.indicator_data:
            symbol_type = "stock"
            in_indicator_groups = True
        else:
            for _, items in self.main_group_items:
                for item_symbol, item_type in items:
                    if item_symbol == symbol:
                        symbol_type = item_type
                        break
                if symbol_type:
                    break
            if not symbol_type:
                for _, items in self.indicator_group_items:
                    for item_symbol, item_type in items:
                        if item_symbol == symbol:
                            symbol_type = item_type
                            in_indicator_groups = True
                            break
                    if symbol_type:
                        break
        if symbol_type not in {"crypto", "stock"}:
            self._log(f"[yellow]Quick action:[/] symbol {symbol} not found in configured groups")
            return

        self.focused_symbol = symbol
        if symbol_type == "crypto":
            state = self.symbol_data.get(symbol)
            for i, (_, items) in enumerate(self.main_group_items):
                if (symbol, symbol_type) in items:
                    self.main_group_index = i
                    self._pause_group_rotation("crypto_quotes", 60)
                    self._update_main_group_panel()
                    break
        else:
            state = self.indicator_data.get(symbol) if in_indicator_groups else self.stock_data.get(symbol)
            target_table_id = "#indicators_table" if in_indicator_groups else "#crypto_quotes"
            target_items = self.indicator_row_item_by_index if in_indicator_groups else self.main_row_item_by_index
            if in_indicator_groups:
                for i, (_, items) in enumerate(self.indicator_group_items):
                    if (symbol, symbol_type) in items:
                        self.indicator_group_index = i
                        self._pause_group_rotation("indicators_table", 60)
                        self._update_indicators_panel()
                        break
            else:
                for i, (_, items) in enumerate(self.main_group_items):
                    if (symbol, symbol_type) in items:
                        self.main_group_index = i
                        self._pause_group_rotation("crypto_quotes", 60)
                        self._update_main_group_panel()
                        break

            if state is not None:
                self._log(
                    f"[bold #99e2ff]{symbol}[/] "
                    f"price={state.price:,.4f} change={state.change_percent:+.2f}% volume={state.volume:,.2f}"
                )
            table = self.query_one(target_table_id, DataTable)
            for row_index, item in target_items.items():
                if item == (symbol, symbol_type):
                    table.move_cursor(row=row_index)
                    break
            return
        if state is not None:
            self._log(
                f"[bold #99e2ff]{symbol}[/] "
                f"price={state.price:,.4f} change={state.change_percent:+.2f}% volume={state.volume:,.2f}"
            )

        table = self.query_one("#crypto_quotes", DataTable)
        for row_index, item in self.main_row_item_by_index.items():
            if item == (symbol, symbol_type):
                table.move_cursor(row=row_index)
                break

    async def on_key(self, event: events.Key) -> None:
        if isinstance(self.screen, (ChartModal, ReadmeModal, CalendarModal)):
            if isinstance(self.screen, CalendarModal):
                if event.key in {"escape", "q"}:
                    self.screen.dismiss(None)
                    event.stop()
                    return
            else:
                if event.key in {"escape", "enter", "q"}:
                    self.screen.dismiss(None)
                    event.stop()
                    return
            # While chart modal is open, global shortcuts must not affect the app.
            return

        main_table = self.query_one("#crypto_quotes", DataTable)
        indicators_table = self.query_one("#indicators_table", DataTable)
        news_table = self.query_one("#news_table", DataTable)

        if main_table.has_focus:
            if event.key in {"up", "down", "pageup", "pagedown", "home", "end", "j", "k"}:
                self._pause_group_rotation("crypto_quotes", 60)
            if event.key in {"left", "comma"} or event.character in {"<", ","}:
                self._cycle_main_group(-1)
                event.stop()
                return
            if event.key in {"right", "full_stop", "period"} or event.character in {">", "."}:
                self._cycle_main_group(1)
                event.stop()
                return

        if news_table.has_focus:
            if event.key in {"up", "down", "pageup", "pagedown", "home", "end", "j", "k"}:
                self._pause_group_rotation("news_table", 60)
            if event.key in {"left", "comma"} or event.character in {"<", ","}:
                self._cycle_news_group(-1)
                event.stop()
                return
            if event.key in {"right", "full_stop", "period"} or event.character in {">", "."}:
                self._cycle_news_group(1)
                event.stop()
                return

        if indicators_table.has_focus:
            if event.key in {"up", "down", "pageup", "pagedown", "home", "end", "j", "k"}:
                self._pause_group_rotation("indicators_table", 60)
            if event.key in {"left", "comma"} or event.character in {"<", ","}:
                self._cycle_indicator_group(-1)
                event.stop()
                return
            if event.key in {"right", "full_stop", "period"} or event.character in {">", "."}:
                self._cycle_indicator_group(1)
                event.stop()
                return

        if self.command_mode:
            if event.key == "escape":
                self._exit_command_mode()
                event.stop()
                return
            if event.key == "enter":
                command_input = self.query_one("#command_input", Input)
                raw = (command_input.value or "").strip()
                if raw.startswith(":"):
                    raw = raw[1:].strip()
                if raw:
                    self._execute_command(raw)
                command_input.value = ""
                self._tab_cycle_key = None
                self._tab_cycle_index = -1
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
        if event.key in {"1", "2", "3"}:
            target = self.quick_actions.get(event.key)
            if target:
                self.action_focus_symbol(target)
            return
        if event.character == "?":
            self.action_show_help_tip()


def run_app(
    crypto_symbols: Iterable[str] | None = None,
    stock_symbols: Iterable[str] | None = None,
    timezone: str = "",
    language: str = "es",
    config_name: str = "",
    calendars: Iterable[dict[str, Any]] | None = None,
    groups: Iterable[dict[str, Any]] | None = None,
    indicator_groups: Iterable[dict[str, Any]] | None = None,
    quick_actions: dict[str, str] | None = None,
    config_path: str = "config.yml",
    symbols_from_config: bool = True,
) -> None:
    NeonQuotesApp(
        crypto_symbols=crypto_symbols,
        stock_symbols=stock_symbols,
        timezone=timezone,
        language=language,
        config_name=config_name,
        calendars=calendars,
        groups=groups,
        indicator_groups=indicator_groups,
        quick_actions=quick_actions,
        config_path=config_path,
        symbols_from_config=symbols_from_config,
    ).run()
