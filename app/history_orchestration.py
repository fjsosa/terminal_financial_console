from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol, TypeVar

T = TypeVar("T")


class HistoryHost(Protocol):
    crypto_symbols: list[str]
    stock_symbols: list[str]
    main_visible_items: list[tuple[str, str]]
    quote_provider: Any
    stock_provider: Any
    boot_modal: Any

    def _seed_symbol_history(
        self,
        symbol: str,
        closes: list[tuple[int, float]],
        candles_raw: list[tuple[int, float, float, float, float]],
    ) -> None: ...
    def _seed_stock_history(
        self,
        symbol: str,
        closes: list[tuple[int, float]],
        candles_raw: list[tuple[int, float, float, float, float]],
    ) -> None: ...
    def _update_main_group_panel(self) -> None: ...
    def _update_alerts_panel(self) -> None: ...
    def _log(self, message: str) -> None: ...


def current_visible_symbols(main_visible_items: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    visible_crypto = [s for s, t in main_visible_items if t == "crypto"]
    visible_stock = [s for s, t in main_visible_items if t == "stock"]
    return visible_crypto, visible_stock


async def preload_visible_group_history(
    host: HistoryHost,
    *,
    cache_ttl_seconds: int,
    initial_history_points: int,
    initial_candle_limit: int,
    startup_io_concurrency: int,
    load_symbol_history_cache_fn: Callable[[str, str, int], dict[str, Any] | None],
    save_symbol_history_cache_fn: Callable[..., Any],
    run_io: Callable[..., Awaitable[T]] = asyncio.to_thread,
) -> None:
    visible_crypto, visible_stock = current_visible_symbols(host.main_visible_items)
    visible_crypto = visible_crypto or host.crypto_symbols[:10]
    visible_stock = visible_stock or host.stock_symbols[:10]
    total = len(visible_crypto) + len(visible_stock)
    if host.boot_modal:
        host.boot_modal.set_total(max(1, total))

    cache_hits = 0
    for symbol in visible_crypto:
        cached = load_symbol_history_cache_fn(symbol, "crypto", cache_ttl_seconds)
        if not cached:
            continue
        closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
        candles = [
            (int(ts), float(o), float(h), float(l), float(c))
            for ts, o, h, l, c in cached.get("candles", [])
        ]
        host._seed_symbol_history(symbol, closes[-initial_history_points:], candles[-initial_candle_limit:])
        cache_hits += 1
    for symbol in visible_stock:
        cached = load_symbol_history_cache_fn(symbol, "stock", cache_ttl_seconds)
        if not cached:
            continue
        closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
        candles = [
            (int(ts), float(o), float(h), float(l), float(c))
            for ts, o, h, l, c in cached.get("candles", [])
        ]
        host._seed_stock_history(symbol, closes[-initial_history_points:], candles[-initial_candle_limit:])
        cache_hits += 1
    if cache_hits:
        host._log(f"[#2ec4b6]CACHE[/] loaded {cache_hits} symbol histories")

    sem = asyncio.Semaphore(startup_io_concurrency)

    async def fetch_crypto(symbol: str) -> None:
        async with sem:
            try:
                closes = await run_io(host.quote_provider.fetch_recent_closes, symbol, initial_history_points)
                candles = await run_io(host.quote_provider.fetch_recent_15m_ohlc, symbol, initial_candle_limit)
                host._seed_symbol_history(symbol, closes, candles)
                await run_io(
                    save_symbol_history_cache_fn,
                    symbol,
                    "crypto",
                    closes=closes,
                    candles=candles,
                )
            except Exception as exc:
                host._log(f"[yellow]History warning {symbol}:[/] {exc!r}")
            finally:
                if host.boot_modal:
                    host.boot_modal.increment()

    async def fetch_stock(symbol: str) -> None:
        async with sem:
            try:
                closes, candles = await run_io(
                    host.stock_provider.fetch_history,
                    symbol,
                    initial_history_points,
                    initial_candle_limit,
                )
                host._seed_stock_history(symbol, closes, candles)
                await run_io(
                    save_symbol_history_cache_fn,
                    symbol,
                    "stock",
                    closes=closes,
                    candles=candles,
                )
            except Exception as exc:
                host._log(f"[yellow]Stock history warning {symbol}:[/] {exc!r}")
            finally:
                if host.boot_modal:
                    host.boot_modal.increment()

    tasks = [asyncio.create_task(fetch_crypto(s)) for s in visible_crypto]
    tasks.extend(asyncio.create_task(fetch_stock(s)) for s in visible_stock)
    if tasks:
        await asyncio.gather(*tasks)
    host._update_main_group_panel()
    host._update_alerts_panel()
    host._log("[#2ec4b6]HISTORY[/] visible group preload complete")


async def load_remaining_history_in_background(
    host: HistoryHost,
    *,
    cache_ttl_seconds: int,
    initial_history_points: int,
    initial_candle_limit: int,
    startup_io_concurrency: int,
    load_symbol_history_cache_fn: Callable[[str, str, int], dict[str, Any] | None],
    save_symbol_history_cache_fn: Callable[..., Any],
    run_io: Callable[..., Awaitable[T]] = asyncio.to_thread,
) -> None:
    visible_crypto, visible_stock = current_visible_symbols(host.main_visible_items)
    remaining_crypto = [s for s in host.crypto_symbols if s not in set(visible_crypto)]
    remaining_stock = [s for s in host.stock_symbols if s not in set(visible_stock)]
    if not remaining_crypto and not remaining_stock:
        return

    host._log(
        f"[#6f8aa8]HISTORY[/] lazy background load started "
        f"(crypto={len(remaining_crypto)} stock={len(remaining_stock)})"
    )
    sem = asyncio.Semaphore(startup_io_concurrency)

    async def fill_crypto(symbol: str) -> None:
        cached = load_symbol_history_cache_fn(symbol, "crypto", cache_ttl_seconds)
        if cached:
            closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
            candles = [
                (int(ts), float(o), float(h), float(l), float(c))
                for ts, o, h, l, c in cached.get("candles", [])
            ]
            host._seed_symbol_history(symbol, closes[-initial_history_points:], candles[-initial_candle_limit:])
            return
        async with sem:
            try:
                closes = await run_io(host.quote_provider.fetch_recent_closes, symbol, initial_history_points)
                candles = await run_io(host.quote_provider.fetch_recent_15m_ohlc, symbol, initial_candle_limit)
                host._seed_symbol_history(symbol, closes, candles)
                await run_io(
                    save_symbol_history_cache_fn,
                    symbol,
                    "crypto",
                    closes=closes,
                    candles=candles,
                )
            except Exception:
                return

    async def fill_stock(symbol: str) -> None:
        cached = load_symbol_history_cache_fn(symbol, "stock", cache_ttl_seconds)
        if cached:
            closes = [(int(ts), float(px)) for ts, px in cached.get("closes", [])]
            candles = [
                (int(ts), float(o), float(h), float(l), float(c))
                for ts, o, h, l, c in cached.get("candles", [])
            ]
            host._seed_stock_history(symbol, closes[-initial_history_points:], candles[-initial_candle_limit:])
            return
        async with sem:
            try:
                closes, candles = await run_io(
                    host.stock_provider.fetch_history,
                    symbol,
                    initial_history_points,
                    initial_candle_limit,
                )
                host._seed_stock_history(symbol, closes, candles)
                await run_io(
                    save_symbol_history_cache_fn,
                    symbol,
                    "stock",
                    closes=closes,
                    candles=candles,
                )
            except Exception:
                return

    tasks = [asyncio.create_task(fill_crypto(s)) for s in remaining_crypto]
    tasks.extend(asyncio.create_task(fill_stock(s)) for s in remaining_stock)
    if tasks:
        await asyncio.gather(*tasks)
    host._log("[#6f8aa8]HISTORY[/] lazy background load completed")
