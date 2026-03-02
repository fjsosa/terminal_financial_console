from __future__ import annotations

from typing import Any, Protocol


class FocusHost(Protocol):
    symbol_data: dict[str, Any]
    stock_data: dict[str, Any]
    indicator_data: dict[str, Any]
    main_group_items: list[tuple[str, list[tuple[str, str]]]]
    indicator_group_items: list[tuple[str, list[tuple[str, str]]]]
    main_group_index: int
    indicator_group_index: int
    main_row_item_by_index: dict[int, tuple[str, str]]
    indicator_row_item_by_index: dict[int, tuple[str, str]]
    focused_symbol: str | None

    def _pause_group_rotation(self, table_id: str, seconds: int = 60) -> None: ...
    def _update_main_group_panel(self) -> None: ...
    def _update_indicators_panel(self) -> None: ...
    def query_one(self, selector: str, cls: type[Any]) -> Any: ...
    def _log(self, message: str) -> None: ...


def _resolve_symbol_type(host: FocusHost, symbol: str) -> tuple[str, bool]:
    if symbol in host.symbol_data:
        return "crypto", False
    if symbol in host.stock_data:
        return "stock", False
    if symbol in host.indicator_data:
        return "stock", True

    for _, items in host.main_group_items:
        for item_symbol, item_type in items:
            if item_symbol == symbol:
                return item_type, False
    for _, items in host.indicator_group_items:
        for item_symbol, item_type in items:
            if item_symbol == symbol:
                return item_type, True
    return "", False


def focus_symbol(host: FocusHost, symbol: str) -> None:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return

    symbol_type, in_indicator_groups = _resolve_symbol_type(host, symbol)
    if symbol_type not in {"crypto", "stock"}:
        host._log(f"[yellow]Quick action:[/] symbol {symbol} not found in configured groups")
        return

    host.focused_symbol = symbol
    if symbol_type == "crypto":
        state = host.symbol_data.get(symbol)
        for i, (_, items) in enumerate(host.main_group_items):
            if (symbol, symbol_type) in items:
                host.main_group_index = i
                host._pause_group_rotation("crypto_quotes", 60)
                host._update_main_group_panel()
                break
        if state is not None:
            host._log(
                f"[bold #99e2ff]{symbol}[/] "
                f"price={state.price:,.4f} change={state.change_percent:+.2f}% volume={state.volume:,.2f}"
            )
        table = host.query_one("#crypto_quotes", object)
        for row_index, item in host.main_row_item_by_index.items():
            if item == (symbol, symbol_type):
                table.move_cursor(row=row_index)
                break
        return

    state = host.indicator_data.get(symbol) if in_indicator_groups else host.stock_data.get(symbol)
    target_table_id = "#indicators_table" if in_indicator_groups else "#crypto_quotes"
    target_items = host.indicator_row_item_by_index if in_indicator_groups else host.main_row_item_by_index
    if in_indicator_groups:
        for i, (_, items) in enumerate(host.indicator_group_items):
            if (symbol, symbol_type) in items:
                host.indicator_group_index = i
                host._pause_group_rotation("indicators_table", 60)
                host._update_indicators_panel()
                break
    else:
        for i, (_, items) in enumerate(host.main_group_items):
            if (symbol, symbol_type) in items:
                host.main_group_index = i
                host._pause_group_rotation("crypto_quotes", 60)
                host._update_main_group_panel()
                break

    if state is not None:
        host._log(
            f"[bold #99e2ff]{symbol}[/] "
            f"price={state.price:,.4f} change={state.change_percent:+.2f}% volume={state.volume:,.2f}"
        )
    table = host.query_one(target_table_id, object)
    for row_index, item in target_items.items():
        if item == (symbol, symbol_type):
            table.move_cursor(row=row_index)
            break
