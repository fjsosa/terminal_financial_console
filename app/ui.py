from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
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
    ticker_label,
)
from .screens import BootModal, CalendarModal, ChartModal, CommandInput, ReadmeModal
from .stocks import StockQuote
from .symbol_names import update_config_group_names
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
from .grouping import build_main_groups, build_symbol_groups
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
from .market_runtime import resample_candles, seed_history_state, update_candles
from .command_ui import autocomplete_command, enter_command_mode, exit_command_mode
from .startup_orchestration import run_startup_sequence
from .task_supervision import TaskSupervisor
from .market_panel_controller import (
    apply_market_groups_change,
    apply_quote,
    apply_stock_quote,
    ensure_main_row_capacity,
    refresh_main_row,
)
from .calendar_ticker_vm import (
    alerts_items_for_ticker,
    build_calendar_text,
    calendar_events_for_ticker,
    calendar_status_label,
    render_ticker_visible_text,
    ticker_chunks_calendar,
    ticker_chunks_news,
    ticker_chunks_quotes,
)
from .focus_navigation import focus_symbol
from .refresh_controller import (
    refresh_calendar,
    refresh_indicators,
    refresh_news,
    refresh_stocks,
    schedule_calendar_refresh,
    schedule_indicator_refresh,
    schedule_news_refresh,
    schedule_stock_refresh,
)
from .actions_controller import (
    enter_command_mode_action,
    exit_command_mode_action,
    open_calendar_modal,
    quick_quit,
    refresh_news_action,
    reset_local_buffers,
)
from .name_resolution import (
    load_cached_descriptions,
    load_cached_symbol_names,
    resolve_names_background,
)
from .chart_controller import (
    handle_row_selected,
    open_alert_chart_for_row,
    open_chart_for_symbol,
    open_main_chart_for_row,
)
from .history_orchestration import (
    current_visible_symbols,
    load_remaining_history_in_background,
    preload_visible_group_history,
)
from .stream_orchestration import consume_feed, refresh_crypto_stream_for_visible_group
from .startup_mount import (
    configure_tables,
    initialize_mount_state,
    refresh_theme_panels,
    schedule_mount_intervals,
)

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
        self.task_supervisor = TaskSupervisor()
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
        configure_tables(
            self,
            alerts_table_size=ALERTS_TABLE_SIZE,
            news_group_size=NEWS_GROUP_SIZE,
            max_events=MAX_EVENTS,
            tr_fn=tr,
        )
        initialize_mount_state(self, tr_fn=tr, create_task_fn=asyncio.create_task)
        self.watch(self.app, "theme", self._on_app_theme_changed, init=False)

        schedule_mount_intervals(
            self,
            ticker_mode_seconds=TICKER_MODE_SECONDS,
            news_refresh_seconds=NEWS_REFRESH_SECONDS,
            calendar_refresh_seconds=CALENDAR_REFRESH_SECONDS,
            news_group_rotate_seconds=NEWS_GROUP_ROTATE_SECONDS,
            stock_group_rotate_seconds=STOCK_GROUP_ROTATE_SECONDS,
            stocks_refresh_seconds=STOCKS_REFRESH_SECONDS,
        )
        self.startup_task = asyncio.create_task(self._startup_sequence())

    def _on_app_theme_changed(self, *_args: Any) -> None:
        # Re-render metadata colors when theme changes from command palette.
        refresh_theme_panels(self)

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
        await self.task_supervisor.shutdown(
            startup_task=self.startup_task,
            lazy_history_task=self.lazy_history_task,
            name_resolve_task=self.name_resolve_task,
            feed_task=self.feed_task,
            timeout=0.2,
        )

    def _spawn_background(self, coro: Any) -> Any:
        return self.task_supervisor.spawn(coro)

    def _load_cached_symbol_names(self) -> None:
        load_cached_symbol_names(
            self,
            ttl_seconds=NAME_CACHE_TTL_SECONDS,
            load_names_cache_fn=load_names_cache,
        )

    def _load_cached_descriptions(self) -> None:
        load_cached_descriptions(
            self,
            ttl_seconds=DESCRIPTION_CACHE_TTL_SECONDS,
            load_descriptions_cache_fn=load_descriptions_cache,
            load_categories_cache_fn=load_categories_cache,
        )

    async def _resolve_names_background(self) -> None:
        await resolve_names_background(
            self,
            save_names_cache_fn=save_names_cache,
            update_config_group_names_fn=update_config_group_names,
        )

    async def _startup_sequence(self) -> None:
        await run_startup_sequence(self)

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
        return alerts_items_for_ticker(self.alerts_row_item_by_index)

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

    def _calendar_events_for_ticker(self) -> list[CalendarEvent]:
        now_local = datetime.now(self.local_tz)
        return calendar_events_for_ticker(
            self.calendar_events,
            local_now=now_local,
            local_today=now_local.date(),
            local_tz=self.local_tz,
        )

    def _build_calendar_text(self) -> Text:
        return build_calendar_text(
            palette=self._ui_palette(),
            calendars=self.calendars,
            calendar_events=self.calendar_events,
            calendar_last_update=self.calendar_last_update,
            horizon_days=CALENDAR_HORIZON_DAYS,
            now_local=datetime.now(self.local_tz),
            soon_hours=CALENDAR_SOON_HOURS,
        )

    def _animate_ticker(self) -> None:
        mode = self.ticker_mode
        if mode == "quotes":
            chunks = ticker_chunks_quotes(
                alerts_items=self._alerts_items_for_ticker(),
                symbol_data=self.symbol_data,
                stock_data=self.stock_data,
            )
        elif mode == "news":
            chunks = ticker_chunks_news(
                latest_items=self.news_latest_items,
                limit=NEWS_TICKER_LIMIT,
            )
        else:
            chunks = ticker_chunks_calendar(
                events=self._calendar_events_for_ticker(),
                max_events=12,
                soon_hours=CALENDAR_SOON_HOURS,
            )

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
        ticker_text = render_ticker_visible_text(
            mode=mode,
            visible=visible,
            palette=palette,
            heartbeat=self.heartbeat,
        )
        self.query_one("#ticker", Static).update(ticker_text)
        self.ticker_offset += 1

    async def _consume_feed(self) -> None:
        await consume_feed(self)

    def _schedule_news_refresh(self) -> None:
        schedule_news_refresh(self)

    def _schedule_calendar_refresh(self) -> None:
        schedule_calendar_refresh(self)

    async def _refresh_calendar(self) -> None:
        await refresh_calendar(self, horizon_days=CALENDAR_HORIZON_DAYS)

    def action_open_calendar(self) -> None:
        open_calendar_modal(self, CalendarModal)

    def action_refresh_news(self) -> None:
        refresh_news_action(self)

    def action_quick_quit(self) -> None:
        quick_quit(self, modal_types=(ChartModal, ReadmeModal, CalendarModal))

    def action_enter_command_mode(self) -> None:
        enter_command_mode_action(self)

    def action_exit_command_mode(self) -> None:
        exit_command_mode_action(self, chart_modal_type=ChartModal)

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
        open_chart_for_symbol(
            self,
            symbol,
            symbol_type,
            chart_modal_cls=ChartModal,
            candle_buffer_max=CANDLE_BUFFER_MAX,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
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
        open_main_chart_for_row(
            self,
            row_index,
            chart_modal_cls=ChartModal,
            candle_buffer_max=CANDLE_BUFFER_MAX,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )

    def _open_alert_chart_for_row(self, row_index: int) -> None:
        open_alert_chart_for_row(
            self,
            row_index,
            chart_modal_cls=ChartModal,
            candle_buffer_max=CANDLE_BUFFER_MAX,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        handle_row_selected(
            self,
            table_id=event.data_table.id,
            cursor_row=event.cursor_row,
            chart_modal_cls=ChartModal,
            candle_buffer_max=CANDLE_BUFFER_MAX,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )

    async def _refresh_news(self) -> None:
        await refresh_news(
            self,
            max_items=NEWS_MAX_ITEMS,
            group_size=NEWS_GROUP_SIZE,
            ticker_limit=NEWS_TICKER_LIMIT,
        )

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
        await refresh_crypto_stream_for_visible_group(self)

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
        return current_visible_symbols(self.main_visible_items)

    async def _preload_visible_group_history(self) -> None:
        if self.boot_modal:
            self.boot_modal.set_phase(tr("Syncing crypto history"))
        await preload_visible_group_history(
            self,
            cache_ttl_seconds=CACHE_TTL_SECONDS,
            initial_history_points=INITIAL_HISTORY_POINTS,
            initial_candle_limit=INITIAL_CANDLE_LIMIT,
            startup_io_concurrency=STARTUP_IO_CONCURRENCY,
            load_symbol_history_cache_fn=load_symbol_history_cache,
            save_symbol_history_cache_fn=save_symbol_history_cache,
        )

    async def _load_remaining_history_in_background(self) -> None:
        await load_remaining_history_in_background(
            self,
            cache_ttl_seconds=CACHE_TTL_SECONDS,
            initial_history_points=INITIAL_HISTORY_POINTS,
            initial_candle_limit=INITIAL_CANDLE_LIMIT,
            startup_io_concurrency=STARTUP_IO_CONCURRENCY,
            load_symbol_history_cache_fn=load_symbol_history_cache,
            save_symbol_history_cache_fn=save_symbol_history_cache,
        )

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
        schedule_stock_refresh(self)

    def _schedule_indicator_refresh(self) -> None:
        schedule_indicator_refresh(self)

    async def _refresh_stocks(self) -> None:
        await refresh_stocks(self)

    async def _refresh_indicators(self) -> None:
        await refresh_indicators(self)

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
        ensure_main_row_capacity(self, required_rows)

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
        apply_market_groups_change(self, resolve_missing_names=resolve_missing_names)

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
        apply_quote(
            self,
            quote,
            fifteen_min_ms=FIFTEEN_MIN_MS,
            candle_cls=Candle,
        )

    def _update_candles(self, symbol: str, price: float, event_time_ms: int) -> None:
        update_candles(
            series=self.candles[symbol],
            candle_cls=Candle,
            price=price,
            event_time_ms=event_time_ms,
            fifteen_min_ms=FIFTEEN_MIN_MS,
        )

    def _refresh_main_row(self, symbol: str, symbol_type: str) -> None:
        refresh_main_row(self, symbol, symbol_type)

    def _apply_stock_quote(self, quote: StockQuote) -> None:
        apply_stock_quote(
            self,
            quote,
            fifteen_min_ms=FIFTEEN_MIN_MS,
            candle_cls=Candle,
        )

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
        reset_local_buffers(
            self,
            symbol_state_factory=SymbolState,
            stock_state_factory=StockState,
        )

    def action_focus_symbol(self, symbol: str) -> None:
        focus_symbol(self, symbol)

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
