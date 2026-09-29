import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.clock import utcnow
from app.db.models import (
    IntegrationClient,
    IntegrationEvent,
    Organization,
    WebhookDelivery,
    WebhookSubscription,
)
from app.infra.config import get_settings
from app.infra.net.signing import verify_webhook_signature
from app.modules.integration import api as integration
from app.worker import feed_dispatcher, webhook_dispatcher
from tests import factories
from tests.worker.conftest import Receiver, provider_admin, provider_org

pytestmark = pytest.mark.asyncio

SECRET = "test-webhook-secret"


async def _prepare(
    db_session: AsyncSession, receiver: Receiver, *, events: list[str] | None = None
) -> tuple[Organization, IntegrationClient, WebhookSubscription, IntegrationEvent]:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    subscription = await factories.create_webhook_subscription(
        db_session, client, url=receiver.url, events=events, secret=SECRET
    )
    event = await factories.create_integration_event(db_session, org)
    await db_session.commit()
    await feed_dispatcher.run_once(utcnow())
    return org, client, subscription, event


async def _delivery(db_session: AsyncSession) -> WebhookDelivery:
    stmt = select(WebhookDelivery).execution_options(populate_existing=True)
    return (await db_session.execute(stmt)).scalars().one()


async def test_successful_delivery_is_signed(db_session: AsyncSession, receiver: Receiver) -> None:
    _, _, _, event = await _prepare(db_session, receiver)

    assert await webhook_dispatcher.run_once(utcnow()) == 2
    assert len(receiver.received) == 1

    got = receiver.received[0]
    assert got.headers["x-event-id"] == ids.encode("event", event.id)
    assert got.headers["x-delivery-id"].startswith("dlv_")
    assert verify_webhook_signature(
        SECRET.encode(),
        int(got.headers["x-timestamp"]),
        got.body,
        got.headers["x-signature"],
        max_age_seconds=300,
        now=int(utcnow().timestamp()),
    )

    envelope = json.loads(got.body)
    assert envelope["schema_version"] == "1"
    assert envelope["event_id"] == ids.encode("event", event.id)
    assert envelope["type"] == "request.assigned"
    assert envelope["resource_version"] == 1

    delivery = await _delivery(db_session)
    assert delivery.state == "delivered"
    assert delivery.last_http_status == 200
    assert delivery.next_attempt_at is None


