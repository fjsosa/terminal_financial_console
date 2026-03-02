from __future__ import annotations

import contextlib
from typing import Any, Protocol

from rich.text import Text
from textual.widgets import DataTable, Static

from .i18n import tr


class TableHost(Protocol):
    main_group_items: list[tuple[str, list[tuple[str, str]]]]
    main_group_index: int
    main_visible_items: list[tuple[str, str]]
    main_row_item_by_index: dict[int, tuple[str, str]]
    main_row_keys: list[Any]
    main_col_keys: dict[str, Any]
    stocks_last_update: str

    indicator_group_items: list[tuple[str, list[tuple[str, str]]]]
    indicator_group_index: int
    indicator_visible_items: list[tuple[str, str]]
    indicator_row_item_by_index: dict[int, tuple[str, str]]
    indicator_row_keys: list[Any]
    indicator_col_keys: dict[str, Any]
    indicators_last_update: str
    indicator_data: dict[str, Any]

    symbol_data: dict[str, Any]
    stock_data: dict[str, Any]
    alerts_row_item_by_index: dict[int, tuple[str, str]]
    alerts_row_keys: list[Any]
    alerts_col_keys: dict[str, Any]

    news_groups: list[tuple[str, list[Any]]]
    news_group_index: int
    news_last_update: str
    news_row_links: dict[int, str]
    news_row_keys: list[Any]
    news_col_keys: dict[str, Any]

    def query_one(self, selector: str, cls: type[Any]) -> Any: ...
    def _ui_palette(self) -> dict[str, str]: ...
    def _trend_color(self, is_up: bool, symbol_type: str | None = None) -> str: ...
    def _ticker_label(self, symbol: str, symbol_type: str, max_name_len: int = 20) -> Text: ...
    def _format_volume(self, volume: float, width: int = 17) -> str: ...
    def _format_news_headline(self, source: str, age: str, title: str, line_len: int = 86) -> Text: ...
    def _refresh_main_row(self, symbol: str, symbol_type: str) -> None: ...
    def _get_change_percent(self, symbol: str, symbol_type: str) -> float: ...
    def _new_stock_state(self, symbol: str) -> Any: ...


def update_main_group_panel(host: TableHost) -> None:
    table = host.query_one("#crypto_quotes", DataTable)
    if not host.main_group_items:
        host.main_visible_items = []
        host.main_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" [{tr('group')} 0/0] "
                f"[{tr('updated')} {host.stocks_last_update}] "
            )
        for i, row_key in enumerate(host.main_row_keys):
            table.update_cell(row_key, host.main_col_keys["symbol"], "-" if i == 0 else "")
            table.update_cell(row_key, host.main_col_keys["type"], "-")
            table.update_cell(row_key, host.main_col_keys["price"], "-")
            table.update_cell(row_key, host.main_col_keys["change"], "-")
            table.update_cell(row_key, host.main_col_keys["volume"], "-")
            table.update_cell(row_key, host.main_col_keys["spark"], "")
        return

    group_name, items = host.main_group_items[host.main_group_index]
    sorted_items = sorted(
        items,
        key=lambda item: host._get_change_percent(item[0], item[1]),
        reverse=True,
    )
    host.main_visible_items = sorted_items
    host.main_row_item_by_index.clear()
    with contextlib.suppress(Exception):
        table.border_title = (
            f" {group_name.upper()} "
            f"[{tr('group')} {host.main_group_index + 1}/{len(host.main_group_items)}] "
            f"[{tr('updated')} {host.stocks_last_update}] "
        )

    for i, row_key in enumerate(host.main_row_keys):
        if i < len(sorted_items):
            symbol, symbol_type = sorted_items[i]
            host.main_row_item_by_index[i] = (symbol, symbol_type)
            host._refresh_main_row(symbol, symbol_type)
            continue

        table.update_cell(row_key, host.main_col_keys["symbol"], "")
        table.update_cell(row_key, host.main_col_keys["type"], "")
        table.update_cell(row_key, host.main_col_keys["price"], "")
        table.update_cell(row_key, host.main_col_keys["change"], "")
        table.update_cell(row_key, host.main_col_keys["volume"], "")
        table.update_cell(row_key, host.main_col_keys["spark"], "")


