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


async def _card(client: AsyncClient, request_id: str, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get(f"/requests/{request_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _offer(
    client: AsyncClient, request_id: str, headers: dict[str, str], key: str, amount: int
) -> dict[str, Any]:
    response = await client.post(
        f"/marketplace/requests/{request_id}/offers",
        headers={**headers, "Idempotency-Key": key},
        json={"amount_minor": amount, "currency": "RUB", "scope_description": "Ремонт на месте"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_s2_card_shows_offers_and_selection(client: AsyncClient) -> None:
    world = await factories.build_world(binding_status=None)
    rival = await factories.build_rival_provider(world)
    manager = await app_headers(world.manager)

    draft = (
        await client.post(
            "/requests",
            headers={**manager, "Idempotency-Key": "s2-draft-01"},
            json={
                "equipment_id": ids.encode("equipment", world.equipment_id),
                "route": "marketplace",
            },
        )
    ).json()
    assert (await _card(client, draft["id"], manager))["search"] is None

    published = await client.post(
        f"/requests/{draft['id']}/actions/publish-search",
        headers={**manager, "Idempotency-Key": "s2-publish-01"},
        json={"expected_version": draft["version"], "published_description": "Не греет"},
    )
    assert published.status_code == 200, published.text
    matched = published.json()["search"]["matched_providers"]
    assert matched >= 2

    card = await _card(client, draft["id"], manager)
    assert card["status"] == "searching"
    search = card["search"]
    assert search["published"] is True
    assert search["matched_providers"] == matched
    assert search["search_expires_at"] is not None
    assert search["public_card"]["published_description"] == "Не греет"
    assert search["public_card"]["published_at"] is not None
    assert search["public_card"]["status"] == "open"
    assert "address" not in search["public_card"]

    own = await app_headers(world.dispatcher)
    other = await app_headers(rival.dispatcher)
    first = await _offer(client, draft["id"], own, "s2-offer-01", 90000)
    second = await _offer(client, draft["id"], other, "s2-offer-02", 80000)

    offers = await client.get(f"/requests/{draft['id']}/offers", headers=manager)
    assert offers.status_code == 200, offers.text
    assert {o["id"] for o in offers.json()} == {first["id"], second["id"]}

    current = await _card(client, draft["id"], manager)
    assert current["search"]["published"] is True
    assert current["search"]["matched_providers"] == matched

    selected = await client.post(
        f"/requests/{draft['id']}/actions/select-offer",
        headers={**manager, "Idempotency-Key": "s2-select-01"},
        json={
            "offer_id": second["id"],
            "offer_version": second["version"],
            "expected_version": current["version"],
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["search"]["published"] is True

    waiting = await _card(client, draft["id"], manager)
    assert waiting["status"] == "awaiting_assignment_confirmation"
    assert waiting["search"]["published"] is True
    assert waiting["search"]["matched_providers"] == matched

    confirmed = await client.post(
        f"/requests/{draft['id']}/actions/accept",
        headers={**(await app_headers(rival.dispatcher)), "Idempotency-Key": "s2-accept-01"},
        json={
            "assignment_id": selected.json()["assignment"]["id"],
            "expected_version": selected.json()["version"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    after = await _card(client, draft["id"], manager)
    assert after["status"] in ("accepted", "scheduled")
    assert after["search"]["published"] is False
    assert after["search"]["search_expires_at"] is None
    assert after["search"]["public_card"]["published_attachment_ids"] == []


async def test_card_search_after_no_providers(client: AsyncClient) -> None:
    empty_world = await helpers.build_world_without_providers()
    manager = await app_headers(empty_world.manager)
    draft = await helpers.make_marketplace_draft(empty_world)
    response = await client.post(
        f"/requests/{draft['id']}/actions/publish-search",
        headers={**manager, "Idempotency-Key": "s5-publish-01"},
        json={"expected_version": draft["version"], "published_description": "Течёт"},
    )
    assert response.status_code == 200, response.text

    card = await _card(client, draft["id"], manager)
    assert card["status"] == "action_required"
    assert card["search"]["published"] is False
    assert card["search"]["matched_providers"] == 0
    assert card["search"]["public_card"]["published_description"] == "Течёт"


async def test_provider_view_and_foreign_org_get_no_search(client: AsyncClient) -> None:
    world = await factories.build_world(binding_status=None)
    other = await factories.build_world()
    published = await helpers.make_published(world)

    foreign = await client.get(
        f"/requests/{published['id']}", headers=await app_headers(other.manager)
    )
    assert foreign.status_code == 404

    provider = await client.get(
        f"/requests/{published['id']}", headers=await app_headers(world.dispatcher)
    )
    assert provider.status_code in (403, 404)
    assert "search" not in provider.text or provider.json().get("search") is None
