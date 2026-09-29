from typing import Any

import pytest
from httpx import AsyncClient

from tests import factories
from tests.app_api.conftest import auth, idem

pytestmark = pytest.mark.usefixtures("clean_db")


async def _login(client: AsyncClient, max_user_id: int) -> str:
    response = await client.post(
        "/auth/max", json={"init_data": factories.sign_init_data(max_user_id)}
    )
    assert response.status_code == 200
    token: str = response.json()["token"]
    return token


async def _create_customer(client: AsyncClient, token: str, key: str, name: str) -> dict[str, Any]:
    cities = (await client.get("/directories/cities", headers=auth(token))).json()["items"]
    response = await client.post(
        "/organizations",
        headers={**auth(token), **idem(f"org-create-{key}")},
        json={
            "name": name,
            "kind": "customer",
            "contact_phone": "+79990000000",
            "first_location": {
                "name": "Первая точка",
                "city_id": cities[0]["id"],
                "address": "ул. Ленина, 1",
            },
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_full_registration_flow(client: AsyncClient) -> None:
    manager_token = await _login(client, 2001)
    created = await _create_customer(client, manager_token, "romashka", "ООО Ромашка")
    org_id = created["organization"]["id"]
    headers = auth(manager_token, org_id)

    current = await client.get("/organizations/current", headers=headers)
    assert current.status_code == 200
    assert current.json()["name"] == "ООО Ромашка"

    patched = await client.patch(
        "/organizations/current",
        headers={**headers, **idem("org-patch-1")},
        json={"contact_email": "info@example.test"},
    )
    assert patched.json()["contact_email"] == "info@example.test"

    locations = (await client.get("/locations", headers=headers)).json()
    assert len(locations["items"]) == 1
    assert locations["next_cursor"] is None
    first_location = locations["items"][0]["id"]

    second = await client.post(
        "/locations",
        headers={**headers, **idem("loc-1")},
        json={
            "name": "Вторая точка",
            "city_id": locations["items"][0]["city_id"],
            "address": "ул. Мира, 2",
        },
    )
    assert second.status_code == 201
    second_location = second.json()["id"]

    categories = (await client.get("/directories/equipment-categories", headers=headers)).json()[
        "items"
    ]
    equipment = await client.post(
        "/equipment",
        headers={**headers, **idem("eq-1")},
        json={
            "location_id": first_location,
            "equipment_category_id": categories[0]["id"],
            "brand": "Бренд",
        },
    )
    assert equipment.status_code == 201
    assert equipment.json()["serial_number"] is None

    repeat = await client.post(
        "/equipment",
        headers={**headers, **idem("eq-1")},
        json={
            "location_id": first_location,
            "equipment_category_id": categories[0]["id"],
            "brand": "Бренд",
        },
    )
    assert repeat.status_code == 201
    assert repeat.json()["id"] == equipment.json()["id"]

    invitation = await client.post(
        "/invitations",
        headers={**headers, **idem("inv-1")},
        json={"role": "customer_employee", "location_ids": [first_location]},
    )
    assert invitation.status_code == 201
    invite_token = invitation.json()["token"]

    preview = await client.get(
        "/invitations/preview",
        params={"token": invite_token},
        headers=auth(manager_token),
    )
    assert preview.status_code == 200
    assert preview.json() == {
        "organization_name": "ООО Ромашка",
        "role": "customer_employee",
        "expires_at": invitation.json()["expires_at"],
        "state": "active",
        "inviter_name": "Иван",
        "location_names": ["Первая точка"],
    }

    employee_token = await _login(client, 2002)
    accepted = await client.post(
        "/invitations/accept",
        headers={**auth(employee_token), **idem("acc-1")},
        json={"token": invite_token},
    )
    assert accepted.status_code == 201
    assert accepted.json()["location_ids"] == [first_location]
    assert accepted.json()["status"] == "pending"
    employee_headers = auth(employee_token, org_id)
    assert (await client.get("/locations", headers=employee_headers)).status_code == 404

    pending = (await client.get("/memberships", headers=headers)).json()["items"]
    waiting = next(m for m in pending if m["status"] == "pending")
    assert waiting["user"]["display_name"]
    assert waiting["accepted_at"] is not None
    approved = await client.post(
        f"/memberships/{accepted.json()['id']}/approve", headers={**headers, **idem("appr-1")}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    employee_locations = (await client.get("/locations", headers=employee_headers)).json()
    assert [i["id"] for i in employee_locations["items"]] == [first_location]
    assert (
        await client.get(f"/locations/{second_location}", headers=employee_headers)
    ).status_code == 404

    reuse = await client.post(
        "/invitations/accept",
        headers={**auth(await _login(client, 2003)), **idem("acc-2")},
        json={"token": invite_token},
    )
    assert reuse.status_code == 409
    assert reuse.json()["error"]["code"] == "INVITATION_INVALID"

    members = (await client.get("/memberships", headers=headers)).json()["items"]
    assert sorted(m["role"] for m in members) == ["customer_employee", "customer_manager"]

    employee_membership = next(m for m in members if m["role"] == "customer_employee")
    updated = await client.put(
        f"/memberships/{employee_membership['id']}/locations",
        headers={**headers, **idem("mem-loc-1")},
        json={"location_ids": [first_location, second_location]},
    )
    assert updated.status_code == 200
    assert sorted(updated.json()["location_ids"]) == sorted([first_location, second_location])

    revoked = await client.post(
        f"/memberships/{employee_membership['id']}/revoke",
        headers={**headers, **idem("mem-rev-1")},
    )
    assert revoked.status_code == 200
    assert (await client.get("/locations", headers=employee_headers)).status_code == 404


async def test_patch_null_semantics_for_location_and_equipment(client: AsyncClient) -> None:
    """ТЗ 10.4: поле, переданное в теле, задаёт значение (в т.ч. `null` — очистка
    nullable-поля); отсутствующее в теле — не меняется; `null` для NOT NULL — 422."""
    manager_token = await _login(client, 2040)
    created = await _create_customer(client, manager_token, "patch-null", "ООО Патч")
    headers = auth(manager_token, created["organization"]["id"])

    locations = (await client.get("/locations", headers=headers)).json()["items"]
    location_id = locations[0]["id"]

    with_phone = await client.patch(
        f"/locations/{location_id}",
        headers={**headers, **idem("patch-loc-phone")},
        json={"contact_phone": "+79990000099"},
    )
    assert with_phone.status_code == 200
    assert with_phone.json()["contact_phone"] == "+79990000099"

    untouched = await client.patch(
        f"/locations/{location_id}",
        headers={**headers, **idem("patch-loc-untouched")},
        json={"name": "Патч-точка"},
    )
    assert untouched.status_code == 200
    assert untouched.json()["contact_phone"] == "+79990000099"

    cleared = await client.patch(
        f"/locations/{location_id}",
        headers={**headers, **idem("patch-loc-null")},
        json={"contact_phone": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["contact_phone"] is None

    rejected = await client.patch(
        f"/locations/{location_id}",
        headers={**headers, **idem("patch-loc-reject")},
        json={"city_id": None},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_FAILED"

    categories = (await client.get("/directories/equipment-categories", headers=headers)).json()[
        "items"
    ]
    equipment = await client.post(
        "/equipment",
        headers={**headers, **idem("patch-eq-create")},
        json={
            "location_id": location_id,
            "equipment_category_id": categories[0]["id"],
            "brand": "Бренд",
        },
    )
    equipment_id = equipment.json()["id"]

    eq_untouched = await client.patch(
        f"/equipment/{equipment_id}",
        headers={**headers, **idem("patch-eq-untouched")},
        json={"model": "Модель"},
    )
    assert eq_untouched.json()["brand"] == "Бренд"

    eq_cleared = await client.patch(
        f"/equipment/{equipment_id}",
        headers={**headers, **idem("patch-eq-clear")},
        json={"brand": None},
    )
    assert eq_cleared.status_code == 200
    assert eq_cleared.json()["brand"] is None

    eq_rejected = await client.patch(
        f"/equipment/{equipment_id}",
        headers={**headers, **idem("patch-eq-reject")},
        json={"equipment_category_id": None},
    )
    assert eq_rejected.status_code == 422


async def test_revoked_invitation_is_rejected(client: AsyncClient) -> None:
    manager_token = await _login(client, 2010)
    created = await _create_customer(client, manager_token, "revoke", "ООО Отзыв")
    headers = auth(manager_token, created["organization"]["id"])

    invitation = (
        await client.post(
            "/invitations",
            headers={**headers, **idem("inv-2")},
            json={"role": "customer_employee"},
        )
    ).json()

    listed = (await client.get("/invitations", headers=headers)).json()["items"]
    assert [i["id"] for i in listed] == [invitation["id"]]
    assert "token" not in listed[0]

    revoke = await client.post(
        f"/invitations/{invitation['id']}/revoke", headers={**headers, **idem("inv-rev-1")}
    )
    assert revoke.status_code == 200
    assert revoke.json()["state"] == "revoked"

    guest_token = await _login(client, 2011)
    response = await client.post(
        "/invitations/accept",
        headers={**auth(guest_token), **idem("acc-3")},
        json={"token": invitation["token"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVITATION_INVALID"
    assert response.json()["error"]["details"] == {}


async def test_mutation_requires_idempotency_key(client: AsyncClient) -> None:
    token = await _login(client, 2020)
    response = await client.post(
        "/organizations",
        headers=auth(token),
        json={"name": "ООО Без ключа", "kind": "customer", "contact_phone": "+79990000000"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_provider_registration_creates_pending_staff(client: AsyncClient) -> None:
    admin_token = await _login(client, 2030)
    created = (
        await client.post(
            "/organizations",
            headers={**auth(admin_token), **idem("org-provider-1")},
            json={
                "name": "Сервис 24",
                "kind": "provider",
                "contact_phone": "+79990000003",
                "provider_kind": "company",
            },
        )
    ).json()
    headers = auth(admin_token, created["organization"]["id"])
    assert created["membership"]["role"] == "provider_admin"

    invitation = (
        await client.post(
            "/invitations",
            headers={**headers, **idem("inv-provider-1")},
            json={"role": "provider_dispatcher"},
        )
    ).json()

    dispatcher_token = await _login(client, 2031)
    accepted = await client.post(
        "/invitations/accept",
        headers={**auth(dispatcher_token), **idem("acc-provider-1")},
        json={"token": invitation["token"]},
    )
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "pending"

    assert (
        await client.get(
            "/organizations/current",
            headers=auth(dispatcher_token, created["organization"]["id"]),
        )
    ).status_code == 404

    approved = await client.post(
        f"/memberships/{accepted.json()['id']}/approve",
        headers={**headers, **idem("mem-appr-1")},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    assert (
        await client.get(
            "/organizations/current",
            headers=auth(dispatcher_token, created["organization"]["id"]),
        )
    ).status_code == 200
