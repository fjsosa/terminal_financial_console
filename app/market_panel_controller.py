from __future__ import annotations

from collections import deque
from typing import Any, Protocol

from rich.text import Text

from .constants import ID_MAIN_TABLE, SYMBOL_TYPE_CRYPTO, SYMBOL_TYPE_STOCK
from .grouping import build_main_groups
from .market_runtime import apply_quote_to_state, update_candles
from .models import Quote


class MarketPanelHost(Protocol):
    crypto_symbols: list[str]
    stock_symbols: list[str]
    market_groups: list[dict[str, Any]]
    main_group_items: list[tuple[str, list[tuple[str, str]]]]
    main_group_index: int
    main_row_keys: list[Any]
    main_col_keys: dict[str, Any]
    main_row_item_by_index: dict[int, tuple[str, str]]
    symbol_data: dict[str, Any]
    stock_data: dict[str, Any]
    candles: dict[str, deque[Any]]
    stock_candles: dict[str, deque[Any]]
    crypto_candles_by_tf: dict[str, dict[str, deque[Any]]]
    stock_candles_by_tf: dict[str, dict[str, deque[Any]]]
    name_resolve_task: Any
    last_tick_ms: int

    def query_one(self, selector: str, cls: type[Any]) -> Any: ...
    def _update_main_group_panel(self) -> None: ...
    def _update_alerts_panel(self) -> None: ...
    def _spawn_background(self, coro: Any) -> Any: ...
    def _refresh_crypto_stream_for_visible_group(self) -> Any: ...
    def _schedule_stock_refresh(self) -> None: ...
    def _resolve_names_background(self) -> Any: ...
    def _sync_market_data_structures(self) -> None: ...
    def _trend_color(self, is_up: bool, symbol_type: str | None = None) -> str: ...
    def _format_volume(self, volume: float, width: int = 17) -> str: ...
    def _sparkline(self, values: deque[float]) -> Text: ...
    def _ticker_label(self, symbol: str, symbol_type: str, max_name_len: int = 20) -> Text: ...
    def _new_stock_state(self, symbol: str) -> Any: ...


def ensure_main_row_capacity(host: MarketPanelHost, required_rows: int) -> None:
    table = host.query_one(ID_MAIN_TABLE, object)
    while len(host.main_row_keys) < required_rows:
        idx = len(host.main_row_keys)
        row_key = table.add_row("-", "-", "-", "-", "-", "", key=f"main_{idx}")
        host.main_row_keys.append(row_key)


def apply_market_groups_change(host: MarketPanelHost, *, resolve_missing_names: bool = False) -> None:
    host.main_group_items = build_main_groups(
        host.market_groups,
        crypto_symbols=host.crypto_symbols,
        stock_symbols=host.stock_symbols,
    )
    host._sync_market_data_structures()
    if host.main_group_items:
        host.main_group_index %= len(host.main_group_items)
        required = max(1, max(len(items) for _, items in host.main_group_items))
    else:
        host.main_group_index = 0
        required = 1
    ensure_main_row_capacity(host, required)
    host._update_main_group_panel()
    host._update_alerts_panel()
    host._spawn_background(host._refresh_crypto_stream_for_visible_group())
    host._schedule_stock_refresh()
    if resolve_missing_names:
        if host.name_resolve_task and not host.name_resolve_task.done():
            host.name_resolve_task.cancel()
        host.name_resolve_task = host._spawn_background(host._resolve_names_background())


def apply_quote(host: MarketPanelHost, quote: Quote, *, fifteen_min_ms: int, candle_cls: type[Any]) -> None:
    host.last_tick_ms = quote.event_time_ms
    apply_quote_to_state(
        state=host.symbol_data[quote.symbol],
        price=quote.price,
        change_percent=quote.change_percent,
        volume=quote.volume,
        event_time_ms=quote.event_time_ms,
    )
    update_candles(
        series=host.candles[quote.symbol],
        candle_cls=candle_cls,
        price=quote.price,
        event_time_ms=quote.event_time_ms,
        fifteen_min_ms=fifteen_min_ms,
    )
    host._update_main_group_panel()
    host._update_alerts_panel()


def apply_stock_quote(
    host: MarketPanelHost, quote: Any, *, fifteen_min_ms: int, candle_cls: type[Any]
) -> None:
    state = host.stock_data.get(quote.symbol)
    if state is None:
        return
    apply_quote_to_state(
        state=state,
        price=quote.price,
        change_percent=quote.change_percent,
        volume=quote.volume,
        event_time_ms=quote.event_time_ms,
    )
    update_candles(
        series=host.stock_candles[quote.symbol],
        candle_cls=candle_cls,
        price=quote.price,
        event_time_ms=quote.event_time_ms,
        fifteen_min_ms=fifteen_min_ms,
    )
    host._update_main_group_panel()
    host._update_alerts_panel()


def refresh_main_row(host: MarketPanelHost, symbol: str, symbol_type: str) -> None:
    table = host.query_one(ID_MAIN_TABLE, object)
    row_index = None
    for idx, item in host.main_row_item_by_index.items():
        if item == (symbol, symbol_type):
            row_index = idx
            break
    if row_index is None or not host.main_col_keys or row_index >= len(host.main_row_keys):
        return
    row_key = host.main_row_keys[row_index]

    if symbol_type == SYMBOL_TYPE_CRYPTO:
        state = host.symbol_data.get(symbol)
        if state is None:
            return
        color = host._trend_color(state.change_percent >= 0, symbol_type=SYMBOL_TYPE_CRYPTO)
        price = Text(f"{state.price:>13,.2f}", style=color)
        change = Text(f"{state.change_percent:>+8.2f}%", style=f"bold {color}")
        volume = host._format_volume(state.volume, 17)
        spark = host._sparkline(state.points or deque())
        type_label = "CRT"
    else:
        state = host.stock_data.get(symbol)
        if state is None:
            state = host._new_stock_state(symbol)
            host.stock_data[symbol] = state
        color = host._trend_color(state.change_percent >= 0, symbol_type=SYMBOL_TYPE_STOCK)
        price = Text(f"{state.price:>13,.2f}", style=color)
        change = Text(f"{state.change_percent:>+8.2f}%", style=f"bold {color}")
        volume = host._format_volume(state.volume, 17)
        spark = host._sparkline(state.points or deque())
        type_label = "STK"

    table.update_cell(row_key, host.main_col_keys["symbol"], host._ticker_label(symbol, symbol_type))
    table.update_cell(row_key, host.main_col_keys["type"], type_label)
    table.update_cell(row_key, host.main_col_keys["price"], price)
    table.update_cell(row_key, host.main_col_keys["change"], change)
    table.update_cell(row_key, host.main_col_keys["volume"], volume)
    table.update_cell(row_key, host.main_col_keys["spark"], spark)
