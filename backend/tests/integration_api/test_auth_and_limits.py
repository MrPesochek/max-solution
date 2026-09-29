import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.integration_api import deps
from app.adapters.integration_api.rate_limit import TokenBucketLimiter
from app.infra.config import get_settings
from app.modules.integration import api as integration
from tests import factories
from tests.integration_api.conftest import bearer, provider_org

pytestmark = pytest.mark.asyncio


async def test_me_returns_organization_and_scopes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await provider_org(db_session)
    client_row, key = await factories.create_integration_client(
        db_session, org, name="CRM", scopes=["requests:read", "events:read"]
    )
    await db_session.commit()

    response = await client.get("/me", headers=bearer(key))

    assert response.status_code == 200
    body = response.json()
    assert body["organization_name"] == "ООО Сервис"
    assert body["organization_id"].startswith("org_")
    assert body["client_id"].startswith("ic_")
    assert body["client_name"] == "CRM"
    assert body["key_prefix"] == client_row.api_key_prefix
    assert body["scopes"] == ["events:read", "requests:read"]
    assert response.headers["RateLimit-Limit"]
    assert response.headers["RateLimit-Remaining"]


async def test_missing_header_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "API_KEY_INVALID"


@pytest.mark.parametrize("header", ["Basic abc", "Bearer ", "Bearer nonsense"])
async def test_bad_key_is_unauthenticated(client: AsyncClient, header: str) -> None:
    response = await client.get("/me", headers={"Authorization": header})
    assert response.status_code == 401


async def test_revoked_key_is_unauthenticated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org, status="revoked")
    await db_session.commit()

    response = await client.get("/me", headers=bearer(key))
    assert response.status_code == 401


@pytest.mark.parametrize("status", ["needs_information", "suspended"])
async def test_inactive_provider_profile_still_reads(
    client: AsyncClient, db_session: AsyncSession, status: str
) -> None:
    """ТЗ 6.5.3: CRM сверяет состояние и без допуска; изменения решает ядро."""
    org = await factories.create_organization(db_session, customer=False, provider=True)
    await factories.create_provider_profile(db_session, org, status=status)
    _, key = await factories.create_integration_client(
        db_session, org, scopes=("requests:read", "events:read")
    )
    await db_session.commit()

    assert (await client.get("/me", headers=bearer(key))).status_code == 200
    assert (await client.get("/events", headers=bearer(key))).status_code == 200


async def test_insufficient_scope_is_forbidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org, scopes=["requests:read"])
    await db_session.commit()

    response = await client.get("/events", headers=bearer(key))
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "INSUFFICIENT_SCOPE"
    assert body["details"]["required_scope"] == "events:read"


