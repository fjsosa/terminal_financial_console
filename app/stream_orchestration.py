from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Callable, Protocol


class StreamHost(Protocol):
    main_visible_items: list[tuple[str, str]]
    feed_task: asyncio.Task[None] | None
    status_text: str
    quote_provider: Any

    def _apply_quote(self, quote: Any) -> None: ...
    def _log(self, message: str) -> None: ...


async def refresh_crypto_stream_for_visible_group(
    host: StreamHost,
    *,
    create_task_fn: Callable[[Any], asyncio.Task[Any]] = asyncio.create_task,
) -> None:
    desired = [s for s, t in host.main_visible_items if t == "crypto"]
    desired = [s.upper() for s in desired if s]
    current = [s.upper() for s in host.quote_provider.symbols]
    if desired == current and host.feed_task is not None:
        return

    if host.feed_task:
        host.feed_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await host.feed_task
        host.feed_task = None

    if not desired:
        host.status_text = "STOCKS ONLY"
        return

    host.quote_provider.set_symbols(desired)
    host.feed_task = create_task_fn(consume_feed(host))


async def consume_feed(host: StreamHost, *, reconnect_sleep_seconds: float = 2.0, max_cycles: int | None = None) -> None:
    host.status_text = "STREAMING"
    host._log("[green]Connected to Binance stream[/]")
    cycles = 0
    while True:
        try:
            async for quote in host.quote_provider.stream():
                host._apply_quote(quote)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            host.status_text = "RECONNECTING"
            host._log(f"[yellow]Stream warning:[/] {exc!r}")
            await asyncio.sleep(reconnect_sleep_seconds)
            host.status_text = "STREAMING"
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
