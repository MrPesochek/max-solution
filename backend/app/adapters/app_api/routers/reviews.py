from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.adapters.app_api.deps import IdemKey, OrgActor
from app.adapters.app_api.schemas import Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.modules.reputation import api as reputation
from app.modules.reputation.api import (
    ComplaintView,
    MyReviewView,
    ProviderReviewView,
    RequestReviewStateView,
    ReviewReplyView,
)

router = APIRouter(prefix="/requests", tags=["reviews"], responses=STANDARD_ERROR_RESPONSES)
reviews_router = APIRouter(prefix="/reviews", tags=["reviews"], responses=STANDARD_ERROR_RESPONSES)


class ReviewSubmitBody(BaseModel):
    rating: int
    assignment_id: str | None = None
    text: Annotated[str, Field(max_length=4000)] | None = None
    show_customer_name: bool = False
    photo_attachment_ids: list[str] = Field(default_factory=list)
    confirm_sensitive: bool = False


class ReviewReplyBody(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=2000)]


class ReviewAppealBody(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    reason_code: (
        Literal["not_our_work", "abuse_or_personal_data", "customer_not_involved", "other"] | None
    ) = None


@router.get("/{request_id}/review", response_model=RequestReviewStateView)
async def get_review(
    actor: OrgActor, request_id: str, assignment_id: str | None = None
) -> RequestReviewStateView:
    return await reputation.get_review_state(
        actor,
        ids.decode("request", request_id),
        assignment_id=ids.decode("assignment", assignment_id) if assignment_id else None,
    )


@router.put("/{request_id}/review", response_model=MyReviewView)
async def put_review(
    actor: OrgActor, request_id: str, body: ReviewSubmitBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = reputation.ReviewSubmitData(
        rating=body.rating,
        text=body.text,
        show_customer_name=body.show_customer_name,
        photo_attachment_ids=[ids.decode("attachment", pid) for pid in body.photo_attachment_ids],
        confirm_sensitive=body.confirm_sensitive,
    )
    idem = make_idempotency(
        idem_key, f"PUT /requests/{request_id}/review", body.model_dump(mode="json")
    )
    result = await reputation.submit_review(
        actor,
        ids.decode("request", request_id),
        data,
        idem=idem,
        assignment_id=(
            ids.decode("assignment", body.assignment_id) if body.assignment_id else None
        ),
    )
    return result.body


@reviews_router.get("/mine", response_model=Page[ProviderReviewView])
async def list_my_reviews(
    actor: OrgActor,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ProviderReviewView]:
    items, next_cursor = await reputation.list_my_reviews(
        actor, cursor=ids.decode("review", cursor) if cursor else None, limit=limit
    )
    return page_of(items, "review", next_cursor)


@reviews_router.post("/{review_id}/reply", response_model=ReviewReplyView, status_code=201)
async def reply_to_review(
    actor: OrgActor, review_id: str, body: ReviewReplyBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /reviews/{review_id}/reply", body.model_dump(mode="json")
    )
    result = await reputation.reply_to_review(
        actor, ids.decode("review", review_id), body.body, idem=idem
    )
    return result.body


@reviews_router.post("/{review_id}/appeal", response_model=ComplaintView, status_code=201)
async def appeal_review(
    actor: OrgActor, review_id: str, body: ReviewAppealBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /reviews/{review_id}/appeal", body.model_dump(mode="json")
    )
    result = await reputation.appeal_review(
        actor, ids.decode("review", review_id), body.reason, idem=idem, reason_code=body.reason_code
    )
    return result.body
