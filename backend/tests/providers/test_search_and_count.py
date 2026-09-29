import pytest
from httpx import AsyncClient

from app.adapters.http.ratelimit import PROVIDER_SEARCH_LIMIT
from app.core import ids
from tests.providers.conftest import auth
from tests.support import (
    OTHER_INN,
    PROVIDER_INN,
    make_customer,
    make_provider,
    org_id,
    session_token,
)

pytestmark = pytest.mark.usefixtures("clean_db")


async def _headers() -> dict[str, str]:
    customer = await make_customer("search-c")
    return auth(await session_token(customer.manager), org_id(customer.manager))


async def test_search_by_name_prefix_and_exact_inn(client: AsyncClient) -> None:
    active = await make_provider(
        "search-a", name="ХолодСервис", status="active", accepting=True, inn=PROVIDER_INN
    )
    await make_provider("search-b", name="Другой Мастер", status="active", inn=OTHER_INN)
    headers = await _headers()
    expected = [ids.encode("organization", active.organization_id)]

    by_name = await client.get("/providers", params={"q": "холод"}, headers=headers)
    assert by_name.status_code == 200, by_name.text
    assert [i["id"] for i in by_name.json()["items"]] == expected

    by_inn = await client.get("/providers", params={"q": PROVIDER_INN}, headers=headers)
    assert [i["id"] for i in by_inn.json()["items"]] == expected

    partial = await client.get("/providers", params={"q": PROVIDER_INN[:6]}, headers=headers)
    assert partial.status_code == 200
    assert partial.json()["items"] == []

    short = await client.get("/providers", params={"q": "хо"}, headers=headers)
    assert short.status_code == 422

    wildcard = await client.get("/providers", params={"q": "%%%"}, headers=headers)
    assert wildcard.status_code == 200
    assert wildcard.json()["items"] == []


async def test_search_skips_inactive_profiles(client: AsyncClient) -> None:
    await make_provider("search-d", name="ХолодСервис", status="draft", inn=PROVIDER_INN)
    await make_provider("search-r", name="Холодок", status="rejected", inn=OTHER_INN)
    headers = await _headers()
    found = await client.get("/providers", params={"q": "Холод"}, headers=headers)
    assert found.json()["items"] == []
    by_inn = await client.get("/providers", params={"q": PROVIDER_INN}, headers=headers)
    assert by_inn.json()["items"] == []


async def test_search_needs_session_and_is_rate_limited(client: AsyncClient) -> None:
    unauthorized = await client.get("/providers", params={"q": "холод"})
    assert unauthorized.status_code == 401
    headers = await _headers()
    for _ in range(PROVIDER_SEARCH_LIMIT):
        ok = await client.get("/providers", params={"q": "холод"}, headers=headers)
        assert ok.status_code == 200
    limited = await client.get("/providers", params={"q": "холод"}, headers=headers)
    assert limited.status_code == 429
    plain = await client.get("/providers", headers=headers)
    assert plain.status_code == 200


async def test_count_only_active_and_accepting(client: AsyncClient) -> None:
    await make_provider("count-a", status="active", accepting=True, inn=PROVIDER_INN)
    await make_provider("count-b", status="active", accepting=False, inn=OTHER_INN)
    await make_provider("count-c", status="draft", accepting=True, inn=None)
    headers = await _headers()
    counted = await client.get("/providers/count", headers=headers)
    assert counted.status_code == 200, counted.text
    assert counted.json() == {"count": 1}
    assert (await client.get("/providers/count")).status_code == 401
