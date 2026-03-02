from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class RotationController:
    """Keeps pause windows and cyclic index operations for rotating groups."""

    pause_until: dict[str, float] = field(default_factory=dict)

    def pause(self, key: str, seconds: int, now: float | None = None) -> None:
        base = time.time() if now is None else now
        self.pause_until[key] = base + max(0, seconds)

    def is_paused(self, key: str, now: float | None = None) -> bool:
        base = time.time() if now is None else now
        return base < self.pause_until.get(key, 0.0)

    @staticmethod
    def cycle_index(current: int, size: int, step: int = 1) -> int:
        if size <= 0:
            return 0
        return (current + step) % size

    def try_rotate(
        self,
        *,
        key: str,
        current: int,
        size: int,
        step: int = 1,
        now: float | None = None,
    ) -> tuple[bool, int]:
        if size <= 0:
            return False, 0
        if self.is_paused(key, now=now):
            return False, current
        return True, self.cycle_index(current, size=size, step=step)
