from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from .grouping import build_symbol_groups
from .symbol_names import resolve_symbol_names, update_config_group_names

T = TypeVar("T")


class NameResolutionHost(Protocol):
    market_groups: list[dict[str, Any]]
    indicator_groups: list[dict[str, Any]]
    indicator_group_items: list[tuple[str, list[tuple[str, str]]]]
    indicator_symbols: list[str]
    indicator_data: dict[str, Any]
    symbol_names: dict[tuple[str, str], str]
    symbol_descriptions: dict[tuple[str, str], str]
    symbol_categories: dict[tuple[str, str], str]
    symbols_from_config: bool
    config_path: str

    def _log(self, message: str) -> None: ...
    def _update_main_group_panel(self) -> None: ...
    def _update_indicators_panel(self) -> None: ...
    def _update_alerts_panel(self) -> None: ...
    def _new_stock_state(self, symbol: str) -> Any: ...


def load_cached_symbol_names(
    host: NameResolutionHost,
    *,
    ttl_seconds: int,
    load_names_cache_fn: Callable[[int], dict[tuple[str, str], str] | None],
) -> None:
    cached = load_names_cache_fn(ttl_seconds)
    if not cached:
        host._log("[#6f8aa8]NAMES[/] no fresh local cache")
        return
    host.symbol_names.update(cached)
    host._log(f"[#2ec4b6]NAMES[/] loaded {len(cached)} cached names")


def load_cached_descriptions(
    host: NameResolutionHost,
    *,
    ttl_seconds: int,
    load_descriptions_cache_fn: Callable[[int], dict[tuple[str, str], str] | None],
    load_categories_cache_fn: Callable[[int], dict[tuple[str, str], str] | None],
) -> None:
    cached = load_descriptions_cache_fn(ttl_seconds) or {}
    added = 0
    for key, value in cached.items():
        if key in host.symbol_descriptions:
            continue
        host.symbol_descriptions[key] = value
        added += 1
    if added:
        host._log(f"[#2ec4b6]DESC[/] loaded {added} cached descriptions")

    cached_categories = load_categories_cache_fn(ttl_seconds) or {}
    cat_added = 0
    for key, value in cached_categories.items():
        if key in host.symbol_categories:
            continue
        host.symbol_categories[key] = value
        cat_added += 1
    if cat_added:
        host._log(f"[#2ec4b6]DESC[/] loaded {cat_added} cached categories")


async def resolve_names_background(
    host: NameResolutionHost,
    *,
    run_io: Callable[..., Awaitable[T]] = asyncio.to_thread,
    resolve_symbol_names_fn: Callable[..., Any] = resolve_symbol_names,
    save_names_cache_fn: Callable[[dict[tuple[str, str], str]], None] | None = None,
    update_config_group_names_fn: Callable[..., bool] = update_config_group_names,
) -> None:
    try:
        groups, indicator_groups, names, stats = await run_io(
            resolve_symbol_names_fn,
            host.market_groups,
            host.indicator_groups,
        )
    except asyncio.CancelledError:
        return
    except Exception as exc:
        host._log(f"[yellow]Names warning:[/] {exc!r}")
        return

    host.market_groups = groups
    host.indicator_groups = indicator_groups
    host.indicator_group_items = build_symbol_groups(
        host.indicator_groups,
        fallback_name="INDICATORS",
    )
    host.indicator_symbols = sorted(
        {symbol for _, items in host.indicator_group_items for symbol, _ in items}
    )
    for symbol in host.indicator_symbols:
        host.indicator_data.setdefault(symbol, host._new_stock_state(symbol))
    for symbol in list(host.indicator_data):
        if symbol not in host.indicator_symbols:
            host.indicator_data.pop(symbol, None)
    host.symbol_names.update(names)
    if save_names_cache_fn is not None:
        save_names_cache_fn(host.symbol_names)
    host._log(
        f"[#2ec4b6]NAMES[/] stocks={stats['stocks_total']} "
        f"(missing={stats['stocks_missing_name']}, resolved={stats['stocks_resolved_remote']})"
    )
    host._log(
        f"[#2ec4b6]NAMES[/] crypto={stats['crypto_total']} "
        f"(missing={stats['crypto_missing_name']}, resolved={stats['crypto_resolved_remote']})"
    )

    if host.symbols_from_config:
        updated = await run_io(
            update_config_group_names_fn,
            host.config_path,
            groups,
            indicator_groups,
        )
        if updated:
            host._log("[#2ec4b6]CONFIG[/] symbol names persisted to config.yml")
        else:
            host._log("[#6f8aa8]CONFIG[/] no symbol name changes to persist")
    else:
        host._log("[#6f8aa8]CONFIG[/] symbols from CLI/env, names kept in memory")

    host._update_main_group_panel()
    host._update_indicators_panel()
    host._update_alerts_panel()
