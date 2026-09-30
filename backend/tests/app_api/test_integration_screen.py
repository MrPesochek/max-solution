from collections.abc import Iterator
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import ids
from app.core.clock import utcnow
from app.db import session as db_session
from app.db.models import AuditEntry, IntegrationEvent, Notification, WebhookDelivery
from app.infra.config import Settings
from tests import factories
from tests.app_api.conftest import auth, idem
from tests.support import OTHER_INN, PROVIDER_INN, make_provider, org_id, session_token

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(
        monkeypatch, SECRETS_ENCRYPTION_KEY=factories.SECRETS_ENCRYPTION_KEY
    )


HOOK = "https://crm.example.com/hooks"


async def _admin_headers(
    key: str, *, inn: str = PROVIDER_INN
) -> tuple[dict[str, str], dict[str, str], object]:
    provider = await make_provider(key, status="active", accepting=True, verified=True, inn=inn)
    admin = auth(await session_token(provider.admin), org_id(provider.admin))
    dispatcher = auth(await session_token(provider.dispatcher), org_id(provider.dispatcher))
    return admin, dispatcher, provider


async def _key(client: AsyncClient, headers: dict[str, str], name: str = "CRM") -> str:
    created = await client.post(
        "/integration/api-keys",
        headers={**headers, **idem(f"key-{name}")},
        json={"name": name, "scopes": ["requests:read", "webhooks:manage"]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_summary_without_secrets(client: AsyncClient) -> None:
    admin, _, provider = await _admin_headers("int-sum")
    empty = await client.get("/integration/summary", headers=admin)
    assert empty.status_code == 200, empty.text
    assert empty.json()["connected"] is False
    assert empty.json()["webhook"] is None
    assert empty.json()["deliveries_24h"]["total"] == 0

    await _key(client, admin)
    created = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("sub-1")},
        json={"url": HOOK, "events": ["request.assigned"]},
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]

    now = utcnow()
    org = provider.organization_id
    subscription_id = ids.decode("webhook_subscription", created.json()["id"])
    async with db_session.transaction() as session:
        for state in ("delivered", "failed", "retrying"):
            event = IntegrationEvent(
                event_type="request.assigned",
                recipient_org_id=org,
                resource_kind="request",
                resource_id=org,
                occurred_at=now,
                payload={},
            )
            session.add(event)
            await session.flush()
            session.add(
                WebhookDelivery(
                    integration_event_id=event.id,
                    webhook_subscription_id=subscription_id,
                    provider_org_id=org,
                    state=state,
                    expires_at=now + timedelta(days=1),
                )
            )

    summary = await client.get("/integration/summary", headers=admin)
    body = summary.json()
    assert body["connected"] is True
    assert body["api_keys_active"] == 1
    assert body["webhook"]["url"] == HOOK
    assert body["last_event_at"] is not None
    assert body["deliveries_24h"] == {
        "total": 3,
        "delivered": 1,
        "failed": 1,
        "retrying": 1,
        "queued": 0,
    }
    assert secret not in summary.text
    assert "secret" not in body["webhook"]


async def test_only_admin_reads_summary_and_manages_subscriptions(client: AsyncClient) -> None:
    admin, dispatcher, _ = await _admin_headers("int-roles")
    await _key(client, admin)
    assert (await client.get("/integration/summary", headers=dispatcher)).status_code == 403
    denied = await client.post(
        "/integration/webhook-subscriptions",
        headers={**dispatcher, **idem("sub-d")},
        json={"url": HOOK, "events": []},
    )
    assert denied.status_code == 403

    other_admin, _, _ = await _admin_headers("int-other", inn=OTHER_INN)
    created = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("sub-own")},
        json={"url": HOOK, "events": []},
    )
    sub_id = created.json()["id"]
    foreign = await client.post(
        f"/integration/webhook-subscriptions/{sub_id}/disable",
        headers={**other_admin, **idem("sub-foreign")},
    )
    assert foreign.status_code == 404


async def test_disable_enable_and_rotate(client: AsyncClient) -> None:
    admin, _, _ = await _admin_headers("int-flow")
    await _key(client, admin)
    created = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("sub-2")},
        json={"url": HOOK, "events": []},
    )
    sub_id = created.json()["id"]
    first_secret = created.json()["secret"]

    replay = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("sub-2")},
        json={"url": HOOK, "events": []},
    )
    assert replay.status_code == 409
    assert first_secret not in replay.text

    disabled = await client.post(
        f"/integration/webhook-subscriptions/{sub_id}/disable", headers={**admin, **idem("d1")}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    again = await client.post(
        f"/integration/webhook-subscriptions/{sub_id}/disable", headers={**admin, **idem("d2")}
    )
    assert again.status_code == 409

    enabled = await client.post(
        f"/integration/webhook-subscriptions/{sub_id}/enable", headers={**admin, **idem("e1")}
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["status"] == "active"

    rotated = await client.post(
        f"/integration/webhook-subscriptions/{sub_id}/rotate-secret",
        headers={**admin, **idem("r1")},
    )
    assert rotated.status_code == 200
    assert rotated.json()["secret"] != first_secret

    listed = await client.get("/integration/webhook-subscriptions", headers=admin)
    assert "secret" not in listed.json()[0]

    async with db_session.transaction() as session:
        actions = set((await session.execute(select(AuditEntry.action))).scalars())
        notified = list((await session.execute(select(Notification.payload))).scalars())
    assert {
        "integration.webhook_subscription.create",
        "integration.webhook_subscription.delete",
        "integration.webhook_subscription.enable",
        "integration.webhook_subscription.rotate_secret",
    } <= actions
    assert {"enabled", "disabled", "created", "secret_rotated"} <= {
        payload.get("change") for payload in notified
    }


async def test_subscription_rejects_private_url_and_needs_key(client: AsyncClient) -> None:
    admin, _, _ = await _admin_headers("int-ssrf")
    no_key = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("nokey")},
        json={"url": HOOK, "events": []},
    )
    assert no_key.status_code == 409
    assert no_key.json()["error"]["code"] == "NO_ACTIVE_API_KEY"

    await _key(client, admin)
    private = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("ssrf")},
        json={"url": "http://127.0.0.1/hook", "events": []},
    )
    assert private.status_code == 422
    assert private.json()["error"]["code"] == "WEBHOOK_URL_REJECTED"

    second = await _key(client, admin, name="CRM-2")
    ambiguous = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("amb")},
        json={"url": HOOK, "events": []},
    )
    assert ambiguous.status_code == 422
    chosen = await client.post(
        "/integration/webhook-subscriptions",
        headers={**admin, **idem("chosen")},
        json={"url": HOOK, "events": [], "client_id": second},
    )
    assert chosen.status_code == 201, chosen.text
