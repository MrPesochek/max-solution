import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import ids
from app.db import session as db_session
from app.db.models import AuditEntry
from app.infra.config import get_settings
from tests.support import (
    CUSTOMER_INN,
    OTHER_INN,
    make_customer,
    make_provider,
    org_id,
    session_token,
)
from tests.trust.conftest import auth, idem_header

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_binding_invitation_flow_over_http(client: AsyncClient) -> None:
    provider = await make_provider("h-inv", status="active", accepting=True, verified=True)
    customer = await make_customer("h-inv-c", verified=True)
    provider_headers = auth(await session_token(provider.admin), org_id(provider.admin))
    customer_headers = auth(await session_token(customer.manager), org_id(customer.manager))
    equipment_id = ids.encode("equipment", customer.equipment_id)

    created = await client.post(
        "/service-binding-invitations",
        headers={**provider_headers, **idem_header("i1")},
        json={
            "customer_inn": CUSTOMER_INN,
            "contract_number": "Д-11",
            "basis": "service_contract",
            "equipment_descriptions": ["Витрина"],
        },
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert len(token) >= 43
    assert "startapp=sb_" in created.json()["webapp_link"]
    assert created.json()["customer_organization_id"] is None

    preview = await client.get(
        "/service-binding-invitations/preview",
        params={"token": token},
        headers=customer_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["contract_number"] == "Д-11"
    assert preview.json()["state"] == "active"

    again = await client.get(
        "/service-binding-invitations/preview",
        params={"token": token},
        headers=customer_headers,
    )
    assert again.json()["state"] == "active"

    accepted = await client.post(
        "/service-binding-invitations/accept",
        headers={**customer_headers, **idem_header("i2")},
        json={"token": token, "equipment_ids": [equipment_id]},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["items"][0]["status"] == "confirmed"

    listing = await client.get("/service-bindings", headers=customer_headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["contract_number"] == "Д-11"

    provider_listing = await client.get("/service-bindings", headers=provider_headers)
    assert provider_listing.json()["items"][0]["customer"]["name"] == "ООО Заказчик"


async def test_binding_request_reply_is_neutral_over_http(client: AsyncClient) -> None:
    provider = await make_provider("h-req", status="active", accepting=True, verified=True)
    customer = await make_customer("h-req-c")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))
    provider_id = ids.encode("organization", provider.organization_id)
    equipment_id = ids.encode("equipment", customer.equipment_id)

    first = await client.post(
        "/service-bindings/requests",
        headers={**headers, **idem_header("r1")},
        json={
            "provider_organization_id": provider_id,
            "contract_number": "Д-1",
            "equipment_ids": [equipment_id],
        },
    )
    second = await client.post(
        "/service-bindings/requests",
        headers={**headers, **idem_header("r2")},
        json={
            "provider_organization_id": provider_id,
            "contract_number": "НЕТ-ТАКОГО",
            "equipment_ids": [equipment_id],
        },
    )
    assert first.status_code == second.status_code == 202
    first_body, second_body = first.json(), second.json()
    assert (first_body.pop("remaining_attempts"), second_body.pop("remaining_attempts")) == (4, 3)
    assert json.dumps(first_body, sort_keys=True) == json.dumps(second_body, sort_keys=True)


async def test_contact_binding_over_http(client: AsyncClient) -> None:
    customer = await make_customer("h-contact")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))

    created = await client.post(
        "/service-bindings/contacts",
        headers={**headers, **idem_header("c1")},
        json={
            "equipment_id": ids.encode("equipment", customer.equipment_id),
            "contact_name": "Мастер Пётр",
            "contact_phone": "+79000000000",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_contact_only"] is True
    assert body["status"] != "confirmed"


async def test_foreign_objects_are_not_found_over_http(client: AsyncClient) -> None:
    provider = await make_provider("h-iso", status="active", accepting=True, verified=True)
    mine = await make_customer("h-iso-mine", verified=True)
    other = await make_customer("h-iso-other", inn=OTHER_INN, verified=True)

    provider_headers = auth(await session_token(provider.admin), org_id(provider.admin))
    mine_headers = auth(await session_token(mine.manager), org_id(mine.manager))
    other_headers = auth(await session_token(other.manager), org_id(other.manager))

    created = await client.post(
        "/service-binding-invitations",
        headers={**provider_headers, **idem_header("iso1")},
        json={
            "customer_inn": CUSTOMER_INN,
            "contract_number": "Д-33",
            "equipment_items": [{"description": "Ларь", "serial_number": "SN-1"}],
        },
    )
    token = created.json()["token"]
    invitation_id = created.json()["id"]

    stolen = await client.post(
        "/service-binding-invitations/accept",
        headers={**other_headers, **idem_header("iso2")},
        json={"token": token, "equipment_ids": []},
    )
    assert stolen.status_code == 409

    accepted = await client.post(
        "/service-binding-invitations/accept",
        headers={**mine_headers, **idem_header("iso3")},
        json={"token": token, "equipment_ids": [ids.encode("equipment", mine.equipment_id)]},
    )
    binding_id = accepted.json()["items"][0]["id"]

    assert (
        await client.get(f"/service-bindings/{binding_id}", headers=other_headers)
    ).status_code == 404
    revoked = await client.post(
        f"/service-bindings/{binding_id}/revoke",
        headers={**other_headers, **idem_header("iso4")},
        json={"reason": "чужое"},
    )
    assert revoked.status_code == 404
    responded = await client.post(
        f"/service-bindings/{binding_id}/respond",
        headers={**other_headers, **idem_header("iso5")},
        json={"decision": "confirm"},
    )
    assert responded.status_code in (403, 404)

    foreign_revoke = await client.post(
        f"/service-binding-invitations/{invitation_id}/revoke",
        headers={**other_headers, **idem_header("iso6")},
        json={},
    )
    assert foreign_revoke.status_code in (403, 404)

    other_listing = await client.get("/service-bindings", headers=other_headers)
    assert other_listing.json()["items"] == []


async def test_idempotent_repeat_returns_same_binding(client: AsyncClient) -> None:
    customer = await make_customer("h-idem")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))
    payload = {
        "equipment_id": ids.encode("equipment", customer.equipment_id),
        "contact_name": "Мастер",
    }
    first = await client.post(
        "/service-bindings/contacts", headers={**headers, **idem_header("id1")}, json=payload
    )
    second = await client.post(
        "/service-bindings/contacts", headers={**headers, **idem_header("id1")}, json=payload
    )
    assert first.json()["id"] == second.json()["id"]

    conflict = await client.post(
        "/service-bindings/contacts",
        headers={**headers, **idem_header("id1")},
        json={**payload, "contact_name": "Другой"},
    )
    assert conflict.status_code == 409


