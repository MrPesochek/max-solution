import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.core import ids
from tests.requests import factories, helpers
from tests.support import org_id, session_token

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_db")]


async def app_headers(actor: Any) -> dict[str, str]:
    token = await session_token(actor)
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id(actor)}


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_missing_photo_reason_is_validation_error(
    client: AsyncClient, reason: str | None
) -> None:
    world = await factories.build_world()
    headers = await app_headers(world.employee)
    created = await client.post(
        "/requests",
        headers={**headers, "Idempotency-Key": "photo-draft"},
        json={"equipment_id": ids.encode("equipment", world.equipment_id), "route": "own_service"},
    )
    draft = created.json()
    response = await client.patch(
        f"/requests/{draft['id']}",
        headers={**headers, "Idempotency-Key": "photo-missing"},
        json={
            "photos_incomplete": True,
            "photos_incomplete_reason": reason,
            "expected_version": draft["version"],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["field"] == "photos_incomplete_reason"
    corrected = await client.patch(
        f"/requests/{draft['id']}",
        headers={**headers, "Idempotency-Key": "photo-corrected"},
        json={
            "photos_incomplete": True,
            "photos_incomplete_reason": "Нет доступа к технике",
            "expected_version": draft["version"],
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["photos_incomplete"] is True


async def test_own_service_flow_via_app_api(client: AsyncClient) -> None:
    world = await factories.build_world()
    employee_headers = await app_headers(world.employee)
    manager_headers = await app_headers(world.manager)
    dispatcher_headers = await app_headers(world.dispatcher)

    draft = (
        await client.post(
            "/requests",
            headers={**employee_headers, "Idempotency-Key": "draft-key-01"},
            json={
                "equipment_id": ids.encode("equipment", world.equipment_id),
                "symptom_description": "Не держит температуру",
            },
        )
    ).json()
    assert draft["status"] == "draft"
    request_id = draft["id"]

    listed = await client.get("/requests", headers=employee_headers)
    assert listed.status_code == 200
    assert request_id in [item["id"] for item in listed.json()["items"]]

    submitted = (
        await client.post(
            f"/requests/{request_id}/actions/submit-to-own-service",
            headers={**employee_headers, "Idempotency-Key": "submit-key-01"},
            json={"expected_version": draft["version"]},
        )
    ).json()
    assert submitted["status"] == "awaiting_provider"
    assignment_id = submitted["assignment"]["id"]

    accepted = (
        await client.post(
            f"/requests/{request_id}/actions/accept",
            headers={**dispatcher_headers, "Idempotency-Key": "accept-key-01"},
            json={"assignment_id": assignment_id, "expected_version": submitted["version"]},
        )
    ).json()
    assert accepted["assignment"]["state"] == "accepted"

    proposed = (
        await client.post(
            f"/requests/{request_id}/actions/propose-visit",
            headers={**dispatcher_headers, "Idempotency-Key": "propose-key-01"},
            json={
                "assignment_id": assignment_id,
                "visit_window_start": helpers.window_start().isoformat(),
                "visit_window_end": helpers.window_end().isoformat(),
                "amount_minor": 200000,
                "currency": "RUB",
                "scope_description": "Диагностика компрессора",
                "expected_version": accepted["version"],
            },
        )
    ).json()
    proposal = proposed["visit_proposals"][0]

    approved = (
        await client.post(
            f"/requests/{request_id}/actions/approve-visit-proposal",
            headers={**manager_headers, "Idempotency-Key": "approve-key-01"},
            json={
                "proposal_id": proposal["id"],
                "proposal_version": proposal["version"],
                "expected_version": proposed["version"],
            },
        )
    ).json()
    assert approved["status"] == "scheduled"

    started = (
        await client.post(
            f"/requests/{request_id}/actions/start-work",
            headers={**dispatcher_headers, "Idempotency-Key": "start-key-01"},
            json={"assignment_id": assignment_id, "expected_version": approved["version"]},
        )
    ).json()
    assert started["status"] == "in_progress"

    reported = (
        await client.post(
            f"/requests/{request_id}/actions/report-completion",
            headers={**dispatcher_headers, "Idempotency-Key": "report-key-01"},
            json={
                "assignment_id": assignment_id,
                "outcome": "resolved",
                "summary": "Заменён компрессор",
                "expected_version": started["version"],
            },
        )
    ).json()
    assert reported["status"] == "completion_reported"

    confirmed = await client.post(
        f"/requests/{request_id}/actions/confirm-completion",
        headers={**manager_headers, "Idempotency-Key": "confirm-key-01"},
        json={"expected_version": reported["version"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "closed"

    history = await client.get(f"/requests/{request_id}/history", headers=manager_headers)
    assert history.status_code == 200
    assert len(history.json()["items"]) > 0


async def test_marketplace_flow_and_disclosure_via_app_api(client: AsyncClient) -> None:
    world = await factories.build_world(binding_status=None)
    rival = await factories.build_rival_provider(world)
    manager_headers = await app_headers(world.manager)
    provider_headers = await app_headers(rival.dispatcher)

    draft = (
        await client.post(
            "/requests",
            headers={**manager_headers, "Idempotency-Key": "mp-draft-01"},
            json={
                "equipment_id": ids.encode("equipment", world.equipment_id),
                "route": "marketplace",
            },
        )
    ).json()
    preview = await client.post(
        f"/requests/{draft['id']}/actions/preview-public-card",
        headers=manager_headers,
        json={"published_description": "Не держит температуру"},
    )
    assert preview.status_code == 200, preview.text
    no_version_publish = await client.post(
        f"/requests/{draft['id']}/actions/publish-search",
        headers={**manager_headers, "Idempotency-Key": "mp-publish-00"},
        json={},
    )
    assert no_version_publish.status_code == 422
    published = (
        await client.post(
            f"/requests/{draft['id']}/actions/publish-search",
            headers={**manager_headers, "Idempotency-Key": "mp-publish-01"},
            json={"expected_version": draft["version"]},
        )
    ).json()
    assert published["search"]["published"] is True

    marketplace_list = await client.get("/marketplace/requests", headers=provider_headers)
    assert marketplace_list.status_code == 200
    assert draft["id"] in [item["request_id"] for item in marketplace_list.json()["items"]]

    offer = (
        await client.post(
            f"/marketplace/requests/{draft['id']}/offers",
            headers={**provider_headers, "Idempotency-Key": "mp-offer-01"},
            json={"amount_minor": 90000, "currency": "RUB", "scope_description": "Ремонт на месте"},
        )
    ).json()

    current = (await client.get(f"/requests/{draft['id']}", headers=manager_headers)).json()
    select_path = f"/requests/{draft['id']}/actions/select-offer"
    without_version = await client.post(
        select_path,
        headers={**manager_headers, "Idempotency-Key": "mp-select-00"},
        json={"offer_id": offer["id"], "expected_version": current["version"]},
    )
    assert without_version.status_code == 422

    stale_offer = await client.post(
        select_path,
        headers={**manager_headers, "Idempotency-Key": "mp-select-stale"},
        json={
            "offer_id": offer["id"],
            "offer_version": offer["version"] + 1,
            "expected_version": current["version"],
        },
    )
    assert stale_offer.status_code == 409
    assert stale_offer.json()["error"]["code"] == "OFFER_NOT_CURRENT"

    selected = (
        await client.post(
            select_path,
            headers={**manager_headers, "Idempotency-Key": "mp-select-01"},
            json={
                "offer_id": offer["id"],
                "offer_version": offer["version"],
                "expected_version": current["version"],
            },
        )
    ).json()

    before = await client.get(f"/requests/{draft['id']}", headers=provider_headers)
    assert before.status_code == 200
    assert before.json()["contacts_disclosed"] is False
    assert before.json()["location"]["address"] is None
    assert before.json()["customer_org_name"] is None

    confirmed = (
        await client.post(
            f"/requests/{draft['id']}/actions/accept",
            headers={**provider_headers, "Idempotency-Key": "mp-confirm-01"},
            json={
                "assignment_id": selected["assignment"]["id"],
                "expected_version": selected["version"],
            },
        )
    ).json()
    assert confirmed["contacts_disclosed"] is True
    assert confirmed["location"]["address"] is not None
    assert confirmed["customer_org_name"]
    card = (await client.get(f"/requests/{draft['id']}", headers=provider_headers)).json()
    assert card["customer_org_name"] == confirmed["customer_org_name"]


async def test_employee_cannot_manage_offers_or_approvals(client: AsyncClient) -> None:
    world = await factories.build_world()
    employee_headers = await app_headers(world.employee)
    scheduled = await helpers.make_accepted(world)

    proposed = (
        await client.post(
            f"/requests/{scheduled['id']}/actions/propose-visit",
            headers={**(await app_headers(world.dispatcher)), "Idempotency-Key": "e-propose"},
            json={
                "assignment_id": scheduled["assignment"]["id"],
                "visit_window_start": helpers.window_start().isoformat(),
                "visit_window_end": helpers.window_end().isoformat(),
                "amount_minor": 100000,
                "currency": "RUB",
                "expected_version": scheduled["version"],
            },
        )
    ).json()
    proposal = proposed["visit_proposals"][0]

    forbidden_approve = await client.post(
        f"/requests/{scheduled['id']}/actions/approve-visit-proposal",
        headers={**employee_headers, "Idempotency-Key": "e-approve"},
        json={
            "proposal_id": proposal["id"],
            "proposal_version": proposal["version"],
            "expected_version": proposed["version"],
        },
    )
    assert forbidden_approve.status_code == 403

    published_world = await factories.build_world(binding_status=None)
    published = await helpers.make_published(published_world)
    forbidden_select = await client.post(
        f"/requests/{published['id']}/actions/select-offer",
        headers={**(await app_headers(published_world.employee)), "Idempotency-Key": "e-select"},
        json={
            "offer_id": ids.encode("offer", uuid.uuid4()),
            "offer_version": 1,
            "expected_version": 1,
        },
    )
    assert forbidden_select.status_code == 403


async def test_foreign_organization_cannot_read_request(client: AsyncClient) -> None:
    world = await factories.build_world()
    other = await factories.build_world()
    draft = await helpers.make_draft(world)

    response = await client.get(
        f"/requests/{draft['id']}", headers=await app_headers(other.manager)
    )
    assert response.status_code == 404


async def test_version_conflict_response_shape(client: AsyncClient) -> None:
    world = await factories.build_world()
    employee_headers = await app_headers(world.employee)
    draft = await helpers.make_draft(world)

    response = await client.patch(
        f"/requests/{draft['id']}",
        headers={**employee_headers, "Idempotency-Key": "patch-stale"},
        json={"symptom_description": "Иначе", "expected_version": draft["version"] + 5},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "VERSION_CONFLICT"
    assert body["error"]["details"]["current_version"] == draft["version"]


async def test_invalid_transition_response_shape(client: AsyncClient) -> None:
    world = await factories.build_world()
    manager_headers = await app_headers(world.manager)
    accepted = await helpers.make_accepted(world)

    response = await client.post(
        f"/requests/{accepted['id']}/actions/confirm-completion",
        headers={**manager_headers, "Idempotency-Key": "bad-transition"},
        json={"expected_version": accepted["version"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_idempotent_create_draft_replay(client: AsyncClient) -> None:
    world = await factories.build_world()
    employee_headers = await app_headers(world.employee)
    body = {
        "equipment_id": ids.encode("equipment", world.equipment_id),
        "symptom_description": "Течёт",
    }

    first = await client.post(
        "/requests", headers={**employee_headers, "Idempotency-Key": "replay-key"}, json=body
    )
    second = await client.post(
        "/requests", headers={**employee_headers, "Idempotency-Key": "replay-key"}, json=body
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_price_approval_ignores_client_supplied_amount(client: AsyncClient) -> None:
    world = await factories.build_world()
    manager_headers = await app_headers(world.manager)
    dispatcher_headers = await app_headers(world.dispatcher)
    accepted = await helpers.make_accepted(world)

    proposed = (
        await client.post(
            f"/requests/{accepted['id']}/actions/propose-visit",
            headers={**dispatcher_headers, "Idempotency-Key": "amt-propose"},
            json={
                "assignment_id": accepted["assignment"]["id"],
                "visit_window_start": helpers.window_start().isoformat(),
                "visit_window_end": helpers.window_end().isoformat(),
                "amount_minor": 300000,
                "currency": "RUB",
                "expected_version": accepted["version"],
            },
        )
    ).json()
    proposal = proposed["visit_proposals"][0]

    approved = await client.post(
        f"/requests/{accepted['id']}/actions/approve-visit-proposal",
        headers={**manager_headers, "Idempotency-Key": "amt-approve"},
        json={
            "proposal_id": proposal["id"],
            "proposal_version": proposal["version"],
            "expected_version": proposed["version"],
            "amount_minor": 1,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["visit_proposals"][0]["price"]["amount_minor"] == 300000


async def test_pending_approvals_endpoint(client: AsyncClient) -> None:
    world = await factories.build_world()
    draft = await helpers.make_submitted(world)
    await client.post(
        f"/requests/{draft['id']}/actions/decline",
        headers={**(await app_headers(world.dispatcher)), "Idempotency-Key": "pa-decline"},
        json={
            "assignment_id": draft["assignment"]["id"],
            "reason": "Нет запчасти",
            "expected_version": draft["version"],
        },
    )

    manager_response = await client.get(
        "/requests/pending-approvals", headers=await app_headers(world.manager)
    )
    assert manager_response.status_code == 200
    items = manager_response.json()
    assert [item["kind"] for item in items] == ["action_required"]
    assert items[0]["request"]["id"] == draft["id"]

    employee_response = await client.get(
        "/requests/pending-approvals", headers=await app_headers(world.employee)
    )
    assert employee_response.status_code == 200
    assert employee_response.json() == []


async def test_patch_draft_null_semantics(client: AsyncClient) -> None:
    world = await factories.build_world()
    headers = await app_headers(world.employee)

    draft = (
        await client.post(
            "/requests",
            headers={**headers, "Idempotency-Key": "pd-create"},
            json={
                "equipment_id": ids.encode("equipment", world.equipment_id),
                "symptom_description": "Не держит температуру",
                "error_code": "E42",
            },
        )
    ).json()

    untouched = (
        await client.patch(
            f"/requests/{draft['id']}",
            headers={**headers, "Idempotency-Key": "pd-untouched"},
            json={"urgency": "urgent", "expected_version": draft["version"]},
        )
    ).json()
    assert untouched["error_code"] == "E42"

    cleared = (
        await client.patch(
            f"/requests/{draft['id']}",
            headers={**headers, "Idempotency-Key": "pd-clear"},
            json={"error_code": None, "expected_version": untouched["version"]},
        )
    ).json()
    assert cleared["error_code"] is None

    rejected = await client.patch(
        f"/requests/{draft['id']}",
        headers={**headers, "Idempotency-Key": "pd-reject"},
        json={"equipment_id": None, "expected_version": cleared["version"]},
    )
    assert rejected.status_code == 422
