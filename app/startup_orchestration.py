from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Protocol


class StartupHost(Protocol):
    is_shutting_down: bool
    lazy_history_task: Any

    async def _show_boot_modal(self) -> None: ...
    async def _preload_visible_group_history(self) -> None: ...
    async def _hide_boot_modal(self) -> None: ...
    async def _refresh_crypto_stream_for_visible_group(self) -> None: ...
    async def _load_remaining_history_in_background(self) -> None: ...
    def _schedule_news_refresh(self) -> None: ...
    def _schedule_calendar_refresh(self) -> None: ...
    def _schedule_stock_refresh(self) -> None: ...
    def _schedule_indicator_refresh(self) -> None: ...
    def _spawn_background(self, coro: Awaitable[Any]) -> Any: ...
    def _log(self, message: str) -> None: ...


async def run_startup_sequence(host: StartupHost) -> None:
    try:
        # Let first frame render before opening boot modal.
        await asyncio.sleep(0)
        await host._show_boot_modal()
        await host._preload_visible_group_history()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        host._log(f"[yellow]Startup warning:[/] {exc!r}")
    finally:
        if host.is_shutting_down:
            return
        await host._hide_boot_modal()
        await host._refresh_crypto_stream_for_visible_group()
        host.lazy_history_task = host._spawn_background(host._load_remaining_history_in_background())
        host._schedule_news_refresh()
        host._schedule_calendar_refresh()
        host._schedule_stock_refresh()
        host._schedule_indicator_refresh()
