from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.app_api.deps import IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import MembershipLocationsBody, Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.http.ratelimit import limit_access_requests
from app.core import ids
from app.core.actor import UserActor
from app.modules.identity import api as identity
from app.modules.identity.api import MembershipView, MemberView

router = APIRouter(prefix="/memberships", tags=["memberships"], responses=STANDARD_ERROR_RESPONSES)


@router.get("", response_model=Page[MemberView])
async def list_members(
    scope: Scope,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[MemberView]:
    items, next_cursor = await identity.list_members(
        scope, cursor=ids.decode("membership", cursor) if cursor else None, limit=limit
    )
    return page_of(items, "membership", next_cursor)


class AccessRequestBody(BaseModel):
    """Только точка и записка: заявку и другие объекты запрос не принимает."""

    model_config = ConfigDict(extra="forbid")

    location_id: str | None = None
    note: Annotated[str, Field(max_length=500)] | None = None


class AccessRequestSentView(BaseModel):
    status: str


@router.post("/me/access-requests", response_model=AccessRequestSentView, status_code=202)
async def request_access(
    actor: OrgActor, body: AccessRequestBody, idem_key: IdemKey
) -> dict[str, Any]:
    """Просьба к руководителям своей стороны открыть доступ (экран «Нет доступа»).

    Ответ одинаков для любой точки и не подтверждает существование объекта."""
    if isinstance(actor, UserActor):
        limit_access_requests(str(actor.membership_id))
    idem = make_idempotency(
        idem_key, "POST /memberships/me/access-requests", body.model_dump(mode="json")
    )
    result = await identity.request_access(
        actor, identity.AccessRequestData(location_id=body.location_id, note=body.note), idem=idem
    )
    return result.body


@router.post("/{membership_id}/approve", response_model=MembershipView)
async def approve_membership(
    actor: OrgActor, membership_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /memberships/{membership_id}/approve", {})
    result = await identity.approve_membership(actor, membership_id, idem=idem)
    return result.body


@router.post("/{membership_id}/revoke", response_model=MembershipView)
async def revoke_membership(
    actor: OrgActor, membership_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /memberships/{membership_id}/revoke", {})
    result = await identity.revoke_membership(actor, membership_id, idem=idem)
    return result.body


@router.put("/{membership_id}/locations", response_model=MembershipView)
async def set_membership_locations(
    actor: OrgActor, membership_id: str, body: MembershipLocationsBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"PUT /memberships/{membership_id}/locations", body.model_dump(mode="json")
    )
    result = await identity.set_membership_locations(
        actor, membership_id, body.location_ids, idem=idem
    )
    return result.body
