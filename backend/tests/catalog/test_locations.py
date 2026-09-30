import uuid

import pytest
from sqlalchemy import select

from app.core import ids
from app.core.actor import UserActor
from app.core.clock import utcnow
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.pipeline import Idempotency, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Location, Membership
from app.modules.catalog import api as catalog
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


def _idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation="location", body_hash=hash_body({"k": key}))


def _actor(
    membership: Membership, *, location_ids: frozenset[uuid.UUID] | None = None
) -> UserActor:
    return UserActor(
        user_id=membership.user_id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role=membership.role,
        location_ids=location_ids,
    )


async def test_manager_creates_and_updates_location() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-loc"), org
        )
        city = await factories.seed_city(s)
        district = await factories.seed_district(s, city)
        actor = _actor(manager)
        city_id = ids.encode("city", city.id)
        district_id = ids.encode("district", district.id) if district else None

    created = await catalog.create_location(
        actor,
        catalog.LocationCreateData(
            name="Кафе", city_id=city_id, address="ул. Мира, 5", district_id=district_id
        ),
        idem=_idem("loc-create-1"),
    )
    assert created.status == 201
    assert created.body["name"] == "Кафе"

    updated = await catalog.update_location(
        actor,
        created.body["id"],
        catalog.LocationUpdateData(name="Кафе на Мира", contact_phone="+79990000002"),
        idem=_idem("loc-update-1"),
    )
    assert updated.body["name"] == "Кафе на Мира"
    assert updated.body["contact_phone"] == "+79990000002"


async def test_update_clears_nullable_district_explicitly() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-loc-clear"), org
        )
        city = await factories.seed_city(s)
        district = await factories.seed_district(s, city)
        actor = _actor(manager)
        city_id = ids.encode("city", city.id)
        district_id = ids.encode("district", district.id) if district else None

    created = await catalog.create_location(
        actor,
        catalog.LocationCreateData(
            name="Кафе", city_id=city_id, address="ул. Мира, 5", district_id=district_id
        ),
        idem=_idem("loc-clear-create"),
    )

    untouched = await catalog.update_location(
        actor,
        created.body["id"],
        catalog.LocationUpdateData(name="Кафе 2"),
        idem=_idem("loc-touch"),
    )
    assert untouched.body["district_id"] == district_id

    cleared = await catalog.update_location(
        actor,
        created.body["id"],
        catalog.LocationUpdateData(district_id=None),
        idem=_idem("loc-clear"),
    )
    assert cleared.body["district_id"] is None


async def test_update_rejects_explicit_null_for_not_null_field() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-loc-notnull"), org
        )
        city = await factories.seed_city(s)
        actor = _actor(manager)
        city_id = ids.encode("city", city.id)

    created = await catalog.create_location(
        actor,
        catalog.LocationCreateData(name="Кафе", city_id=city_id, address="ул. Мира, 5"),
        idem=_idem("loc-notnull-create"),
    )

    with pytest.raises(ValidationFailed) as exc:
        await catalog.update_location(
            actor,
            created.body["id"],
            catalog.LocationUpdateData(city_id=None),
            idem=_idem("loc-notnull-1"),
        )
    assert exc.value.details.get("field") == "city_id"

    with pytest.raises(ValidationFailed) as exc:
        await catalog.update_location(
            actor,
            created.body["id"],
            catalog.LocationUpdateData(name=None),
            idem=_idem("loc-notnull-2"),
        )
    assert exc.value.details.get("field") == "name"


async def test_create_location_is_idempotent() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-idem"), org
        )
        city = await factories.seed_city(s)
        actor = _actor(manager)
        city_id = ids.encode("city", city.id)

    data = catalog.LocationCreateData(name="Склад", city_id=city_id, address="ул. Новая, 2")
    idem = _idem("loc-create-2")
    first = await catalog.create_location(actor, data, idem=idem)
    second = await catalog.create_location(actor, data, idem=idem)

    assert second.replayed is True
    assert first.body == second.body
    async with db_session.transaction() as s:
        rows = list((await s.execute(select(Location))).scalars())
    assert len(rows) == 1


