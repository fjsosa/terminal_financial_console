from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import Any


class TaskSupervisor:
    def __init__(self) -> None:
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @property
    def background_tasks(self) -> set[asyncio.Task[Any]]:
        return self._background_tasks

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def shutdown(
        self,
        *,
        startup_task: asyncio.Task[Any] | None = None,
        lazy_history_task: asyncio.Task[Any] | None = None,
        name_resolve_task: asyncio.Task[Any] | None = None,
        feed_task: asyncio.Task[Any] | None = None,
        timeout: float = 0.2,
    ) -> None:
        for task in list(self._background_tasks):
            task.cancel()
        for task in list(self._background_tasks):
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(task, timeout=timeout)

        for task in (startup_task, lazy_history_task, name_resolve_task, feed_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(task, timeout=timeout)
