import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.providers.api import find_matching_providers as _find_matching_providers


async def find_matching_providers(
    session: AsyncSession,
    *,
    category_id: uuid.UUID,
    city_id: uuid.UUID,
    district_id: uuid.UUID | None,
    brand: str | None,
) -> list[uuid.UUID]:
    return list(
        await _find_matching_providers(category_id, city_id, district_id, brand, session=session)
    )


async def is_matching_provider(
    session: AsyncSession,
    provider_org_id: uuid.UUID,
    *,
    category_id: uuid.UUID,
    city_id: uuid.UUID,
    district_id: uuid.UUID | None,
    brand: str | None,
) -> bool:
    found = await find_matching_providers(
        session,
        category_id=category_id,
        city_id=city_id,
        district_id=district_id,
        brand=brand,
    )
    return provider_org_id in set(found)
