from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.db.models import (
    AuditEntry,
    IdempotencyKey,
    IntegrationEvent,
    LoginLink,
    MaxUpdate,
    Notification,
    Session,
    WebhookDelivery,
)
from app.infra.crypto import hash_token
from app.worker import cleanup
from tests import factories
from tests.worker.conftest import provider_org

pytestmark = pytest.mark.asyncio


async def _count(session: AsyncSession, model: type) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_removes_expired_keys_sessions_events_and_deliveries(
    db_session: AsyncSession,
) -> None:
    now = utcnow()
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    subscription = await factories.create_webhook_subscription(db_session, client)

    old_event = await factories.create_integration_event(db_session, org, feed_seq=1)
    fresh_event = await factories.create_integration_event(db_session, org, feed_seq=2)
    old_delivery = await factories.create_webhook_delivery(db_session, old_event, subscription)

    user = await factories.create_user(db_session)
    await factories.create_session_token(db_session, user, expires_at=now - timedelta(hours=1))
    await factories.create_session_token(db_session, user)

    db_session.add(
        IdempotencyKey(
            scope="user:x",
            key="expired",
            request_path="POST /x",
            request_body_hash=b"0" * 32,
            expires_at=now - timedelta(days=1),
        )
    )
    db_session.add(
        IdempotencyKey(
            scope="user:x",
            key="fresh",
            request_path="POST /x",
            request_body_hash=b"0" * 32,
            expires_at=now + timedelta(days=1),
        )
    )
    await db_session.flush()

    stale = now - timedelta(days=40)
    await db_session.execute(
        update(IntegrationEvent).where(IntegrationEvent.id == old_event.id).values(created_at=stale)
    )
    await db_session.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.id == old_delivery.id)
        .values(created_at=stale)
    )
    await db_session.commit()

    removed = await cleanup.run_once(utcnow())
    assert removed == 4

    assert await _count(db_session, IdempotencyKey) == 1
    assert await _count(db_session, Session) == 1
    assert await _count(db_session, WebhookDelivery) == 0
    events = list((await db_session.execute(select(IntegrationEvent.id))).scalars())
    assert events == [fresh_event.id]


async def test_nothing_to_remove(db_session: AsyncSession) -> None:
    assert await cleanup.run_once(utcnow()) == 0


async def test_removes_expired_login_links(db_session: AsyncSession) -> None:
    now = utcnow()
    user = await factories.create_user(db_session)
    for suffix, expires_at in (
        ("old", now - timedelta(minutes=1)),
        ("fresh", now + timedelta(minutes=4)),
    ):
        db_session.add(
            LoginLink(user_id=user.id, token_hash=hash_token(suffix), expires_at=expires_at)
        )
    await db_session.commit()

    await cleanup.run_once(now)

    left = (await db_session.execute(select(LoginLink.token_hash))).scalars().all()
    assert left == [hash_token("fresh")]


def _max_update(key: str, status: str, *, age: timedelta, now: datetime) -> MaxUpdate:
    at = now - age
    return MaxUpdate(
        max_update_id=key,
        update_type="message_created",
        raw_payload={"message": {"body": {"text": "секрет"}}},
        conversation_snapshot={"context": {"data": {"phone": "+7999"}}},
        received_at=at,
        processed_at=at if status == "processed" else None,
        status=status,
        attempts=1,
    )


async def test_max_updates_retention(db_session: AsyncSession) -> None:
    """Обработанные — удаляются по сроку; у неуспешных обнуляется содержимое."""
    now = utcnow()
    db_session.add_all(
        [
            _max_update("old-processed", "processed", age=timedelta(days=8), now=now),
            _max_update("fresh-processed", "processed", age=timedelta(days=1), now=now),
            _max_update("old-dead", "dead", age=timedelta(days=15), now=now),
            _max_update("old-failed", "failed", age=timedelta(days=15), now=now),
            _max_update("fresh-dead", "dead", age=timedelta(days=2), now=now),
            _max_update("old-processing", "processing", age=timedelta(days=30), now=now),
        ]
    )
    await db_session.commit()

    await cleanup.run_once(now)

    db_session.expire_all()
    rows = {
        row.max_update_id: row for row in (await db_session.execute(select(MaxUpdate))).scalars()
    }
    assert set(rows) == {
        "fresh-processed",
        "old-dead",
        "old-failed",
        "fresh-dead",
        "old-processing",
    }
    for key in ("old-dead", "old-failed"):
        assert rows[key].raw_payload == {}
        assert rows[key].conversation_snapshot is None
        assert rows[key].status in {"dead", "failed"}
    assert rows["fresh-dead"].raw_payload != {}
    assert rows["old-processing"].raw_payload != {}
    nulls = await db_session.scalar(
        select(func.count()).select_from(MaxUpdate).where(MaxUpdate.conversation_snapshot.is_(None))
    )
    assert nulls == 2

    assert await cleanup.run_once(now) == 0


async def test_finished_notifications_retention_keeps_audit(db_session: AsyncSession) -> None:
    now = utcnow()
    user = await factories.create_user(db_session)
    old = now - timedelta(days=31)
    kept: list[str] = []
    for state, created_at in (
        ("sent", old),
        ("failed", old),
        ("skipped", old),
        ("queued", old),
        ("sent", now - timedelta(days=1)),
    ):
        row = await factories.create_notification(db_session, user, state=state)
        row.created_at = created_at
        if state == "queued" or created_at != old:
            kept.append(str(row.id))
    db_session.add(
        AuditEntry(
            actor_kind="system",
            action="test.audit",
            object_type="notification",
            result="success",
            created_at=old - timedelta(days=365),
        )
    )
    await db_session.commit()

    await cleanup.run_once(now)

    left = sorted(str(i) for i in (await db_session.execute(select(Notification.id))).scalars())
    assert left == sorted(kept)
    assert await _count(db_session, AuditEntry) == 1
