from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import BindingsRead, BindingsWrite, Idem
from app.adapters.integration_api.schemas import (
    BindingInvitationCreateBody,
    BindingResponseBody,
    Page,
)
from app.core import ids
from app.core.scope import scope_of
from app.modules.trust import api as trust
from app.modules.trust.api import (
    BindingInvitationIssuedView,
    BindingInvitationView,
    ProviderBindingView,
)

bindings_router = APIRouter(
    prefix="/service-bindings", tags=["service-bindings"], responses=STANDARD_ERROR_RESPONSES
)
invitations_router = APIRouter(
    prefix="/service-binding-invitations",
    tags=["service-bindings"],
    responses=STANDARD_ERROR_RESPONSES,
)


@bindings_router.get(
    "",
    response_model=Page[ProviderBindingView],
    description="Привязки к этому исполнителю, включая ожидающие его ответа (`status=pending`).",
)
async def list_bindings(
    actor: BindingsRead,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[Any]:
    items, next_cursor = await trust.list_bindings(
        scope_of(actor),
        status=status,
        cursor=ids.decode("service_binding", cursor) if cursor else None,
        limit=limit,
    )
    return Page(items=items, next_cursor=ids.encode_opt("service_binding", next_cursor))


@bindings_router.post(
    "/{binding_id}/response",
    response_model=ProviderBindingView,
    description="Подтвердить или отклонить привязку, предложенную заказчиком.",
)
async def respond_binding(
    actor: BindingsWrite, binding_id: str, body: BindingResponseBody, idem: Idem
) -> dict[str, Any]:
    result = await trust.respond_binding(
        actor, binding_id, body.decision, body.reason, idem=idem.of(body)
    )
    return result.body


@invitations_router.post(
    "",
    response_model=BindingInvitationIssuedView,
    status_code=201,
    description=(
        "Только допущенный (проверенный) исполнитель. Токен и ссылки приглашения "
        "показываются один раз: повтор того же `Idempotency-Key` их не выдаёт."
    ),
)
async def create_invitation(
    actor: BindingsWrite, body: BindingInvitationCreateBody, idem: Idem
) -> dict[str, Any]:
    data = trust.BindingInvitationData(
        customer_inn=body.customer_inn,
        contract_number=body.contract_number,
        basis=body.basis,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        customer_name=body.customer_name,
        guarantor_kind=body.guarantor_kind,
        guarantor_name=body.guarantor_name,
        equipment_items=[
            trust.BindingInvitationItem(
                description=item.description,
                serial_number=item.serial_number,
                model=item.model,
            )
            for item in body.equipment_items
        ],
    )
    result = await trust.create_binding_invitation(actor, data, idem=idem.of(body))
    return result.body


@invitations_router.post(
    "/{invitation_id}/revoke",
    response_model=BindingInvitationView,
    description="Отозвать своё ещё не использованное приглашение.",
)
async def revoke_invitation(actor: BindingsWrite, invitation_id: str, idem: Idem) -> dict[str, Any]:
    result = await trust.revoke_binding_invitation(actor, invitation_id, idem=idem.of())
    return result.body
