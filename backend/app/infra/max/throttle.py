from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, delay: float) -> None: ...


class RealClock:
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)


class MaxThrottle:
    def __init__(
        self,
        *,
        per_chat_rps: float = 2.0,
        global_rps: float = 30.0,
        clock: Clock | None = None,
    ) -> None:
        if per_chat_rps <= 0 or global_rps <= 0:
            raise ValueError("лимиты rps должны быть положительными")
        self._per_chat_interval = 1.0 / per_chat_rps
        self._global_interval = 1.0 / global_rps
        self._clock = clock or RealClock()
        self._chat_next: dict[int, float] = {}
        self._global_next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self, chat_id: int) -> None:
        async with self._lock:
            now = self._clock.now()
            chat_next = self._chat_next.get(chat_id, now)
            start = max(now, chat_next, self._global_next)
            wait = start - now
            self._chat_next[chat_id] = start + self._per_chat_interval
            self._global_next = start + self._global_interval
        if wait > 0:
            await self._clock.sleep(wait)