async def test_rate_limit_returns_429_with_headers(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    monkeypatch.setenv("INTEGRATION_RATE_LIMIT_BURST", "2")
    monkeypatch.setenv("INTEGRATION_RATE_LIMIT_RPS", "0.001")
    get_settings.cache_clear()
    deps.reset_limiter()

    assert (await client.get("/me", headers=bearer(key))).status_code == 200
    second = await client.get("/me", headers=bearer(key))
    assert second.status_code == 200
    assert second.headers["RateLimit-Remaining"] == "0"

    blocked = await client.get("/me", headers=bearer(key))
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["RateLimit-Limit"] == "2"
    assert blocked.headers["RateLimit-Remaining"] == "0"


async def test_rate_limit_is_per_key(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await provider_org(db_session)
    _, first = await factories.create_integration_client(db_session, org, name="CRM-1")
    _, second = await factories.create_integration_client(db_session, org, name="CRM-2")
    await db_session.commit()

    monkeypatch.setenv("INTEGRATION_RATE_LIMIT_BURST", "1")
    monkeypatch.setenv("INTEGRATION_RATE_LIMIT_RPS", "0.001")
    get_settings.cache_clear()
    deps.reset_limiter()

    assert (await client.get("/me", headers=bearer(first))).status_code == 200
    assert (await client.get("/me", headers=bearer(first))).status_code == 429
    assert (await client.get("/me", headers=bearer(second))).status_code == 200


async def test_openapi_is_served_separately(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/me" in schema["paths"]
    assert "/webhook-subscriptions" in schema["paths"]
    assert "/events" in schema["paths"]
    assert "/auth/max" not in schema["paths"]


async def test_failed_authentication_is_limited_by_ip(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L11: перебор ключей упирается в лимит неудачных попыток до проверки ключа."""
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_BURST", "2")
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_RPS", "0.001")
    get_settings.cache_clear()
    deps.reset_limiter()

    wrong = {"Authorization": "Bearer rk_test_abcdef123456_wrong-secret"}
    assert (await client.get("/me", headers=wrong)).status_code == 401
    assert (await client.get("/me", headers=wrong)).status_code == 401
    blocked = await client.get("/me", headers=wrong)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) > 0
    assert (await client.get("/me", headers=bearer(key))).status_code == 200


async def test_failed_authentication_has_a_higher_limit_per_ip(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Перебор с разными префиксами упирается в общий порог адреса."""
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_BURST", "2")
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_IP_BURST", "3")
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_IP_RPS", "0.001")
    get_settings.cache_clear()
    deps.reset_limiter()

    for prefix in ("aaaa1111", "bbbb2222", "cccc3333"):
        wrong = {"Authorization": f"Bearer rk_test_{prefix}_wrong-secret"}
        assert (await client.get("/me", headers=wrong)).status_code == 401
    blocked = await client.get(
        "/me", headers={"Authorization": "Bearer rk_test_dddd4444_wrong-secret"}
    )
    assert blocked.status_code == 429
    assert (await client.get("/me", headers=bearer(key))).status_code == 429


async def test_parallel_failures_do_not_bypass_the_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Токен списывается до обращения к БД: одновременные попытки не проскакивают."""
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_BURST", "2")
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_RPS", "0.001")
    get_settings.cache_clear()
    deps.reset_limiter()

    wrong = {"Authorization": "Bearer rk_test_abcdef123456_wrong-secret"}
    statuses = await asyncio.gather(*(client.get("/me", headers=wrong) for _ in range(6)))
    codes = sorted(r.status_code for r in statuses)
    assert codes == [401, 401, 429, 429, 429, 429]


async def test_limiter_forgets_old_buckets() -> None:
    limiter = TokenBucketLimiter(rate_per_second=1.0, burst=2, max_tracked=3)
    for index in range(10):
        limiter.check(f"ip-{index}", now=float(index))
    assert len(limiter) <= 3


async def test_successful_requests_do_not_consume_failure_budget(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()
    monkeypatch.setenv("INTEGRATION_AUTH_FAILURE_BURST", "1")
    get_settings.cache_clear()
    deps.reset_limiter()

    for _ in range(3):
        assert (await client.get("/me", headers=bearer(key))).status_code == 200


async def test_malformed_json_is_400(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    _, key = await factories.create_integration_client(db_session, org)
    await db_session.commit()

    response = await client.post(
        "/webhook-subscriptions",
        headers={
            **bearer(key),
            "Idempotency-Key": "test-key-json",
            "Content-Type": "application/json",
        },
        content=b'{"url": "https://crm.example.com/hooks",',
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"

    invalid = await client.post(
        "/webhook-subscriptions",
        headers={**bearer(key), "Idempotency-Key": "test-key-json2"},
        json={"url": 42, "events": "x"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(61, "Connection refused"),
        OperationalError("SELECT 1", {}, Exception("server closed the connection")),
    ],
)
async def test_database_unavailable_is_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def down(raw: str) -> None:
        raise error

    monkeypatch.setattr(integration, "authenticate_api_key", down)
    response = await client.get("/me", headers={"Authorization": "Bearer rk_test_abc_def"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.headers["Retry-After"]
