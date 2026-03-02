from __future__ import annotations

from typing import Any


def rotate_news_group(host: Any) -> None:
    if not host.news_groups:
        return
    if host.rotation.is_paused("news_table"):
        return
    host.news_group_index = host.rotation.cycle_index(host.news_group_index, len(host.news_groups))
    host._update_news_panel()


def rotate_main_group(host: Any) -> None:
    if host.is_shutting_down:
        return
    if not host.main_group_items:
        return
    if host.rotation.is_paused("crypto_quotes"):
        return
    host.main_group_index = host.rotation.cycle_index(host.main_group_index, len(host.main_group_items))
    host._update_main_group_panel()
    host._schedule_stock_refresh()
    host._spawn_background(host._refresh_crypto_stream_for_visible_group())
    if host.lazy_history_task and not host.lazy_history_task.done():
        host.lazy_history_task.cancel()
    host.lazy_history_task = host._spawn_background(host._load_remaining_history_in_background())


def rotate_indicator_group(host: Any) -> None:
    if host.is_shutting_down:
        return
    if not host.indicator_group_items:
        return
    if host.rotation.is_paused("indicators_table"):
        return
    host.indicator_group_index = host.rotation.cycle_index(
        host.indicator_group_index, len(host.indicator_group_items)
    )
    host._update_indicators_panel()
    host._schedule_indicator_refresh()


def pause_group_rotation(host: Any, table_id: str, seconds: int = 60) -> None:
    host.rotation.pause(table_id, seconds)


def cycle_main_group(host: Any, step: int) -> None:
    if host.is_shutting_down:
        return
    if not host.main_group_items:
        return
    host.main_group_index = host.rotation.cycle_index(
        host.main_group_index, len(host.main_group_items), step
    )
    pause_group_rotation(host, "crypto_quotes", 60)
    host._update_main_group_panel()
    host._schedule_stock_refresh()
    host._spawn_background(host._refresh_crypto_stream_for_visible_group())


def cycle_news_group(host: Any, step: int) -> None:
    if not host.news_groups:
        return
    host.news_group_index = host.rotation.cycle_index(host.news_group_index, len(host.news_groups), step)
    pause_group_rotation(host, "news_table", 60)
    host._update_news_panel()


def cycle_indicator_group(host: Any, step: int) -> None:
    if not host.indicator_group_items:
        return
    host.indicator_group_index = host.rotation.cycle_index(
        host.indicator_group_index,
        len(host.indicator_group_items),
        step,
    )
    pause_group_rotation(host, "indicators_table", 60)
    host._update_indicators_panel()
    host._schedule_indicator_refresh()
