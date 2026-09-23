from typing import Any

from fastapi import APIRouter

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import Idem, WebhooksManage
from app.adapters.integration_api.schemas import (
    WebhookSubscriptionCreateBody,
    WebhookSubscriptionListResponse,
    WebhookSubscriptionTestBody,
)
from app.modules.integration import api as integration
from app.modules.integration.api import (
    WebhookSubscriptionSecretView,
    WebhookTestResultView,
)

router = APIRouter(
    prefix="/webhook-subscriptions", tags=["webhooks"], responses=STANDARD_ERROR_RESPONSES
)


@router.get("", response_model=WebhookSubscriptionListResponse)
async def list_subscriptions(actor: WebhooksManage) -> WebhookSubscriptionListResponse:
    items = await integration.list_subscriptions(actor)
    return WebhookSubscriptionListResponse(items=items)


@router.post("", response_model=WebhookSubscriptionSecretView, status_code=201)
async def create_subscription(
    actor: WebhooksManage, body: WebhookSubscriptionCreateBody, idem: Idem
) -> dict[str, Any]:
    data = integration.SubscriptionCreateData(url=body.url, events=body.events)
    result = await integration.create_subscription(actor, data, idem=idem.of(body))
    return result.body


@router.delete("/{subscription_id}", status_code=204)
async def delete_subscription(actor: WebhooksManage, subscription_id: str, idem: Idem) -> None:
    await integration.delete_subscription(actor, subscription_id, idem=idem.of())


@router.post(
    "/{subscription_id}/rotate-secret",
    response_model=WebhookSubscriptionSecretView,
    description=(
        "Новый секрет показывается один раз. Каждая ротация — со своим `Idempotency-Key`: "
        "повтор того же ключа секрет повторно не выдаёт."
    ),
)
async def rotate_secret(actor: WebhooksManage, subscription_id: str, idem: Idem) -> dict[str, Any]:
    result = await integration.rotate_subscription_secret(actor, subscription_id, idem=idem.of())
    return result.body


@router.post(
    "/{subscription_id}/test",
    response_model=WebhookTestResultView,
    description=(
        "Тестовая доставка `ping` (или указанного типа). Повтор с тем же `Idempotency-Key` "
        "возвращает сохранённый итог и не отправляет запрос повторно."
    ),
)
async def send_test(
    actor: WebhooksManage,
    subscription_id: str,
    idem: Idem,
    body: WebhookSubscriptionTestBody | None = None,
) -> WebhookTestResultView:
    event_type = body.event_type if body is not None else None
    return await integration.send_test(
        actor, subscription_id, event_type=event_type, idem=idem.of({"event_type": event_type})
    )