def update_indicators_panel(host: TableHost) -> None:
    table = host.query_one("#indicators_table", DataTable)
    if not host.indicator_group_items:
        host.indicator_visible_items = []
        host.indicator_row_item_by_index.clear()
        with contextlib.suppress(Exception):
            table.border_title = (
                f" {tr('INDICATORS')} "
                f"[{tr('group')} 0/0] "
                f"[{tr('updated')} {host.indicators_last_update}] "
            )
        for i, row_key in enumerate(host.indicator_row_keys):
            table.update_cell(row_key, host.indicator_col_keys["symbol"], "-" if i == 0 else "")
            table.update_cell(row_key, host.indicator_col_keys["change"], "-")
            table.update_cell(row_key, host.indicator_col_keys["price"], "-")
        return

    group_name, items = host.indicator_group_items[host.indicator_group_index]
    sorted_items = sorted(
        items,
        key=lambda item: getattr(host.indicator_data.get(item[0]), "change_percent", 0.0),
        reverse=True,
    )
    host.indicator_visible_items = sorted_items
    host.indicator_row_item_by_index.clear()
    with contextlib.suppress(Exception):
        table.border_title = (
            f" {group_name.upper()} "
            f"[{tr('group')} {host.indicator_group_index + 1}/{len(host.indicator_group_items)}] "
            f"[{tr('updated')} {host.indicators_last_update}] "
        )

    for i, row_key in enumerate(host.indicator_row_keys):
        if i >= len(sorted_items):
            table.update_cell(row_key, host.indicator_col_keys["symbol"], "")
            table.update_cell(row_key, host.indicator_col_keys["change"], "")
            table.update_cell(row_key, host.indicator_col_keys["price"], "")
            continue

        symbol, symbol_type = sorted_items[i]
        host.indicator_row_item_by_index[i] = (symbol, symbol_type)
        state = host.indicator_data.get(symbol)
        if state is None:
            state = host._new_stock_state(symbol)
            host.indicator_data[symbol] = state
        color = host._trend_color(state.change_percent >= 0, symbol_type="stock")
        table.update_cell(
            row_key,
            host.indicator_col_keys["symbol"],
            host._ticker_label(symbol, symbol_type, max_name_len=25),
        )
        table.update_cell(
            row_key,
            host.indicator_col_keys["change"],
            Text(f"{state.change_percent:>+8.2f}%", style=f"bold {color}"),
        )
        table.update_cell(
            row_key,
            host.indicator_col_keys["price"],
            Text(f"{state.price:>13,.2f}", style=color),
        )


def update_alerts_panel(host: TableHost, alerts_table_size: int) -> None:
    table = host.query_one("#stock_quotes", DataTable)
    entries: list[tuple[str, str, float, float, float]] = []
    for symbol, state in host.symbol_data.items():
        if state.price <= 0 and state.last_update_ms <= 0:
            continue
        entries.append((symbol, "crypto", state.change_percent, state.price, state.volume))
    for symbol, state in host.stock_data.items():
        if state.price <= 0 and state.last_update_ms <= 0:
            continue
        entries.append((symbol, "stock", state.change_percent, state.price, state.volume))

    entries.sort(key=lambda item: item[2], reverse=True)
    top = entries[:alerts_table_size]
    host.alerts_row_item_by_index.clear()
    with contextlib.suppress(Exception):
        table.border_title = (
            f" {tr('ALERTAS')} "
            f"[{tr('updated')} {host.stocks_last_update}] "
        )

    for i, row_key in enumerate(host.alerts_row_keys):
        if i >= len(top):
            table.update_cell(row_key, host.alerts_col_keys["symbol"], "")
            table.update_cell(row_key, host.alerts_col_keys["type"], "")
            table.update_cell(row_key, host.alerts_col_keys["change"], "")
            table.update_cell(row_key, host.alerts_col_keys["price"], "")
            table.update_cell(row_key, host.alerts_col_keys["volume"], "")
            continue

        symbol, symbol_type, change_pct, price, volume = top[i]
        host.alerts_row_item_by_index[i] = (symbol, symbol_type)
        color = host._trend_color(change_pct >= 0, symbol_type=symbol_type)
        type_label = "CRT" if symbol_type == "crypto" else "STK"
        table.update_cell(row_key, host.alerts_col_keys["symbol"], host._ticker_label(symbol, symbol_type))
        table.update_cell(row_key, host.alerts_col_keys["type"], type_label)
        table.update_cell(
            row_key,
            host.alerts_col_keys["change"],
            Text(f"{change_pct:>+8.2f}%", style=f"bold {color}"),
        )
        table.update_cell(
            row_key,
            host.alerts_col_keys["price"],
            Text(f"{price:>13,.2f}", style=color),
        )
        table.update_cell(row_key, host.alerts_col_keys["volume"], host._format_volume(volume, 17))


def update_news_panel(host: TableHost, news_group_size: int, news_refresh_seconds: int) -> None:
    header = host.query_one("#news_header", Static)
    table = host.query_one("#news_table", DataTable)

    if not host.news_groups:
        header.update(Text("NEWS // finviz.com (refresh 10m)", style=host._ui_palette()["accent"]))
        host.news_row_links.clear()
        for i in range(news_group_size):
            row_key = host.news_row_keys[i]
            table.update_cell(
                row_key,
                host.news_col_keys["title"],
                Text(tr("No headlines available\nTry refresh [n]\n")),
            )
        return

    category, items = host.news_groups[host.news_group_index]
    palette = host._ui_palette()
    title_style = (
        palette["ok"]
        if "CRYPTO" in category
        else palette["warn"] if "STOCK" in category else palette["accent"]
    )
    header_txt = Text()
    header_txt.append(f"{category} // ", style=f"bold {title_style}")
    header_txt.append("finviz.com", style=palette["accent"])
    header_txt.append(f" (refresh {news_refresh_seconds // 60}m) ", style=palette["muted"])
    header_txt.append(
        f"[group {host.news_group_index + 1}/{len(host.news_groups)} | updated {host.news_last_update}]",
        style=palette["muted"],
    )
    header.update(header_txt)

    host.news_row_links.clear()
    for i in range(news_group_size):
        row_key = host.news_row_keys[i]
        if i < len(items):
            item = items[i]
            host.news_row_links[i] = item.url
            source = (item.source or "source").strip()
            age = (item.age or "-").strip()
            table.update_cell(
                row_key,
                host.news_col_keys["title"],
                host._format_news_headline(
                    source=source,
                    age=age,
                    title=item.title,
                    line_len=72,
                ),
            )
        else:
            table.update_cell(row_key, host.news_col_keys["title"], Text("\n\n"))
