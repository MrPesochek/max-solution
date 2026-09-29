import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.infra.config import get_settings
from app.infra.net.signing import verify_webhook_signature
from tests import factories
from tests.integration_api.conftest import Receiver, bearer, idem, provider_org

pytestmark = pytest.mark.asyncio


async def _key(db_session: AsyncSession, **kwargs: object) -> str:
    org = await provider_org(db_session, **kwargs)  # type: ignore[arg-type]
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()
    return key


async def test_create_list_and_delete(client: AsyncClient, db_session: AsyncSession) -> None:
    key = await _key(db_session)

    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": "https://crm.example.com/hooks", "events": ["request.assigned"]},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["secret"]
    assert body["status"] == "active"
    assert body["events"] == ["request.assigned"]
    assert body["id"].startswith("whs_")

    listed = await client.get("/webhook-subscriptions", headers=bearer(key))
    assert listed.status_code == 200
    page = listed.json()
    assert [item["id"] for item in page["items"]] == [body["id"]]
    assert "secret" not in page["items"][0]
    assert page["has_more"] is False

    deleted = await client.delete(
        f"/webhook-subscriptions/{body['id']}", headers={**bearer(key), **idem("delete")}
    )
    assert deleted.status_code == 204

    listed = await client.get("/webhook-subscriptions", headers=bearer(key))
    assert listed.json()["items"][0]["status"] == "disabled"


async def test_invalid_url_is_rejected(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = await _key(db_session)
    monkeypatch.setenv("ALLOWED_PRIVATE_WEBHOOK_HOSTS", "")
    get_settings.cache_clear()

    response = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": "http://169.254.169.254/latest/meta-data", "events": []},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WEBHOOK_URL_REJECTED"


async def test_rotate_secret(client: AsyncClient, db_session: AsyncSession) -> None:
    key = await _key(db_session)
    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": "https://crm.example.com/hooks", "events": []},
    )
    subscription_id = created.json()["id"]

    rotated = await client.post(
        f"/webhook-subscriptions/{subscription_id}/rotate-secret",
        headers={**bearer(key), **idem("rotate")},
        json={},
    )
    assert rotated.status_code == 200
    assert rotated.json()["secret"] != created.json()["secret"]
    assert rotated.json()["id"] == subscription_id


async def test_test_delivery_is_signed(
    client: AsyncClient, db_session: AsyncSession, receiver: Receiver
) -> None:
    key = await _key(db_session)
    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": receiver.url, "events": []},
    )
    secret = created.json()["secret"]
    subscription_id = created.json()["id"]

    response = await client.post(
        f"/webhook-subscriptions/{subscription_id}/test",
        headers={**bearer(key), **idem("test")},
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["delivered"] is True
    assert body["status_code"] == 200
    assert body["event_id"].startswith("evt_")
    assert body["delivery_id"].startswith("dlv_")

    got = receiver.received[0]
    assert got.headers["x-event-id"] == body["event_id"]
    assert verify_webhook_signature(
        secret.encode(),
        int(got.headers["x-timestamp"]),
        got.body,
        got.headers["x-signature"],
        max_age_seconds=300,
        now=int(utcnow().timestamp()),
    )
    envelope = json.loads(got.body)
    assert envelope["type"] == "ping"
    assert envelope["data"] == {"test": True}


async def test_test_delivery_accepts_domain_event_type(
    client: AsyncClient, db_session: AsyncSession, receiver: Receiver
) -> None:
    key = await _key(db_session)
    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": receiver.url, "events": []},
    )
    response = await client.post(
        f"/webhook-subscriptions/{created.json()['id']}/test",
        headers={**bearer(key), **idem("test")},
        json={"event_type": "request.changed"},
    )
    assert response.status_code == 200
    assert json.loads(receiver.received[0].body)["type"] == "request.changed"


async def test_test_delivery_reports_receiver_error(
    client: AsyncClient, db_session: AsyncSession, receiver: Receiver
) -> None:
    key = await _key(db_session)
    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": receiver.url, "events": []},
    )
    receiver.respond_with(500)

    response = await client.post(
        f"/webhook-subscriptions/{created.json()['id']}/test",
        headers={**bearer(key), **idem("test")},
        json={},
    )
    assert response.json() == {
        "delivered": False,
        "event_id": response.json()["event_id"],
        "delivery_id": response.json()["delivery_id"],
        "status_code": 500,
        "error": "http:500",
    }


async def test_foreign_subscription_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner_key = await _key(db_session, name="А")
    stranger_key = await _key(db_session, name="Б")

    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(owner_key), **idem("create")},
        json={"url": "https://crm.example.com/hooks", "events": []},
    )
    subscription_id = created.json()["id"]

    listed = await client.get("/webhook-subscriptions", headers=bearer(stranger_key))
    assert listed.json()["items"] == []

    deleted = await client.delete(
        f"/webhook-subscriptions/{subscription_id}",
        headers={**bearer(stranger_key), **idem("delete")},
    )
    assert deleted.status_code == 404


async def test_webhooks_manage_scope_required(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(
        db_session, org, scopes=["requests:read", "events:read"]
    )
    await db_session.commit()

    response = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": "https://crm.example.com/hooks", "events": []},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_SCOPE"


async def test_idempotent_create_does_not_replay_secret(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    key = await _key(db_session)
    payload = {"url": "https://crm.example.com/hooks", "events": ["request.assigned"]}

    first = await client.post(
        "/webhook-subscriptions", headers={**bearer(key), **idem("same")}, json=payload
    )
    second = await client.post(
        "/webhook-subscriptions", headers={**bearer(key), **idem("same")}, json=payload
    )
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "IDEMPOTENT_SECRET_NOT_REPLAYABLE"
    assert error["details"]["response"]["id"] == first.json()["id"]
    assert first.json()["secret"] not in second.text

    listed = await client.get("/webhook-subscriptions", headers=bearer(key))
    assert len(listed.json()["items"]) == 1


async def test_test_delivery_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, receiver: Receiver
) -> None:
    key = await _key(db_session)
    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), **idem("create")},
        json={"url": receiver.url, "events": []},
    )
    url = f"/webhook-subscriptions/{created.json()['id']}/test"

    missing = await client.post(url, headers=bearer(key), json={})
    assert missing.status_code == 422

    first = await client.post(url, headers={**bearer(key), **idem("ping")}, json={})
    second = await client.post(url, headers={**bearer(key), **idem("ping")}, json={})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(receiver.received) == 1

    other = await client.post(
        url, headers={**bearer(key), **idem("ping")}, json={"event_type": "request.changed"}
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_list_requires_webhooks_manage(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org, scopes=["requests:read"])
    await db_session.commit()

    response = await client.get("/webhook-subscriptions", headers=bearer(key))
    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_scope"] == "webhooks:manage"


async def test_key_does_not_see_other_client_subscriptions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await provider_org(db_session)
    _, key_a = await factories.create_integration_client(db_session, org, name="A")
    _, key_b = await factories.create_integration_client(db_session, org, name="B")
    await db_session.commit()
    created = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key_a), **idem("create")},
        json={"url": "https://crm.example.com/hooks", "events": []},
    )

    listed = await client.get("/webhook-subscriptions", headers=bearer(key_b))
    assert listed.json()["items"] == []
    deleted = await client.delete(
        f"/webhook-subscriptions/{created.json()['id']}",
        headers={**bearer(key_b), **idem("delete")},
    )
    assert deleted.status_code == 404
