import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select

from app.core.clock import utcnow
from app.core.locking import lock_by_id
from app.db import session as db_session
from app.db.enums import NotificationState
from app.db.models import Notification, User
from app.infra.config import get_settings
from app.infra.max.transport import MaxRetryableError, MaxTransport
from app.worker import notification_templates
from app.worker.transport_factory import get_max_transport

log = structlog.get_logger("worker.notifications")


@dataclass(frozen=True, slots=True)
class NotificationJob:
    notification_id: uuid.UUID
    notification_type: str
    payload: dict[str, Any]
    max_user_id: str
    recipient_user_id: uuid.UUID
    attempt: int
    recipient_membership_id: uuid.UUID | None = None


async def run_once(now: datetime, *, transport: MaxTransport | None = None) -> int:
    jobs = await lease(now)
    if not jobs:
        return 0
    sender = transport or get_max_transport()
    for job in jobs:
        await _send(job, sender)
    return len(jobs)


async def lease(now: datetime, *, batch: int | None = None) -> list[NotificationJob]:
    settings = get_settings()
    limit = batch or settings.notification_send_batch
    lease_window = timedelta(seconds=settings.notification_lease_seconds)
    jobs: list[NotificationJob] = []

    async with db_session.transaction() as session:
        rows = list(
            (
                await session.execute(
                    select(Notification)
                    .where(
                        Notification.state == NotificationState.QUEUED.value,
                        or_(
                            Notification.next_attempt_at.is_(None),
                            Notification.next_attempt_at <= now,
                        ),
                        or_(
                            Notification.lease_until.is_(None),
                            Notification.lease_until <= now,
                        ),
                    )
                    .order_by(Notification.next_attempt_at.nulls_first())
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for notification in rows:
            user = await session.get(User, notification.recipient_user_id)
            if user is None or not user.bot_available:
                notification.state = NotificationState.SKIPPED.value
                notification.last_error = "bot_unavailable"
                notification.next_attempt_at = None
                continue
            notification.attempt_count += 1
            notification.lease_until = now + lease_window
            jobs.append(
                NotificationJob(
                    notification_id=notification.id,
                    notification_type=notification.notification_type,
                    payload=dict(notification.payload),
                    max_user_id=user.max_user_id,
                    recipient_user_id=notification.recipient_user_id,
                    attempt=notification.attempt_count,
                    recipient_membership_id=notification.recipient_membership_id,
                )
            )
    return jobs


async def _send(job: NotificationJob, transport: MaxTransport) -> None:
    if not job.max_user_id.isdigit():
        await record(job, sent=False, error="max_user_id_invalid", retryable=False)
        return
    now = utcnow()
    async with db_session.transaction() as session:
        message = await notification_templates.render(
            session,
            job.notification_type,
            job.payload,
            recipient_user_id=job.recipient_user_id,
            now=now,
            recipient_membership_id=job.recipient_membership_id,
        )
    if message.skip_reason is not None:
        await skip(job, message.skip_reason)
        return
    try:
        await transport.send_message(
            user_id=int(job.max_user_id),
            text=message.text,
            format=message.format,
            attachments=message.attachments,
        )
    except MaxRetryableError as exc:
        await record(job, sent=False, error=f"max_retryable:{exc.status}", retryable=True)
    except Exception as exc:
        log.warning("notification_failed", reason=type(exc).__name__)
        await record(job, sent=False, error=f"max_error:{type(exc).__name__}", retryable=False)
    else:
        await record(job, sent=True, error=None, retryable=False)


async def skip(job: NotificationJob, reason: str) -> None:
    async with db_session.transaction() as session:
        notification = await lock_by_id(session, Notification, job.notification_id)
        notification.lease_until = None
        notification.state = NotificationState.SKIPPED.value
        notification.last_error = reason
        notification.next_attempt_at = None


async def record(job: NotificationJob, *, sent: bool, error: str | None, retryable: bool) -> None:
    settings = get_settings()
    now = utcnow()
    async with db_session.transaction() as session:
        notification = await lock_by_id(session, Notification, job.notification_id)
        notification.lease_until = None
        if sent:
            notification.state = NotificationState.SENT.value
            notification.sent_at = now
            notification.next_attempt_at = None
            notification.last_error = None
            return
        notification.last_error = error
        if retryable and notification.attempt_count < settings.notification_max_attempts:
            delay = min(
                settings.notification_retry_base_seconds * (2 ** (notification.attempt_count - 1)),
                settings.notification_retry_max_seconds,
            )
            notification.state = NotificationState.QUEUED.value
            notification.next_attempt_at = now + timedelta(seconds=delay)
        else:
            notification.state = NotificationState.FAILED.value
            notification.next_attempt_at = None
