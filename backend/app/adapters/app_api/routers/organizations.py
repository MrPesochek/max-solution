from typing import Any

from fastapi import APIRouter

from app.adapters.app_api.deps import CurrentActor, IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import (
    FirstLocationBody,
    OrganizationCreateBody,
    OrganizationUpdateBody,
    ParticipationBody,
)
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.http.patch import field_or_unset
from app.core import ids
from app.modules.identity import api as identity
from app.modules.identity.api import OrganizationCreatedView, OrganizationView

router = APIRouter(tags=["organizations"], responses=STANDARD_ERROR_RESPONSES)


@router.post("/organizations", response_model=OrganizationCreatedView, status_code=201)
async def create_organization(
    actor: CurrentActor, body: OrganizationCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    first_location = _first_location(body.first_location)
    data = identity.OrganizationCreateData(
        name=body.name,
        kind=body.kind,
        contact_phone=body.contact_phone,
        contact_name=body.contact_name,
        representative_position=body.representative_position,
        contact_email=body.contact_email,
        legal_form=body.legal_form,
        inn=body.inn,
        provider_kind=body.provider_kind,
        first_location=first_location,
    )
    idem = make_idempotency(idem_key, "POST /organizations", body.model_dump(mode="json"))
    result = await identity.create_organization(actor, data, idem=idem)
    return result.body


def _first_location(src: FirstLocationBody | None) -> identity.FirstLocationData | None:
    if src is None:
        return None
    return identity.FirstLocationData(
        name=src.name,
        city_id=ids.decode("city", src.city_id),
        address=src.address,
        district_id=ids.decode("district", src.district_id) if src.district_id else None,
        timezone=src.timezone,
        contact_name=src.contact_name,
        contact_phone=src.contact_phone,
    )


@router.get("/organizations/current", response_model=OrganizationView)
async def get_current_organization(scope: Scope) -> OrganizationView:
    return await identity.get_organization(scope)


def _update_data(body: OrganizationUpdateBody) -> identity.OrganizationUpdateData:
    return identity.OrganizationUpdateData(
        name=field_or_unset(body, "name"),
        contact_name=field_or_unset(body, "contact_name"),
        representative_position=field_or_unset(body, "representative_position"),
        contact_phone=field_or_unset(body, "contact_phone"),
        contact_email=field_or_unset(body, "contact_email"),
        legal_form=field_or_unset(body, "legal_form"),
        inn=field_or_unset(body, "inn"),
    )


@router.patch("/organizations/current", response_model=OrganizationView)
async def update_current_organization(
    actor: OrgActor, body: OrganizationUpdateBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(idem_key, "PATCH /organizations/current", body.model_dump(mode="json"))
    result = await identity.update_organization(actor, _update_data(body), idem=idem)
    return result.body


@router.patch("/organizations/{organization_id}", response_model=OrganizationView)
async def update_organization(
    actor: OrgActor, organization_id: str, body: OrganizationUpdateBody, idem_key: IdemKey
) -> dict[str, Any]:
    idem = make_idempotency(
        idem_key, f"PATCH /organizations/{organization_id}", body.model_dump(mode="json")
    )
    result = await identity.update_organization(
        actor,
        _update_data(body),
        idem=idem,
        organization_id=ids.decode("organization", organization_id),
    )
    return result.body


@router.post(
    "/organizations/{organization_id}/participation",
    response_model=OrganizationCreatedView,
    status_code=201,
)
async def add_participation(
    actor: OrgActor, organization_id: str, body: ParticipationBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = identity.ParticipationData(
        kind=body.kind,
        provider_kind=body.provider_kind,
        first_location=_first_location(body.first_location),
    )
    idem = make_idempotency(
        idem_key,
        f"POST /organizations/{organization_id}/participation",
        body.model_dump(mode="json"),
    )
    result = await identity.add_participation(
        actor, ids.decode("organization", organization_id), data, idem=idem
    )
    return result.body
