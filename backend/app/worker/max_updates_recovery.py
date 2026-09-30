from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from maxapi.methods.types.getted_updates import process_update_webhook
from sqlalchemy import and_, or_, select
from sqlalchemy import update as sql_update

from app.adapters.bot import runtime as bot_runtime
from app.adapters.bot import updates
from app.adapters.bot.runtime import BotRuntime
from app.db import session as db_session
from app.db.models import MaxUpdate
from app.db.models.max import MaxUpdateStatus
from app.infra.config import get_settings

log = structlog.get_logger("worker.max_updates")

_own_runtime: BotRuntime | None = None
_own_runtime_built = False


def _runtime() -> BotRuntime | None:
    global _own_runtime, _own_runtime_built
    runtime = bot_runtime.get_runtime()
    if runtime is not None:
        return runtime
    if not _own_runtime_built:
        _own_runtime_built = True
        _own_runtime = bot_runtime.build_runtime()
    return _own_runtime


async def run_once(now: datetime) -> int:
    settings = get_settings()
    await _bury_exhausted(now, settings.max_update_max_attempts)
    runtime = _runtime()
    if runtime is None:
        return 0

    stale_received = now - timedelta(seconds=settings.max_update_lease_seconds)
    due = or_(
        and_(
            MaxUpdate.status == MaxUpdateStatus.RECEIVED.value,
            MaxUpdate.received_at < stale_received,
        ),
        and_(
            MaxUpdate.status == MaxUpdateStatus.PROCESSING.value,
            MaxUpdate.lease_until < now,
        ),
        and_(
            MaxUpdate.status == MaxUpdateStatus.FAILED.value,
            MaxUpdate.next_retry_at <= now,
        ),
    )
    async with db_session.transaction() as session:
        rows = (
            await session.execute(
                select(MaxUpdate.max_update_id, MaxUpdate.raw_payload)
                .where(due, MaxUpdate.attempts < settings.max_update_max_attempts)
                .order_by(MaxUpdate.received_at)
                .limit(settings.max_update_recovery_batch)
            )
        ).all()

    handled = 0
    for key, payload in rows:
        event = (
            await process_update_webhook(event_json=payload, bot=runtime.bot) if payload else None
        )
        if event is None or updates.update_key(event) != key:
            await _bury(key, "no_payload")
            handled += 1
            continue
        outcome = await updates.process(runtime.dispatcher, event, now=now)
        if not outcome.duplicate:
            handled += 1
    return handled


async def _bury_exhausted(now: datetime, max_attempts: int) -> None:
    async with db_session.transaction() as session:
        result = await session.execute(
            sql_update(MaxUpdate)
            .where(
                MaxUpdate.status == MaxUpdateStatus.PROCESSING.value,
                MaxUpdate.lease_until < now,
                MaxUpdate.attempts >= max_attempts,
            )
            .values(
                status=MaxUpdateStatus.DEAD.value,
                lease_until=None,
                processing_error="lease_expired",
            )
            .returning(MaxUpdate.id)
        )
        buried = len(result.all())
    if buried:
        log.error("max_update_dead", reason="lease_expired", count=buried)


async def _bury(key: str, reason: str) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            sql_update(MaxUpdate)
            .where(
                MaxUpdate.max_update_id == key,
                MaxUpdate.status.in_(
                    [
                        MaxUpdateStatus.RECEIVED.value,
                        MaxUpdateStatus.PROCESSING.value,
                        MaxUpdateStatus.FAILED.value,
                    ]
                ),
            )
            .values(
                status=MaxUpdateStatus.DEAD.value,
                lease_until=None,
                next_retry_at=None,
                processing_error=reason,
            )
        )
    log.error("max_update_dead", reason=reason)
