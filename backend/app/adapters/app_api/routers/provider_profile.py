from typing import Any

from fastapi import APIRouter

from app.adapters.app_api.deps import IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import (
    AcceptingRequestsBody,
    ProfileAppealBody,
    ProviderProfileUpdateBody,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.http.patch import field_or_unset
from app.modules.providers import api as providers
from app.modules.providers.api import ProviderProfileView
from app.modules.reputation import api as reputation
from app.modules.reputation.api import ComplaintView

router = APIRouter(
    prefix="/provider-profile", tags=["provider-profile"], responses=STANDARD_ERROR_RESPONSES
)


@router.get("", response_model=ProviderProfileView)
async def get_profile(scope: Scope) -> ProviderProfileView:
    return await providers.get_own_profile(scope)


@router.patch("", response_model=ProviderProfileView)
async def update_profile(
    actor: OrgActor, body: ProviderProfileUpdateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = providers.ProviderProfileUpdateData(
        provider_kind=field_or_unset(body, "provider_kind"),
        legal_form=field_or_unset(body, "legal_form"),
        inn=field_or_unset(body, "inn"),
        contact_name=field_or_unset(body, "contact_name"),
        representative_position=field_or_unset(body, "representative_position"),
        contact_phone=field_or_unset(body, "contact_phone"),
        contact_email=field_or_unset(body, "contact_email"),
        visit_terms=field_or_unset(body, "visit_terms"),
        visit_price_from_minor=field_or_unset(body, "visit_price_from_minor"),
        can_provide_documents=field_or_unset(body, "can_provide_documents"),
        description=field_or_unset(body, "description"),
        category_ids=body.category_ids,
        service_areas=(
            [
                providers.ServiceAreaInput(city_id=a.city_id, district_ids=a.district_ids)
                for a in body.service_areas
            ]
            if body.service_areas is not None
            else None
        ),
        brand_restrictions=(
            [
                providers.BrandRestrictionInput(
                    equipment_category_id=r.equipment_category_id, brands=r.brands
                )
                for r in body.brand_restrictions
            ]
            if body.brand_restrictions is not None
            else None
        ),
    )
    idem = make_idempotency(idem_key, "PATCH /provider-profile", body.model_dump(mode="json"))
    result = await providers.update_profile(actor, data, idem=idem)
    return result.body


@router.post("/submit", response_model=ProviderProfileView)
async def submit_profile(actor: OrgActor, idem_key: IdemKey) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "POST /provider-profile/submit", {})
    result = await providers.submit_for_review(actor, idem=idem)
    return result.body


@router.post("/accepting", response_model=ProviderProfileView)
async def set_accepting(
    actor: OrgActor, body: AcceptingRequestsBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "POST /provider-profile/accepting", body.model_dump())
    result = await providers.set_accepting_new_requests(actor, body.accepting, idem=idem)
    return result.body


@router.post("/appeal", response_model=ComplaintView, status_code=201)
async def appeal_profile(
    actor: OrgActor, body: ProfileAppealBody, idem_key: IdemKey
) -> dict[str, Any]:
    """ТЗ 6.5.1: обжалование отказа или приостановки — дело в очередь оператора."""
    idem = make_idempotency(idem_key, "POST /provider-profile/appeal", body.model_dump())
    result = await reputation.appeal_provider_profile(actor, body.text, idem=idem)
    return result.body
