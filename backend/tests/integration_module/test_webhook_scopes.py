import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.db.models import WebhookDelivery
from app.modules.integration import api as integration
from app.worker import feed_dispatcher, webhook_dispatcher
from tests import factories
from tests.integration_module.conftest import provider_org
from tests.worker.conftest import Receiver, receiver

pytestmark = pytest.mark.asyncio

__all__ = ["receiver"]


async def _deliveries(db_session: AsyncSession) -> list[WebhookDelivery]:
    stmt = select(WebhookDelivery).execution_options(populate_existing=True)
    return list((await db_session.execute(stmt)).scalars())


async def test_event_skipped_without_read_scope(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(
        db_session, org, scopes=["marketplace:read", "webhooks:manage"]
    )
    await factories.create_webhook_subscription(
        db_session,
        client,
        url=receiver.url,
        events=["request.assigned", "marketplace.request.available"],
    )
    await factories.create_integration_event(db_session, org, event_type="request.assigned")
    await factories.create_integration_event(
        db_session, org, event_type="marketplace.request.available"
    )
    await db_session.commit()
    await feed_dispatcher.run_once(utcnow())

    await webhook_dispatcher.run_once(utcnow())

    assert len(receiver.received) == 1
    assert b"marketplace.request.available" in receiver.received[0].body
    assert len(await _deliveries(db_session)) == 1


async def test_revoked_client_gets_no_queued_delivery(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client, url=receiver.url)
    await factories.create_integration_event(db_session, org)
    await db_session.commit()
    await feed_dispatcher.run_once(utcnow())
    now = utcnow()

    assert await integration.enqueue_deliveries(now) == 1

    client.status = "revoked"
    client.revoked_at = now
    await db_session.commit()

    await webhook_dispatcher.send_pending(utcnow())

    assert receiver.received == []
    [delivery] = await _deliveries(db_session)
    assert delivery.state == "failed"
    assert delivery.last_error == "api_key_revoked"


async def test_scope_removed_after_enqueue(db_session: AsyncSession, receiver: Receiver) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client, url=receiver.url)
    await factories.create_integration_event(db_session, org)
    await db_session.commit()
    await feed_dispatcher.run_once(utcnow())

    assert await integration.enqueue_deliveries(utcnow()) == 1
    client.scopes = ["webhooks:manage", "events:read"]
    await db_session.commit()

    await webhook_dispatcher.send_pending(utcnow())

    assert receiver.received == []
    [delivery] = await _deliveries(db_session)
    assert delivery.last_error == "scope_missing"


async def test_revoked_client_is_not_enqueued(db_session: AsyncSession, receiver: Receiver) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org, status="revoked")
    await factories.create_webhook_subscription(db_session, client, url=receiver.url)
    await factories.create_integration_event(db_session, org)
    await db_session.commit()
    await feed_dispatcher.run_once(utcnow())

    await webhook_dispatcher.run_once(utcnow())

    assert receiver.received == []
    assert await _deliveries(db_session) == []
