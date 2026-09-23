from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.core import ids
from app.db.enums import IntegrationEventType
from app.db.models import IntegrationClient, IntegrationEvent, WebhookDelivery, WebhookSubscription
from app.modules.integration.policy import key_warnings

SCHEMA_VERSION = "1"

_RESOURCE_KINDS = {
    "request": "request",
    "assignment": "assignment",
    "offer": "offer",
    "visit_proposal": "visit_proposal",
    "repair_quote": "repair_quote",
    "cancellation": "cancellation",
    "message": "message",
    "service_binding": "service_binding",
    "review": "review",
}


class ApiKeyView(BaseModel):
    id: str
    name: str
    scopes: list[str]
    status: str
    key_prefix: str
    created_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    warnings: list[str] = []


class ApiKeyIssuedView(ApiKeyView):
    key: str


class WebhookSubscriptionView(BaseModel):
    id: str
    url: str
    events: list[str]
    status: str
    created_at: datetime
    disabled_at: datetime | None = None


class WebhookSubscriptionSecretView(WebhookSubscriptionView):
    secret: str


_EVENT_TYPE_NAMES = [*sorted(str(t) for t in IntegrationEventType), "ping"]

_DATA_DESCRIPTION = (
    "Разрешённое получателю представление ресурса на момент события; состав зависит "
    "от `type`. `request.*`, `assignment.revoked`, `cancellation.requested` — поля "
    "карточки заявки для исполнителя (`status`, `assignment_state`, `version` и др.); "
    "`message.created` — сообщение; `offer.selected` — выбранное предложение без "
    "точного адреса; `visit_proposal.responded` и `repair_quote.responded` — id, "
    "версия и решение по предложению; `service_binding.changed` — привязка в "
    "договорном объёме без токена приглашения; `marketplace.request.*` — только "
    'публичная карточка биржи; `ping` — `{"test": true}`. Поля могут добавляться; '
    "при сомнении читайте актуальный ресурс по `resource_id` и сравнивайте "
    "`resource_version` (ТЗ 11, п. 3)."
)


class EventEnvelopeView(BaseModel):
    """Конверт события (ТЗ 11). Один и тот же для тела вебхука и ленты /events."""

    schema_version: str
    event_id: str
    type: Annotated[
        str,
        Field(description="Тип события.", json_schema_extra={"enum": _EVENT_TYPE_NAMES}),
    ]
    occurred_at: datetime
    recipient_organization_id: str
    resource_id: str
    resource_version: int | None = None
    data: Annotated[
        dict[str, Any],
        Field(
            description=_DATA_DESCRIPTION,
            json_schema_extra={"type": "object", "additionalProperties": True},
        ),
    ]


class EventsPageView(BaseModel):
    events: list[EventEnvelopeView]
    next_cursor: str | None = None
    has_more: bool = False


class DeliveryView(BaseModel):
    id: str
    event_id: str
    event_type: str
    subscription_id: str
    state: str
    in_flight: bool
    attempt_count: int
    delivery_id: str
    last_http_status: int | None = None
    last_error: str | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    expires_at: datetime
    created_at: datetime


class DeliveryPageView(BaseModel):
    items: list[DeliveryView]
    next_cursor: str | None = None
    has_more: bool = False


class IntegrationWebhookBriefView(BaseModel):
    """Подписка в сводке — без секрета подписи."""

    id: str
    url: str
    status: str


class IntegrationDeliveriesStatsView(BaseModel):
    total: int = 0
    delivered: int = 0
    failed: int = 0
    retrying: int = 0
    queued: int = 0


class IntegrationSummaryView(BaseModel):
    """Сводка экрана «Интеграция» (ТЗ 6.7): состояние подключения и доставки за сутки.

    `connected` — у организации есть действующий ключ CRM; `webhook` — последняя
    активная подписка (если активных нет — последняя отключённая)."""

    connected: bool
    api_keys_active: int
    last_key_used_at: datetime | None = None
    webhook: IntegrationWebhookBriefView | None = None
    last_event_at: datetime | None = None
    deliveries_24h: IntegrationDeliveriesStatsView


class WebhookTestResultView(BaseModel):
    delivered: bool
    event_id: str
    delivery_id: str
    status_code: int | None = None
    error: str | None = None


def encode_resource_id(resource_kind: str, resource_id: Any) -> str:
    kind = _RESOURCE_KINDS.get(resource_kind)
    return ids.encode(kind, resource_id) if kind else str(resource_id)


def to_api_key_view(client: IntegrationClient) -> ApiKeyView:
    return ApiKeyView(
        id=ids.encode("integration_client", client.id),
        name=client.name,
        scopes=list(client.scopes),
        status=client.status,
        key_prefix=client.api_key_prefix,
        created_at=client.created_at,
        rotated_at=client.rotated_at,
        revoked_at=client.revoked_at,
        last_used_at=client.last_used_at,
        warnings=key_warnings(client.scopes),
    )


def to_api_key_issued_view(client: IntegrationClient, key: str) -> ApiKeyIssuedView:
    return ApiKeyIssuedView(**to_api_key_view(client).model_dump(), key=key)


def to_subscription_view(subscription: WebhookSubscription) -> WebhookSubscriptionView:
    return WebhookSubscriptionView(
        id=ids.encode("webhook_subscription", subscription.id),
        url=subscription.url,
        events=list(subscription.event_types),
        status=subscription.status,
        created_at=subscription.created_at,
        disabled_at=subscription.disabled_at,
    )


def to_subscription_secret_view(
    subscription: WebhookSubscription, secret: str
) -> WebhookSubscriptionSecretView:
    return WebhookSubscriptionSecretView(
        **to_subscription_view(subscription).model_dump(), secret=secret
    )


def to_envelope(event: IntegrationEvent) -> EventEnvelopeView:
    return EventEnvelopeView(
        schema_version=SCHEMA_VERSION,
        event_id=ids.encode("event", event.id),
        type=event.event_type,
        occurred_at=event.occurred_at,
        recipient_organization_id=ids.encode("organization", event.recipient_org_id),
        resource_id=encode_resource_id(event.resource_kind, event.resource_id),
        resource_version=event.resource_version,
        data=event.payload,
    )


def to_delivery_view(delivery: WebhookDelivery, event_type: str, now: datetime) -> DeliveryView:
    return DeliveryView(
        id=ids.encode("delivery", delivery.id),
        event_id=ids.encode("event", delivery.integration_event_id),
        event_type=event_type,
        subscription_id=ids.encode("webhook_subscription", delivery.webhook_subscription_id),
        state=delivery.state,
        in_flight=delivery.lease_until is not None and delivery.lease_until > now,
        attempt_count=delivery.attempt_count,
        delivery_id=ids.encode("delivery", delivery.current_delivery_id),
        last_http_status=delivery.last_http_status,
        last_error=delivery.last_error,
        last_attempt_at=delivery.last_attempt_at,
        next_attempt_at=delivery.next_attempt_at,
        expires_at=delivery.expires_at,
        created_at=delivery.created_at,
    )