async def test_wrong_secret_is_rejected_by_receiver(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    """A20: получатель отвергает подпись, рассчитанную другим секретом."""
    await _prepare(db_session, receiver)
    await webhook_dispatcher.run_once(utcnow())
    got = receiver.received[0]

    assert not verify_webhook_signature(
        b"another-secret",
        int(got.headers["x-timestamp"]),
        got.body,
        got.headers["x-signature"],
        max_age_seconds=300,
        now=int(utcnow().timestamp()),
    )


async def test_server_error_retries_then_succeeds(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    await _prepare(db_session, receiver)
    receiver.respond_with(500)

    await webhook_dispatcher.run_once(utcnow())
    delivery = await _delivery(db_session)
    assert delivery.state == "retrying"
    assert delivery.last_http_status == 500
    assert delivery.attempt_count == 1
    assert delivery.next_attempt_at is not None

    first_delivery_id = delivery.current_delivery_id
    await _make_due(db_session)
    assert await webhook_dispatcher.send_pending(utcnow()) == 1

    delivery = await _delivery(db_session)
    assert delivery.state == "delivered"
    assert delivery.attempt_count == 2
    assert delivery.current_delivery_id != first_delivery_id

    assert receiver.received[0].headers["x-event-id"] == receiver.received[1].headers["x-event-id"]
    assert (
        receiver.received[0].headers["x-delivery-id"]
        != receiver.received[1].headers["x-delivery-id"]
    )


async def test_permanent_client_error_fails_without_retry(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    await _prepare(db_session, receiver)
    receiver.respond_with(410)

    await webhook_dispatcher.run_once(utcnow())
    delivery = await _delivery(db_session)
    assert delivery.state == "failed"
    assert delivery.last_http_status == 410
    assert delivery.next_attempt_at is None

    assert await webhook_dispatcher.send_pending(utcnow()) == 0
    assert len(receiver.received) == 1


async def test_retry_window_exhausted(db_session: AsyncSession, receiver: Receiver) -> None:
    await _prepare(db_session, receiver)
    receiver.respond_with(503)
    await webhook_dispatcher.run_once(utcnow())

    delivery = await _delivery(db_session)
    delivery.expires_at = utcnow() - timedelta(seconds=1)
    delivery.next_attempt_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()

    await webhook_dispatcher.send_pending(utcnow())
    delivery = await _delivery(db_session)
    assert delivery.state == "failed"
    assert delivery.last_error == "retry_window_exhausted"
    assert len(receiver.received) == 1


async def test_unreachable_receiver_then_recovery_delivers_once(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    """A18: пока CRM недоступна, событие остаётся в очереди; после восстановления
    оно доставляется, и логически — ровно один раз (один event_id)."""
    _, _, _, event = await _prepare(db_session, receiver)
    receiver.respond_with(503, 503)

    await webhook_dispatcher.run_once(utcnow())
    await _make_due(db_session)
    await webhook_dispatcher.send_pending(utcnow())
    assert (await _delivery(db_session)).state == "retrying"

    await _make_due(db_session)
    await webhook_dispatcher.send_pending(utcnow())

    delivery = await _delivery(db_session)
    assert delivery.state == "delivered"
    assert len({r.headers["x-event-id"] for r in receiver.received}) == 1
    assert receiver.received[0].headers["x-event-id"] == ids.encode("event", event.id)

    deliveries = list((await db_session.execute(select(WebhookDelivery))).scalars())
    assert len(deliveries) == 1


async def test_ssrf_check_before_each_attempt(
    db_session: AsyncSession, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _prepare(db_session, receiver)
    await webhook_dispatcher.run_once(utcnow())

    monkeypatch.setenv("ALLOWED_PRIVATE_WEBHOOK_HOSTS", "")
    get_settings.cache_clear()

    delivery = await _delivery(db_session)
    delivery.state = "queued"
    delivery.next_attempt_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    sent_before = len(receiver.received)

    await webhook_dispatcher.send_pending(utcnow())
    delivery = await _delivery(db_session)
    assert delivery.state == "blocked"
    assert delivery.last_error is not None and delivery.last_error.startswith("ssrf:")
    assert len(receiver.received) == sent_before


async def test_enqueue_is_idempotent(db_session: AsyncSession, receiver: Receiver) -> None:
    await _prepare(db_session, receiver)
    assert await integration.enqueue_deliveries(utcnow()) == 1
    assert await integration.enqueue_deliveries(utcnow()) == 0

    deliveries = list((await db_session.execute(select(WebhookDelivery))).scalars())
    assert len(deliveries) == 1


async def test_event_type_filter(db_session: AsyncSession, receiver: Receiver) -> None:
    await _prepare(db_session, receiver, events=["request.closed"])
    assert await integration.enqueue_deliveries(utcnow()) == 0
    assert list((await db_session.execute(select(WebhookDelivery))).scalars()) == []


async def test_disabled_subscription_gets_nothing(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    _, _, subscription, _ = await _prepare(db_session, receiver)
    subscription.status = "disabled"
    await db_session.commit()

    assert await integration.enqueue_deliveries(utcnow()) == 0


async def test_foreign_organization_subscription_is_not_used(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    await _prepare(db_session, receiver)
    other = await provider_org(db_session, name="Чужой")
    other_client, _ = await factories.create_integration_client(db_session, other)
    await factories.create_webhook_subscription(db_session, other_client, url=receiver.url)
    await db_session.commit()

    await webhook_dispatcher.run_once(utcnow())
    deliveries = list((await db_session.execute(select(WebhookDelivery))).scalars())
    assert len(deliveries) == 1
    assert deliveries[0].webhook_subscription_id != other_client.id


async def test_restart_picks_up_queued_and_stale_lease(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    """A22: новый экземпляр цикла подхватывает очередь, зависшая аренда освобождается."""
    await _prepare(db_session, receiver)
    await integration.enqueue_deliveries(utcnow())

    leased = await integration.lease_deliveries(utcnow())
    assert len(leased) == 1
    assert await integration.lease_deliveries(utcnow()) == []

    delivery = await _delivery(db_session)
    assert delivery.state == "queued"
    delivery.lease_until = utcnow() - timedelta(seconds=1)
    await db_session.commit()

    assert await webhook_dispatcher.send_pending(utcnow()) == 1
    assert (await _delivery(db_session)).state == "delivered"


async def test_delivery_view_distinguishes_in_flight_from_waiting_retry(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org, _, _, _ = await _prepare(db_session, receiver)
    await integration.enqueue_deliveries(utcnow())

    leased = await integration.lease_deliveries(utcnow())
    assert len(leased) == 1
    page = await integration.list_deliveries(org.id)
    assert page.items[0].state == "queued"
    assert page.items[0].in_flight is True

    await integration.record_attempt(
        leased[0], integration.AttemptResult(outcome="retryable", error="timeout"), utcnow()
    )
    page = await integration.list_deliveries(org.id)
    assert page.items[0].state == "retrying"
    assert page.items[0].in_flight is False


async def test_redeliver_by_admin_keeps_event_id(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org, _, _, event = await _prepare(db_session, receiver)
    admin = await provider_admin(db_session, org)
    await db_session.commit()
    receiver.respond_with(410)

    await webhook_dispatcher.run_once(utcnow())
    delivery = await _delivery(db_session)
    assert delivery.state == "failed"
    first_delivery_id = receiver.received[0].headers["x-delivery-id"]

    page = await integration.list_deliveries(org.id)
    assert page.items[0].event_id == ids.encode("event", event.id)

    await integration.redeliver(admin, page.items[0].id)
    assert (await _delivery(db_session)).state == "queued"

    await webhook_dispatcher.send_pending(utcnow())
    assert receiver.received[1].headers["x-event-id"] == ids.encode("event", event.id)
    assert receiver.received[1].headers["x-delivery-id"] != first_delivery_id


async def test_redeliver_rejects_foreign_organization(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org, _, _, _ = await _prepare(db_session, receiver)
    other = await provider_org(db_session, name="Чужой")
    stranger = await provider_admin(db_session, other)
    await db_session.commit()
    receiver.respond_with(410)
    await webhook_dispatcher.run_once(utcnow())

    page = await integration.list_deliveries(org.id)
    with pytest.raises(Exception) as exc:
        await integration.redeliver(stranger, page.items[0].id)
    assert getattr(exc.value, "status", None) == 404


async def test_deliveries_are_scoped_to_organization(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org, _, _, _ = await _prepare(db_session, receiver)
    other = await provider_org(db_session, name="Чужой")
    await db_session.commit()
    await webhook_dispatcher.run_once(utcnow())

    assert len((await integration.list_deliveries(org.id)).items) == 1
    assert (await integration.list_deliveries(other.id)).items == []


async def _make_due(db_session: AsyncSession) -> None:
    delivery = await _delivery(db_session)
    delivery.next_attempt_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()


async def test_event_without_feed_seq_is_not_delivered(
    db_session: AsyncSession, receiver: Receiver
) -> None:
    org = await provider_org(db_session)
    client, _ = await factories.create_integration_client(db_session, org)
    await factories.create_webhook_subscription(db_session, client, url=receiver.url)
    await factories.create_integration_event(db_session, org)
    await db_session.commit()

    assert await integration.enqueue_deliveries(utcnow()) == 0
    stored = (await db_session.execute(select(IntegrationEvent))).scalars().one()
    assert stored.feed_seq is None