async def test_employee_cannot_manage_locations() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        employee = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="e-loc"), org, role="customer_employee"
        )
        city = await factories.seed_city(s)
        actor = _actor(employee, location_ids=frozenset())
        city_id = ids.encode("city", city.id)

    with pytest.raises(Forbidden):
        await catalog.create_location(
            actor,
            catalog.LocationCreateData(name="Своя", city_id=city_id, address="ул. Х, 1"),
            idem=_idem("loc-create-3"),
        )


async def test_employee_sees_only_granted_locations() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        granted = await factories.create_location(s, org, name="Разрешённая")
        hidden = await factories.create_location(s, org, name="Скрытая")
        employee = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="e-scope"),
            org,
            role="customer_employee",
            locations=[granted],
        )
        actor = _actor(employee, location_ids=frozenset({granted.id}))
        granted_id, hidden_id = granted.id, hidden.id

    items, cursor = await catalog.list_locations(scope_of(actor))
    assert cursor is None
    assert [i.id for i in items] == [ids.encode("location", granted_id)]

    assert (await catalog.get_location(scope_of(actor), granted_id)).name == "Разрешённая"
    with pytest.raises(NotFound):
        await catalog.get_location(scope_of(actor), hidden_id)


async def test_location_of_other_organization_is_not_found() -> None:
    async with db_session.transaction() as s:
        mine = await factories.create_organization(s, name="Моя")
        other = await factories.create_organization(s, name="Чужая")
        foreign = await factories.create_location(s, other)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-iso"), mine
        )
        actor = _actor(manager)
        foreign_id = foreign.id
        foreign_public_id = ids.encode("location", foreign.id)

    with pytest.raises(NotFound):
        await catalog.get_location(scope_of(actor), foreign_id)
    with pytest.raises(NotFound):
        await catalog.update_location(
            actor,
            foreign_public_id,
            catalog.LocationUpdateData(name="Захват"),
            idem=_idem("loc-update-2"),
        )


async def test_provider_context_has_no_customer_locations() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, customer=True, provider=True)
        await factories.create_location(s, org)
        admin = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="pa-loc"), org, role="provider_admin"
        )
        actor = _actor(admin)

    with pytest.raises(Forbidden):
        await catalog.list_locations(scope_of(actor))


async def test_unknown_city_rejected() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-city"), org
        )
        actor = _actor(manager)

    with pytest.raises(ValidationFailed):
        await catalog.create_location(
            actor,
            catalog.LocationCreateData(
                name="Точка", city_id=ids.encode("city", uuid.uuid4()), address="ул. Х, 1"
            ),
            idem=_idem("loc-create-4"),
        )


async def test_cursor_pagination_walks_all_locations() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        for index in range(3):
            await factories.create_location(s, org, name=f"Точка {index}")
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-page"), org
        )
        actor = _actor(manager)

    scope = scope_of(actor)
    first, cursor = await catalog.list_locations(scope, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, tail = await catalog.list_locations(scope, cursor=cursor, limit=2)
    assert tail is None
    assert len(second) == 1
    assert {i.id for i in first}.isdisjoint({i.id for i in second})


async def test_directories_are_readable() -> None:
    cities = await catalog.list_cities()
    categories = await catalog.list_equipment_categories()
    assert cities and categories
    assert all(c.id.startswith("city_") for c in cities)
    assert all(isinstance(c.photo_template, list) for c in categories)


async def test_location_list_counts_active_equipment() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        busy = await factories.create_location(s, org, name="С витринами")
        empty = await factories.create_location(s, org, name="Пустая")
        await factories.create_equipment(s, org, busy)
        await factories.create_equipment(s, org, busy)
        archived = await factories.create_equipment(s, org, busy)
        archived.archived_at = utcnow()
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-count"), org
        )
        actor = _actor(manager)
        busy_id, empty_id = busy.id, empty.id

    items, _ = await catalog.list_locations(scope_of(actor))
    counts = {item.id: item.equipment_count for item in items}
    assert counts == {ids.encode("location", busy_id): 2, ids.encode("location", empty_id): 0}
