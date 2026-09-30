import pytest
from sqlalchemy import select

from app.core.actor import OperatorActor
from app.core.clock import utcnow
from app.core.errors import Forbidden, Unauthenticated
from app.db import session as db_session
from app.db.models import PlatformRole, User
from app.modules.identity import api as identity
from app.modules.identity import platform
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def _make_operator(max_user_id: str) -> User:
    async with db_session.transaction() as s:
        user = User(max_user_id=max_user_id, display_name="Оператор")
        s.add(user)
        await s.flush()
        s.add(PlatformRole(user_id=user.id, role="operator", granted_at=utcnow()))
    return user


async def _active_role(max_user_id: str) -> bool:
    async with db_session.transaction() as s:
        row = (
            await s.execute(
                select(PlatformRole.id)
                .join(User, User.id == PlatformRole.user_id)
                .where(User.max_user_id == max_user_id, PlatformRole.revoked_at.is_(None))
            )
        ).scalar_one_or_none()
    return row is not None


@pytest.mark.parametrize("user_key", ["alice", "123456", "demo:manager", "", "   "])
async def test_demo_login_accepts_only_seed_keys(user_key: str) -> None:
    with pytest.raises(Unauthenticated):
        await identity.login_demo(user_key)
    async with db_session.transaction() as s:
        assert (await s.execute(select(User))).first() is None


async def test_operator_demo_login_on_local_stand(monkeypatch: pytest.MonkeyPatch) -> None:
    await _make_operator("demo:operator")
    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="local", MAX_BOT_TOKEN=""):
        issued = await identity.login_demo("operator")
        assert issued.token


@pytest.mark.parametrize("app_env", ["demo", "test"])
async def test_operator_demo_login_refused_outside_local(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    await _make_operator("demo:operator")
    for _ in factories.apply_test_settings(monkeypatch, APP_ENV=app_env):
        with pytest.raises(Unauthenticated):
            await identity.login_demo("operator")
        assert (await identity.login_demo("manager")).token


async def test_operator_demo_login_refused_on_local_with_real_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _make_operator("demo:operator")
    for _ in factories.apply_test_settings(
        monkeypatch,
        APP_ENV="local",
        MAX_UPDATES_MODE="polling",
        DEMO_LOGIN_ENABLED="true",
        DEMO_LOGIN_WITH_REAL_BOT="true",
    ):
        with pytest.raises(Unauthenticated):
            await identity.login_demo("operator")


async def test_any_platform_role_blocks_demo_login_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _make_operator("demo:manager")
    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="demo"):
        with pytest.raises(Unauthenticated):
            await identity.login_demo("manager")


async def test_demo_operator_cannot_grant_role_to_real_max_account() -> None:
    demo_operator = await _make_operator("demo:operator")
    actor = OperatorActor(user_id=demo_operator.id)

    with pytest.raises(Forbidden):
        await platform.grant_operator(actor, "987654321", idem=None)
    assert await _active_role("987654321") is False

    await platform.grant_operator(actor, "demo:manager", idem=None)
    assert await _active_role("demo:manager") is True


async def test_demo_operator_cannot_revoke_real_operator() -> None:
    demo_operator = await _make_operator("demo:operator")
    await _make_operator("555")

    with pytest.raises(Forbidden):
        await platform.revoke_operator(OperatorActor(user_id=demo_operator.id), "555", idem=None)
    assert await _active_role("555") is True


async def test_real_operator_still_grants_roles() -> None:
    real = await _make_operator("555")
    await platform.grant_operator(OperatorActor(user_id=real.id), "987654321", idem=None)
    assert await _active_role("987654321") is True
