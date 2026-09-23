from typing import Annotated

from fastapi import APIRouter, Query

from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.integration_api.deps import EquipmentRead
from app.adapters.integration_api.schemas import Page
from app.modules.integration import api as integration
from app.modules.integration.api import ProviderEquipmentView

router = APIRouter(prefix="/equipment", tags=["equipment"], responses=STANDARD_ERROR_RESPONSES)


@router.get(
    "",
    response_model=Page[ProviderEquipmentView],
    description=(
        "Только оборудование с подтверждённой привязкой к этому исполнителю и только "
        "договорный объём: без адреса точки и внутренних заметок заказчика."
    ),
)
async def list_equipment(
    actor: EquipmentRead,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ProviderEquipmentView]:
    items, next_cursor = await integration.list_bound_equipment(actor, cursor=cursor, limit=limit)
    return Page(items=items, next_cursor=next_cursor)
