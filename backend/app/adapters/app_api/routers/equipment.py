from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.adapters.app_api.deps import IdemKey, OrgActor, Scope
from app.adapters.app_api.schemas import EquipmentCreateBody, EquipmentUpdateBody, Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.idempotency import make_idempotency
from app.adapters.http.patch import field_or_unset
from app.core import ids
from app.modules.catalog import api as catalog
from app.modules.catalog.api import EquipmentView

router = APIRouter(prefix="/equipment", tags=["equipment"], responses=STANDARD_ERROR_RESPONSES)


@router.get("", response_model=Page[EquipmentView])
async def list_equipment(
    scope: Scope,
    location_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[EquipmentView]:
    items, next_cursor = await catalog.list_equipment(
        scope,
        location_id=ids.decode("location", location_id) if location_id else None,
        cursor=ids.decode("equipment", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "equipment", next_cursor)


@router.post("", response_model=EquipmentView, status_code=201)
async def create_equipment(
    actor: OrgActor, body: EquipmentCreateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = catalog.EquipmentCreateData(
        location_id=body.location_id,
        equipment_category_id=body.equipment_category_id,
        brand=body.brand,
        model=body.model,
        serial_number=body.serial_number,
        notes=body.notes,
    )
    idem = make_idempotency(idem_key, "POST /equipment", body.model_dump(mode="json"))
    result = await catalog.create_equipment(actor, data, idem=idem)
    return result.body


@router.get("/{equipment_id}", response_model=EquipmentView)
async def get_equipment(scope: Scope, equipment_id: str) -> EquipmentView:
    return await catalog.get_equipment(scope, ids.decode("equipment", equipment_id))


@router.patch("/{equipment_id}", response_model=EquipmentView)
async def update_equipment(
    actor: OrgActor, equipment_id: str, body: EquipmentUpdateBody, idem_key: IdemKey
) -> dict[str, Any]:
    data = catalog.EquipmentUpdateData(
        location_id=field_or_unset(body, "location_id"),
        equipment_category_id=field_or_unset(body, "equipment_category_id"),
        brand=field_or_unset(body, "brand"),
        model=field_or_unset(body, "model"),
        serial_number=field_or_unset(body, "serial_number"),
        notes=field_or_unset(body, "notes"),
    )
    idem = make_idempotency(
        idem_key, f"PATCH /equipment/{equipment_id}", body.model_dump(mode="json")
    )
    result = await catalog.update_equipment(actor, equipment_id, data, idem=idem)
    return result.body
