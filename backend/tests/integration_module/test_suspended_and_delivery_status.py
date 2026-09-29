from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import Conflict
from app.db.models import ProviderProfile
from app.modules.integration import api as integration
from tests import factories
from tests.integration_module.conftest import (
    idem,
    integration_actor,
    provider_admin,
    provider_org,
)

pytestmark = pytest.mark.asyncio


async def _suspend(session: AsyncSession, org_id: object) -> None:
    await session.execute(
        update(ProviderProfile)
        .where(ProviderProfile.organization_id == org_id)
        .values(status="suspended")
    )
    await session.commit()


async def test_suspended_provider_cannot_manage_keys_and_webhooks(
    db_session: AsyncSession,
) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    client, _ = await factories.create_integration_client(db_session, org)
    subscription = await factories.create_webhook_subscription(db_session, client)
    await db_session.commit()
    await _suspend(db_session, org.id)
    client_public_id = ids.encode("integration_client", client.id)
    subscription_public_id = ids.encode("webhook_subscription", subscription.id)

    attempts = [
        integration.create_api_key(
            admin,
            integration.ApiKeyCreateData(name="Новый", scopes=["requests:read"]),
            idem=idem("POST /api-keys"),
        ),
        integration.rotate_api_key(admin, client_public_id, idem=idem("POST /rotate")),
        integration.create_subscription(
            integration_actor(client),
            integration.SubscriptionCreateData(url="https://crm.example.com/other"),
            idem=idem("POST /webhook-subscriptions"),
        ),
        integration.rotate_subscription_secret(
            admin, subscription_public_id, idem=idem("POST /rotate-secret")
        ),
    ]
    for attempt in attempts:
        with pytest.raises(Conflict) as exc:
            await attempt
        assert exc.value.code == "PROVIDER_NOT_ACTIVE"

    disabled = await integration.delete_subscription(
        admin, subscription_public_id, idem=idem("DELETE /webhook-subscriptions")
    )
    assert disabled.body["status"] == "disabled"
    revoked = await integration.revoke_api_key(admin, client_public_id, idem=idem("revoke"))
    assert revoked.body["status"] == "revoked"


async def test_active_provider_creates_key(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()
    created = await integration.create_api_key(
        admin,
        integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]),
        idem=idem("POST /api-keys"),
    )
    assert created.status == 201


async def test_key_without_webhook_is_not_crm(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    event = await factories.create_integration_event(db_session, org)
    await db_session.commit()

    status = await integration.request_delivery_status(
        db_session,
        request_id=event.resource_id,
        provider_org_id=org.id,
        since=utcnow() - timedelta(hours=1),
    )
    assert (status.state, status.channel) == ("none", "app")

    await factories.create_webhook_subscription(db_session, client)
    await db_session.commit()
    status = await integration.request_delivery_status(
        db_session,
        request_id=event.resource_id,
        provider_org_id=org.id,
        since=utcnow() - timedelta(hours=1),
    )
    assert (status.state, status.channel) == ("queued", "crm")
    assert await integration.providers_with_active_webhook(db_session, [org.id]) == {org.id}


async def test_redeliver_refuses_delivery_in_flight(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    client, _ = await factories.create_integration_client(db_session, org)
    subscription = await factories.create_webhook_subscription(db_session, client)
    event = await factories.create_integration_event(db_session, org)
    delivery = await factories.create_webhook_delivery(
        db_session, event, subscription, state="retrying"
    )
    delivery.lease_until = utcnow() + timedelta(minutes=1)
    await db_session.commit()
    public_id = ids.encode("delivery", delivery.id)

    with pytest.raises(Conflict) as exc:
        await integration.redeliver(admin, public_id, idem=idem("redeliver"))
    assert exc.value.code == "DELIVERY_IN_FLIGHT"

    delivery.lease_until = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    result = await integration.redeliver(admin, public_id, idem=idem("redeliver-2"))
    assert result.body["state"] == "queued"
