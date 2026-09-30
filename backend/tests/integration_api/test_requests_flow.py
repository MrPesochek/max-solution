import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.core import ids
from app.db import session as db_session
from app.db.models import Organization
from tests import factories
from tests.integration_api.conftest import bearer, idem
from tests.requests import factories as rf
from tests.requests import helpers
from tests.support import org_id, session_token

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_db")]


async def _api_key(
    org_id_: uuid.UUID, *, scopes: tuple[str, ...] = ("requests:read", "requests:write")
) -> str:
    async with db_session.transaction() as session:
        org = await session.get(Organization, org_id_)
        assert org is not None
        _, raw = await factories.create_integration_client(session, org, scopes=scopes)
        return raw


async def app_headers(actor: Any) -> dict[str, str]:
    token = await session_token(actor)
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id(actor)}


async def test_s1_own_service_flow_across_both_apis(
    client: AsyncClient, app_client: AsyncClient
) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id, scopes=("requests:read", "requests:write"))
    employee_headers = await app_headers(world.employee)
    manager_headers = await app_headers(world.manager)

    draft = (
        await app_client.post(
            "/requests",
            headers={**employee_headers, **idem("draft")},
            json={"equipment_id": ids.encode("equipment", world.equipment_id)},
        )
    ).json()
    request_id = draft["id"]

    submitted = await app_client.post(
        f"/requests/{request_id}/actions/submit-to-own-service",
        headers={**employee_headers, **idem("submit")},
        json={"expected_version": draft["version"]},
    )
    assert submitted.status_code == 200
    submitted_body = submitted.json()
    assignment_id = submitted_body["assignment"]["id"]

    accepted = await client.post(
        f"/requests/{request_id}/accept",
        headers={**bearer(crm_key), **idem("accept")},
        json={"assignment_id": assignment_id, "expected_version": submitted_body["version"]},
    )
    assert accepted.status_code == 200, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["contacts_disclosed"] is True

    message = await client.post(
        f"/requests/{request_id}/messages",
        headers={**bearer(crm_key), **idem("msg")},
        json={"body": "Уточните код ошибки", "assignment_id": assignment_id},
    )
    assert message.status_code == 201
    assert message.json()["author_kind"] == "integration_client"

    current = (await client.get(f"/requests/{request_id}", headers=bearer(crm_key))).json()
    proposed = await client.post(
        f"/requests/{request_id}/visit-proposals",
        headers={**bearer(crm_key), **idem("visit")},
        json={
            "expected_version": current["version"],
            "assignment_id": assignment_id,
            "visit_window_start": helpers.window_start().isoformat(),
            "visit_window_end": helpers.window_end().isoformat(),
            "amount_minor": 150000,
            "currency": "RUB",
            "scope_description": "Диагностика и ремонт",
        },
    )
    assert proposed.status_code == 201, proposed.text
    proposed_body = proposed.json()
    proposal = proposed_body["visit_proposals"][0]

    approved = await app_client.post(
        f"/requests/{request_id}/actions/approve-visit-proposal",
        headers={**manager_headers, **idem("approve-visit")},
        json={
            "proposal_id": proposal["id"],
            "proposal_version": proposal["version"],
            "expected_version": proposed_body["version"],
        },
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "scheduled"
    assert approved_body["visit_proposals"][0]["price"]["amount_minor"] == 150000

    started = await client.post(
        f"/requests/{request_id}/start-work",
        headers={**bearer(crm_key), **idem("start")},
        json={"assignment_id": assignment_id, "expected_version": approved_body["version"]},
    )
    assert started.status_code == 200
    started_body = started.json()
    assert started_body["status"] == "in_progress"

    completed = await client.post(
        f"/requests/{request_id}/complete",
        headers={**bearer(crm_key), **idem("complete")},
        json={
            "assignment_id": assignment_id,
            "outcome": "resolved",
            "summary": "Заменён термостат",
            "expected_version": started_body["version"],
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["status"] == "completion_reported"

    confirmed = await app_client.post(
        f"/requests/{request_id}/actions/confirm-completion",
        headers={**manager_headers, **idem("confirm")},
        json={"expected_version": completed_body["version"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "closed"


async def test_s2_marketplace_two_providers_across_apis(
    client: AsyncClient, app_client: AsyncClient
) -> None:
    world = await rf.build_world(binding_status=None)
    rival = await rf.build_rival_provider(world)
    manager_headers = await app_headers(world.manager)

    api_key = await _api_key(
        world.provider_org_id,
        scopes=("requests:read", "requests:write", "marketplace:read", "marketplace:write"),
    )
    rival_headers = await app_headers(rival.dispatcher)

    draft = (
        await app_client.post(
            "/requests",
            headers={**manager_headers, **idem("draft")},
            json={
                "equipment_id": ids.encode("equipment", world.equipment_id),
                "route": "marketplace",
            },
        )
    ).json()
    request_id = draft["id"]

    published = await app_client.post(
        f"/requests/{request_id}/actions/publish-search",
        headers={**manager_headers, **idem("publish")},
        json={"expected_version": draft["version"]},
    )
    assert published.status_code == 200, published.text
    published_body = published.json()
    assert published_body["search"]["published"] is True

    offer_a = await client.post(
        f"/marketplace/requests/{request_id}/offers",
        headers={**bearer(api_key), **idem("offer-a")},
        json={
            "amount_minor": 100000,
            "currency": "RUB",
            "scope_description": "Выезд и диагностика",
        },
    )
    assert offer_a.status_code == 201, offer_a.text
    offer_a_id = offer_a.json()["id"]

    offer_b = await app_client.post(
        f"/marketplace/requests/{request_id}/offers",
        headers={**rival_headers, **idem("offer-b")},
        json={
            "amount_minor": 120000,
            "currency": "RUB",
            "scope_description": "Выезд и диагностика",
        },
    )
    assert offer_b.status_code == 201, offer_b.text

    card = await client.get(f"/marketplace/requests/{request_id}", headers=bearer(api_key))
    assert card.status_code == 200
    assert "address" not in card.json()["card"]

    current = (await app_client.get(f"/requests/{request_id}", headers=manager_headers)).json()
    selected = await app_client.post(
        f"/requests/{request_id}/actions/select-offer",
        headers={**manager_headers, **idem("select")},
        json={
            "offer_id": offer_a_id,
            "offer_version": offer_a.json()["version"],
            "expected_version": current["version"],
        },
    )
    assert selected.status_code == 200, selected.text
    selected_body = selected.json()
    assignment_id = selected_body["assignment"]["id"]

    pending_view = await client.get(f"/requests/{request_id}", headers=bearer(api_key))
    assert pending_view.status_code == 200
    pending_body = pending_view.json()
    assert pending_body["contacts_disclosed"] is False
    assert pending_body["location"]["address"] is None

    confirmed = await client.post(
        f"/requests/{request_id}/accept",
        headers={**bearer(api_key), **idem("confirm-assignment")},
        json={"assignment_id": assignment_id, "expected_version": selected_body["version"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    assert confirmed_body["contacts_disclosed"] is True
    assert confirmed_body["location"]["address"] is not None

    rival_offers = await app_client.get(f"/requests/{request_id}/offers", headers=rival_headers)
    assert rival_offers.status_code == 200
    assert [o["state"] for o in rival_offers.json()] == ["closed"]


async def test_insufficient_scope_forbidden(client: AsyncClient) -> None:
    world = await rf.build_world()
    read_only_key = await _api_key(world.provider_org_id, scopes=("requests:read",))
    submitted = await helpers.make_submitted(world)

    response = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(read_only_key), **idem("accept")},
        json={
            "assignment_id": submitted["assignment"]["id"],
            "expected_version": submitted["version"],
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_SCOPE"


async def test_foreign_key_sees_nothing(client: AsyncClient) -> None:
    world = await rf.build_world()
    other = await rf.build_world()
    other_key = await _api_key(other.provider_org_id)
    submitted = await helpers.make_submitted(world)

    response = await client.get(f"/requests/{submitted['id']}", headers=bearer(other_key))
    assert response.status_code == 404


async def test_late_response_on_revoked_assignment_is_conflict(
    client: AsyncClient, app_client: AsyncClient
) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id)
    manager_headers = await app_headers(world.manager)
    submitted = await helpers.make_submitted(world)

    revoked = await app_client.post(
        f"/requests/{submitted['id']}/actions/revoke-assignment",
        headers={**manager_headers, **idem("revoke")},
        json={
            "assignment_id": submitted["assignment"]["id"],
            "expected_version": submitted["version"],
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "action_required"

    late_accept = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(crm_key), **idem("late-accept")},
        json={
            "assignment_id": submitted["assignment"]["id"],
            "expected_version": revoked.json()["version"],
        },
    )
    assert late_accept.status_code == 409
    assert late_accept.json()["error"]["code"] == "ASSIGNMENT_NOT_ACTIVE"


async def test_version_conflict_response_shape(client: AsyncClient) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id)
    submitted = await helpers.make_submitted(world)

    response = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(crm_key), **idem("stale")},
        json={"assignment_id": submitted["assignment"]["id"], "expected_version": 999},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "VERSION_CONFLICT"
    assert body["error"]["details"]["current_version"] == submitted["version"]
    assert "request_id" in body["error"]


async def test_invalid_transition_response_shape(client: AsyncClient) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id)
    completed = await helpers.make_completion_reported(world)

    response = await client.post(
        f"/requests/{completed['id']}/start-work",
        headers={**bearer(crm_key), **idem("bad-transition")},
        json={
            "assignment_id": completed["assignment"]["id"],
            "expected_version": completed["version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_idempotent_repeat_post(client: AsyncClient) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id)
    submitted = await helpers.make_submitted(world)
    body = {
        "assignment_id": submitted["assignment"]["id"],
        "expected_version": submitted["version"],
    }

    first = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(crm_key), **idem("repeat")},
        json=body,
    )
    second = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(crm_key), **idem("repeat")},
        json=body,
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    conflicting = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(crm_key), **idem("repeat")},
        json={**body, "expected_version": (submitted["version"] or 0) + 100},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_request_mutation_requires_expected_version(client: AsyncClient) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id)
    submitted = await helpers.make_submitted(world)

    response = await client.post(
        f"/requests/{submitted['id']}/accept",
        headers={**bearer(crm_key), **idem("no-version")},
        json={"assignment_id": submitted["assignment"]["id"]},
    )
    assert response.status_code == 422
    fields = [f["field"] for f in response.json()["error"]["details"]["fields"]]
    assert "expected_version" in fields


async def test_crm_repair_quote_with_items(client: AsyncClient) -> None:
    world = await rf.build_world()
    crm_key = await _api_key(world.provider_org_id)
    accepted = await helpers.make_accepted(world)
    body = {
        "assignment_id": accepted["assignment"]["id"],
        "description_of_work": "Замена компрессора",
        "currency": "RUB",
        "items": [
            {"title": "Компрессор", "amount_minor": 300000},
            {"title": "Работа", "amount_minor": 50000},
        ],
        "expected_version": accepted["version"],
    }
    created = await client.post(
        f"/requests/{accepted['id']}/repair-quotes",
        headers={**bearer(crm_key), **idem("quote-items")},
        json=body,
    )
    assert created.status_code == 201, created.text
    quote = created.json()["repair_quotes"][0]
    assert quote["price"]["amount_minor"] == 350000
    assert [item["title"] for item in quote["items"]] == ["Компрессор", "Работа"]

    mismatch = await client.post(
        f"/requests/{accepted['id']}/repair-quotes",
        headers={**bearer(crm_key), **idem("quote-items-bad")},
        json={**body, "amount_minor": 1, "expected_version": created.json()["version"]},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "QUOTE_ITEMS_SUM_MISMATCH"
