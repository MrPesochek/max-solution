from fastapi import APIRouter

from app.adapters.app_api.deps import CurrentSession
from app.adapters.app_api.schemas import Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.modules.catalog import api as catalog
from app.modules.catalog.api import CityView, EquipmentCategoryView

router = APIRouter(prefix="/directories", tags=["directories"], responses=STANDARD_ERROR_RESPONSES)


@router.get("/cities", response_model=Page[CityView])
async def list_cities(session: CurrentSession) -> Page[CityView]:
    return page_of(await catalog.list_cities(), "city", None)


@router.get("/equipment-categories", response_model=Page[EquipmentCategoryView])
async def list_equipment_categories(
    session: CurrentSession,
) -> Page[EquipmentCategoryView]:
    return page_of(await catalog.list_equipment_categories(), "category", None)
