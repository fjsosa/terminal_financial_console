from __future__ import annotations

from collections import deque
from typing import Any, Callable


def normalize_symbol_type(symbol: str, symbol_type: str) -> str:
    st = (symbol_type or "").strip().lower()
    if st in {"crypto", "stock"}:
        return st
    return "crypto" if symbol.upper().endswith("USDT") else "stock"


def find_group_index(market_groups: list[dict[str, Any]], group_name: str) -> int | None:
    wanted = (group_name or "").strip().casefold()
    if not wanted:
        return None
    for idx, group in enumerate(market_groups):
        name = str(group.get("name") or "").strip().casefold()
        if name == wanted:
            return idx
    return None


def find_symbol_entry(
    market_groups: list[dict[str, Any]], symbol: str
) -> tuple[int, int, dict[str, Any]] | None:
    needle = (symbol or "").strip().upper()
    if not needle:
        return None
    for group_idx, group in enumerate(market_groups):
        symbols = group.get("symbols")
        if not isinstance(symbols, list):
            continue
        for item_idx, item in enumerate(symbols):
            if not isinstance(item, dict):
                continue
            value = str(item.get("symbol") or "").strip().upper()
            if value == needle:
                return group_idx, item_idx, item
    return None


def clear_quick_actions_for_symbol(quick_actions: dict[str, str], symbol: str) -> list[str]:
    removed: list[str] = []
    for key in ("1", "2", "3"):
        if quick_actions.get(key, "").upper() == symbol.upper():
            quick_actions[key] = ""
            removed.append(key)
    return removed


def sync_market_data_structures(
    *,
    main_group_items: list[tuple[str, list[tuple[str, str]]]],
    symbol_data: dict[str, Any],
    stock_data: dict[str, Any],
    candles: dict[str, deque[Any]],
    stock_candles: dict[str, deque[Any]],
    crypto_candles_by_tf: dict[str, dict[str, deque[Any]]],
    stock_candles_by_tf: dict[str, dict[str, deque[Any]]],
    candle_buffer_max: int,
    symbol_state_factory: Callable[[str], Any],
    stock_state_factory: Callable[[str], Any],
) -> tuple[list[str], list[str]]:
    crypto_symbols: list[str] = []
    stock_symbols: list[str] = []
    seen_crypto: set[str] = set()
    seen_stock: set[str] = set()
    for _, items in main_group_items:
        for symbol, symbol_type in items:
            if symbol_type == "crypto":
                if symbol not in seen_crypto:
                    seen_crypto.add(symbol)
                    crypto_symbols.append(symbol)
            else:
                if symbol not in seen_stock:
                    seen_stock.add(symbol)
                    stock_symbols.append(symbol)

    for symbol in crypto_symbols:
        symbol_data.setdefault(symbol, symbol_state_factory(symbol))
        candles.setdefault(symbol, deque(maxlen=candle_buffer_max))
        for tf in crypto_candles_by_tf:
            crypto_candles_by_tf[tf].setdefault(symbol, deque(maxlen=candle_buffer_max))
    for symbol in list(symbol_data):
        if symbol not in seen_crypto:
            symbol_data.pop(symbol, None)
            candles.pop(symbol, None)
            for tf in crypto_candles_by_tf:
                crypto_candles_by_tf[tf].pop(symbol, None)

    for symbol in stock_symbols:
        stock_data.setdefault(symbol, stock_state_factory(symbol))
        stock_candles.setdefault(symbol, deque(maxlen=candle_buffer_max))
        for tf in stock_candles_by_tf:
            stock_candles_by_tf[tf].setdefault(symbol, deque(maxlen=candle_buffer_max))
    for symbol in list(stock_data):
        if symbol not in seen_stock:
            stock_data.pop(symbol, None)
            stock_candles.pop(symbol, None)
            for tf in stock_candles_by_tf:
                stock_candles_by_tf[tf].pop(symbol, None)

    return crypto_symbols, stock_symbols
