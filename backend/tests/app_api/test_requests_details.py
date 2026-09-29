from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.requests import api
from tests.requests import factories, helpers
from tests.support import org_id, session_token

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_db")]


async def app_headers(actor: Any) -> dict[str, str]:
    token = await session_token(actor)
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": org_id(actor)}


async def test_update_details_route(client: AsyncClient) -> None:
    world = await factories.build_world()
    submitted = await helpers.make_submitted(world)
    declined = (
        await api.decline_assignment(
            world.dispatcher,
            helpers.rid(submitted),
            assignment_id=helpers.assignment_id(submitted),
            reason="Нет мастера",
        )
    ).body
    manager_headers = await app_headers(world.manager)
    employee_headers = await app_headers(world.employee)
    path = f"/requests/{submitted['id']}/actions/update-details"

    forbidden = await client.post(
        path,
        headers={**employee_headers, "Idempotency-Key": "details-employee"},
        json={"urgency": "critical", "expected_version": declined["version"]},
    )
    assert forbidden.status_code == 403

    stale = await client.post(
        path,
        headers={**manager_headers, "Idempotency-Key": "details-stale"},
        json={"urgency": "critical", "expected_version": declined["version"] - 1},
    )
    assert stale.status_code == 409

    updated = await client.post(
        path,
        headers={**manager_headers, "Idempotency-Key": "details-ok"},
        json={
            "urgency": "critical",
            "symptom_description": "Шкаф не морозит",
            "expected_version": declined["version"],
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["urgency"] == "critical"
    assert body["symptom_description"] == "Шкаф не морозит"
    assert body["version"] == declined["version"] + 1

    history = await client.get(f"/requests/{submitted['id']}/history", headers=manager_headers)
    assert history.json()["items"][-1]["event_type"] == "RequestDetailsUpdated"


async def test_messages_read_route(client: AsyncClient) -> None:
    world = await factories.build_world()
    submitted = await helpers.make_submitted(world)
    await api.post_message(
        world.dispatcher,
        helpers.rid(submitted),
        body="Будем завтра",
        assignment_id=helpers.assignment_id(submitted),
    )
    headers = await app_headers(world.manager)

    card = (await client.get(f"/requests/{submitted['id']}", headers=headers)).json()
    assert card["unread_messages_count"] == 1
    listing = (await client.get("/requests", headers=headers)).json()["items"]
    assert listing[0]["equipment_id"] == card["equipment"]["id"]

    marked = await client.post(f"/requests/{submitted['id']}/messages/read", headers=headers)
    assert marked.status_code == 200, marked.text
    assert marked.json()["unread_messages_count"] == 0
    assert marked.json()["last_read_message_id"] is not None
    card = (await client.get(f"/requests/{submitted['id']}", headers=headers)).json()
    assert card["unread_messages_count"] == 0
