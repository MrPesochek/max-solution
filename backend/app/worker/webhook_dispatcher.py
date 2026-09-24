import asyncio
from datetime import datetime

import structlog

from app.core.clock import utcnow
from app.infra.config import get_settings
from app.modules.integration import api as integration

log = structlog.get_logger("worker.webhooks")


async def run_once(now: datetime) -> int:
    created = await integration.enqueue_deliveries(now)
    sent = await send_pending(now)
    return created + sent


async def send_pending(now: datetime) -> int:
    jobs = await integration.lease_deliveries(now)
    if not jobs:
        return 0
    settings = get_settings()
    results = await asyncio.gather(
        *(
            integration.deliver(
                job.outgoing,
                timeout=settings.webhook_timeout_seconds,
                private_hosts=settings.private_webhook_hosts,
            )
            for job in jobs
        ),
        return_exceptions=True,
    )
    for job, result in zip(jobs, results, strict=True):
        if isinstance(result, BaseException):
            log.exception("webhook_attempt_failed", event_type=job.event_type, exc_info=result)
            result = integration.AttemptResult(
                outcome="retryable", error=f"internal:{type(result).__name__}"
            )
        state = await integration.record_attempt(job, result, utcnow())
        log.info(
            "webhook_attempt",
            event_type=job.event_type,
            attempt=job.attempt,
            outcome=result.outcome,
            status=result.status_code,
            state=state,
        )
    return len(jobs)
