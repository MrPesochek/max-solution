import asyncio
import copy
import importlib.util
import io
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.adapters.operator import cli
from app.db import session as db_session
from app.db.models import AuditEntry
from app.demo import seed
from app.infra.config import Settings
from app.main import create_app
from tests import factories
from tests.demo.conftest import CONNECTOR_API_KEY

pytestmark = pytest.mark.usefixtures("clean_db")

REPO_ROOT = Path(__file__).resolve().parents[3]
PASSPORT = REPO_ROOT / "DATA-API.yaml"
EXTENSION = REPO_ROOT / "DATA-API.extended.yaml"
SCRIPT = REPO_ROOT / "scripts" / "data-api-check.py"
BASE_URL = "http://testserver"
LINK_ROLES = ("employee", "outsider_manager", "provider_admin")
LOGIN_CHECKS = ("login-customer-employee", "login-customer-outsider", "login-provider-admin")


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_api_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


@pytest.fixture
def passport() -> Any:
    return checker.load_passport(PASSPORT)


@pytest.fixture
def link_stand(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Стенд проверки: демо-сид и бот, demo-вход выключен."""
    yield from factories.apply_test_settings(
        monkeypatch, APP_ENV="demo", MAX_UPDATES_MODE="webhook", DEMO_LOGIN_ENABLED="false"
    )


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url=BASE_URL) as http:
        yield http


def _bridge(client: AsyncClient, loop: asyncio.AbstractEventLoop) -> Any:
    def send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> Any:
        future = asyncio.run_coroutine_threadsafe(
            client.request(method, url, headers=headers, content=body), loop
        )
        reply = future.result(timeout=30)
        return checker.Response(reply.status_code, dict(reply.headers), reply.content)

    return send


async def _run(
    client: AsyncClient,
    passport: Any,
    *,
    access: str = "demo",
    suite: str = "full",
    env: dict[str, str] | None = None,
) -> Any:
    runner = checker.Runner(
        passport,
        base_url=BASE_URL,
        access=access,
        suite=suite,
        transport=_bridge(client, asyncio.get_running_loop()),
        env=env or {},
        sleep=lambda _: None,
    )
    await asyncio.to_thread(runner.run)
    return runner


def _outcomes(runner: Any) -> dict[str, str]:
    return {r.check_id: r.outcome for r in runner.results}


def _report(runner: Any) -> str:
    out = io.StringIO()
    checker.print_report(runner, out)
    return out.getvalue()


def _check(passport: Any, check_id: str) -> dict[str, Any]:
    return next(c for c in passport.checks if c["id"] == check_id)


def test_passport_matches_openapi(passport: Any) -> None:
    assert checker.validate_passport(passport) == []


def test_extension_is_loaded_from_either_file(passport: Any) -> None:
    via_extension = checker.load_passport(EXTENSION)
    assert via_extension.doc == passport.doc
    assert via_extension.ext == passport.ext
    assert passport.ext["extends"] == "DATA-API.yaml"


def test_passport_without_expected_version_is_rejected(passport: Any) -> None:
    """Прежний дефект паспорта: submit без expected_version получал 422."""
    del _check(passport, "submit-to-own-service")["request"]["body"]["expected_version"]
    problems = checker.validate_passport(passport)
    assert any("expected_version" in p and "submit-to-own-service" in p for p in problems)


def test_validation_catches_unknown_variable_and_field(passport: Any) -> None:
    broken = copy.deepcopy(passport)
    _check(broken, "crm-me")["request"]["headers"]["Authorization"] = "Bearer ${nope}"
    _check(broken, "me")["expected"]["requiredFields"].append("no_such_field")
    problems = checker.validate_passport(broken)
    assert any("${nope}" in p for p in problems)
    assert any("no_such_field" in p for p in problems)


def test_every_check_has_role_access_and_expectations(passport: Any) -> None:
    roles = passport.roles
    for check in passport.checks:
        role = roles[check["role"]]
        assert role["access"] in {"none", "session", "integration_key"}, check["id"]
        if role["access"] == "session":
            assert role["user_key"] in seed.DEMO_USER_KEYS
            assert role["login"] in LOGIN_CHECKS
            assert (
                _check(passport, role["login"])["request"]["body"]["user_key"] == role["user_key"]
            )
        assert check["expected"]["statusCodes"], check["id"]
        if check["expected"]["statusCodes"][0] < 300 and check["method"] != "GET":
            assert check["expected"].get("requiredFields"), check["id"]
        if check["method"] != "GET":
            assert "repeatable" in check, check["id"]
        authorization = (check.get("request") or {}).get("headers", {}).get("Authorization")
        assert authorization is None or "${" in authorization, check["id"]


async def test_full_suite_passes_with_demo_login(client: AsyncClient, passport: Any) -> None:
    await seed.run()

    runner = await _run(client, passport)

    outcomes = _outcomes(runner)
    assert set(outcomes.values()) == {"PASS"}, _report(runner)
    assert {*LOGIN_CHECKS, "crm-accept", "cleanup:revoke-check-key"} <= set(outcomes)


async def test_report_hides_session_and_integration_key(client: AsyncClient, passport: Any) -> None:
    await seed.run()
    runner = await _run(client, passport)

    report = _report(runner) + str(checker.json_report(runner))

    for name in passport.secret_names():
        if name in runner.ctx.vars:
            assert runner.ctx.vars[name] not in report, name
    assert runner.ctx.vars["integrationApiKey"] not in report
    assert runner.ctx.vars["customerToken"] not in report


async def test_rerun_on_same_stand_passes(client: AsyncClient, passport: Any) -> None:
    """Повторный прогон: новая заявка и новый ключ, данные прошлого прогона не мешают
    (Idempotency-Key помечен уникальной для прогона меткой ${runMarker})."""
    await seed.run()
    first = await _run(client, passport)
    second = await _run(client, passport)

    assert set(_outcomes(first).values()) == {"PASS"}, _report(first)
    assert set(_outcomes(second).values()) == {"PASS"}, _report(second)
    assert first.ctx.vars["requestId"] != second.ctx.vars["requestId"]


async def test_failed_step_skips_dependents(client: AsyncClient, passport: Any) -> None:
    """Без сида нет демо-пользователей: дальше по цепочке — SKIP, а не ложный PASS."""
    runner = await _run(client, passport)

    outcomes = _outcomes(runner)
    assert outcomes["health"] == "PASS"
    assert outcomes["app-auth-required"] == "PASS"
    assert outcomes["login-customer-employee"] == "FAIL"
    assert outcomes["request-create"] == "SKIP"
    assert outcomes["crm-accept"] == "SKIP"
    assert "cleanup:revoke-check-key" not in outcomes


async def test_crm_suite_with_pre_issued_key(client: AsyncClient, passport: Any) -> None:
    """Боевой вариант: только API CRM, ключ выдан заранее (INTEGRATION_API_KEY)."""
    await seed.run()
    full = await _run(client, passport)
    assert set(_outcomes(full).values()) == {"PASS"}
    runner = await _run(
        client, passport, suite="crm", env={"INTEGRATION_API_KEY": CONNECTOR_API_KEY}
    )

    outcomes = _outcomes(runner)
    assert set(outcomes.values()) == {"PASS"}, _report(runner)
    assert not any(key.startswith("login-") for key in outcomes)
    assert "crm-issue-key" not in outcomes


async def test_crm_suite_without_key_fails(client: AsyncClient, passport: Any) -> None:
    await seed.run()

    runner = await _run(client, passport, suite="crm")

    assert _outcomes(runner)["crm-me"] == "SKIP"


async def test_full_suite_passes_with_cli_login_links(
    link_stand: Settings, passport: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Стенд проверки без demo-входа: ссылки ролей выпущены CLI оператора."""
    await seed.run()
    args = ["issue-login-link", "--ttl-minutes", "60"]
    for key in LINK_ROLES:
        args += ["--user-key", key]
    await cli.run(cli.build_parser().parse_args(args))
    lines = capsys.readouterr().out.splitlines()
    env = dict(line.split("=", 1) for line in lines if line.startswith("LOGIN_LINK_"))
    assert set(env) == {cli.login_link_env_name(key) for key in LINK_ROLES}

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url=BASE_URL) as http:
        assert (
            await http.post("/app-api/v1/auth/demo", json={"user_key": "employee"})
        ).status_code == 404
        runner = await _run(http, passport, access="link", env=env)
        assert set(_outcomes(runner).values()) == {"PASS"}, _report(runner)
        assert all(
            r.request.startswith("POST /app-api/v1/auth/link")
            for r in runner.results
            if r.check_id in LOGIN_CHECKS
        )

        again = await _run(http, passport, access="link", env=env)
    assert _outcomes(again)["login-customer-employee"] == "FAIL"
    assert _outcomes(again)["request-create"] == "SKIP"

    async with db_session.transaction() as s:
        actions = [
            (row.action, row.actor_kind, row.result)
            for row in (await s.execute(select(AuditEntry))).scalars()
            if row.object_type == "login_link"
        ]
    issued = [a for a in actions if a[0] == "login_link.issue_demo"]
    assert len(issued) == len(LINK_ROLES)
    assert all(kind == "system" and result == "success" for _, kind, result in issued)
    assert ("login_link.redeem", "user", "success") in actions


async def test_link_access_without_links_skips_roles(link_stand: Settings, passport: Any) -> None:
    await seed.run()
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url=BASE_URL) as http:
        runner = await _run(http, passport, access="link")

    outcomes = _outcomes(runner)
    assert outcomes["health"] == "PASS"
    assert outcomes["login-customer-employee"] == "SKIP"
    assert outcomes["submit-to-own-service"] == "SKIP"
