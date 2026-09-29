from typing import Any

import pytest
from httpx import AsyncClient

from app.core import ids
from tests.requests import factories
from tests.support import org_id, session_token

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_db")]


async def app_headers(actor: Any) -> dict[str, str]:
    token = await session_token(actor)
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id(actor)}


async def _marketplace_draft(client: AsyncClient, world: Any, key: str) -> dict[str, Any]:
    response = await client.post(
        "/requests",
        headers={**(await app_headers(world.employee)), "Idempotency-Key": key},
        json={
            "equipment_id": ids.encode("equipment", world.equipment_id),
            "route": "marketplace",
            "urgency": "critical",
            "symptom_description": "Не держит холод",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_patch_stores_reason_and_approval_keeps_it(client: AsyncClient) -> None:
    world = await factories.build_world()
    headers = await app_headers(world.employee)
    draft = await _marketplace_draft(client, world, "pi-create")

    patched = await client.patch(
        f"/requests/{draft['id']}",
        headers={**headers, "Idempotency-Key": "pi-patch-01"},
        json={
            "photos_incomplete": True,
            "photos_incomplete_reason": "  Общий вид: Камера не работает ",
            "expected_version": draft["version"],
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["photos_incomplete"] is True
    assert body["photos_incomplete_reason"] == "Общий вид: Камера не работает"

    approval = await client.post(
        f"/requests/{draft['id']}/actions/request-approval",
        headers={**headers, "Idempotency-Key": "pi-approval"},
        json={"expected_version": body["version"]},
    )
    assert approval.status_code == 200, approval.text

    seen = (
        await client.get(f"/requests/{draft['id']}", headers=await app_headers(world.manager))
    ).json()
    assert seen["status"] == "approval_required"
    assert seen["photos_incomplete"] is True
    assert seen["photos_incomplete_reason"] == "Общий вид: Камера не работает"


async def test_null_flag_rejected_and_foreign_draft_forbidden(client: AsyncClient) -> None:
    world = await factories.build_world()
    draft = await _marketplace_draft(client, world, "pi-create-2")

    rejected = await client.patch(
        f"/requests/{draft['id']}",
        headers={**(await app_headers(world.employee)), "Idempotency-Key": "pi-null-01"},
        json={"photos_incomplete": None, "expected_version": draft["version"]},
    )
    assert rejected.status_code == 422

    foreign = await client.patch(
        f"/requests/{draft['id']}",
        headers={**(await app_headers(world.other_employee)), "Idempotency-Key": "pi-foreign"},
        json={
            "photos_incomplete": True,
            "photos_incomplete_reason": "Чужая причина",
            "expected_version": draft["version"],
        },
    )
    assert foreign.status_code in (403, 404)

    unchanged = (
        await client.get(f"/requests/{draft['id']}", headers=await app_headers(world.employee))
    ).json()
    assert unchanged["photos_incomplete"] is False
    assert unchanged["photos_incomplete_reason"] is None


async def test_omitted_fields_untouched_and_flag_off_clears_reason(client: AsyncClient) -> None:
    world = await factories.build_world()
    headers = await app_headers(world.employee)
    draft = await _marketplace_draft(client, world, "pi-create-3")

    marked_response = await client.patch(
        f"/requests/{draft['id']}",
        headers={**headers, "Idempotency-Key": "pi-mark-01"},
        json={
            "photos_incomplete": True,
            "photos_incomplete_reason": "Нет времени, срочно",
            "expected_version": draft["version"],
        },
    )
    assert marked_response.status_code == 200, marked_response.text
    marked = marked_response.json()

    untouched = (
        await client.patch(
            f"/requests/{draft['id']}",
            headers={**headers, "Idempotency-Key": "pi-untouched"},
            json={"symptom_description": "Иней на стенке", "expected_version": marked["version"]},
        )
    ).json()
    assert untouched["photos_incomplete"] is True
    assert untouched["photos_incomplete_reason"] == "Нет времени, срочно"

    cleared = (
        await client.patch(
            f"/requests/{draft['id']}",
            headers={**headers, "Idempotency-Key": "pi-clear-01"},
            json={"photos_incomplete": False, "expected_version": untouched["version"]},
        )
    ).json()
    assert cleared["photos_incomplete"] is False
    assert cleared["photos_incomplete_reason"] is None
