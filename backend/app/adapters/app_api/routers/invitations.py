from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.adapters.app_api.deps import CurrentActor, CurrentSession, IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import (
    InvitationAcceptBody,
    InvitationCreateBody,
    Page,
    page_of,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.infra.crypto import hash_token
from app.modules.identity import api as identity
from app.modules.identity.api import (
    InvitationIssuedView,
    InvitationPreviewView,
    InvitationView,
    MembershipView,
)

router = APIRouter(prefix="/invitations", tags=["invitations"], responses=STANDARD_ERROR_RESPONSES)


@router.post("", response_model=InvitationIssuedView, status_code=201)
async def create_invitation(
    actor: OrgActor, body: InvitationCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = identity.InvitationCreateData(
        role=body.role,
        location_ids=[ids.decode("location", pid) for pid in body.location_ids],
        recipient_max_user_id=body.recipient_max_user_id,
        recipient_name=body.recipient_name,
    )
    idem = make_idempotency(idem_key, "POST /invitations", body.model_dump(mode="json"))
    result = await identity.create_invitation(actor, data, idem=idem)
    return result.body


@router.get("", response_model=Page[InvitationView])
async def list_invitations(
    scope: Scope,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[InvitationView]:
    items, next_cursor = await identity.list_invitations(
        scope, cursor=ids.decode("invitation", cursor) if cursor else None, limit=limit
    )
    return page_of(items, "invitation", next_cursor)


class InvitationPreviewBody(BaseModel):
    token: Annotated[str, Field(min_length=8, max_length=512)]


@router.post("/preview", response_model=InvitationPreviewView)
async def preview_invitation_by_body(
    session: CurrentSession, body: InvitationPreviewBody
) -> InvitationPreviewView:
    """Предпросмотр ничего не расходует (ТЗ 6.7); токен в теле — не попадает в журналы URL."""
    return await identity.preview_invitation(body.token)


@router.get("/preview", response_model=InvitationPreviewView, deprecated=True)
async def preview_invitation(
    session: CurrentSession, token: Annotated[str, Query(min_length=8, max_length=512)]
) -> InvitationPreviewView:
    """Устарело: токен в query оседает в журналах прокси. Используйте POST /invitations/preview."""
    return await identity.preview_invitation(token)


@router.post("/accept", response_model=MembershipView, status_code=201)
async def accept_invitation(
    actor: CurrentActor, body: InvitationAcceptBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, "POST /invitations/accept", {"token_sha256": hash_token(body.token).hex()}
    )
    result = await identity.accept_invitation(actor, body.token, idem=idem)
    return result.body


@router.post("/{invitation_id}/revoke", response_model=InvitationView)
async def revoke_invitation(
    actor: OrgActor, invitation_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /invitations/{invitation_id}/revoke", {})
    result = await identity.revoke_invitation(actor, invitation_id, idem=idem)
    return result.body
