from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app.adapters.app_api.deps import IdemKey, OrgActor
from app.adapters.app_api.schemas import (
    DialogMessageBody,
    MarketplaceOfferSubmitBody,
    MarketplaceOfferWithdrawBody,
    Page,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.core import ids
from app.modules.requests import api as requests_api
from app.modules.requests.api import OfferInput
from app.modules.requests.views import (
    MarketplaceCardView,
    MarketplaceListItemView,
    MessageView,
    OfferView,
)

router = APIRouter(prefix="/marketplace", tags=["marketplace"], responses=STANDARD_ERROR_RESPONSES)

MessageDirectionQuery = Annotated[
    Literal["forward", "backward"],
    Query(
        description=(
            "forward — от старых к новым; backward — сначала свежие, курсор ведёт к более "
            "ранним. Внутри страницы порядок хронологический."
        )
    ),
]


@router.get("/requests", response_model=Page[MarketplaceListItemView])
async def list_marketplace_requests(
    actor: OrgActor,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[MarketplaceListItemView]:
    items, next_cursor = await requests_api.list_marketplace_requests(
        actor, cursor=cursor, limit=limit
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get("/requests/{request_id}", response_model=MarketplaceCardView)
async def get_marketplace_request(actor: OrgActor, request_id: str) -> MarketplaceCardView:
    return await requests_api.get_marketplace_card(actor, ids.decode("request", request_id))


@router.post("/requests/{request_id}/offers", response_model=OfferView, status_code=201)
async def submit_offer(
    actor: OrgActor, request_id: str, body: MarketplaceOfferSubmitBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /marketplace/requests/{request_id}/offers", body.model_dump(mode="json")
    )
    result = await requests_api.submit_offer(
        actor,
        ids.decode("request", request_id),
        data=OfferInput(
            visit_window_start=body.visit_window_start,
            visit_window_end=body.visit_window_end,
            amount_minor=body.amount_minor,
            currency=body.currency,
            vat_mode=body.vat_mode,
            zero_cost_reason=body.zero_cost_reason,
            scope_description=body.scope_description,
            comment=body.comment,
            access_requirements=body.access_requirements,
            valid_until=body.valid_until,
        ),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


@router.get("/requests/{request_id}/messages", response_model=Page[MessageView])
async def list_marketplace_messages(
    actor: OrgActor,
    request_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    direction: MessageDirectionQuery = "forward",
) -> Page[MessageView]:
    """Свой тред вопросов по публичной карточке (S3.5)."""
    items, next_cursor = await requests_api.list_dialog_messages(
        actor,
        ids.decode("request", request_id),
        cursor=cursor,
        limit=limit,
        direction=direction,
    )
    return Page(items=items, next_cursor=next_cursor)


@router.post("/requests/{request_id}/messages", response_model=MessageView, status_code=201)
async def ask_marketplace_question(
    actor: OrgActor, request_id: str, body: DialogMessageBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /marketplace/requests/{request_id}/messages", body.model_dump(mode="json")
    )
    result = await requests_api.post_dialog_message(
        actor,
        ids.decode("request", request_id),
        body=body.body,
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body


offers_router = APIRouter(
    prefix="/offers", tags=["marketplace"], responses=STANDARD_ERROR_RESPONSES
)


@offers_router.post("/{offer_id}/withdraw", response_model=OfferView)
async def withdraw_offer(
    actor: OrgActor, offer_id: str, body: MarketplaceOfferWithdrawBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"POST /offers/{offer_id}/withdraw", body.model_dump(mode="json")
    )
    result = await requests_api.withdraw_offer_by_id(
        actor,
        ids.decode("offer", offer_id),
        expected_version=body.expected_version,
        idem=idem,
    )
    return result.body