async def test_binding_request_rate_limit_over_http(client: AsyncClient) -> None:
    provider = await make_provider("h-rate", status="active", accepting=True, verified=True)
    customer = await make_customer("h-rate-c")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))
    payload = {
        "provider_organization_id": ids.encode("organization", provider.organization_id),
        "equipment_ids": [ids.encode("equipment", customer.equipment_id)],
    }
    remaining = []
    for attempt in range(5):
        response = await client.post(
            "/service-bindings/requests",
            headers={**headers, **idem_header(f"rl{attempt}")},
            json={**payload, "contract_number": f"Д-{attempt}"},
        )
        assert response.status_code == 202
        remaining.append(response.json()["remaining_attempts"])
    assert remaining == [4, 3, 2, 1, 0]

    limited = await client.post(
        "/service-bindings/requests",
        headers={**headers, **idem_header("rl-last")},
        json={**payload, "contract_number": "Д-last"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    retry_after = limited.json()["error"]["details"]["retry_after_seconds"]
    assert 1 <= retry_after <= get_settings().binding_request_window_seconds


async def test_unknown_public_id_is_not_found(client: AsyncClient) -> None:
    customer = await make_customer("h-badid")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))
    assert (
        await client.get("/service-bindings/inv_0000000000000000000000", headers=headers)
    ).status_code == 404
    assert (
        await client.get("/providers/sb_0000000000000000000000", headers=headers)
    ).status_code == 404


