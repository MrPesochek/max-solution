import uuid
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.scope import AccessScope
from app.db import session as db_session
from app.db.models import City, District, Equipment, EquipmentCategory, Location
from app.modules.catalog import policy
from app.modules.catalog.summary import equipment_summaries
from app.modules.catalog.views import (
    CityView,
    EquipmentCategoryView,
    EquipmentView,
    LocationView,
    to_category_view,
    to_city_view,
    to_equipment_view,
    to_location_view,
)

DEFAULT_LIMIT = 50


def _paginate[T](
    rows: list[T], limit: int, key: Callable[[T], uuid.UUID]
) -> tuple[list[T], uuid.UUID | None]:
    if len(rows) <= limit:
        return rows, None
    page = rows[:limit]
    return page, key(page[-1])


async def list_cities() -> list[CityView]:
    async with db_session.transaction() as session:
        cities = list((await session.execute(select(City).order_by(City.name))).scalars())
        districts = list(
            (await session.execute(select(District).order_by(District.name))).scalars()
        )
        by_city: dict[uuid.UUID, list[District]] = {c.id: [] for c in cities}
        for district in districts:
            by_city.setdefault(district.city_id, []).append(district)
        return [to_city_view(c, by_city.get(c.id, [])) for c in cities]


async def list_equipment_categories() -> list[EquipmentCategoryView]:
    async with db_session.transaction() as session:
        rows = (
            await session.execute(select(EquipmentCategory).order_by(EquipmentCategory.name))
        ).scalars()
        return [to_category_view(c) for c in rows]


async def list_locations(
    scope: AccessScope, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[LocationView], uuid.UUID | None]:
    policy.require_customer_side(scope)
    async with db_session.transaction() as session:
        stmt = (
            select(Location)
            .where(Location.customer_org_id == scope.organization_id)
            .order_by(Location.id)
            .limit(limit + 1)
        )
        if scope.location_ids is not None:
            stmt = stmt.where(Location.id.in_(scope.location_ids))
        if cursor is not None:
            stmt = stmt.where(Location.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda loc: loc.id)
        counts = await _equipment_counts(session, [loc.id for loc in page])
        return [
            to_location_view(loc, equipment_count=counts.get(loc.id, 0)) for loc in page
        ], next_cursor


async def _equipment_counts(
    session: AsyncSession, location_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not location_ids:
        return {}
    stmt = (
        select(Equipment.location_id, func.count())
        .where(Equipment.location_id.in_(location_ids), Equipment.archived_at.is_(None))
        .group_by(Equipment.location_id)
    )
    return {row[0]: int(row[1]) for row in (await session.execute(stmt)).all()}


async def get_location(scope: AccessScope, location_id: uuid.UUID) -> LocationView:
    policy.require_customer_side(scope)
    async with db_session.transaction() as session:
        location = await _load_location(session, scope, location_id)
        return to_location_view(location)


async def list_equipment(
    scope: AccessScope,
    *,
    location_id: uuid.UUID | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[EquipmentView], uuid.UUID | None]:
    policy.require_customer_side(scope)
    async with db_session.transaction() as session:
        if location_id is not None:
            await _load_location(session, scope, location_id)
        stmt = (
            select(Equipment)
            .where(Equipment.customer_org_id == scope.organization_id)
            .order_by(Equipment.id)
            .limit(limit + 1)
        )
        if location_id is not None:
            stmt = stmt.where(Equipment.location_id == location_id)
        elif scope.location_ids is not None:
            stmt = stmt.where(Equipment.location_id.in_(scope.location_ids))
        if cursor is not None:
            stmt = stmt.where(Equipment.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda eq: eq.id)
        summaries = await equipment_summaries(session, scope, page)
        return [to_equipment_view(eq, summaries.get(eq.id)) for eq in page], next_cursor


async def get_equipment(scope: AccessScope, equipment_id: uuid.UUID) -> EquipmentView:
    policy.require_customer_side(scope)
    async with db_session.transaction() as session:
        equipment = (
            await session.execute(
                select(Equipment).where(
                    Equipment.id == equipment_id,
                    Equipment.customer_org_id == scope.organization_id,
                )
            )
        ).scalar_one_or_none()
        if equipment is None:
            raise NotFound()
        policy.check_location_visible(scope, equipment.location_id)
        summaries = await equipment_summaries(session, scope, [equipment])
        return to_equipment_view(equipment, summaries.get(equipment.id))


async def _load_location(
    session: AsyncSession, scope: AccessScope, location_id: uuid.UUID
) -> Location:
    location = (
        await session.execute(
            select(Location).where(
                Location.id == location_id,
                Location.customer_org_id == scope.organization_id,
            )
        )
    ).scalar_one_or_none()
    if location is None:
        raise NotFound()
    policy.check_location_visible(scope, location.id)
    return location
