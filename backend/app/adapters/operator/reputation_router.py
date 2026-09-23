from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.operator.deps import CurrentOperator, IdemKey
from app.adapters.operator.schemas import Page, page_of
from app.core import ids
from app.modules.reputation import api as reputation
from app.modules.reputation.api import (
    ComplaintView,
    ModerationCaseOperatorView,
    ReviewOperatorView,
)

router = APIRouter(tags=["operator-reputation"], responses=STANDARD_ERROR_RESPONSES)

ModerationDecision = Literal["published", "rejected", "removed"]


class ReviewDecisionBody(BaseModel):
    decision: Annotated[ModerationDecision, Field(description="Решение по отзыву")]
    reason: Annotated[str, Field(max_length=2000)] | None = None


class FraudFlagBody(BaseModel):
    suspected: bool
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class CaseDecisionBody(BaseModel):
    decision: Annotated[ModerationDecision, Field(description="Решение по делу")]
    reason: Annotated[str, Field(max_length=2000)] | None = None


@router.get("/reviews", response_model=Page[ReviewOperatorView])
async def list_reviews(
    operator: CurrentOperator,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ReviewOperatorView]:
    items, next_cursor = await reputation.list_review_queue(
        operator,
        status=status,
        cursor=ids.decode("review", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "review", next_cursor)


@router.get("/reviews/{review_id}", response_model=ReviewOperatorView)
async def get_review(operator: CurrentOperator, review_id: str) -> ReviewOperatorView:
    return await reputation.get_review_operator(operator, ids.decode("review", review_id))


@router.post("/reviews/{review_id}/decision", response_model=ReviewOperatorView)
async def decide_review(
    operator: CurrentOperator, review_id: str, body: ReviewDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /reviews/{review_id}/decision", body.model_dump(mode="json")
    )
    result = await reputation.decide_review(
        operator, ids.decode("review", review_id), body.decision, body.reason, idem=idem
    )
    return result.body


@router.post("/reviews/{review_id}/fraud", response_model=ReviewOperatorView)
async def set_fraud_flag(
    operator: CurrentOperator, review_id: str, body: FraudFlagBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, f"POST /reviews/{review_id}/fraud", body.model_dump())
    result = await reputation.mark_suspected_fraud(
        operator, ids.decode("review", review_id), body.suspected, body.reason, idem=idem
    )
    return result.body


@router.get("/moderation-cases", response_model=Page[ModerationCaseOperatorView])
async def list_moderation_cases(
    operator: CurrentOperator,
    subject_type: str | None = None,
    status: str | None = None,
    kind: Annotated[
        str | None, Query(description="Вид дела из evidence.kind, например appeal")
    ] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ModerationCaseOperatorView]:
    items, next_cursor = await reputation.list_moderation_case_queue(
        operator,
        subject_type=subject_type,
        status=status,
        kind=kind,
        cursor=ids.decode("moderation_case", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "moderation_case", next_cursor)


@router.get("/moderation-cases/{case_id}", response_model=ModerationCaseOperatorView)
async def get_moderation_case(
    operator: CurrentOperator, case_id: str
) -> ModerationCaseOperatorView:
    return await reputation.get_moderation_case_operator(
        operator, ids.decode("moderation_case", case_id)
    )


@router.post("/moderation-cases/{case_id}/decision", response_model=ComplaintView)
async def decide_moderation_case(
    operator: CurrentOperator, case_id: str, body: CaseDecisionBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /moderation-cases/{case_id}/decision", body.model_dump(mode="json")
    )
    result = await reputation.decide_moderation_case(
        operator, ids.decode("moderation_case", case_id), body.decision, body.reason, idem=idem
    )
    return result.body
