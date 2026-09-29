from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.operator import cli
from app.core.actor import OperatorActor, SystemActor
from app.core.errors import DomainError, Forbidden, NotFound, Unauthenticated, ValidationFailed
from app.db import session as db_module
from app.db.models import AuditEntry, LoginLink, PlatformRole
from app.infra.config import Settings
from app.modules.identity import api as identity
from tests import factories

CLI = SystemActor(cli.CLI_ACTOR_NAME)


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Стенд проверки: демо-окружение с ботом (иначе ссылку негде погасить)."""
    yield from factories.apply_test_settings(
        monkeypatch,
        APP_ENV="demo",
        MAX_UPDATES_MODE="webhook",
        PUBLIC_BASE_URL="https://stand.test",
    )


def _token(url: str) -> str:
    return url.split("t=", 1)[1]


async def _audit(action: str) -> list[AuditEntry]:
    async with db_module.transaction() as s:
        rows = (await s.execute(select(AuditEntry))).scalars().all()
    return [row for row in rows if row.action == action]


async def test_issued_link_logs_demo_user_in(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    user = await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()

    parser = cli.build_parser()
    await cli.run(parser.parse_args(["issue-login-link", "--user-key", "employee"]))

    line = capsys.readouterr().out.strip()
    name, url = line.split("=", 1)
    assert name == "LOGIN_LINK_EMPLOYEE"
    assert url.startswith("https://stand.test/#/auth/link?t=")
    session = await identity.login_with_link(_token(url))
    assert session.issued.token

    [entry] = await _audit("login_link.issue_demo")
    assert entry.actor_kind == "system"
    assert entry.result == "success"
    assert entry.details["user_key"] == "employee"
    assert _token(url) not in str(entry.details)
    async with db_module.transaction() as s:
        link = (await s.execute(select(LoginLink))).scalar_one()
    assert link.user_id == user.id


async def test_ttl_is_configurable_within_a_week(db_session: AsyncSession) -> None:
    await factories.create_user(db_session, max_user_id="demo:provider_admin")
    await db_session.commit()

    issued = await identity.issue_demo_login_link(CLI, "provider_admin", ttl_seconds=24 * 3600)
    async with db_module.transaction() as s:
        link = (await s.execute(select(LoginLink))).scalar_one()
    assert abs((link.expires_at - issued.expires_at).total_seconds()) < 1
    lifetime = (link.expires_at - link.created_at).total_seconds()
    assert 24 * 3600 - 5 < lifetime <= 24 * 3600 + 5

    for ttl in (30, 8 * 24 * 3600):
        with pytest.raises(ValidationFailed):
            await identity.issue_demo_login_link(CLI, "provider_admin", ttl_seconds=ttl)


async def test_link_is_single_use(db_session: AsyncSession) -> None:
    await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()

    issued = await identity.issue_demo_login_link(CLI, "employee")
    await identity.login_with_link(_token(issued.url))
    with pytest.raises(Unauthenticated):
        await identity.login_with_link(_token(issued.url))


async def test_refused_on_prod_with_denied_audit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()

    for _ in factories.apply_test_settings(
        monkeypatch,
        APP_ENV="prod",
        MAX_UPDATES_MODE="webhook",
        MAX_WEBHOOK_SECRET="s" * 32,
        PUBLIC_BASE_URL="https://x.test",
    ):
        with pytest.raises(Forbidden) as exc:
            await identity.issue_demo_login_link(CLI, "employee")
    assert exc.value.code == "DEMO_ONLY"
    [denied] = await _audit("login_link.issue_demo")
    assert denied.result == "denied"
    assert denied.actor_kind == "system"
    async with db_module.transaction() as s:
        assert (await s.execute(select(LoginLink))).first() is None


@pytest.mark.parametrize("user_key", ["123456789", "demo:employee", "manager | employee", ""])
async def test_refuses_keys_outside_demo_seed(db_session: AsyncSession, user_key: str) -> None:
    await factories.create_user(db_session, max_user_id="123456789")
    await db_session.commit()

    with pytest.raises(Forbidden):
        await identity.issue_demo_login_link(CLI, user_key)
    async with db_module.transaction() as s:
        assert (await s.execute(select(LoginLink))).first() is None


async def test_refuses_demo_user_with_platform_role(db_session: AsyncSession) -> None:
    user = await factories.create_user(db_session, max_user_id="demo:operator")
    db_session.add(PlatformRole(user_id=user.id, role="operator"))
    await db_session.commit()

    with pytest.raises(Forbidden):
        await identity.issue_demo_login_link(CLI, "operator")


async def test_refuses_without_bot(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()

    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="demo", MAX_UPDATES_MODE="off"):
        with pytest.raises(Forbidden) as exc:
            await identity.issue_demo_login_link(CLI, "employee")
    assert exc.value.code == "LOGIN_LINKS_OFF"


async def test_only_cli_actor_may_issue(db_session: AsyncSession) -> None:
    user = await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()

    with pytest.raises(Forbidden):
        await identity.issue_demo_login_link(OperatorActor(user_id=user.id), "employee")


async def test_retry_after_missing_seed(db_session: AsyncSession) -> None:
    """Без сида — понятный отказ; после сида повтор той же команды выпускает ссылку."""
    with pytest.raises(NotFound):
        await identity.issue_demo_login_link(CLI, "employee")

    await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()
    issued = await identity.issue_demo_login_link(CLI, "employee")

    assert (await identity.login_with_link(_token(issued.url))).issued.token


async def test_cli_stops_on_refusal_without_printing_links(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await factories.create_user(db_session, max_user_id="demo:employee")
    await db_session.commit()
    args = ["issue-login-link", "--user-key", "not-a-demo-key", "--user-key", "employee"]

    with pytest.raises(DomainError):
        await cli.run(cli.build_parser().parse_args(args))

    assert "LOGIN_LINK_" not in capsys.readouterr().out
