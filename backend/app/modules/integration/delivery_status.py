import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    DeliveryState,
    IntegrationClientStatus,
    IntegrationEventType,
    WebhookSubscriptionStatus,
)
from app.db.models import IntegrationClient, IntegrationEvent, WebhookDelivery, WebhookSubscription

RequestDeliveryState = Literal["queued", "delivered", "retrying", "failed", "none"]

_ASSIGNING_EVENTS = (
    IntegrationEventType.REQUEST_ASSIGNED.value,
    IntegrationEventType.OFFER_SELECTED.value,
)
_PRIORITY = (
    DeliveryState.DELIVERED.value,
    DeliveryState.RETRYING.value,
    DeliveryState.QUEUED.value,
    DeliveryState.FAILED.value,
    DeliveryState.BLOCKED.value,
)


async def providers_with_active_webhook(
    session: AsyncSession, provider_org_ids: Collection[uuid.UUID]
) -> set[uuid.UUID]:
    """K-05: «у исполнителя есть CRM» — действующая подписка на вебхук с
    действующим ключом. Ключ без подписки (CRM читает ленту `/events`) сюда не
    относится: по нему нет достоверного признака доставки (K-16)."""
    if not provider_org_ids:
        return set()
    rows = await session.execute(
        select(WebhookSubscription.provider_org_id)
        .join(IntegrationClient, IntegrationClient.id == WebhookSubscription.integration_client_id)
        .where(
            WebhookSubscription.provider_org_id.in_(tuple(provider_org_ids)),
            WebhookSubscription.status == WebhookSubscriptionStatus.ACTIVE.value,
            IntegrationClient.status == IntegrationClientStatus.ACTIVE.value,
        )
    )
    return set(rows.scalars())


@dataclass(frozen=True, slots=True)
class RequestDeliveryStatus:
    """`channel="app"` — у исполнителя нет CRM, заявка приходит в бот и мини-приложение."""

    state: RequestDeliveryState
    channel: Literal["crm", "app"]
    delivered_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None


async def request_delivery_status(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    provider_org_id: uuid.UUID,
    since: datetime,
) -> RequestDeliveryStatus:
    """`since` — начало назначения: события прежних попыток не учитываются."""
    has_client = provider_org_id in await providers_with_active_webhook(session, [provider_org_id])
    if not has_client:
        return RequestDeliveryStatus(state="none", channel="app")

    event = (
        await session.execute(
            select(IntegrationEvent)
            .where(
                IntegrationEvent.recipient_org_id == provider_org_id,
                IntegrationEvent.resource_kind == "request",
                IntegrationEvent.resource_id == request_id,
                IntegrationEvent.event_type.in_(_ASSIGNING_EVENTS),
                IntegrationEvent.created_at >= since,
            )
            .order_by(IntegrationEvent.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if event is None:
        return RequestDeliveryStatus(state="none", channel="crm")

    deliveries = list(
        (
            await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.integration_event_id == event.id)
            )
        ).scalars()
    )
    if not deliveries:
        return RequestDeliveryStatus(state="queued", channel="crm")

    return _aggregate(deliveries)


async def message_delivery_statuses(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    provider_org_id: uuid.UUID,
    message_public_ids: Collection[str],
) -> dict[str, RequestDeliveryStatus]:
    """Доставка событий `message.created` в CRM исполнителя по id сообщений.

    Сообщение без события или исполнитель без действующей подписки в ответ не попадают:
    строку «Доставлено в CRM» тогда не показывают."""
    if not message_public_ids:
        return {}
    has_client = provider_org_id in await providers_with_active_webhook(session, [provider_org_id])
    if not has_client:
        return {}
    message_id = IntegrationEvent.payload["message"]["id"].astext
    events = (
        await session.execute(
            select(IntegrationEvent.id, message_id).where(
                IntegrationEvent.recipient_org_id == provider_org_id,
                IntegrationEvent.resource_kind == "request",
                IntegrationEvent.resource_id == request_id,
                IntegrationEvent.event_type == IntegrationEventType.MESSAGE_CREATED.value,
                message_id.in_(tuple(message_public_ids)),
            )
        )
    ).all()
    if not events:
        return {}
    by_event = {event_id: public_id for event_id, public_id in events}
    deliveries: dict[uuid.UUID, list[WebhookDelivery]] = {event_id: [] for event_id in by_event}
    for delivery in (
        await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.integration_event_id.in_(tuple(by_event)))
        )
    ).scalars():
        deliveries[delivery.integration_event_id].append(delivery)
    return {by_event[event_id]: _aggregate(rows) for event_id, rows in deliveries.items()}


def _aggregate(deliveries: list[WebhookDelivery]) -> RequestDeliveryStatus:
    if not deliveries:
        return RequestDeliveryStatus(state="queued", channel="crm")
    best = min(deliveries, key=lambda row: _PRIORITY.index(row.state))
    if best.state == DeliveryState.DELIVERED.value:
        return RequestDeliveryStatus(
            state="delivered",
            channel="crm",
            delivered_at=best.last_attempt_at or best.updated_at,
            last_attempt_at=best.last_attempt_at,
        )
    if best.state in (DeliveryState.FAILED.value, DeliveryState.BLOCKED.value):
        return RequestDeliveryStatus(
            state="failed", channel="crm", last_attempt_at=best.last_attempt_at
        )
    return RequestDeliveryStatus(
        state="retrying" if best.state == DeliveryState.RETRYING.value else "queued",
        channel="crm",
        last_attempt_at=best.last_attempt_at,
        next_attempt_at=best.next_attempt_at,
    )
