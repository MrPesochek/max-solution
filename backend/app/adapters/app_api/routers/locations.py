from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.app_api.deps import IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import LocationCreateBody, LocationUpdateBody, Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.http.patch import field_or_unset
from app.core import ids
from app.modules.catalog import api as catalog
from app.modules.catalog.api import LocationView

router = APIRouter(prefix="/locations", tags=["locations"], responses=STANDARD_ERROR_RESPONSES)


@router.get("", response_model=Page[LocationView])
async def list_locations(
    scope: Scope,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[LocationView]:
    items, next_cursor = await catalog.list_locations(
        scope, cursor=ids.decode("location", cursor) if cursor else None, limit=limit
    )
    return page_of(items, "location", next_cursor)


@router.post("", response_model=LocationView, status_code=201)
async def create_location(
    actor: OrgActor, body: LocationCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = catalog.LocationCreateData(
        name=body.name,
        city_id=body.city_id,
        address=body.address,
        district_id=body.district_id,
        timezone=body.timezone,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
    )
    idem = make_idempotency(idem_key, "POST /locations", body.model_dump(mode="json"))
    result = await catalog.create_location(actor, data, idem=idem)
    return result.body


@router.get("/{location_id}", response_model=LocationView)
async def get_location(scope: Scope, location_id: str) -> LocationView:
    return await catalog.get_location(scope, ids.decode("location", location_id))


@router.patch("/{location_id}", response_model=LocationView)
async def update_location(
    actor: OrgActor, location_id: str, body: LocationUpdateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = catalog.LocationUpdateData(
        name=field_or_unset(body, "name"),
        city_id=field_or_unset(body, "city_id"),
        district_id=field_or_unset(body, "district_id"),
        address=field_or_unset(body, "address"),
        timezone=field_or_unset(body, "timezone"),
        contact_name=field_or_unset(body, "contact_name"),
        contact_phone=field_or_unset(body, "contact_phone"),
    )
    idem = make_idempotency(
        idem_key, f"PATCH /locations/{location_id}", body.model_dump(mode="json")
    )
    result = await catalog.update_location(actor, location_id, data, idem=idem)
    return result.body
