from typing import Any

import pytest

from app.modules.requests import api
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _publish(world: World, equipment_id: Any) -> dict[str, Any]:
    draft = await h.make_marketplace_draft(world, equipment_id=equipment_id)
    result = await api.publish_search(
        world.manager, h.rid(draft), expected_version=draft["version"]
    )
    return result.body


async def test_marketplace_pages_do_not_lose_cards(world: World) -> None:
    first = await _publish(world, world.equipment_id)
    second = await _publish(world, world.other_equipment_id)

    page, cursor = await api.list_marketplace_requests(world.dispatcher, limit=1)
    assert [item.request_id for item in page] == [second["id"]]
    assert cursor is not None
    rest, tail = await api.list_marketplace_requests(world.dispatcher, cursor=cursor, limit=1)
    assert [item.request_id for item in rest] == [first["id"]]
    assert tail is None


async def test_marketplace_single_page_has_no_cursor(world: World) -> None:
    await _publish(world, world.equipment_id)
    page, cursor = await api.list_marketplace_requests(world.dispatcher, limit=5)
    assert len(page) == 1
    assert cursor is None


async def test_customer_sees_provider_employee_name_only_after_acceptance(world: World) -> None:
    submitted = await h.make_submitted(world)
    request_id = h.rid(submitted)
    await api.post_message(
        world.dispatcher,
        request_id,
        body="Уточните модель",
        assignment_id=h.assignment_id(submitted),
    )
    messages, _ = await api.list_messages(world.manager, request_id)
    assert messages[-1].author_display_name is None
    assert messages[-1].author_organization_name == "Холод-Сервис"

    await api.accept_assignment(
        world.dispatcher,
        request_id,
        assignment_id=h.assignment_id(submitted),
        expected_version=(await api.get_request(world.manager, request_id)).version,
    )
    messages, _ = await api.list_messages(world.manager, request_id)
    assert messages[-1].author_display_name == "Диспетчер"
