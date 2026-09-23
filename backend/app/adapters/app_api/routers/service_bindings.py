from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.app_api.deps import CurrentActor, IdemKey, Scope
from app.adapters.app_api.schemas import (
    BindingRequestBody,
    BindingRespondBody,
    BindingRevokeBody,
    ContactBindingBody,
    Page,
    page_of,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.modules.trust import api as trust
from app.modules.trust.api import (
    BindingRequestAcceptedView,
    ProviderBindingView,
    ServiceBindingView,
)

router = APIRouter(
    prefix="/service-bindings", tags=["service-bindings"], responses=STANDARD_ERROR_RESPONSES
)

BindingView = ServiceBindingView | ProviderBindingView


@router.get("", response_model=Page[BindingView])
async def list_bindings(
    scope: Scope,
    equipment_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[BindingView]:
    items, next_cursor = await trust.list_bindings(
        scope,
        equipment_id=ids.decode("equipment", equipment_id) if equipment_id else None,
        status=status,
        cursor=ids.decode("service_binding", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "service_binding", next_cursor)


@router.post("/requests", response_model=BindingRequestAcceptedView, status_code=202)
async def request_binding(
    actor: CurrentActor, body: BindingRequestBody, idem_key: IdemKey
) -> dict[str, Any]:
    """ТЗ 6.6.3: ответ одинаков независимо от того, существует ли такой договор."""
    data = trust.BindingRequestData(
        provider_organization_id=body.provider_organization_id,
        contract_number=body.contract_number,
        equipment_ids=body.equipment_ids,
        basis=body.basis,
    )
    idem = make_idempotency(idem_key, "POST /service-bindings/requests", body.model_dump())
    result = await trust.request_binding(actor, data, idem=idem)
    return result.body


@router.post("/contacts", response_model=ServiceBindingView, status_code=201)
async def create_contact_binding(
    actor: CurrentActor, body: ContactBindingBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = trust.ContactBindingData(
        equipment_id=body.equipment_id,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
    )
    idem = make_idempotency(idem_key, "POST /service-bindings/contacts", body.model_dump())
    result = await trust.create_contact_binding(actor, data, idem=idem)
    return result.body


@router.get("/{binding_id}", response_model=BindingView)
async def get_binding(scope: Scope, binding_id: str) -> BindingView:
    return await trust.get_binding(scope, ids.decode("service_binding", binding_id))


@router.post("/{binding_id}/respond", response_model=ProviderBindingView)
async def respond_binding(
    actor: CurrentActor, binding_id: str, body: BindingRespondBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /service-bindings/{binding_id}/respond", body.model_dump()
    )
    result = await trust.respond_binding(actor, binding_id, body.decision, body.reason, idem=idem)
    return result.body


@router.post("/{binding_id}/revoke", response_model=ServiceBindingView)
async def revoke_binding(
    actor: CurrentActor, binding_id: str, body: BindingRevokeBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /service-bindings/{binding_id}/revoke", body.model_dump()
    )
    result = await trust.revoke_binding(actor, binding_id, body.reason, idem=idem)
    return result.body
