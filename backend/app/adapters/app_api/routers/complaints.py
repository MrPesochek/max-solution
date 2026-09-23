from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.adapters.app_api.deps import IdemKey, OrgActor
from app.adapters.app_api.schemas import Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.modules.reputation import api as reputation
from app.modules.reputation.api import ComplaintView

router = APIRouter(prefix="/complaints", tags=["complaints"], responses=STANDARD_ERROR_RESPONSES)


class ComplaintCreateBody(BaseModel):
    subject_type: str
    target_id: str
    description: Annotated[str, Field(min_length=1, max_length=2000)]


@router.post("", response_model=ComplaintView, status_code=201)
async def create_complaint(
    actor: OrgActor, body: ComplaintCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = reputation.ComplaintCreateData(
        subject_type=body.subject_type, target_id=body.target_id, description=body.description
    )
    idem = make_idempotency(idem_key, "POST /complaints", body.model_dump())
    result = await reputation.create_complaint(actor, data, idem=idem)
    return result.body


@router.get("", response_model=Page[ComplaintView])
async def list_complaints(
    actor: OrgActor,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ComplaintView]:
    items, next_cursor = await reputation.list_my_complaints(
        actor,
        cursor=ids.decode("moderation_case", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "moderation_case", next_cursor)


@router.post("/{complaint_id}/withdraw", response_model=ComplaintView)
async def withdraw_complaint(
    actor: OrgActor, complaint_id: str, idem_key: IdemKey
) -> dict[str, Any]:
    """Отозвать свою жалобу или оспаривание до решения оператора."""
    idem = make_idempotency(idem_key, f"POST /complaints/{complaint_id}/withdraw", {})
    result = await reputation.withdraw_complaint(
        actor, ids.decode("moderation_case", complaint_id), idem=idem
    )
    return result.body
