from datetime import timedelta
from urllib.parse import parse_qsl, urlencode

import pytest
from sqlalchemy import func, select, update

from app.core.clock import utcnow
from app.core.errors import Unauthenticated
from app.db import session as db_session
from app.db.models import Session, User
from app.infra.config import Settings
from app.infra.max.init_data import validate_init_data
from app.modules.identity import api as identity
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_login_creates_user_and_session() -> None:
    issued = await identity.login_with_init_data(factories.sign_init_data(777))

    assert issued.token
    assert issued.user.display_name == "Иван"
    assert issued.memberships == []

    async with db_session.transaction() as s:
        user = (await s.execute(select(User).where(User.max_user_id == "777"))).scalar_one()
        count = await s.scalar(
            select(func.count()).select_from(Session).where(Session.user_id == user.id)
        )
    assert count == 1


async def test_login_updates_display_name_and_reuses_user() -> None:
    await identity.login_with_init_data(factories.sign_init_data(778, display_name="Иван"))
    await identity.login_with_init_data(factories.sign_init_data(778, display_name="Иван П"))

    async with db_session.transaction() as s:
        users = list((await s.execute(select(User).where(User.max_user_id == "778"))).scalars())
    assert [u.display_name for u in users] == ["Иван П"]


async def test_forged_signature_is_rejected() -> None:
    raw = factories.sign_init_data(779, signature="0" * 64)
    with pytest.raises(Unauthenticated) as exc:
        await identity.login_with_init_data(raw)
    assert exc.value.code == "INIT_DATA_INVALID"
    assert exc.value.details == {}


async def test_stale_init_data_is_rejected(settings: Settings) -> None:
    stale = utcnow() - timedelta(seconds=settings.init_data_max_age_seconds + 120)
    with pytest.raises(Unauthenticated) as exc:
        await identity.login_with_init_data(factories.sign_init_data(780, auth_date=stale))
    assert exc.value.code == "INIT_DATA_INVALID"


async def test_init_data_signed_by_other_bot_is_rejected() -> None:
    raw = factories.sign_init_data(781, bot_token="999:другой-бот")
    with pytest.raises(Unauthenticated):
        await identity.login_with_init_data(raw)


async def test_authenticate_unknown_token() -> None:
    with pytest.raises(Unauthenticated):
        await identity.authenticate_session("нет-такого-токена")


async def test_authenticate_refreshes_last_seen_at_most_once_a_minute() -> None:
    issued = await identity.login_with_init_data(factories.sign_init_data(782))

    async with db_session.transaction() as s:
        before = (await s.execute(select(Session))).scalar_one().last_seen_at
        await s.execute(update(Session).values(last_seen_at=before - timedelta(seconds=5)))
    await identity.authenticate_session(issued.token)
    async with db_session.transaction() as s:
        unchanged = (await s.execute(select(Session))).scalar_one().last_seen_at
    assert unchanged == before - timedelta(seconds=5)

    async with db_session.transaction() as s:
        await s.execute(update(Session).values(last_seen_at=before - timedelta(minutes=5)))
    await identity.authenticate_session(issued.token)
    async with db_session.transaction() as s:
        refreshed = (await s.execute(select(Session))).scalar_one().last_seen_at
    assert refreshed > before - timedelta(minutes=5)


async def test_idle_and_absolute_expiry(settings: Settings) -> None:
    now = utcnow()
    async with db_session.transaction() as s:
        user = await factories.create_user(s)
        idle_token = await factories.create_session_token(
            s,
            user,
            last_seen_at=now - timedelta(seconds=settings.session_idle_ttl_seconds + 60),
        )
        expired_token = await factories.create_session_token(
            s, user, expires_at=now - timedelta(minutes=1)
        )
        revoked_token = await factories.create_session_token(s, user, revoked_at=now)

    for token in (idle_token, expired_token, revoked_token):
        with pytest.raises(Unauthenticated):
            await identity.authenticate_session(token)


async def test_logout_revokes_session() -> None:
    issued = await identity.login_with_init_data(factories.sign_init_data(783))
    info = await identity.authenticate_session(issued.token)
    await identity.logout(info)
    with pytest.raises(Unauthenticated):
        await identity.authenticate_session(issued.token)


async def test_demo_login_disabled_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infra.config import get_settings

    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    try:
        assert identity.demo_login_enabled() is False
        with pytest.raises(Unauthenticated):
            await identity.login_demo("manager")
    finally:
        get_settings.cache_clear()


async def test_demo_login_issues_session() -> None:
    issued = await identity.login_demo("manager")
    assert issued.token
    async with db_session.transaction() as s:
        user = (
            await s.execute(select(User).where(User.max_user_id == "demo:manager"))
        ).scalar_one()
    assert user.display_name == "Демо manager"


async def test_login_refused_without_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    forged = factories.sign_init_data(790, bot_token="")
    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="demo", MAX_BOT_TOKEN=""):
        with pytest.raises(Unauthenticated):
            await identity.login_with_init_data(forged)


def test_prod_settings_require_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_BOT_TOKEN", "")
    with pytest.raises(ValueError, match="MAX_BOT_TOKEN"):
        Settings(app_env="prod")


def test_settings_default_to_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(max_bot_token="t").app_env == "prod"


async def test_repeated_init_data_revokes_previous_session() -> None:
    raw = factories.sign_init_data(791)
    first = await identity.login_with_init_data(raw)
    second = await identity.login_with_init_data(raw)

    assert second.token != first.token
    await identity.authenticate_session(second.token)
    with pytest.raises(Unauthenticated):
        await identity.authenticate_session(first.token)


async def test_reordered_init_data_is_the_same_key() -> None:
    raw = factories.sign_init_data(792)
    reordered = urlencode(list(reversed(parse_qsl(raw, keep_blank_values=True))))
    assert reordered != raw

    first = await identity.login_with_init_data(raw)
    await identity.login_with_init_data(reordered)
    with pytest.raises(Unauthenticated):
        await identity.authenticate_session(first.token)


def test_init_data_key_ignores_parameter_order(settings: Settings) -> None:
    raw = factories.sign_init_data(793)
    reordered = urlencode(list(reversed(parse_qsl(raw, keep_blank_values=True))))
    now = utcnow()

    def key(value: str) -> str:
        return validate_init_data(
            value,
            settings.max_bot_token,
            max_age=settings.init_data_max_age_seconds,
            clock_skew=settings.init_data_clock_skew_seconds,
            now=now,
        ).signature

    assert key(raw) == key(reordered)


async def test_other_init_data_keeps_session() -> None:
    first = await identity.login_with_init_data(factories.sign_init_data(794))
    await identity.login_with_init_data(
        factories.sign_init_data(794, auth_date=utcnow() - timedelta(seconds=5))
    )
    await identity.authenticate_session(first.token)


async def test_demo_login_needs_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="demo", DEMO_LOGIN_ENABLED="false"):
        assert identity.demo_login_enabled() is False
        with pytest.raises(Unauthenticated):
            await identity.login_demo("manager")
