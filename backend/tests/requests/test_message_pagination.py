from typing import Any

import pytest

from app.core.errors import NotFound
from app.modules.requests import api
from tests.requests import factories
from tests.requests import helpers as h
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def conversation(world: World, count: int) -> dict[str, Any]:
    accepted = await h.make_accepted(world)
    for n in range(count):
        await api.post_message(world.employee, h.rid(accepted), body=f"Сообщение {n}")
    return accepted


async def test_backward_pages_start_from_newest(world: World) -> None:
    accepted = await conversation(world, 5)
    request_id = h.rid(accepted)

    newest, older = await api.list_messages(
        world.manager, request_id, limit=2, direction="backward"
    )
    assert [m.body for m in newest] == ["Сообщение 3", "Сообщение 4"]
    assert older is not None

    middle, older = await api.list_messages(
        world.manager, request_id, cursor=older, limit=2, direction="backward"
    )
    assert [m.body for m in middle] == ["Сообщение 1", "Сообщение 2"]
    assert older is not None

    oldest, older = await api.list_messages(
        world.manager, request_id, cursor=older, limit=2, direction="backward"
    )
    assert [m.body for m in oldest] == ["Сообщение 0"]
    assert older is None


async def test_forward_order_is_unchanged(world: World) -> None:
    accepted = await conversation(world, 3)
    first, cursor = await api.list_messages(world.manager, h.rid(accepted), limit=2)
    assert [m.body for m in first] == ["Сообщение 0", "Сообщение 1"]
    rest, cursor = await api.list_messages(world.manager, h.rid(accepted), cursor=cursor, limit=2)
    assert [m.body for m in rest] == ["Сообщение 2"]
    assert cursor is None


async def test_backward_keeps_channel_visibility(world: World) -> None:
    accepted = await conversation(world, 2)
    rival = await factories.build_rival_provider(world)
    with pytest.raises(NotFound):
        await api.list_messages(rival.dispatcher, h.rid(accepted), direction="backward")
