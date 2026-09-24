import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import structlog

from app.core.clock import utcnow

log = structlog.get_logger("worker")

RunOnce = Callable[[datetime], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class Loop:
    name: str
    run_once: RunOnce
    interval_seconds: float


class Heartbeat(Protocol):
    async def succeeded(self, loop: str, now: datetime, processed: int) -> None: ...

    async def failed(self, loop: str, now: datetime, error: BaseException) -> None: ...


async def run_loop(loop: Loop, stop: asyncio.Event, heartbeat: Heartbeat | None = None) -> None:
    log.info("loop_started", loop=loop.name, interval=loop.interval_seconds)
    while not stop.is_set():
        started = time.monotonic()
        try:
            processed = await loop.run_once(utcnow())
            if processed:
                log.info("loop_tick", loop=loop.name, processed=processed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("loop_failed", loop=loop.name)
            if heartbeat is not None:
                await _beat(loop.name, heartbeat.failed(loop.name, utcnow(), exc))
        else:
            if heartbeat is not None:
                await _beat(loop.name, heartbeat.succeeded(loop.name, utcnow(), processed))
        delay = max(0.0, loop.interval_seconds - (time.monotonic() - started))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)
    log.info("loop_stopped", loop=loop.name)


async def _beat(name: str, write: Awaitable[None]) -> None:
    try:
        await write
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("heartbeat_write_failed", loop=name, reason=type(exc).__name__)


async def run_loops(
    loops: Sequence[Loop], stop: asyncio.Event, heartbeat: Heartbeat | None = None
) -> None:
    async with asyncio.TaskGroup() as group:
        for loop in loops:
            group.create_task(run_loop(loop, stop, heartbeat), name=loop.name)
