import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import Select, delete, select, update
from sqlalchemy.orm import InstrumentedAttribute

from app.db import session as db_session
from app.db.enums import NotificationState
from app.db.models import (
    IdempotencyKey,
    IntegrationEvent,
    LoginLink,
    MaxUpdate,
    Notification,
    Session,
    WebhookDelivery,
)
from app.db.models.max import MaxUpdateStatus
from app.infra.config import get_settings

log = structlog.get_logger("worker.cleanup")


async def run_once(now: datetime) -> int:
    settings = get_settings()
    batch = settings.cleanup_batch
    cutoff = now - timedelta(days=settings.events_retention_days)

    removed = await _delete_batched(
        IdempotencyKey,
        IdempotencyKey.id,
        select(IdempotencyKey.id).where(IdempotencyKey.expires_at <= now),
        batch,
    )
    removed += await _delete_batched(
        WebhookDelivery,
        WebhookDelivery.id,
        select(WebhookDelivery.id).where(WebhookDelivery.created_at < cutoff),
        batch,
    )
    removed += await _delete_batched(
        IntegrationEvent,
        IntegrationEvent.id,
        select(IntegrationEvent.id).where(
            IntegrationEvent.created_at < cutoff,
            ~select(WebhookDelivery.id)
            .where(WebhookDelivery.integration_event_id == IntegrationEvent.id)
            .exists(),
        ),
        batch,
    )
    removed += await _delete_batched(
        Session, Session.id, select(Session.id).where(Session.expires_at <= now), batch
    )
    removed += await _delete_batched(
        LoginLink, LoginLink.id, select(LoginLink.id).where(LoginLink.expires_at <= now), batch
    )
    removed += await _delete_batched(
        MaxUpdate,
        MaxUpdate.id,
        select(MaxUpdate.id).where(
            MaxUpdate.status == MaxUpdateStatus.PROCESSED.value,
            MaxUpdate.processed_at < now - timedelta(days=settings.max_updates_retention_days),
        ),
        batch,
    )
    removed += await _delete_batched(
        Notification,
        Notification.id,
        select(Notification.id).where(
            Notification.state != NotificationState.QUEUED.value,
            Notification.created_at < now - timedelta(days=settings.notifications_retention_days),
        ),
        batch,
    )
    removed += await _scrub_failed_updates(
        now - timedelta(days=settings.max_updates_payload_retention_days), batch
    )
    if removed:
        log.info("cleanup_done", removed=removed)
    return removed


async def _scrub_failed_updates(cutoff: datetime, batch: int) -> int:
    """Неуспешные события MAX: ключ и причина остаются, содержимое — нет (ТЗ 12, 14)."""
    ids = (
        select(MaxUpdate.id)
        .where(
            MaxUpdate.status.in_([MaxUpdateStatus.FAILED.value, MaxUpdateStatus.DEAD.value]),
            MaxUpdate.received_at < cutoff,
            (MaxUpdate.raw_payload != {}) | MaxUpdate.conversation_snapshot.is_not(None),
        )
        .limit(batch)
    )
    total = 0
    while True:
        async with db_session.transaction() as session:
            scrubbed = (
                (
                    await session.execute(
                        update(MaxUpdate)
                        .where(MaxUpdate.id.in_(ids))
                        .values(raw_payload={}, conversation_snapshot=None, replies=[])
                        .returning(MaxUpdate.id)
                    )
                )
                .scalars()
                .all()
            )
        total += len(scrubbed)
        if len(scrubbed) < batch:
            return total


async def _delete_batched(
    model: type[Any],
    id_column: InstrumentedAttribute[uuid.UUID],
    ids: Select[tuple[uuid.UUID]],
    batch: int,
) -> int:
    total = 0
    while True:
        async with db_session.transaction() as session:
            deleted = (
                (
                    await session.execute(
                        delete(model).where(id_column.in_(ids.limit(batch))).returning(id_column)
                    )
                )
                .scalars()
                .all()
            )
        total += len(deleted)
        if len(deleted) < batch:
            return total
