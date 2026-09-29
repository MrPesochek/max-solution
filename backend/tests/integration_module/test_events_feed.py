import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import Forbidden
from app.db.models import IntegrationEvent
from app.modules.integration import api as integration
from tests import factories
from tests.integration_module.conftest import integration_actor, provider_org

pytestmark = pytest.mark.asyncio


async def _seed(db_session: AsyncSession, org, count: int) -> None:
    for seq in range(1, count + 1):
        await factories.create_integration_event(
            db_session, org, feed_seq=seq, resource_version=seq
        )


async def test_envelope_matches_contract(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    resource_id = uuid.uuid4()
    await factories.create_integration_event(
        db_session,
        org,
        feed_seq=1,
        resource_id=resource_id,
        resource_version=7,
        payload={"status": "scheduled"},
    )
    await db_session.commit()

    page = await integration.list_events(integration_actor(client), cursor=None, limit=50)
    envelope = page.events[0]
    assert envelope.schema_version == "1"
    assert envelope.event_id.startswith("evt_")
    assert envelope.type == "request.assigned"
    assert envelope.recipient_organization_id == ids.encode("organization", org.id)
    assert envelope.resource_id == ids.encode("request", resource_id)
    assert envelope.resource_version == 7
    assert envelope.data == {"status": "scheduled"}
    assert page.next_cursor == "1"
    assert page.has_more is False


async def test_cursor_pagination(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await _seed(db_session, org, 5)
    await db_session.commit()
    actor = integration_actor(client)

    first = await integration.list_events(actor, cursor=None, limit=2)
    assert [e.resource_version for e in first.events] == [1, 2]
    assert first.has_more is True
    assert first.next_cursor == "2"

    second = await integration.list_events(actor, cursor=first.next_cursor, limit=2)
    assert [e.resource_version for e in second.events] == [3, 4]

    last = await integration.list_events(actor, cursor=second.next_cursor, limit=2)
    assert [e.resource_version for e in last.events] == [5]
    assert last.has_more is False

    empty = await integration.list_events(actor, cursor=last.next_cursor, limit=2)
    assert empty.events == []
    assert empty.next_cursor == "5"


async def test_unassigned_events_are_invisible(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_integration_event(db_session, org, feed_seq=None)
    await db_session.commit()

    page = await integration.list_events(integration_actor(client), cursor=None, limit=50)
    assert page.events == []


async def test_expired_cursor(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await _seed(db_session, org, 4)
    await db_session.execute(delete(IntegrationEvent).where(IntegrationEvent.feed_seq < 3))
    await db_session.commit()

    with pytest.raises(integration.CursorExpired) as exc:
        await integration.list_events(integration_actor(client), cursor="0", limit=50)
    assert exc.value.code == "CURSOR_EXPIRED"
    assert exc.value.status == 409

    page = await integration.list_events(integration_actor(client), cursor="2", limit=50)
    assert [e.resource_version for e in page.events] == [3, 4]


async def test_malformed_cursor(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    with pytest.raises(integration.CursorExpired):
        await integration.list_events(integration_actor(client), cursor="abc", limit=50)


async def test_foreign_organization_does_not_see_events(db_session: AsyncSession) -> None:
    org_a = await provider_org(db_session, name="А")
    org_b = await provider_org(db_session, name="Б")
    _, _ = await factories.create_integration_client(db_session, org_a)
    client_b, _ = await factories.create_integration_client(db_session, org_b)
    await _seed(db_session, org_a, 3)
    await db_session.commit()

    page = await integration.list_events(integration_actor(client_b), cursor=None, limit=50)
    assert page.events == []


async def test_events_read_scope_required(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org, scopes=["requests:read"])
    await db_session.commit()

    with pytest.raises(Forbidden) as exc:
        await integration.list_events(integration_actor(client), cursor=None, limit=50)
    assert exc.value.code == "INSUFFICIENT_SCOPE"


async def test_limit_is_capped(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await _seed(db_session, org, 3)
    await db_session.commit()

    page = await integration.list_events(integration_actor(client), cursor=None, limit=1000)
    assert len(page.events) == 3


async def test_numbering_survives_retention_cleanup(db_session: AsyncSession) -> None:
    """После 30 дней тишины уборка удаляет все события — нумерация не начинается заново."""
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    for version in (1, 2, 3):
        await factories.create_integration_event(db_session, org, resource_version=version)
    await db_session.commit()
    assert await integration.assign_feed_seq(utcnow()) == 3
    actor = integration_actor(client)
    page = await integration.list_events(actor, cursor=None, limit=50)
    assert page.next_cursor == "3"

    await db_session.execute(delete(IntegrationEvent))
    await db_session.commit()

    empty = await integration.list_events(actor, cursor="3", limit=50)
    assert empty.events == []
    with pytest.raises(integration.CursorExpired):
        await integration.list_events(actor, cursor="1", limit=50)

    await factories.create_integration_event(db_session, org, resource_version=4)
    await db_session.commit()
    await integration.assign_feed_seq(utcnow())

    fresh = await integration.list_events(actor, cursor="3", limit=50)
    assert [e.resource_version for e in fresh.events] == [4]
    assert fresh.next_cursor == "4"
    seq = await db_session.scalar(select(IntegrationEvent.feed_seq))
    assert seq == 4


async def test_cursor_ahead_of_feed_is_expired(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await _seed(db_session, org, 2)
    await db_session.commit()

    with pytest.raises(integration.CursorExpired):
        await integration.list_events(integration_actor(client), cursor="10", limit=50)
