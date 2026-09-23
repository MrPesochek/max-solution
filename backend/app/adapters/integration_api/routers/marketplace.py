from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import Idem, MarketplaceRead, MarketplaceWrite
from app.adapters.integration_api.schemas import OfferSubmitBody, OfferWithdrawBody, Page
from app.core import ids
from app.modules.requests import api as requests_api
from app.modules.requests.api import OfferInput
from app.modules.requests.views import MarketplaceCardView, OfferView, RequestPublicCardView

router = APIRouter(tags=["marketplace"], responses=STANDARD_ERROR_RESPONSES)


@router.get(
    "/marketplace/requests",
    response_model=Page[RequestPublicCardView],
)
async def list_marketplace_requests(
    actor: MarketplaceRead,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[RequestPublicCardView]:
    items, next_cursor = await requests_api.list_marketplace_requests(
        actor, cursor=cursor, limit=limit
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get(
    "/marketplace/requests/{request_id}",
    response_model=MarketplaceCardView,
)
async def get_marketplace_request(actor: MarketplaceRead, request_id: str) -> MarketplaceCardView:
    return await requests_api.get_marketplace_card(actor, ids.decode("request", request_id))


@router.post(
    "/marketplace/requests/{request_id}/offers",
    response_model=OfferView,
    status_code=201,
)
async def submit_offer(
    actor: MarketplaceWrite, request_id: str, body: OfferSubmitBody, idem: Idem
) -> dict[str, Any]:
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
        idem=idem.of(body),
    )
    return result.body


@router.post(
    "/offers/{offer_id}/withdraw",
    response_model=OfferView,
)
async def withdraw_offer(
    actor: MarketplaceWrite, offer_id: str, body: OfferWithdrawBody, idem: Idem
) -> dict[str, Any]:
    result = await requests_api.withdraw_offer_by_id(
        actor,
        ids.decode("offer", offer_id),
        expected_version=body.expected_version,
        idem=idem.of(body),
    )
    return result.body
