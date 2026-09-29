import uuid

import pytest

from app.core import ids
from app.core.actor import UserActor
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.pipeline import Idempotency, hash_body
from app.core.scope import scope_of
from app.db import session as db_session
from app.db.models import Membership
from app.modules.catalog import api as catalog
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


def _idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation="equipment", body_hash=hash_body({"k": key}))


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


async def test_manager_creates_equipment_without_serial_number() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        location = await factories.create_location(s, org)
        category = await factories.seed_category(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-eq"), org
        )
        actor = _actor(manager)
        location_id = ids.encode("location", location.id)
        category_id = ids.encode("category", category.id)

    created = await catalog.create_equipment(
        actor,
        catalog.EquipmentCreateData(
            location_id=location_id, equipment_category_id=category_id, brand="Бренд"
        ),
        idem=_idem("eq-create-1"),
    )
    assert created.status == 201
    assert created.body["serial_number"] is None

    updated = await catalog.update_equipment(
        actor,
        created.body["id"],
        catalog.EquipmentUpdateData(serial_number="SN-1", model="M-1"),
        idem=_idem("eq-update-1"),
    )
    assert updated.body["serial_number"] == "SN-1"
    assert updated.body["model"] == "M-1"


async def test_create_equipment_is_idempotent() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        location = await factories.create_location(s, org)
        category = await factories.seed_category(s)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-eq-idem"), org
        )
        actor = _actor(manager)
        data = catalog.EquipmentCreateData(
            location_id=ids.encode("location", location.id),
            equipment_category_id=ids.encode("category", category.id),
        )

    idem = _idem("eq-create-2")
    first = await catalog.create_equipment(actor, data, idem=idem)
    second = await catalog.create_equipment(actor, data, idem=idem)
    assert second.replayed is True
    assert first.body["id"] == second.body["id"]


async def test_employee_cannot_create_equipment() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        location = await factories.create_location(s, org)
        category = await factories.seed_category(s)
        employee = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="e-eq"),
            org,
            role="customer_employee",
            locations=[location],
        )
        actor = _actor(employee, location_ids=frozenset({location.id}))
        data = catalog.EquipmentCreateData(
            location_id=ids.encode("location", location.id),
            equipment_category_id=ids.encode("category", category.id),
        )

    with pytest.raises(Forbidden):
        await catalog.create_equipment(actor, data, idem=_idem("eq-create-3"))


async def test_employee_sees_equipment_of_granted_locations_only() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        granted = await factories.create_location(s, org, name="Разрешённая")
        hidden = await factories.create_location(s, org, name="Скрытая")
        visible = await factories.create_equipment(s, org, granted)
        invisible = await factories.create_equipment(s, org, hidden)
        employee = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id="e-eq-scope"),
            org,
            role="customer_employee",
            locations=[granted],
        )
        actor = _actor(employee, location_ids=frozenset({granted.id}))
        visible_id, invisible_id, hidden_id = visible.id, invisible.id, hidden.id

    items, _cursor = await catalog.list_equipment(scope_of(actor))
    assert [i.id for i in items] == [ids.encode("equipment", visible_id)]

    assert (await catalog.get_equipment(scope_of(actor), visible_id)).id == ids.encode(
        "equipment", visible_id
    )
    with pytest.raises(NotFound):
        await catalog.get_equipment(scope_of(actor), invisible_id)
    with pytest.raises(NotFound):
        await catalog.list_equipment(scope_of(actor), location_id=hidden_id)


async def test_equipment_of_other_organization_is_not_found() -> None:
    async with db_session.transaction() as s:
        mine = await factories.create_organization(s, name="Моя")
        other = await factories.create_organization(s, name="Чужая")
        foreign_location = await factories.create_location(s, other)
        foreign = await factories.create_equipment(s, other, foreign_location)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-eq-iso"), mine
        )
        actor = _actor(manager)
        foreign_id = foreign.id
        foreign_public_id = ids.encode("equipment", foreign.id)

    with pytest.raises(NotFound):
        await catalog.get_equipment(scope_of(actor), foreign_id)
    with pytest.raises(NotFound):
        await catalog.update_equipment(
            actor,
            foreign_public_id,
            catalog.EquipmentUpdateData(brand="Захват"),
            idem=_idem("eq-update-2"),
        )


async def test_unknown_category_rejected() -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s)
        location = await factories.create_location(s, org)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id="m-eq-cat"), org
        )
        actor = _actor(manager)
        data = catalog.EquipmentCreateData(
            location_id=ids.encode("location", location.id),
            equipment_category_id=ids.encode("category", uuid.uuid4()),
        )

    with pytest.raises(ValidationFailed):
        await catalog.create_equipment(actor, data, idem=_idem("eq-create-4"))
