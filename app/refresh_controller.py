from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .constants import SYMBOL_TYPE_STOCK
from .i18n import tr
from .models import StockState
from .refresh_services import refresh_calendar_data, refresh_news_data, refresh_stock_quotes


class RefreshHost(Protocol):
    is_shutting_down: bool
    local_tz: Any
    calendars: list[dict[str, str]]
    calendar_events: list[Any]
    calendar_last_update: str
    news_groups: list[tuple[str, list[Any]]]
    news_latest_items: list[Any]
    news_last_update: str
    news_group_index: int
    stock_symbols: list[str]
    indicator_symbols: list[str]
    main_visible_items: list[tuple[str, str]]
    indicator_visible_items: list[tuple[str, str]]
    indicator_data: dict[str, Any]
    stocks_last_update: str
    indicators_last_update: str

    def _spawn_background(self, coro: Any) -> Any: ...
    async def _refresh_news(self) -> None: ...
    async def _refresh_calendar(self) -> None: ...
    async def _refresh_stocks(self) -> None: ...
    async def _refresh_indicators(self) -> None: ...
    def _news_age_minutes(self, age: str) -> int: ...
    def _update_news_panel(self) -> None: ...
    def _update_main_group_panel(self) -> None: ...
    def _update_alerts_panel(self) -> None: ...
    def _update_indicators_panel(self) -> None: ...
    def _apply_stock_quote(self, quote: Any) -> None: ...
    def _new_stock_state(self, symbol: str) -> StockState: ...
    def _log(self, message: str) -> None: ...
    def _ui_palette(self) -> dict[str, str]: ...

    @property
    def news_provider(self) -> Any: ...

    @property
    def calendar_provider(self) -> Any: ...

    @property
    def stock_provider(self) -> Any: ...


def schedule_news_refresh(host: RefreshHost) -> None:
    if host.is_shutting_down:
        return
    host._spawn_background(host._refresh_news())


def schedule_calendar_refresh(host: RefreshHost) -> None:
    if host.is_shutting_down:
        return
    host._spawn_background(host._refresh_calendar())


def schedule_stock_refresh(host: RefreshHost) -> None:
    if host.is_shutting_down:
        return
    host._spawn_background(host._refresh_stocks())


def schedule_indicator_refresh(host: RefreshHost) -> None:
    if host.is_shutting_down:
        return
    host._spawn_background(host._refresh_indicators())


async def refresh_calendar(host: RefreshHost, *, horizon_days: int) -> None:
    if not host.calendars:
        host._log(
            f"[{host._ui_palette()['warn']}]CALENDAR[/] "
            f"{tr('no calendars configured in config.yml')}"
        )
        return
    try:
        result = await refresh_calendar_data(
            provider=host.calendar_provider,
            calendars=host.calendars,
            horizon_days=horizon_days,
            local_now=lambda: datetime.now(host.local_tz),
        )
        host.calendar_events = result.events
        host.calendar_last_update = result.last_update_hhmm
        host._log(
            f"[{host._ui_palette()['accent']}]CALENDAR[/] refreshed {len(result.events)} events "
            f"from {result.calendar_count} calendars (next {horizon_days}d)"
        )
    except Exception as exc:
        host._log(f"[{host._ui_palette()['warn']}]Calendar warning:[/] {exc!r}")


async def refresh_news(
    host: RefreshHost,
    *,
    max_items: int,
    group_size: int,
    ticker_limit: int,
) -> None:
    try:
        result = await refresh_news_data(
            provider=host.news_provider,
            max_items=max_items,
            group_size=group_size,
            ticker_limit=ticker_limit,
            local_now=lambda: datetime.now(host.local_tz),
            age_minutes=host._news_age_minutes,
        )
        host.news_groups = result.groups
        host.news_latest_items = result.latest_items
        host.news_last_update = result.last_update_hhmm
        host.news_group_index = 0
        host._update_news_panel()
        host._log(
            f"[#2ec4b6]NEWS[/] refreshed {result.total_items} headlines across {result.feed_count} feeds"
        )
    except Exception as exc:
        host._log(f"[yellow]News warning:[/] {exc!r}")


async def refresh_stocks(host: RefreshHost) -> None:
    if not host.stock_symbols:
        return
    visible_stock_symbols = [s for s, t in host.main_visible_items if t == SYMBOL_TYPE_STOCK]
    symbols_to_refresh = visible_stock_symbols or host.stock_symbols
    if not symbols_to_refresh:
        return
    try:
        result = await refresh_stock_quotes(
            provider=host.stock_provider,
            symbols=symbols_to_refresh,
            local_now=lambda: datetime.now(host.local_tz),
        )
        for quote in result.quotes:
            host._apply_stock_quote(quote)
        host.stocks_last_update = result.last_update_hhmm
        host._update_main_group_panel()
        host._update_alerts_panel()
        host._log(
            f"[#2ec4b6]STOCKS[/] refreshed {len(result.quotes)} symbols "
            f"({result.symbols_requested} in active group)"
        )
    except Exception as exc:
        host._log(f"[yellow]Stocks warning:[/] {exc!r}")


async def refresh_indicators(host: RefreshHost) -> None:
    if not host.indicator_symbols:
        return
    visible_symbols = [s for s, _ in host.indicator_visible_items]
    symbols_to_refresh = visible_symbols or host.indicator_symbols
    if not symbols_to_refresh:
        return
    try:
        result = await refresh_stock_quotes(
            provider=host.stock_provider,
            symbols=symbols_to_refresh,
            local_now=lambda: datetime.now(host.local_tz),
        )
        for quote in result.quotes:
            state = host.indicator_data.get(quote.symbol)
            if state is None:
                state = host._new_stock_state(quote.symbol)
                host.indicator_data[quote.symbol] = state
            state.price = quote.price
            state.change_percent = quote.change_percent
            state.volume = quote.volume
            state.last_update_ms = quote.event_time_ms
        host.indicators_last_update = result.last_update_hhmm
        host._update_indicators_panel()
        host._log(
            f"[#2ec4b6]{tr('INDICATORS')}[/] refreshed {len(result.quotes)} symbols "
            f"({result.symbols_requested} in active group)"
        )
    except Exception as exc:
        host._log(f"[yellow]{tr('INDICATORS')} warning:[/] {exc!r}")
