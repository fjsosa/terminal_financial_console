from __future__ import annotations

from typing import Any, Iterable

from .constants import SYMBOL_TYPE_CRYPTO, SYMBOL_TYPE_STOCK, SYMBOL_TYPES


GroupItems = list[tuple[str, str]]
GroupList = list[tuple[str, GroupItems]]


def build_symbol_groups(
    source_groups: Iterable[dict[str, Any]],
    *,
    fallback_name: str = "MAIN",
    fallback_items: Iterable[tuple[str, str]] | None = None,
) -> GroupList:
    groups: GroupList = []
    for group in source_groups:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or fallback_name).strip() or fallback_name
        raw_items = group.get("symbols")
        if not isinstance(raw_items, list):
            continue
        symbols: GroupItems = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            symbol_type = str(item.get("type") or "").strip().lower()
            if symbol_type not in SYMBOL_TYPES:
                symbol_type = SYMBOL_TYPE_CRYPTO if symbol.endswith("USDT") else SYMBOL_TYPE_STOCK
            if not symbol:
                continue
            key = (symbol, symbol_type)
            if key in seen:
                continue
            seen.add(key)
            symbols.append(key)
        if symbols:
            groups.append((name, symbols))

    if groups:
        return groups
    fallback_symbols = list(fallback_items or [])
    if fallback_symbols:
        return [(fallback_name, fallback_symbols)]
    return []


def build_main_groups(
    market_groups: Iterable[dict[str, Any]],
    *,
    crypto_symbols: Iterable[str],
    stock_symbols: Iterable[str],
) -> GroupList:
    fallback_symbols: GroupItems = []
    for symbol in crypto_symbols:
        fallback_symbols.append((symbol, SYMBOL_TYPE_CRYPTO))
    for symbol in stock_symbols:
        fallback_symbols.append((symbol, SYMBOL_TYPE_STOCK))
    return build_symbol_groups(
        market_groups,
        fallback_name="MAIN",
        fallback_items=fallback_symbols,
    )


def flatten_group_items(main_group_items: GroupList) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, items in main_group_items:
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
    return out


def advance_symbol_across_groups(
    main_group_items: GroupList,
    *,
    symbol: str,
    symbol_type: str,
    step: int,
) -> tuple[str, str] | None:
    ordered = flatten_group_items(main_group_items)
    if not ordered:
        return None
    current = (symbol, symbol_type)
    try:
        idx = ordered.index(current)
    except ValueError:
        idx = 0
    return ordered[(idx + step) % len(ordered)]
