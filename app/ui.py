from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable
from zoneinfo import ZoneInfo

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, RichLog, Static

from .commands import (
    execute_command,
)
from .config import (
    CACHE_TTL_SECONDS,
    CALENDAR_HORIZON_DAYS,
    CALENDAR_REFRESH_SECONDS,
    CALENDAR_SOON_HOURS,
    CHART_HISTORY_POINTS,
    DESCRIPTION_CACHE_TTL_SECONDS,
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
from .config_repository import YamlConfigRepository
from .calendar import CalendarEvent
from .cache import (
    append_app_log_line,
    load_categories_cache,
    load_descriptions_cache,
    load_names_cache,
    save_categories_cache,
    load_symbol_history_cache,
    save_descriptions_cache,
    save_names_cache,
    save_symbol_history_cache,
)
from .i18n import format_time_local, set_language, tr
from .models import Candle, Quote, StockState, SymbolState
from .news import NewsItem
from .ports import (
    CalendarProvider,
    ConfigRepository,
    NewsProvider,
    ProfileProvider,
    QuoteProvider,
    StockProvider,
)
from .providers import (
    BinanceQuoteProvider,
    DefaultProfileProvider,
    FinvizNewsProvider,
    ForexFactoryCalendarProvider,
    YFinanceStockProvider,
)
from .formatters import (
    format_news_headline,
    format_volume,
    headline_inline,
    ticker_label,
)
from .screens import BootModal, CalendarModal, ChartModal, CommandInput, ReadmeModal
from .stocks import StockQuote
from .symbol_names import resolve_symbol_names, update_config_group_names
from .chart_history import (
    ChartHistoryConfig,
    ensure_crypto_chart_history,
    ensure_stock_chart_history,
)
from .chart_rendering import (
    build_chart_text,
    build_stock_chart_text,
    compress_series,
)
from .rotation import RotationController
from .grouping import advance_symbol_across_groups, build_main_groups, build_symbol_groups
from .tables import (
    update_alerts_panel,
    update_indicators_panel,
    update_main_group_panel,
    update_news_panel,
)
from .bindings import (
    handle_command_mode_keys,
    handle_global_shortcuts,
    handle_modal_shortcuts,
    handle_table_navigation,
)
from .version import get_app_version
from .presenters import build_header_markup, build_status_line_text
from .runtime_config import (
    clear_quick_actions_for_symbol,
    find_group_index,
    find_symbol_entry,
    normalize_symbol_type,
    sync_market_data_structures,
)
from .refresh_services import refresh_calendar_data, refresh_news_data, refresh_stock_quotes
from .market_runtime import apply_quote_to_state, resample_candles, seed_history_state, update_candles
from .command_ui import autocomplete_command, enter_command_mode, exit_command_mode

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
        quote_provider: QuoteProvider | None = None,
        stock_provider: StockProvider | None = None,
        news_provider: NewsProvider | None = None,
        calendar_provider: CalendarProvider | None = None,
        profile_provider: ProfileProvider | None = None,
        config_repository: ConfigRepository | None = None,
    ) -> None:
        super().__init__()
        self.crypto_symbols = list(crypto_symbols or DEFAULT_CRYPTO_SYMBOLS)
        self.stock_symbols = [symbol.upper() for symbol in (stock_symbols or DEFAULT_STOCK_SYMBOLS)]
        self.market_groups = list(groups or [])
        self.indicator_groups = list(indicator_groups or [])
        self.symbol_names = dict(symbol_names or {})
        self.symbol_descriptions: dict[tuple[str, str], str] = {}
        self.symbol_categories: dict[tuple[str, str], str] = {}
        self.description_fetching: set[tuple[str, str]] = set()
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
        self.quote_provider = quote_provider or BinanceQuoteProvider([])
        self.stock_provider = stock_provider or YFinanceStockProvider()
        self.news_provider = news_provider or FinvizNewsProvider()
        self.calendar_provider = calendar_provider or ForexFactoryCalendarProvider()
        self.profile_provider = profile_provider or DefaultProfileProvider()
        self.config_repository = config_repository or YamlConfigRepository()
        self.symbol_data = {symbol: SymbolState(symbol=symbol) for symbol in self.crypto_symbols}
        self.stock_data = {symbol: StockState(symbol=symbol) for symbol in self.stock_symbols}
        self.indicator_group_items: list[tuple[str, list[tuple[str, str]]]] = build_symbol_groups(
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
        self.main_group_items: list[tuple[str, list[tuple[str, str]]]] = build_main_groups(
            self.market_groups,
            crypto_symbols=self.crypto_symbols,
            stock_symbols=self.stock_symbols,
        )
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
        self.rotation = RotationController()
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
        self.chart_history_cfg = ChartHistoryConfig(
            candle_buffer_max=CANDLE_BUFFER_MAX,
            chart_history_points=CHART_HISTORY_POINTS,
            max_points=MAX_POINTS,
            initial_candle_limit=INITIAL_CANDLE_LIMIT,
        )
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
        self._load_cached_descriptions()
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

    def _load_cached_descriptions(self) -> None:
        cached = load_descriptions_cache(DESCRIPTION_CACHE_TTL_SECONDS)
        if not cached:
            return
        added = 0
        for key, value in cached.items():
            if key in self.symbol_descriptions:
                continue
            self.symbol_descriptions[key] = value
            added += 1
        if added:
            self._log(f"[#2ec4b6]DESC[/] loaded {added} cached descriptions")
        cached_categories = load_categories_cache(DESCRIPTION_CACHE_TTL_SECONDS)
        cat_added = 0
        for key, value in cached_categories.items():
            if key in self.symbol_categories:
                continue
            self.symbol_categories[key] = value
            cat_added += 1
        if cat_added:
            self._log(f"[#2ec4b6]DESC[/] loaded {cat_added} cached categories")

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
        self.indicator_group_items = build_symbol_groups(
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
        now = format_time_local(datetime.now(self.local_tz), tzinfo=self.local_tz)
        header = build_header_markup(
            palette=palette,
            app_version=self.app_version,
            config_name=self.config_name,
            now_text=now,
            status_text=self.status_text,
            age_ms=age_ms,
            heartbeat=self.heartbeat,
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
        return headline_inline(
            source=item.source,
            age=item.age,
            title=item.title,
            max_title_len=NEWS_TICKER_HEADLINE_MAX,
        )

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
                async for quote in self.quote_provider.stream():
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
            result = await refresh_calendar_data(
                provider=self.calendar_provider,
                calendars=self.calendars,
                horizon_days=CALENDAR_HORIZON_DAYS,
                local_now=lambda: datetime.now(self.local_tz),
            )
            self.calendar_events = result.events
            self.calendar_last_update = result.last_update_hhmm
            self._log(
                f"[{self._ui_palette()['accent']}]CALENDAR[/] refreshed {len(result.events)} events "
                f"from {result.calendar_count} calendars (next {CALENDAR_HORIZON_DAYS}d)"
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
        self._schedule_symbol_description_fetch(symbol, symbol_type)
        current = {"symbol": symbol, "type": symbol_type}

        def chart_builder(tf: str, candles: int) -> Text:
            return self._build_chart_for_item(current["symbol"], current["type"], tf, candles)

        async def ensure_history(tf: str, candles: int) -> None:
            await self._ensure_chart_history_for_item(current["symbol"], current["type"], tf, candles)

        def navigate(step: int) -> tuple[str, str] | None:
            nxt = advance_symbol_across_groups(
                self.main_group_items,
                symbol=current["symbol"],
                symbol_type=current["type"],
                step=step,
            )
            if not nxt:
                return None
            current["symbol"], current["type"] = nxt
            self._schedule_symbol_description_fetch(current["symbol"], current["type"])
            for i, (_, items) in enumerate(self.main_group_items):
                if nxt in items:
                    self.main_group_index = i
                    self._pause_group_rotation("crypto_quotes", 60)
                    self._update_main_group_panel()
                    break
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
            return build_stock_chart_text(self, state, timeframe=timeframe, target_candles=target_candles)
        state = self.symbol_data.get(symbol)
        if state is None:
            state = SymbolState(symbol=symbol)
            self.symbol_data[symbol] = state
        return build_chart_text(self, state, timeframe=timeframe, target_candles=target_candles)

    async def _ensure_chart_history_for_item(
        self, symbol: str, symbol_type: str, timeframe: str, target_candles: int
    ) -> None:
        if symbol_type == "stock":
            await self._ensure_stock_chart_history(symbol, timeframe, target_candles)
            return
        await self._ensure_crypto_chart_history(symbol, timeframe, target_candles)

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
            result = await refresh_news_data(
                provider=self.news_provider,
                max_items=NEWS_MAX_ITEMS,
                group_size=NEWS_GROUP_SIZE,
                ticker_limit=NEWS_TICKER_LIMIT,
                local_now=lambda: datetime.now(self.local_tz),
                age_minutes=self._news_age_minutes,
            )
            self.news_groups = result.groups
            self.news_latest_items = result.latest_items
            self.news_last_update = result.last_update_hhmm
            self.news_group_index = 0
            self._update_news_panel()
            self._log(
                f"[#2ec4b6]NEWS[/] refreshed {result.total_items} headlines across {result.feed_count} feeds"
            )
        except Exception as exc:
            self._log(f"[yellow]News warning:[/] {exc!r}")

    def _rotate_news_group(self) -> None:
        if not self.news_groups:
            return
        if self.rotation.is_paused("news_table"):
            return
        self.news_group_index = self.rotation.cycle_index(self.news_group_index, len(self.news_groups))
        self._update_news_panel()

    def _rotate_main_group(self) -> None:
        if self.is_shutting_down:
            return
        if not self.main_group_items:
            return
        if self.rotation.is_paused("crypto_quotes"):
            return
        self.main_group_index = self.rotation.cycle_index(self.main_group_index, len(self.main_group_items))
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
        if self.rotation.is_paused("indicators_table"):
            return
        self.indicator_group_index = self.rotation.cycle_index(
            self.indicator_group_index, len(self.indicator_group_items)
        )
        self._update_indicators_panel()
        self._schedule_indicator_refresh()

    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None:
        self.rotation.pause(table_id, seconds)

    def _cycle_main_group(self, step: int) -> None:
        if self.is_shutting_down:
            return
        if not self.main_group_items:
            return
        self.main_group_index = self.rotation.cycle_index(
            self.main_group_index, len(self.main_group_items), step
        )
        self._pause_group_rotation("crypto_quotes", 60)
        self._update_main_group_panel()
        self._schedule_stock_refresh()
        self._spawn_background(self._refresh_crypto_stream_for_visible_group())

    def _cycle_news_group(self, step: int) -> None:
        if not self.news_groups:
            return
        self.news_group_index = self.rotation.cycle_index(self.news_group_index, len(self.news_groups), step)
        self._pause_group_rotation("news_table", 60)
        self._update_news_panel()

    def _cycle_indicator_group(self, step: int) -> None:
        if not self.indicator_group_items:
            return
        self.indicator_group_index = self.rotation.cycle_index(
            self.indicator_group_index,
            len(self.indicator_group_items),
            step,
        )
        self._pause_group_rotation("indicators_table", 60)
        self._update_indicators_panel()
        self._schedule_indicator_refresh()

    async def _refresh_crypto_stream_for_visible_group(self) -> None:
        desired = [s for s, t in self.main_visible_items if t == "crypto"]
        desired = [s.upper() for s in desired if s]
        current = [s.upper() for s in self.quote_provider.symbols]
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

        self.quote_provider.set_symbols(desired)
        self.feed_task = asyncio.create_task(self._consume_feed())

    def _update_main_group_panel(self) -> None:
        update_main_group_panel(self)

    def _update_indicators_panel(self) -> None:
        update_indicators_panel(self)

    def _update_alerts_panel(self) -> None:
        update_alerts_panel(self, ALERTS_TABLE_SIZE)

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
                        self.quote_provider.fetch_recent_closes, symbol, INITIAL_HISTORY_POINTS
                    )
                    candles = await asyncio.to_thread(
                        self.quote_provider.fetch_recent_15m_ohlc, symbol, INITIAL_CANDLE_LIMIT
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
                        self.stock_provider.fetch_history,
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
                        self.quote_provider.fetch_recent_closes, symbol, INITIAL_HISTORY_POINTS
                    )
                    candles = await asyncio.to_thread(
                        self.quote_provider.fetch_recent_15m_ohlc, symbol, INITIAL_CANDLE_LIMIT
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
                        self.stock_provider.fetch_history,
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
            result = await refresh_stock_quotes(
                provider=self.stock_provider,
                symbols=symbols_to_refresh,
                local_now=lambda: datetime.now(self.local_tz),
            )
            for quote in result.quotes:
                self._apply_stock_quote(quote)
            self.stocks_last_update = result.last_update_hhmm
            self._update_main_group_panel()
            self._update_alerts_panel()
            self._log(
                f"[#2ec4b6]STOCKS[/] refreshed {len(result.quotes)} symbols "
                f"({result.symbols_requested} in active group)"
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
            result = await refresh_stock_quotes(
                provider=self.stock_provider,
                symbols=symbols_to_refresh,
                local_now=lambda: datetime.now(self.local_tz),
            )
            for quote in result.quotes:
                state = self.indicator_data.get(quote.symbol)
                if state is None:
                    state = StockState(symbol=quote.symbol)
                    self.indicator_data[quote.symbol] = state
                state.price = quote.price
                state.change_percent = quote.change_percent
                state.volume = quote.volume
                state.last_update_ms = quote.event_time_ms
            self.indicators_last_update = result.last_update_hhmm
            self._update_indicators_panel()
            self._log(
                f"[#2ec4b6]{tr('INDICATORS')}[/] refreshed {len(result.quotes)} symbols "
                f"({result.symbols_requested} in active group)"
            )
        except Exception as exc:
            self._log(f"[yellow]{tr('INDICATORS')} warning:[/] {exc!r}")

    async def _ensure_crypto_chart_history(
        self, symbol: str, timeframe: str, target_candles: int
    ) -> None:
        await ensure_crypto_chart_history(
            self,
            symbol=symbol,
            timeframe=timeframe,
            target_candles=target_candles,
            candle_cls=Candle,
            cfg=self.chart_history_cfg,
        )

    async def _ensure_stock_chart_history(
        self, symbol: str, timeframe: str, target_candles: int
    ) -> None:
        await ensure_stock_chart_history(
            self,
            symbol=symbol,
            timeframe=timeframe,
            target_candles=target_candles,
            candle_cls=Candle,
            cfg=self.chart_history_cfg,
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
        seed_history_state(
            state=self.symbol_data[symbol],
            series=self.candles[symbol],
            closes=closes,
            candles_raw=candles_raw,
            max_points=MAX_POINTS,
            candle_cls=Candle,
        )

        self._refresh_main_row(symbol, "crypto")

    def _seed_stock_history(
        self,
        symbol: str,
        closes: list[tuple[int, float]],
        candles_raw: list[tuple[int, float, float, float, float]],
    ) -> None:
        seed_history_state(
            state=self.stock_data[symbol],
            series=self.stock_candles[symbol],
            closes=closes,
            candles_raw=candles_raw,
            max_points=MAX_POINTS,
            candle_cls=Candle,
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
        update_news_panel(self, NEWS_GROUP_SIZE, NEWS_REFRESH_SECONDS)

    def _format_news_headline(self, source: str, age: str, title: str, line_len: int = 86) -> Text:
        return format_news_headline(
            source=source,
            age=age,
            title=title,
            line_len=line_len,
            news_palette=self._news_palette(),
            body_color=self._ui_palette()["text"],
        )

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
        enter_command_mode(self)

    def _exit_command_mode(self) -> None:
        exit_command_mode(self)

    def _render_status_line(self) -> None:
        palette = self._ui_palette()
        line = self.query_one("#status_line", Static)
        line.update(
            build_status_line_text(
                palette=palette,
                command_mode=self.command_mode,
                command_buffer=self.command_buffer,
                width=self.size.width,
            )
        )

    def autocomplete_command_input(self) -> None:
        autocomplete_command(self)

    @staticmethod
    def _normalize_symbol_type(symbol: str, symbol_type: str) -> str:
        return normalize_symbol_type(symbol, symbol_type)

    def _find_group_index(self, group_name: str) -> int | None:
        return find_group_index(self.market_groups, group_name)

    def _find_symbol_entry(self, symbol: str) -> tuple[int, int, dict[str, Any]] | None:
        return find_symbol_entry(self.market_groups, symbol)

    def _persist_config(self) -> bool:
        return self.config_repository.persist_runtime_config(
            path=self.config_path,
            config_name=self.config_name,
            timezone=self.timezone,
            language=self.language,
            quick_actions=self.quick_actions,
            calendars=self.calendars,
            indicator_groups=self.indicator_groups,
            market_groups=self.market_groups,
        )

    def _ensure_main_row_capacity(self, required_rows: int) -> None:
        table = self.query_one("#crypto_quotes", DataTable)
        while len(self.main_row_keys) < required_rows:
            idx = len(self.main_row_keys)
            row_key = table.add_row("-", "-", "-", "-", "-", "", key=f"main_{idx}")
            self.main_row_keys.append(row_key)

    def _sync_market_data_structures(self) -> None:
        self.crypto_symbols, self.stock_symbols = sync_market_data_structures(
            main_group_items=self.main_group_items,
            symbol_data=self.symbol_data,
            stock_data=self.stock_data,
            candles=self.candles,
            stock_candles=self.stock_candles,
            crypto_candles_by_tf=self.crypto_candles_by_tf,
            stock_candles_by_tf=self.stock_candles_by_tf,
            candle_buffer_max=CANDLE_BUFFER_MAX,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )

    def _apply_market_groups_change(self, resolve_missing_names: bool = False) -> None:
        self.main_group_items = build_main_groups(
            self.market_groups,
            crypto_symbols=self.crypto_symbols,
            stock_symbols=self.stock_symbols,
        )
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
        removed = clear_quick_actions_for_symbol(self.quick_actions, symbol)
        if removed:
            self._log(
                f"[#ffcf5c]CONFIG[/] quick actions cleared for {symbol}: "
                f"{', '.join(removed)}"
            )

    def _execute_command(self, command: str) -> None:
        execute_command(self, command)

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
        apply_quote_to_state(
            state=self.symbol_data[quote.symbol],
            price=quote.price,
            change_percent=quote.change_percent,
            volume=quote.volume,
            event_time_ms=quote.event_time_ms,
        )
        self._update_candles(quote.symbol, quote.price, quote.event_time_ms)
        self._update_main_group_panel()
        self._update_alerts_panel()

    def _update_candles(self, symbol: str, price: float, event_time_ms: int) -> None:
        update_candles(
            series=self.candles[symbol],
            candle_cls=Candle,
            price=price,
            event_time_ms=event_time_ms,
            fifteen_min_ms=FIFTEEN_MIN_MS,
        )

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
        apply_quote_to_state(
            state=state,
            price=quote.price,
            change_percent=quote.change_percent,
            volume=quote.volume,
            event_time_ms=quote.event_time_ms,
        )
        self._update_stock_candles(quote.symbol, quote.price, quote.event_time_ms)
        self._update_main_group_panel()
        self._update_alerts_panel()

    def _update_stock_candles(self, symbol: str, price: float, event_time_ms: int) -> None:
        update_candles(
            series=self.stock_candles[symbol],
            candle_cls=Candle,
            price=price,
            event_time_ms=event_time_ms,
            fifteen_min_ms=FIFTEEN_MIN_MS,
        )

    def _refresh_row(self, state: SymbolState) -> None:
        self._refresh_main_row(state.symbol, "crypto")

    def _refresh_stock_row(self, state: StockState) -> None:
        self._refresh_main_row(state.symbol, "stock")

    def _new_stock_state(self, symbol: str) -> StockState:
        return StockState(symbol=symbol)

    def _ticker_label(self, symbol: str, symbol_type: str, max_name_len: int = 20) -> Text:
        return ticker_label(
            symbol=symbol,
            symbol_type=symbol_type,
            symbol_names=self.symbol_names,
            palette=self._ui_palette(),
            max_name_len=max_name_len,
        )

    def _format_volume(self, volume: float, width: int = 17) -> str:
        return format_volume(volume=volume, width=width)

    def _sparkline(self, values: deque[float]) -> Text:
        if not values:
            return Text("·", style=self._ui_palette()["muted"])
        sampled = compress_series(list(values), target=24)
        lo = min(sampled)
        hi = max(sampled)
        span = hi - lo or 1.0
        points = []
        for value in sampled:
            idx = int((value - lo) / span * (len(SPARKS) - 1))
            points.append(SPARKS[idx])
        trend_color = self._trend_color(sampled[-1] >= sampled[0], symbol_type=None)
        return Text("".join(points), style=trend_color)

    def _schedule_symbol_description_fetch(self, symbol: str, symbol_type: str) -> None:
        key = (symbol, symbol_type)
        if self.symbol_descriptions.get(key):
            return
        if key in self.description_fetching:
            return
        self.description_fetching.add(key)
        self._spawn_background(self._fetch_symbol_description(symbol, symbol_type))

    async def _fetch_symbol_description(self, symbol: str, symbol_type: str) -> None:
        key = (symbol, symbol_type)
        try:
            description, category = await asyncio.to_thread(
                self.profile_provider.fetch_symbol_profile, symbol, symbol_type
            )
            description = (description or "").strip()
            category = (category or "").strip()
            if not description and not category:
                return
            if description:
                self.symbol_descriptions[key] = description
            if category:
                self.symbol_categories[key] = category
            save_descriptions_cache(self.symbol_descriptions)
            save_categories_cache(self.symbol_categories)
            self._log(f"[#2ec4b6]DESC[/] loaded profile for {symbol}")
        except Exception as exc:
            self._log(f"[yellow]Description warning {symbol}:[/] {exc!r}")
        finally:
            self.description_fetching.discard(key)

    def _resample_candles(self, candles: list[Candle], timeframe: str) -> list[Candle]:
        return resample_candles(candles, timeframe)

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
        if handle_modal_shortcuts(self, event):
            return

        if handle_table_navigation(self, event):
            return

        if handle_command_mode_keys(self, event):
            return

        handle_global_shortcuts(self, event)


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
