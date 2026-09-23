from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import Idem, ReviewsRead, ReviewsWrite
from app.adapters.integration_api.schemas import Page
from app.core import ids
from app.modules.reputation import api as reputation
from app.modules.reputation.api import PublicReviewView, ReviewReplyView

router = APIRouter(prefix="/reviews", tags=["reviews"], responses=STANDARD_ERROR_RESPONSES)


class ReviewReplyBody(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=2000)]


@router.get("", response_model=Page[PublicReviewView])
async def list_reviews(
    actor: ReviewsRead,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[PublicReviewView]:
    items, next_cursor = await reputation.list_reviews_for_provider(
        actor, cursor=ids.decode("review", cursor) if cursor else None, limit=limit
    )
    return Page(items=items, next_cursor=ids.encode_opt("review", next_cursor))


@router.post(
    "/{review_id}/reply",
    response_model=ReviewReplyView,
    status_code=201,
)
async def reply_to_review(
    actor: ReviewsWrite, review_id: str, body: ReviewReplyBody, idem: Idem
) -> dict[str, Any]:
    result = await reputation.reply_to_review(
        actor, ids.decode("review", review_id), body.body, idem=idem.of(body)
    )
    return result.body
