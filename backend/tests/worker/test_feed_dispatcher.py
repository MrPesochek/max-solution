import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import IntegrationActor
from app.core.clock import utcnow
from app.db import session as db_session_module
from app.db.models import IntegrationClient, IntegrationEvent, Organization
from app.modules.integration import api as integration
from app.worker import feed_dispatcher
from tests import factories
from tests.worker.conftest import provider_org

pytestmark = pytest.mark.asyncio


def _event(org: Organization) -> IntegrationEvent:
    return IntegrationEvent(
        event_type="request.assigned",
        recipient_org_id=org.id,
        resource_kind="request",
        resource_id=uuid.uuid4(),
        resource_version=1,
        occurred_at=utcnow(),
        payload={},
    )


def _actor(client: IntegrationClient) -> IntegrationActor:
    return IntegrationActor(
        integration_client_id=client.id,
        organization_id=client.provider_org_id,
        scopes=frozenset(client.scopes),
    )


async def _feed_sequences(session: AsyncSession, org: Organization) -> list[int]:
    rows = (
        await session.execute(
            select(IntegrationEvent.feed_seq)
            .where(IntegrationEvent.recipient_org_id == org.id)
            .order_by(IntegrationEvent.feed_seq)
        )
    ).scalars()
    return [seq for seq in rows if seq is not None]


async def test_assigns_sequence_per_recipient(db_session: AsyncSession) -> None:
    org_a = await provider_org(db_session, name="А")
    org_b = await provider_org(db_session, name="Б")
    for _ in range(3):
        await factories.create_integration_event(db_session, org_a)
    for _ in range(2):
        await factories.create_integration_event(db_session, org_b)
    await db_session.commit()

    assert await feed_dispatcher.run_once(utcnow()) == 5
    assert await feed_dispatcher.run_once(utcnow()) == 0

    assert await _feed_sequences(db_session, org_a) == [1, 2, 3]
    assert await _feed_sequences(db_session, org_b) == [1, 2]


async def test_late_commit_does_not_create_gap(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await db_session.commit()
    actor = _actor(client)

    maker = db_session_module.get_sessionmaker()
    async with maker() as slow, maker() as fast:
        await slow.begin()
        early = _event(org)
        slow.add(early)
        await slow.flush()

        await fast.begin()
        late = _event(org)
        fast.add(late)
        await fast.flush()
        assert early.id < late.id
        late_id = late.id
        early_id = early.id
        await fast.commit()

        assert await feed_dispatcher.run_once(utcnow()) == 1
        page = await integration.list_events(actor, cursor=None, limit=50)
        assert [e.event_id for e in page.events] == [ids.encode("event", late_id)]
        cursor = page.next_cursor

        await slow.commit()

    assert await feed_dispatcher.run_once(utcnow()) == 1
    page = await integration.list_events(actor, cursor=cursor, limit=50)
    assert [e.event_id for e in page.events] == [ids.encode("event", early_id)]
    assert await _feed_sequences(db_session, org) == [1, 2]


async def test_parallel_writers_leave_no_gaps(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    await db_session.commit()
    maker = db_session_module.get_sessionmaker()
    writers = 12

    async def write(index: int) -> None:
        await asyncio.sleep(index % 3 * 0.005)
        async with maker() as session, session.begin():
            session.add(_event(org))

    async def dispatch() -> None:
        for _ in range(12):
            await feed_dispatcher.run_once(utcnow())
            await asyncio.sleep(0.005)

    await asyncio.gather(*(write(i) for i in range(writers)), dispatch())
    while await feed_dispatcher.run_once(utcnow()):
        pass

    assert await _feed_sequences(db_session, org) == list(range(1, writers + 1))


async def test_two_dispatchers_do_not_collide(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    for _ in range(6):
        await factories.create_integration_event(db_session, org)
    await db_session.commit()

    counts = await asyncio.gather(
        feed_dispatcher.run_once(utcnow()), feed_dispatcher.run_once(utcnow())
    )
    assert sum(counts) == 6
    assert await _feed_sequences(db_session, org) == [1, 2, 3, 4, 5, 6]
