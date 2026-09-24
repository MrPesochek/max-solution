from datetime import datetime

import structlog

from app.modules.requests import api as requests

log = structlog.get_logger("worker.request_sweeper")


async def run_once(now: datetime) -> int:
    counters = await requests.expire_due(now)
    return sum(counters.values())
