from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import Settings
from app.main import create_app
from app.modules.identity import api as identity
from tests import factories
from tests.app_api.conftest import BASE_URL, auth

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(monkeypatch, MAX_UPDATES_MODE="webhook")


async def _token(db: AsyncSession, target: str | None = None, max_user_id: str = "5501") -> str:
    user = await factories.create_user(db, max_user_id=max_user_id, display_name="Мария")
    org = await factories.create_organization(db, name="ООО Ромашка")
    await factories.create_membership(db, user, org, role="customer_manager")
    await db.commit()
    url = (await identity.issue_login_link(max_user_id, target)).url
    return url.partition("#/auth/link?t=")[2]


async def test_link_login_returns_session_memberships_and_target(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _token(db_session, "req_req_0000000000000000000001")

    response = await client.post("/auth/link", json={"token": token})

    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "req_req_0000000000000000000001"
    assert body["user"]["display_name"] == "Мария"
    assert [m["role"] for m in body["memberships"]] == ["customer_manager"]
    assert body["organizations"][0]["name"] == "ООО Ромашка"
    me = await client.get("/me", headers=auth(body["token"]))
    assert me.status_code == 200


async def test_used_and_unknown_links_get_same_neutral_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _token(db_session)
    assert (await client.post("/auth/link", json={"token": token})).status_code == 200

    repeated = await client.post("/auth/link", json={"token": token})
    unknown = await client.post("/auth/link", json={"token": "x" * 43})

    for response in (repeated, unknown):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "LOGIN_LINK_INVALID"
    assert repeated.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_link_login_is_rejected_when_bot_is_off(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    token = await _token(db_session)
    for _ in factories.apply_test_settings(monkeypatch, MAX_UPDATES_MODE="off"):
        app: FastAPI = create_app()
        assert "/app-api/v1/auth/link" in app.openapi()["paths"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as http:
            response = await http.post("/auth/link", json={"token": token})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "LOGIN_LINK_INVALID"


async def test_link_login_exists_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in factories.apply_test_settings(
        monkeypatch, APP_ENV="prod", MAX_WEBHOOK_SECRET="secret-1234", DEMO_LOGIN_ENABLED="false"
    ):
        paths = create_app().openapi()["paths"]
        assert "/app-api/v1/auth/link" in paths
        assert "/app-api/v1/auth/demo" not in paths


async def test_link_login_attempts_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in factories.apply_test_settings(
        monkeypatch, MAX_UPDATES_MODE="webhook", AUTH_RATE_LIMIT_ATTEMPTS="3"
    ):
        app: FastAPI = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as http:
            codes = [
                (await http.post("/auth/link", json={"token": "guess"})).status_code
                for _ in range(4)
            ]
        assert codes == [401, 401, 401, 429]


async def test_token_is_not_logged_by_http_layer(
    client: AsyncClient, db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    token = await _token(db_session)
    capsys.readouterr()
    assert (await client.post("/auth/link", json={"token": token})).status_code == 200
    assert (await client.post("/auth/link", json={"token": token})).status_code == 401

    output = capsys.readouterr().out
    assert '"path": "/app-api/v1/auth/link"' in output
    assert "login_link_rejected" in output
    assert token not in output
