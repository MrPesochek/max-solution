from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.adapters.app_api.deps import CurrentActor, IdemKey, Scope
from app.adapters.app_api.schemas import (
    BindingInvitationAcceptBody,
    BindingInvitationCreateBody,
    Page,
    page_of,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.infra.crypto import hash_token
from app.modules.trust import api as trust
from app.modules.trust.api import (
    BindingInvitationAcceptedView,
    BindingInvitationIssuedView,
    BindingInvitationPreviewView,
    BindingInvitationView,
)

router = APIRouter(
    prefix="/service-binding-invitations",
    tags=["service-binding-invitations"],
    responses=STANDARD_ERROR_RESPONSES,
)


@router.post("", response_model=BindingInvitationIssuedView, status_code=201)
async def create_invitation(
    actor: CurrentActor, body: BindingInvitationCreateBody, idem_key: IdemKey
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
        equipment_descriptions=body.equipment_descriptions,
    )
    idem = make_idempotency(
        idem_key, "POST /service-binding-invitations", body.model_dump(mode="json")
    )
    result = await trust.create_binding_invitation(actor, data, idem=idem)
    return result.body


@router.get("", response_model=Page[BindingInvitationView])
async def list_invitations(
    scope: Scope,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[BindingInvitationView]:
    items, next_cursor = await trust.list_binding_invitations(
        scope, cursor=ids.decode("invitation", cursor) if cursor else None, limit=limit
    )
    return page_of(items, "invitation", next_cursor)


class BindingInvitationPreviewBody(BaseModel):
    token: Annotated[str, Field(min_length=8, max_length=512)]


@router.post("/preview", response_model=BindingInvitationPreviewView)
async def preview_invitation_by_body(
    actor: CurrentActor, body: BindingInvitationPreviewBody
) -> BindingInvitationPreviewView:
    return await trust.preview_binding_invitation(body.token, actor)


@router.get("/preview", response_model=BindingInvitationPreviewView, deprecated=True)
async def preview_invitation(
    actor: CurrentActor, token: Annotated[str, Query(min_length=8, max_length=512)]
) -> BindingInvitationPreviewView:
    return await trust.preview_binding_invitation(token, actor)


@router.post("/accept", response_model=BindingInvitationAcceptedView, status_code=201)
async def accept_invitation(
    actor: CurrentActor, body: BindingInvitationAcceptBody, idem_key: IdemKey
) -> dict[str, Any]:
    matches = [
        trust.BindingItemMatch(item_index=m.item_index, equipment_id=m.equipment_id)
        for m in body.matches
    ] or [
        trust.BindingItemMatch(item_index=index, equipment_id=equipment_id)
        for index, equipment_id in enumerate(body.equipment_ids)
    ]
    idem = make_idempotency(
        idem_key,
        "POST /service-binding-invitations/accept",
        {
            "token_sha256": hash_token(body.token).hex(),
            "matches": [[m.item_index, m.equipment_id] for m in matches],
        },
    )
    result = await trust.accept_binding_invitation(actor, body.token, matches, idem=idem)
    return result.body


class BindingInvitationDeclineBody(BaseModel):
    token: Annotated[str, Field(min_length=8, max_length=512)]
    reason: Annotated[str | None, Field(default=None, max_length=500)]


@router.post("/decline", response_model=BindingInvitationPreviewView)
async def decline_invitation(
    actor: CurrentActor, body: BindingInvitationDeclineBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key,
        "POST /service-binding-invitations/decline",
        {"token_sha256": hash_token(body.token).hex(), "reason": body.reason},
    )
    result = await trust.decline_binding_invitation(actor, body.token, body.reason, idem=idem)
    return result.body


@router.post("/{invitation_id}/revoke", response_model=BindingInvitationView)
async def revoke_invitation(
    actor: CurrentActor, invitation_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /service-binding-invitations/{invitation_id}/revoke", {}
    )
    result = await trust.revoke_binding_invitation(actor, invitation_id, idem=idem)
    return result.body
