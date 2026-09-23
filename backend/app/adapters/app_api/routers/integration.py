from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.app_api.deps import IdemKey, OrgActor
from app.adapters.app_api.schemas import ApiKeyCreateBody, WebhookSubscriptionCreateBody
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.modules.integration import api as integration
from app.modules.integration.api import (
    ApiKeyIssuedView,
    ApiKeyView,
    DeliveryPageView,
    DeliveryView,
    IntegrationSummaryView,
    WebhookSubscriptionSecretView,
    WebhookSubscriptionView,
)

router = APIRouter(prefix="/integration", tags=["integration"], responses=STANDARD_ERROR_RESPONSES)


@router.post("/api-keys", response_model=ApiKeyIssuedView, status_code=201)
async def create_api_key(
    actor: OrgActor, body: ApiKeyCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = integration.ApiKeyCreateData(name=body.name, scopes=body.scopes)
    idem = make_idempotency(idem_key, "POST /integration/api-keys", body.model_dump(mode="json"))
    result = await integration.create_api_key(actor, data, idem=idem)
    return result.body


@router.get("/api-keys", response_model=list[ApiKeyView])
async def list_api_keys(actor: OrgActor) -> list[ApiKeyView]:
    return await integration.list_api_keys(actor)


@router.post("/api-keys/{client_id}/revoke", response_model=ApiKeyView)
async def revoke_api_key(actor: OrgActor, client_id: str, idem_key: IdemKey) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /integration/api-keys/{client_id}/revoke", {})
    result = await integration.revoke_api_key(actor, client_id, idem=idem)
    return result.body


@router.post("/api-keys/{client_id}/rotate", response_model=ApiKeyIssuedView)
async def rotate_api_key(actor: OrgActor, client_id: str, idem_key: IdemKey) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /integration/api-keys/{client_id}/rotate", {})
    result = await integration.rotate_api_key(actor, client_id, idem=idem)
    return result.body


@router.get("/summary", response_model=IntegrationSummaryView)
async def integration_summary(actor: OrgActor) -> IntegrationSummaryView:
    """Сводка экрана «Интеграция»: ключи, подписка и доставки за сутки, без секретов."""
    return await integration.integration_summary(actor)


@router.get("/webhook-subscriptions", response_model=list[WebhookSubscriptionView])
async def list_subscriptions(actor: OrgActor) -> list[WebhookSubscriptionView]:
    return await integration.list_subscriptions(actor)


@router.post(
    "/webhook-subscriptions", response_model=WebhookSubscriptionSecretView, status_code=201
)
async def create_subscription(
    actor: OrgActor, body: WebhookSubscriptionCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    """Секрет подписи показывается один раз; адрес проходит ту же проверку, что в API CRM."""
    data = integration.SubscriptionCreateData(
        url=body.url, events=body.events, client_public_id=body.client_id
    )
    idem = make_idempotency(
        idem_key, "POST /integration/webhook-subscriptions", body.model_dump(mode="json")
    )
    result = await integration.create_subscription(actor, data, idem=idem)
    return result.body


@router.post(
    "/webhook-subscriptions/{subscription_id}/disable", response_model=WebhookSubscriptionView
)
async def disable_subscription(
    actor: OrgActor, subscription_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    """Отключает доставку; ключи интеграции при этом не отзываются."""
    idem = make_idempotency(
        idem_key, f"POST /integration/webhook-subscriptions/{subscription_id}/disable", {}
    )
    result = await integration.delete_subscription(actor, subscription_id, idem=idem)
    return result.body


@router.post(
    "/webhook-subscriptions/{subscription_id}/enable", response_model=WebhookSubscriptionView
)
async def enable_subscription(
    actor: OrgActor, subscription_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /integration/webhook-subscriptions/{subscription_id}/enable", {}
    )
    result = await integration.enable_subscription(actor, subscription_id, idem=idem)
    return result.body


@router.post(
    "/webhook-subscriptions/{subscription_id}/rotate-secret",
    response_model=WebhookSubscriptionSecretView,
)
async def rotate_subscription_secret(
    actor: OrgActor, subscription_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    """Новый секрет показывается один раз; повтор с тем же ключом его не выдаёт."""
    idem = make_idempotency(
        idem_key, f"POST /integration/webhook-subscriptions/{subscription_id}/rotate-secret", {}
    )
    result = await integration.rotate_subscription_secret(actor, subscription_id, idem=idem)
    return result.body


@router.get("/deliveries", response_model=DeliveryPageView)
async def list_deliveries(
    actor: OrgActor,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DeliveryPageView:
    access = integration.webhook_access(actor)
    return await integration.list_deliveries(access.organization_id, cursor=cursor, limit=limit)


@router.post("/deliveries/{delivery_id}/redeliver", response_model=DeliveryView)
async def redeliver(actor: OrgActor, delivery_id: str, idem_key: IdemKey) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /integration/deliveries/{delivery_id}/redeliver", {})
    result = await integration.redeliver(actor, delivery_id, idem=idem)
    return result.body