async def test_invitation_items_and_matches_over_http(client: AsyncClient) -> None:
    provider = await make_provider("h-items", status="active", accepting=True, verified=True)
    customer = await make_customer("h-items-c", verified=True)
    provider_headers = auth(await session_token(provider.admin), org_id(provider.admin))
    customer_headers = auth(await session_token(customer.manager), org_id(customer.manager))

    empty = await client.post(
        "/service-binding-invitations",
        headers={**provider_headers, **idem_header("it0")},
        json={"customer_inn": CUSTOMER_INN, "contract_number": "Д-50"},
    )
    assert empty.status_code == 422

    created = await client.post(
        "/service-binding-invitations",
        headers={**provider_headers, **idem_header("it1")},
        json={
            "customer_inn": CUSTOMER_INN,
            "contract_number": "Д-51",
            "equipment_items": [{"description": "Ларь", "model": "L-1"}],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["equipment_items"] == [
        {"index": 0, "description": "Ларь", "serial_number": None, "model": "L-1"}
    ]
    accepted = await client.post(
        "/service-binding-invitations/accept",
        headers={**customer_headers, **idem_header("it2")},
        json={
            "token": created.json()["token"],
            "matches": [
                {"item_index": 0, "equipment_id": ids.encode("equipment", customer.equipment_id)}
            ],
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["items"][0]["invitation_item_index"] == 0


async def _issue_invitation(
    client: AsyncClient, headers: dict[str, str], key: str, *, inn: str = CUSTOMER_INN
) -> str:
    created = await client.post(
        "/service-binding-invitations",
        headers={**headers, **idem_header(key)},
        json={
            "customer_inn": inn,
            "contract_number": f"Д-{key}",
            "customer_name": "Кафе «Ромашка»",
            "equipment_items": [{"description": "Витрина Carboma у кассы"}],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["customer_name"] == "Кафе «Ромашка»"
    return str(created.json()["token"])


async def test_binding_invitation_decline_over_http(client: AsyncClient) -> None:
    provider = await make_provider("h-dec", status="active", accepting=True, verified=True)
    customer = await make_customer("h-dec-c", verified=True)
    stranger = await make_customer("h-dec-x", inn=OTHER_INN, verified=True)
    provider_headers = auth(await session_token(provider.admin), org_id(provider.admin))
    customer_headers = auth(await session_token(customer.manager), org_id(customer.manager))
    token = await _issue_invitation(client, provider_headers, "dec1")

    preview = await client.post(
        "/service-binding-invitations/preview", headers=customer_headers, json={"token": token}
    )
    assert preview.json()["requisites_verified"] is True
    assert preview.json()["representative_verified"] is True
    assert preview.json()["details_disclosed"] is True

    for headers in (
        auth(await session_token(stranger.manager), org_id(stranger.manager)),
        {"Authorization": f"Bearer {await session_token(stranger.manager)}"},
    ):
        neutral = await client.post(
            "/service-binding-invitations/preview", headers=headers, json={"token": token}
        )
        assert neutral.status_code == 200
        assert neutral.json()["state"] == "active"
        assert neutral.json()["contract_number"] is None
        assert neutral.json()["equipment_items"] == []
        assert neutral.json()["details_disclosed"] is False

    foreign = await client.post(
        "/service-binding-invitations/decline",
        headers={
            **auth(await session_token(stranger.manager), org_id(stranger.manager)),
            **idem_header("dec-x"),
        },
        json={"token": token},
    )
    assert foreign.status_code == 409
    employee = await client.post(
        "/service-binding-invitations/decline",
        headers={
            **auth(await session_token(customer.employee), org_id(customer.employee)),
            **idem_header("dec-e"),
        },
        json={"token": token},
    )
    assert employee.status_code == 403

    declined = await client.post(
        "/service-binding-invitations/decline",
        headers={**customer_headers, **idem_header("dec2")},
        json={"token": token, "reason": "Договор расторгнут"},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["state"] == "declined"
    again = await client.post(
        "/service-binding-invitations/decline",
        headers={**customer_headers, **idem_header("dec3")},
        json={"token": token},
    )
    assert again.status_code == 200
    assert again.json()["state"] == "declined"

    accepted = await client.post(
        "/service-binding-invitations/accept",
        headers={**customer_headers, **idem_header("dec4")},
        json={"token": token, "equipment_ids": [ids.encode("equipment", customer.equipment_id)]},
    )
    assert accepted.status_code == 409

    listing = (await client.get("/service-binding-invitations", headers=provider_headers)).json()
    item = listing["items"][0]
    assert item["state"] == "declined"
    assert item["decline_reason"] == "Договор расторгнут"
    assert item["declined_at"] is not None
    assert item["customer_name"] == "Кафе «Ромашка»"
    assert item["customer_organization_id"] is None

    async with db_session.transaction() as s:
        actions = list(
            (
                await s.execute(
                    select(AuditEntry.action).where(
                        AuditEntry.action == "binding_invitation.decline"
                    )
                )
            ).scalars()
        )
    assert actions == ["binding_invitation.decline"]


async def test_binding_view_carries_invitation_item_and_contact(client: AsyncClient) -> None:
    provider = await make_provider("h-item", status="active", accepting=True, verified=True)
    customer = await make_customer("h-item-c", verified=True)
    provider_headers = auth(await session_token(provider.admin), org_id(provider.admin))
    customer_headers = auth(await session_token(customer.manager), org_id(customer.manager))
    token = await _issue_invitation(client, provider_headers, "item1")

    accepted = await client.post(
        "/service-binding-invitations/accept",
        headers={**customer_headers, **idem_header("item2")},
        json={"token": token, "equipment_ids": [ids.encode("equipment", customer.equipment_id)]},
    )
    assert accepted.json()["items"][0]["invitation_item_description"] == "Витрина Carboma у кассы"
    binding_id = accepted.json()["items"][0]["id"]
    card = (await client.get(f"/service-bindings/{binding_id}", headers=customer_headers)).json()
    assert card["invitation_item_description"] == "Витрина Carboma у кассы"
    assert card["contact_name"] is None

    contact = await client.post(
        "/service-bindings/contacts",
        headers={**customer_headers, **idem_header("item3")},
        json={
            "equipment_id": ids.encode("equipment", customer.equipment_id),
            "contact_name": "Мастер Пётр",
            "contact_phone": "+79000000000",
        },
    )
    listed = (await client.get("/service-bindings", headers=customer_headers)).json()["items"]
    mine = next(item for item in listed if item["id"] == contact.json()["id"])
    assert (mine["contact_name"], mine["contact_phone"]) == ("Мастер Пётр", "+79000000000")

    provider_items = (await client.get("/service-bindings", headers=provider_headers)).json()
    assert contact.json()["id"] not in [item["id"] for item in provider_items["items"]]
    assert all("contact_phone" not in item for item in provider_items["items"])
