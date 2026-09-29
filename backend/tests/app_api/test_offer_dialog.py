import pytest
from httpx import AsyncClient

from app.modules.requests import api
from tests.app_api.test_requests_flow import app_headers
from tests.requests import factories, helpers

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_db")]


async def test_offer_dialog_over_http(client: AsyncClient) -> None:
    world = await factories.build_world()
    rival = await factories.build_rival_provider(world)
    published = await helpers.make_published(world)
    request_id = published["id"]
    offer = (
        await api.submit_offer(
            world.dispatcher, helpers.rid(published), data=api.OfferInput(amount_minor=100000)
        )
    ).body
    dispatcher = await app_headers(world.dispatcher)

    asked = await client.post(
        f"/marketplace/requests/{request_id}/messages",
        headers={**dispatcher, "Idempotency-Key": "dialog-q-1"},
        json={"body": "Какой этаж?"},
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["thread_provider_id"] == offer["provider_organization_id"]

    listing = (await client.get("/marketplace/requests", headers=dispatcher)).json()["items"]
    assert listing[0]["has_open_question"] is True
    assert listing[0]["offers_count"] == 1

    employee = await app_headers(world.employee)
    pending = (await client.get("/requests/pending-approvals", headers=employee)).json()
    assert [(item["kind"], item["thread_provider_id"]) for item in pending] == [
        ("question", offer["provider_organization_id"])
    ]

    thread = await client.get(
        f"/requests/{request_id}/offers/{offer['id']}/messages", headers=employee
    )
    assert thread.status_code == 200
    assert [m["body"] for m in thread.json()["items"]] == ["Какой этаж?"]

    answered = await client.post(
        f"/requests/{request_id}/offers/{offer['id']}/messages",
        headers={**employee, "Idempotency-Key": "dialog-a-1"},
        json={"body": "Третий, есть лифт"},
    )
    assert answered.status_code == 201, answered.text

    mine = await client.get(f"/marketplace/requests/{request_id}/messages", headers=dispatcher)
    assert [m["body"] for m in mine.json()["items"]] == ["Какой этаж?", "Третий, есть лифт"]

    foreign = await client.get(
        f"/marketplace/requests/{request_id}/messages", headers=await app_headers(rival.dispatcher)
    )
    assert foreign.status_code == 200
    assert foreign.json()["items"] == []

    other_employee = await app_headers(world.other_employee)
    hidden = await client.get(
        f"/requests/{request_id}/offers/{offer['id']}/messages", headers=other_employee
    )
    assert hidden.status_code == 404
