import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.clock import utcnow
from app.db.models import Organization
from app.worker import webhook_dispatcher
from tests import factories
from tests.integration_api.conftest import Receiver, idem, provider_org

pytestmark = pytest.mark.asyncio


async def _admin_headers(
    db_session: AsyncSession, org: Organization, *, role: str = "provider_admin"
) -> dict[str, str]:
    user = await factories.create_user(db_session)
    await factories.create_membership(db_session, user, org, role=role)
    token = await factories.create_session_token(db_session, user)
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": ids.encode("organization", org.id),
    }


async def test_api_key_lifecycle(app_client: AsyncClient, db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    headers = await _admin_headers(db_session, org)
    await db_session.commit()

    created = await app_client.post(
        "/integration/api-keys",
        headers={**headers, **idem("create")},
        json={"name": "CRM", "scopes": ["requests:read", "webhooks:manage"]},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith("rk_test_")
    key_id = body["id"]

    listed = await app_client.get("/integration/api-keys", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [key_id]
    assert "key" not in listed.json()[0]

    rotated = await app_client.post(
        f"/integration/api-keys/{key_id}/rotate", headers={**headers, **idem("rotate")}, json={}
    )
    assert rotated.status_code == 200
    assert rotated.json()["key"] != body["key"]

    revoked = await app_client.post(
        f"/integration/api-keys/{key_id}/revoke", headers={**headers, **idem("revoke")}, json={}
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


async def test_dispatcher_cannot_manage_keys(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await provider_org(db_session)
    headers = await _admin_headers(db_session, org, role="provider_dispatcher")
    await db_session.commit()

    response = await app_client.post(
        "/integration/api-keys",
        headers={**headers, **idem("create")},
        json={"name": "CRM", "scopes": ["requests:read"]},
    )
    assert response.status_code == 403

    listed = await app_client.get("/integration/api-keys", headers=headers)
    assert listed.status_code == 403


async def test_subscriptions_and_deliveries_screen(
    app_client: AsyncClient, db_session: AsyncSession, receiver: Receiver
) -> None:
    org = await provider_org(db_session)
    headers = await _admin_headers(db_session, org)
    client_row, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client_row, url=receiver.url)
    event = await factories.create_integration_event(db_session, org, feed_seq=1)
    await db_session.commit()
    receiver.respond_with(410)
    await webhook_dispatcher.run_once(utcnow())

    subscriptions = await app_client.get("/integration/webhook-subscriptions", headers=headers)
    assert subscriptions.status_code == 200
    assert [item["url"] for item in subscriptions.json()] == [receiver.url]

    deliveries = await app_client.get("/integration/deliveries", headers=headers)
    assert deliveries.status_code == 200
    page = deliveries.json()
    assert page["items"][0]["state"] == "failed"
    assert page["items"][0]["event_id"] == ids.encode("event", event.id)
    assert page["items"][0]["event_type"] == "request.assigned"
    assert page["items"][0]["last_http_status"] == 410

    redelivered = await app_client.post(
        f"/integration/deliveries/{page['items'][0]['id']}/redeliver",
        headers={**headers, **idem("redeliver")},
        json={},
    )
    assert redelivered.status_code == 200
    assert redelivered.json()["state"] == "queued"


async def test_foreign_organization_sees_nothing(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a = await provider_org(db_session, name="А")
    org_b = await provider_org(db_session, name="Б")
    headers_b = await _admin_headers(db_session, org_b)
    client_a, _ = await factories.create_integration_client(db_session, org_a)
    await factories.create_webhook_subscription(db_session, client_a)
    await db_session.commit()

    subscriptions = await app_client.get("/integration/webhook-subscriptions", headers=headers_b)
    assert subscriptions.json() == []

    keys = await app_client.get("/integration/api-keys", headers=headers_b)
    assert keys.json() == []

    deliveries = await app_client.get("/integration/deliveries", headers=headers_b)
    assert deliveries.json()["items"] == []
