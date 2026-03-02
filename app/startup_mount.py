from __future__ import annotations

from typing import Any, Callable

from .constants import (
    ID_ALERTS_TABLE,
    ID_COMMAND_INPUT,
    ID_EVENTS,
    ID_INDICATORS_TABLE,
    ID_MAIN_TABLE,
    ID_NEWS_HEADER,
    ID_NEWS_TABLE,
)


def configure_tables(
    host: Any,
    *,
    alerts_table_size: int,
    news_group_size: int,
    max_events: int,
    tr_fn: Callable[[str], str],
) -> None:
    main_table = host.query_one(ID_MAIN_TABLE)
    main_table.cursor_type = "row"
    main_table.zebra_stripes = True
    col_symbol = main_table.add_column(tr_fn("Ticker"), width=25)
    col_type = main_table.add_column(tr_fn("Type"), width=4)
    col_price = main_table.add_column(tr_fn("Price"), width=13)
    col_change = main_table.add_column("24h %", width=9)
    col_volume = main_table.add_column(tr_fn("Volume"), width=17)
    col_spark = main_table.add_column(tr_fn("Spark"))
    host.main_col_keys = {
        "symbol": col_symbol,
        "type": col_type,
        "price": col_price,
        "change": col_change,
        "volume": col_volume,
        "spark": col_spark,
    }
    host.main_row_keys.clear()
    main_rows = max(1, max((len(items) for _, items in host.main_group_items), default=1))
    for i in range(main_rows):
        row_key = main_table.add_row("-", "-", "-", "-", "-", "", key=f"main_{i}")
        host.main_row_keys.append(row_key)
    host._update_main_group_panel()

    alerts_table = host.query_one(ID_ALERTS_TABLE)
    alerts_table.cursor_type = "row"
    alerts_table.zebra_stripes = True
    a_symbol = alerts_table.add_column(tr_fn("Ticker"), width=25)
    a_type = alerts_table.add_column(tr_fn("Type"), width=4)
    a_change = alerts_table.add_column("24h %", width=9)
    a_price = alerts_table.add_column(tr_fn("Price"), width=13)
    a_volume = alerts_table.add_column(tr_fn("Volume"), width=17)
    host.alerts_col_keys = {
        "symbol": a_symbol,
        "type": a_type,
        "change": a_change,
        "price": a_price,
        "volume": a_volume,
    }
    host.alerts_row_keys.clear()
    for i in range(alerts_table_size):
        row_key = alerts_table.add_row("-", "-", "-", "-", "-", key=f"alert_{i}")
        host.alerts_row_keys.append(row_key)
    host._update_alerts_panel()

    indicators_table = host.query_one(ID_INDICATORS_TABLE)
    indicators_table.cursor_type = "row"
    indicators_table.zebra_stripes = True
    i_symbol = indicators_table.add_column(tr_fn("Indicator"), width=30)
    i_change = indicators_table.add_column("24h %", width=9)
    i_price = indicators_table.add_column(tr_fn("Price"), width=13)
    host.indicator_col_keys = {
        "symbol": i_symbol,
        "change": i_change,
        "price": i_price,
    }
    host.indicator_row_keys.clear()
    indicator_rows = max(1, max((len(items) for _, items in host.indicator_group_items), default=1))
    for i in range(indicator_rows):
        row_key = indicators_table.add_row("-", "-", "-", key=f"indicator_{i}")
        host.indicator_row_keys.append(row_key)
    host._update_indicators_panel()

    news_table = host.query_one(ID_NEWS_TABLE)
    news_table.cursor_type = "row"
    news_table.zebra_stripes = True
    news_table.show_horizontal_scrollbar = False
    n_title = news_table.add_column(tr_fn("Headline"), width=82)
    host.news_col_keys = {"title": n_title}
    host.news_row_keys.clear()
    for i in range(news_group_size):
        row_key = news_table.add_row(
            tr_fn("Loading headlines...\nPlease wait\n"),
            key=f"news_{i}",
            height=3,
        )
        host.news_row_keys.append(row_key)

    events_log = host.query_one(ID_EVENTS)
    events_log.max_lines = max_events


def initialize_mount_state(
    host: Any,
    *,
    tr_fn: Callable[[str], str],
    create_task_fn: Callable[[Any], Any],
) -> None:
    host._log(tr_fn("Booting market stream..."))
    host._load_cached_descriptions()
    host._load_cached_symbol_names()
    host._log("[#6f8aa8]NAMES[/] resolving symbol names in background...")
    host.name_resolve_task = create_task_fn(host._resolve_names_background())
    palette = host._ui_palette()
    host.query_one(ID_NEWS_HEADER).update(
        f"[{palette['accent']}]{tr_fn('NEWS // finviz.com (refresh {minutes}m)').format(minutes=10)}[/]"
    )
    command_input = host.query_one(ID_COMMAND_INPUT)
    command_input.value = ""
    command_input.display = False
    host._render_status_line()


def schedule_mount_intervals(
    host: Any,
    *,
    ticker_mode_seconds: int,
    news_refresh_seconds: int,
    calendar_refresh_seconds: int,
    news_group_rotate_seconds: int,
    stock_group_rotate_seconds: int,
    stocks_refresh_seconds: int,
) -> None:
    host.set_interval(0.5, host._update_clock)
    host.set_interval(0.15, host._animate_ticker)
    host.set_interval(ticker_mode_seconds, host._rotate_ticker_mode)
    host.set_interval(news_refresh_seconds, host._schedule_news_refresh)
    host.set_interval(calendar_refresh_seconds, host._schedule_calendar_refresh)
    host.set_interval(news_group_rotate_seconds, host._rotate_news_group)
    host.set_interval(stock_group_rotate_seconds, host._rotate_main_group)
    host.set_interval(stock_group_rotate_seconds, host._rotate_indicator_group)
    host.set_interval(stocks_refresh_seconds, host._schedule_stock_refresh)
    host.set_interval(stocks_refresh_seconds, host._schedule_indicator_refresh)


def refresh_theme_panels(host: Any) -> None:
    host._update_news_panel()
    host._update_main_group_panel()
    host._update_indicators_panel()
    host._update_alerts_panel()
    host._render_status_line()
    host._update_clock()
