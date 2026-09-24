import asyncio
import signal

import structlog

from app.core.clock import utcnow
from app.db import session as db_session
from app.infra.config import get_settings
from app.infra.logging import configure_logging
from app.modules.ops import api as ops
from app.worker.loops import build_loops
from app.worker.runner import run_loops

log = structlog.get_logger("worker")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.app_env)
    stop = asyncio.Event()
    running = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        running.add_signal_handler(sig, _request_stop, stop, sig)

    log.info("worker_started", env=settings.app_env)
    loops = build_loops(settings)
    heartbeat = ops.HeartbeatWriter.for_loops(
        {loop.name: loop.interval_seconds for loop in loops}, settings
    )
    try:
        try:
            await heartbeat.register(utcnow())
        except Exception as exc:
            log.warning("heartbeat_register_failed", reason=type(exc).__name__)
        await run_loops(loops, stop, heartbeat)
    finally:
        await db_session.dispose()
        log.info("worker_stopped")


def _request_stop(stop: asyncio.Event, sig: signal.Signals) -> None:
    log.info("worker_stopping", signal=sig.name)
    stop.set()


if __name__ == "__main__":
    asyncio.run(main())
