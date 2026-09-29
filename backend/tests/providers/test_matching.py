import uuid

import pytest
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import City, District, EquipmentCategory, Organization
from app.modules.providers import api as providers
from tests import factories
from tests.support import make_provider

pytestmark = pytest.mark.usefixtures("clean_db")


async def _directories() -> tuple[EquipmentCategory, City, District | None, EquipmentCategory]:
    async with db_session.transaction() as s:
        categories = list(
            (await s.execute(select(EquipmentCategory).order_by(EquipmentCategory.code))).scalars()
        )
        city = await factories.seed_city(s)
        district = await factories.seed_district(s, city)
        return categories[0], city, district, categories[1]


async def _attach(
    organization_id: uuid.UUID,
    *,
    category: EquipmentCategory,
    city: City,
    district: District | None = None,
    brands: tuple[str, ...] = (),
) -> None:
    async with db_session.transaction() as s:
        org = await s.get(Organization, organization_id)
        assert org is not None
        await factories.add_provider_category(s, org, category)
        await factories.add_provider_service_area(s, org, city, district)
        for brand in brands:
            await factories.add_brand_restriction(s, org, category, brand)


async def test_matching_respects_status_category_and_territory() -> None:
    category, city, district, other_category = await _directories()

    active = await make_provider(
        "m-active", status="active", accepting=True, with_category=False, with_area=False
    )
    await _attach(active.organization_id, category=category, city=city)

    draft = await make_provider("m-draft", with_category=False, with_area=False)
    await _attach(draft.organization_id, category=category, city=city)

    paused = await make_provider(
        "m-paused", status="active", accepting=False, with_category=False, with_area=False, inn=None
    )
    await _attach(paused.organization_id, category=category, city=city)

    suspended = await make_provider(
        "m-susp", status="suspended", accepting=True, with_category=False, with_area=False, inn=None
    )
    await _attach(suspended.organization_id, category=category, city=city)

    other = await make_provider(
        "m-other", status="active", accepting=True, with_category=False, with_area=False, inn=None
    )
    await _attach(other.organization_id, category=other_category, city=city)

    found = await providers.find_matching_providers(category.id, city.id)
    assert found == [active.organization_id]

    if district is not None:
        assert active.organization_id in await providers.find_matching_providers(
            category.id, city.id, district.id
        )


async def test_matching_by_district_and_brand() -> None:
    category, city, district, _ = await _directories()
    if district is None:
        pytest.skip("в справочнике нет районов")
    other_district_id = await _other_district(city, district)

    by_district = await make_provider(
        "m-dist", status="active", accepting=True, with_category=False, with_area=False, inn=None
    )
    await _attach(by_district.organization_id, category=category, city=city, district=district)

    branded = await make_provider(
        "m-brand", status="active", accepting=True, with_category=False, with_area=False, inn=None
    )
    await _attach(branded.organization_id, category=category, city=city, brands=("Bosch",))

    assert by_district.organization_id in await providers.find_matching_providers(
        category.id, city.id, district.id
    )
    assert by_district.organization_id not in await providers.find_matching_providers(
        category.id, city.id, other_district_id
    )
    assert by_district.organization_id not in await providers.find_matching_providers(
        category.id, city.id
    )

    assert branded.organization_id in await providers.find_matching_providers(
        category.id, city.id, None, "bosch"
    )
    assert branded.organization_id not in await providers.find_matching_providers(
        category.id, city.id, None, "Miele"
    )
    assert branded.organization_id not in await providers.find_matching_providers(
        category.id, city.id, None, None
    )


async def _other_district(city: City, district: District) -> uuid.UUID:
    async with db_session.transaction() as s:
        other = (
            (
                await s.execute(
                    select(District).where(District.city_id == city.id, District.id != district.id)
                )
            )
            .scalars()
            .first()
        )
        if other is not None:
            return other.id
        row = District(city_id=city.id, name="Тестовый район")
        s.add(row)
        await s.flush()
        return row.id


async def test_catalog_lists_only_active_providers() -> None:
    category, city, _district, _ = await _directories()
    active = await make_provider(
        "cat-active", status="active", accepting=True, with_category=False, with_area=False
    )
    await _attach(active.organization_id, category=category, city=city)
    await make_provider("cat-draft", inn=None)

    items, _cursor = await providers.list_catalog(category_id=category.id, city_id=city.id)
    assert [item.name for item in items] == ["ООО Сервис"]
    assert items[0].details_verified is False
    assert items[0].rating is None
