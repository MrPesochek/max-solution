import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IntegrationEvent
from tests import factories
from tests.integration_api.conftest import bearer, provider_org

pytestmark = pytest.mark.asyncio


async def test_events_page_shape(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    for seq in range(1, 4):
        await factories.create_integration_event(
            db_session, org, feed_seq=seq, resource_version=seq
        )
    await db_session.commit()

    response = await client.get("/events", params={"limit": 2}, headers=bearer(key))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"events", "next_cursor", "has_more"}
    assert body["has_more"] is True
    assert body["next_cursor"] == "2"

    envelope = body["events"][0]
    assert set(envelope) == {
        "schema_version",
        "event_id",
        "type",
        "occurred_at",
        "recipient_organization_id",
        "resource_id",
        "resource_version",
        "data",
    }

    rest = await client.get("/events", params={"cursor": body["next_cursor"]}, headers=bearer(key))
    assert [e["resource_version"] for e in rest.json()["events"]] == [3]
    assert rest.json()["has_more"] is False


async def test_expired_cursor_returns_409(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    for seq in range(1, 4):
        await factories.create_integration_event(db_session, org, feed_seq=seq)
    await db_session.execute(delete(IntegrationEvent).where(IntegrationEvent.feed_seq < 3))
    await db_session.commit()

    response = await client.get("/events", params={"cursor": "0"}, headers=bearer(key))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CURSOR_EXPIRED"


async def test_limit_is_validated(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    response = await client.get("/events", params={"limit": 101}, headers=bearer(key))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_foreign_events_are_invisible(client: AsyncClient, db_session: AsyncSession) -> None:
    org_a = await provider_org(db_session, name="А")
    org_b = await provider_org(db_session, name="Б")
    _, key_b = await factories.create_integration_client(db_session, org_b)
    await factories.create_integration_event(db_session, org_a, feed_seq=1)
    await db_session.commit()

    response = await client.get("/events", headers=bearer(key_b))
    assert response.json()["events"] == []
