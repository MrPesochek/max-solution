from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.clock import utcnow
from app.db import session as db_session
from app.infra.config import Settings, get_settings
from app.main import create_app
from tests import factories
from tests.app_api.conftest import BASE_URL, auth

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_login_returns_session_and_memberships(client: AsyncClient) -> None:
    response = await client.post("/auth/max", json={"init_data": factories.sign_init_data(1001)})
    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["user"]["id"].startswith("usr_")
    assert body["memberships"] == []

    me = await client.get("/me", headers=auth(body["token"]))
    assert me.status_code == 200
    assert me.json()["user"]["id"] == body["user"]["id"]
    assert me.json()["memberships"] == []
    assert me.json()["organizations"] == []
    assert body["organizations"] == []


async def test_forged_init_data_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/max", json={"init_data": factories.sign_init_data(1002, signature="0" * 64)}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INIT_DATA_INVALID"


async def test_stale_init_data_is_rejected(client: AsyncClient, settings: Settings) -> None:
    stale = utcnow() - timedelta(seconds=settings.init_data_max_age_seconds + 120)
    response = await client.post(
        "/auth/max", json={"init_data": factories.sign_init_data(1003, auth_date=stale)}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INIT_DATA_INVALID"


async def test_request_without_token_is_unauthenticated(client: AsyncClient) -> None:
    assert (await client.get("/me")).status_code == 401
    assert (await client.get("/locations")).status_code == 401
    assert (
        await client.get("/me", headers={"Authorization": "Bearer no-such-token"})
    ).status_code == 401


async def test_logout_ends_session(client: AsyncClient) -> None:
    token = (
        await client.post("/auth/max", json={"init_data": factories.sign_init_data(1004)})
    ).json()["token"]

    assert (await client.post("/auth/logout", headers=auth(token))).status_code == 204
    assert (await client.get("/me", headers=auth(token))).status_code == 401


async def test_demo_login_available_outside_production(client: AsyncClient) -> None:
    response = await client.post("/auth/demo", json={"user_key": "manager"})
    assert response.status_code == 200
    assert response.json()["token"]


async def test_demo_login_is_absent_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    try:
        prod_app: FastAPI = create_app()
        paths = prod_app.openapi()["paths"]
        assert "/app-api/v1/auth/demo" not in paths
        assert "/app-api/v1/auth/max" in paths
        assert prod_app.docs_url is None

        async with AsyncClient(transport=ASGITransport(app=prod_app), base_url=BASE_URL) as http:
            assert (await http.post("/auth/demo", json={"user_key": "x"})).status_code == 404
    finally:
        get_settings.cache_clear()


async def test_openapi_is_published_under_api_prefix(client: AsyncClient) -> None:
    response = await client.get("http://testserver/app-api/v1/openapi.json")
    assert response.status_code == 200
    assert "/app-api/v1/organizations" in response.json()["paths"]


async def test_healthz_and_readyz(client: AsyncClient) -> None:
    assert (await client.get("http://testserver/healthz")).status_code == 200
    assert (await client.get("http://testserver/readyz")).status_code == 200


async def test_demo_login_is_absent_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="demo", DEMO_LOGIN_ENABLED="false"):
        demo_app: FastAPI = create_app()
        assert "/app-api/v1/auth/demo" not in demo_app.openapi()["paths"]


async def test_login_attempts_are_limited_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in factories.apply_test_settings(monkeypatch, AUTH_RATE_LIMIT_ATTEMPTS="3"):
        limited_app: FastAPI = create_app()
        async with AsyncClient(transport=ASGITransport(app=limited_app), base_url=BASE_URL) as http:
            codes = [
                (await http.post("/auth/max", json={"init_data": "hash=0"})).status_code
                for _ in range(4)
            ]
        assert codes == [401, 401, 401, 429]


async def test_me_lists_membership_sides_and_organization_kinds(client: AsyncClient) -> None:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, name="Обе роли", provider=True)
        user = await factories.create_user(s, max_user_id="me-dual")
        await factories.create_membership(s, user, org, role="customer_manager")
        await factories.create_membership(s, user, org, role="provider_dispatcher")
        token = await factories.create_session_token(s, user)

    body = (await client.get("/me", headers=auth(token))).json()
    assert {(m["role"], m["side"]) for m in body["memberships"]} == {
        ("customer_manager", "customer"),
        ("provider_dispatcher", "provider"),
    }
    assert [o["kinds"] for o in body["organizations"]] == [["customer", "provider"]]
