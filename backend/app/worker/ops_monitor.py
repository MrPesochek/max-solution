from datetime import datetime

import structlog

from app.infra.config import get_settings
from app.modules.ops import api as ops

log = structlog.get_logger("ops")


async def run_once(now: datetime) -> int:
    status = await ops.collect_status(now, get_settings())
    for alarm in status.alarms:
        log.error("ops_alarm", code=alarm.code, alarm=alarm.message, **alarm.details)
    return len(status.alarms)
