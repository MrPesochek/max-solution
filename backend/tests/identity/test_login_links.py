import asyncio
from collections.abc import Iterator
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import NotFound, Unauthenticated
from app.db import session as app_db
from app.db.models import AuditEntry, LoginLink, Session
from app.infra.config import Settings
from app.infra.crypto import hash_token
from app.modules.identity import api as identity
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(
        monkeypatch, MAX_UPDATES_MODE="webhook", PUBLIC_BASE_URL="https://app.test"
    )


def _token_of(url: str) -> str:
    parts = urlsplit(url)
    assert parts.query == ""
    assert parts.fragment.startswith("/auth/link?t=")
    return parts.fragment.removeprefix("/auth/link?t=")


async def _user(db: AsyncSession, max_user_id: str = "9001") -> None:
    await factories.create_user(db, max_user_id=max_user_id, display_name="Иван")
    await db.commit()


async def test_issue_stores_only_hash_and_target(db_session: AsyncSession) -> None:
    await _user(db_session)

    issued = await identity.issue_login_link("9001", "req_req_0000000000000000000001")

    assert issued.url.startswith("https://app.test/#/auth/link?t=")
    token = _token_of(issued.url)
    assert len(token) >= 43
    async with app_db.transaction() as s:
        link = (await s.execute(select(LoginLink))).scalar_one()
    assert link.token_hash == hash_token(token)
    assert link.target == "req_req_0000000000000000000001"
    assert token not in issued.url.partition("#")[0]


async def test_redeem_issues_session_with_target(db_session: AsyncSession) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001", "scr_equipment")).url)

    result = await identity.login_with_link(token)

    assert result.target == "scr_equipment"
    assert result.issued.user.display_name == "Иван"
    info = await identity.authenticate_session(result.issued.token)
    assert info.display_name == "Иван"


async def test_link_is_single_use(db_session: AsyncSession) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001")).url)
    await identity.login_with_link(token)

    with pytest.raises(Unauthenticated) as exc:
        await identity.login_with_link(token)
    assert exc.value.code == "LOGIN_LINK_INVALID"


async def test_expired_link_is_rejected(db_session: AsyncSession) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001")).url)
    async with app_db.transaction() as s:
        await s.execute(update(LoginLink).values(expires_at=utcnow() - timedelta(seconds=1)))

    with pytest.raises(Unauthenticated) as exc:
        await identity.login_with_link(token)
    assert exc.value.code == "LOGIN_LINK_INVALID"


async def test_unknown_link_is_rejected_the_same_way() -> None:
    with pytest.raises(Unauthenticated) as exc:
        await identity.login_with_link("no-such-token")
    assert exc.value.code == "LOGIN_LINK_INVALID"
    assert exc.value.details == {}


async def test_ttl_follows_settings(db_session: AsyncSession, settings: Settings) -> None:
    await _user(db_session)
    ttl = timedelta(seconds=settings.login_link_ttl_seconds)
    before = utcnow()
    issued = await identity.issue_login_link("9001")
    assert before + ttl <= issued.expires_at <= utcnow() + ttl


async def test_concurrent_redeem_succeeds_once(db_session: AsyncSession) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001")).url)

    results = await asyncio.gather(
        identity.login_with_link(token), identity.login_with_link(token), return_exceptions=True
    )

    assert sum(1 for r in results if isinstance(r, identity.LinkSessionIssued)) == 1
    assert sum(1 for r in results if isinstance(r, Unauthenticated)) == 1
    async with app_db.transaction() as s:
        sessions = list((await s.execute(select(Session))).scalars())
    assert len(sessions) == 1


async def test_link_logs_in_only_its_own_user(db_session: AsyncSession) -> None:
    await _user(db_session, "9001")
    await _user(db_session, "9002")
    token = _token_of((await identity.issue_login_link("9001")).url)

    result = await identity.login_with_link(token)

    async with app_db.transaction() as s:
        owner = (
            await s.execute(
                select(LoginLink.user_id).where(LoginLink.token_hash == hash_token(token))
            )
        ).scalar_one()
    info = await identity.authenticate_session(result.issued.token)
    assert info.user_id == owner


async def test_unknown_max_user_gets_no_link() -> None:
    with pytest.raises(NotFound):
        await identity.issue_login_link("424242")


async def test_invalid_target_is_dropped(db_session: AsyncSession) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001", "req_<script>")).url)
    assert (await identity.login_with_link(token)).target is None


async def test_disabled_without_bot(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001")).url)
    for _ in factories.apply_test_settings(monkeypatch, MAX_UPDATES_MODE="off"):
        with pytest.raises(NotFound):
            await identity.issue_login_link("9001")
        with pytest.raises(Unauthenticated):
            await identity.login_with_link(token)


async def test_issue_and_redeem_are_audited_without_token(db_session: AsyncSession) -> None:
    await _user(db_session)
    token = _token_of((await identity.issue_login_link("9001", "scr_home")).url)
    await identity.login_with_link(token)
    with pytest.raises(Unauthenticated):
        await identity.login_with_link(token)

    async with app_db.transaction() as s:
        entries = list(
            (
                await s.execute(
                    select(AuditEntry)
                    .where(AuditEntry.object_type == "login_link")
                    .order_by(AuditEntry.occurred_at, AuditEntry.id)
                )
            ).scalars()
        )
    assert [(e.action, e.result) for e in entries] == [
        ("login_link.issue", "success"),
        ("login_link.redeem", "success"),
        ("login_link.redeem", "failure"),
    ]
    assert entries[2].details == {"reason": "used"}
    assert all(token not in str(e.details) for e in entries)


async def test_token_is_not_logged(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    await _user(db_session)
    capsys.readouterr()
    token = _token_of((await identity.issue_login_link("9001")).url)
    await identity.login_with_link(token)
    with pytest.raises(Unauthenticated):
        await identity.login_with_link(token)

    output = capsys.readouterr().out
    assert "login_link_issued" in output
    assert "login_link_rejected" in output
    assert token not in output
