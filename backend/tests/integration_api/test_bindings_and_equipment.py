from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.db.models import Equipment, Organization, ServiceBinding
from tests import factories
from tests.integration_api.conftest import bearer, idem, provider_org

pytestmark = pytest.mark.asyncio

ALL = ("equipment:read", "service_bindings:read", "service_bindings:write")
VALID_INN = "7707083893"


@dataclass
class World:
    provider: Organization
    other_provider: Organization
    customer: Organization
    confirmed: Equipment
    pending_binding: ServiceBinding
    foreign_binding: ServiceBinding
    key: str
    other_key: str


async def _world(db_session: AsyncSession) -> World:
    provider = await provider_org(db_session, name="ООО Сервис")
    other = await provider_org(db_session, name="ООО Чужой")
    customer = await factories.create_organization(db_session, name="Кафе", customer=True)
    user = await factories.create_user(db_session)
    manager = await factories.create_membership(db_session, user, customer, role="customer_manager")
    location = await factories.create_location(db_session, customer, address="Секретный адрес")
    confirmed = await factories.create_equipment(db_session, customer, location, serial_number="S1")
    confirmed.notes = "внутренняя заметка"
    pending_eq = await factories.create_equipment(db_session, customer, location)
    foreign_eq = await factories.create_equipment(db_session, customer, location)
    contract = await factories.create_service_contract(db_session, provider, customer, number="Д-7")
    await factories.create_service_binding(
        db_session,
        confirmed,
        customer,
        manager,
        provider=provider,
        status="confirmed",
        contract=contract,
    )
    pending = await factories.create_service_binding(
        db_session, pending_eq, customer, manager, provider=provider
    )
    foreign = await factories.create_service_binding(
        db_session, foreign_eq, customer, manager, provider=other, status="confirmed"
    )
    _, key = await factories.create_integration_client(db_session, provider, scopes=ALL)
    _, other_key = await factories.create_integration_client(db_session, other, scopes=ALL)
    await db_session.commit()
    return World(provider, other, customer, confirmed, pending, foreign, key, other_key)


async def _key(db_session: AsyncSession, org: Organization, *scopes: str) -> str:
    _, key = await factories.create_integration_client(
        db_session, org, name="Узкий", scopes=scopes or ("requests:read",)
    )
    await db_session.commit()
    return key


async def test_equipment_lists_only_confirmed_bindings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await _world(db_session)

    response = await client.get("/equipment", headers=bearer(world.key))

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [ids.encode("equipment", world.confirmed.id)]
    item = items[0]
    assert item["serial_number"] == "S1"
    assert item["customer_name"] == "Кафе"
    assert item["bindings"][0]["contract_number"] == "Д-7"
    assert "Секретный адрес" not in response.text
    assert "внутренняя заметка" not in response.text
    assert "notes" not in item and "location_id" not in item


async def test_equipment_cursor_pagination(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    world.pending_binding.status = "confirmed"
    await db_session.commit()

    first = (await client.get("/equipment?limit=1", headers=bearer(world.key))).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = (
        await client.get(
            f"/equipment?limit=1&cursor={first['next_cursor']}", headers=bearer(world.key)
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert second["next_cursor"] is None


async def test_equipment_requires_scope(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    key = await _key(db_session, world.provider)

    response = await client.get("/equipment", headers=bearer(key))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_SCOPE"


async def test_bindings_include_pending(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)

    response = await client.get("/service-bindings", headers=bearer(world.key))

    assert response.status_code == 200, response.text
    statuses = sorted(item["status"] for item in response.json()["items"])
    assert statuses == ["confirmed", "pending"]
    assert ids.encode("service_binding", world.foreign_binding.id) not in response.text

    pending = await client.get("/service-bindings?status=pending", headers=bearer(world.key))
    assert [b["id"] for b in pending.json()["items"]] == [
        ids.encode("service_binding", world.pending_binding.id)
    ]


async def test_bindings_cursor_advances(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    first = (await client.get("/service-bindings?limit=1", headers=bearer(world.key))).json()
    second = (
        await client.get(
            f"/service-bindings?limit=1&cursor={first['next_cursor']}", headers=bearer(world.key)
        )
    ).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert second["next_cursor"] is None


async def test_bindings_list_requires_scope(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    key = await _key(db_session, world.provider, "equipment:read")
    response = await client.get("/service-bindings", headers=bearer(key))
    assert response.status_code == 403


async def test_binding_response_confirms(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    binding_id = ids.encode("service_binding", world.pending_binding.id)

    response = await client.post(
        f"/service-bindings/{binding_id}/response",
        headers={**bearer(world.key), **idem("confirm")},
        json={"decision": "confirm"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"
    equipment = (await client.get("/equipment", headers=bearer(world.key))).json()["items"]
    assert len(equipment) == 2


async def test_binding_response_errors(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    pending_id = ids.encode("service_binding", world.pending_binding.id)
    foreign_id = ids.encode("service_binding", world.foreign_binding.id)

    foreign = await client.post(
        f"/service-bindings/{foreign_id}/response",
        headers={**bearer(world.key), **idem("foreign")},
        json={"decision": "reject", "reason": "не наш договор"},
    )
    assert foreign.status_code == 404

    read_only = await _key(db_session, world.provider, "service_bindings:read")
    denied = await client.post(
        f"/service-bindings/{pending_id}/response",
        headers={**bearer(read_only), **idem("denied")},
        json={"decision": "confirm"},
    )
    assert denied.status_code == 403

    no_key = await client.post(
        f"/service-bindings/{pending_id}/response",
        headers=bearer(world.key),
        json={"decision": "confirm"},
    )
    assert no_key.status_code == 422


async def test_invitation_create_and_revoke(client: AsyncClient, db_session: AsyncSession) -> None:
    world = await _world(db_session)
    payload = {
        "customer_inn": VALID_INN,
        "contract_number": "Д-100",
        "equipment_items": [{"description": "Посудомоечная машина", "serial_number": "PM-1"}],
    }

    created = await client.post(
        "/service-binding-invitations",
        headers={**bearer(world.key), **idem("invite")},
        json=payload,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["token"]
    invitation_id = body["id"]

    replay = await client.post(
        "/service-binding-invitations",
        headers={**bearer(world.key), **idem("invite")},
        json=payload,
    )
    assert body["token"] not in replay.text

    foreign = await client.post(
        f"/service-binding-invitations/{invitation_id}/revoke",
        headers={**bearer(world.other_key), **idem("revoke-foreign")},
    )
    assert foreign.status_code == 404

    revoked = await client.post(
        f"/service-binding-invitations/{invitation_id}/revoke",
        headers={**bearer(world.key), **idem("revoke")},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["state"] == "revoked"


async def test_invitation_requires_write_scope(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    world = await _world(db_session)
    key = await _key(db_session, world.provider, "service_bindings:read")

    response = await client.post(
        "/service-binding-invitations",
        headers={**bearer(key), **idem("invite")},
        json={"customer_inn": VALID_INN, "contract_number": "Д-1"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_scope"] == "service_bindings:write"
