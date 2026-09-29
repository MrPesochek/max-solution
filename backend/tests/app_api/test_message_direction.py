import pytest
from httpx import AsyncClient

from tests.app_api.test_requests_flow import app_headers
from tests.requests import factories
from tests.requests.test_message_pagination import conversation

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_db")]


async def test_direction_over_http(client: AsyncClient) -> None:
    world = await factories.build_world()
    accepted = await conversation(world, 3)
    headers = await app_headers(world.manager)
    url = f"/requests/{accepted['id']}/messages"

    page = await client.get(url, headers=headers, params={"direction": "backward", "limit": 1})
    assert page.status_code == 200, page.text
    body = page.json()
    assert [m["body"] for m in body["items"]] == ["Сообщение 2"]
    assert body["next_cursor"] is not None

    wrong = await client.get(url, headers=headers, params={"direction": "sideways"})
    assert wrong.status_code == 422
