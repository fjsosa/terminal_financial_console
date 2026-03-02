from __future__ import annotations

from collections import deque
from typing import Any, Callable, Protocol

from .grouping import advance_symbol_across_groups


class ChartHost(Protocol):
    main_group_items: list[tuple[str, list[tuple[str, str]]]]
    main_group_index: int
    main_row_item_by_index: dict[int, tuple[str, str]]
    alerts_row_item_by_index: dict[int, tuple[str, str]]
    symbol_data: dict[str, Any]
    stock_data: dict[str, Any]
    candles: dict[str, deque[Any]]
    stock_candles: dict[str, deque[Any]]
    crypto_candles_by_tf: dict[str, dict[str, deque[Any]]]
    stock_candles_by_tf: dict[str, dict[str, deque[Any]]]

    def _schedule_symbol_description_fetch(self, symbol: str, symbol_type: str) -> None: ...
    def _build_chart_for_item(
        self, symbol: str, symbol_type: str, timeframe: str, target_candles: int
    ) -> Any: ...
    async def _ensure_chart_history_for_item(
        self, symbol: str, symbol_type: str, timeframe: str, target_candles: int
    ) -> None: ...
    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None: ...
    def _update_main_group_panel(self) -> None: ...
    def _copy_news_link(self, row_index: int) -> None: ...
    def push_screen(self, screen: Any) -> None: ...


def open_chart_for_symbol(
    host: ChartHost,
    symbol: str,
    symbol_type: str,
    *,
    chart_modal_cls: type[Any],
    candle_buffer_max: int,
    symbol_state_factory: Callable[[str], Any],
    stock_state_factory: Callable[[str], Any],
) -> None:
    host._schedule_symbol_description_fetch(symbol, symbol_type)
    current = {"symbol": symbol, "type": symbol_type}

    def chart_builder(tf: str, candles: int):
        return host._build_chart_for_item(current["symbol"], current["type"], tf, candles)

    async def ensure_history(tf: str, candles: int) -> None:
        await host._ensure_chart_history_for_item(current["symbol"], current["type"], tf, candles)

    def navigate(step: int) -> tuple[str, str] | None:
        nxt = advance_symbol_across_groups(
            host.main_group_items,
            symbol=current["symbol"],
            symbol_type=current["type"],
            step=step,
        )
        if not nxt:
            return None
        current["symbol"], current["type"] = nxt
        host._schedule_symbol_description_fetch(current["symbol"], current["type"])
        for i, (_, items) in enumerate(host.main_group_items):
            if nxt in items:
                host.main_group_index = i
                host._pause_group_rotation("crypto_quotes", 60)
                host._update_main_group_panel()
                break
        return nxt

    if symbol_type == "stock":
        if symbol not in host.stock_data:
            host.stock_data[symbol] = stock_state_factory(symbol)
            host.stock_candles[symbol] = deque(maxlen=candle_buffer_max)
            for tf in host.stock_candles_by_tf:
                host.stock_candles_by_tf[tf].setdefault(symbol, deque(maxlen=candle_buffer_max))
        host.push_screen(
            chart_modal_cls(
                symbol=symbol,
                symbol_type=symbol_type,
                chart_builder=chart_builder,
                ensure_history=ensure_history,
                navigate_symbol=navigate,
            )
        )
        return

    if symbol not in host.symbol_data:
        host.symbol_data[symbol] = symbol_state_factory(symbol)
        host.candles[symbol] = deque(maxlen=candle_buffer_max)
        for tf in host.crypto_candles_by_tf:
            host.crypto_candles_by_tf[tf].setdefault(symbol, deque(maxlen=candle_buffer_max))
    host.push_screen(
        chart_modal_cls(
            symbol=symbol,
            symbol_type=symbol_type,
            chart_builder=chart_builder,
            ensure_history=ensure_history,
            navigate_symbol=navigate,
        )
    )


def open_main_chart_for_row(host: ChartHost, row_index: int, **kwargs: Any) -> None:
    item = host.main_row_item_by_index.get(row_index)
    if not item:
        return
    symbol, symbol_type = item
    open_chart_for_symbol(host, symbol, symbol_type, **kwargs)


def open_alert_chart_for_row(host: ChartHost, row_index: int, **kwargs: Any) -> None:
    item = host.alerts_row_item_by_index.get(row_index)
    if not item:
        return
    symbol, symbol_type = item
    open_chart_for_symbol(host, symbol, symbol_type, **kwargs)


def handle_row_selected(
    host: ChartHost,
    *,
    table_id: str,
    cursor_row: int,
    **kwargs: Any,
) -> None:
    if table_id == "crypto_quotes":
        open_main_chart_for_row(host, cursor_row, **kwargs)
        return
    if table_id == "stock_quotes":
        open_alert_chart_for_row(host, cursor_row, **kwargs)
        return
    if table_id == "news_table":
        host._copy_news_link(cursor_row)
