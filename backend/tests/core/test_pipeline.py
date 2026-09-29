import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.core.actor import BareUserActor
from app.core.errors import Forbidden, IdempotencyConflict
from app.core.pipeline import CommandContext, CommandResult, Idempotency, hash_body, run_command
from app.db import session as db_session
from app.db.models import AuditEntry, IdempotencyKey, User

pytestmark = pytest.mark.usefixtures("clean_db")


async def _make_user() -> uuid.UUID:
    async with db_session.transaction() as s:
        user = User(max_user_id=uuid.uuid4().hex, display_name="Тест")
        s.add(user)
        await s.flush()
        return user.id


def _idem(key: str, payload: dict) -> Idempotency:
    return Idempotency(key=key, operation="test.op", body_hash=hash_body(payload))


async def test_replay_returns_saved_response_and_runs_once():
    actor = BareUserActor(await _make_user())
    calls = 0

    async def handler(ctx: CommandContext) -> CommandResult:
        nonlocal calls
        calls += 1
        ctx.audit("test.op", "thing")
        return CommandResult({"n": calls}, status=201)

    first = await run_command(actor, handler, idempotency=_idem("key-00001", {"a": 1}))
    second = await run_command(actor, handler, idempotency=_idem("key-00001", {"a": 1}))

    assert (first.status, first.body, first.replayed) == (201, {"n": 1}, False)
    assert (second.status, second.body, second.replayed) == (201, {"n": 1}, True)
    assert calls == 1


async def test_same_key_other_body_conflicts():
    actor = BareUserActor(await _make_user())

    async def handler(ctx: CommandContext) -> CommandResult:
        return CommandResult({})

    await run_command(actor, handler, idempotency=_idem("key-00002", {"a": 1}))
    with pytest.raises(IdempotencyConflict):
        await run_command(actor, handler, idempotency=_idem("key-00002", {"a": 2}))


async def test_failed_command_does_not_keep_key():
    actor = BareUserActor(await _make_user())

    async def failing(ctx: CommandContext) -> CommandResult:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await run_command(actor, failing, idempotency=_idem("key-00003", {}))

    async with db_session.transaction() as s:
        assert await s.scalar(select(func.count()).select_from(IdempotencyKey)) == 0


async def test_concurrent_same_key_executes_once():
    actor = BareUserActor(await _make_user())
    calls = 0

    async def handler(ctx: CommandContext) -> CommandResult:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)
        return CommandResult({"ok": True})

    results = await asyncio.gather(
        *[run_command(actor, handler, idempotency=_idem("key-00004", {})) for _ in range(5)]
    )
    assert calls == 1
    assert sorted(r.replayed for r in results) == [False, True, True, True, True]


async def test_denied_is_audited():
    actor = BareUserActor(await _make_user())

    async def handler(ctx: CommandContext) -> CommandResult:
        raise Forbidden()

    with pytest.raises(Forbidden):
        await run_command(actor, handler)

    async with db_session.transaction() as s:
        rows = (await s.execute(select(AuditEntry))).scalars().all()
    assert [r.result for r in rows] == ["denied"]


async def test_denied_audit_names_the_operation():
    """Действие отказа — операция команды, а не имя замыкания обработчика."""
    actor = BareUserActor(await _make_user())

    async def handler(ctx: CommandContext) -> CommandResult:
        raise Forbidden()

    with pytest.raises(Forbidden):
        await run_command(actor, handler, idempotency=_idem("key-00005", {}))
    with pytest.raises(Forbidden):
        await run_command(actor, handler, action="request.cancel")
    with pytest.raises(Forbidden):
        await run_command(actor, handler)

    async with db_session.transaction() as s:
        rows = (await s.execute(select(AuditEntry).order_by(AuditEntry.occurred_at))).scalars()
        actions = sorted(r.action for r in rows)
    assert "test.op" in actions
    assert "request.cancel" in actions
    assert any(a.endswith("handler") for a in actions)


async def test_key_under_pre_0011_scope_is_not_replayed():
    """Старый формат scope больше не читается: лишнего SELECT на каждую команду нет."""
    from datetime import timedelta

    from app.core.actor import UserActor
    from app.core.clock import utcnow
    from tests import factories

    async with db_session.transaction() as s:
        user = await factories.create_user(s)
        org = await factories.create_organization(s)
        membership = await factories.create_membership(s, user, org, role="customer_manager")
        actor = UserActor(
            user_id=user.id,
            membership_id=membership.id,
            organization_id=org.id,
            role="customer_manager",
        )
        s.add(
            IdempotencyKey(
                scope=f"user:{user.id}:{org.id}",
                key="key-legacy",
                organization_id=org.id,
                membership_id=membership.id,
                request_path="test.op",
                request_body_hash=hash_body({"a": 1}),
                response_status=201,
                response_body={"n": 0},
                expires_at=utcnow() + timedelta(days=1),
            )
        )
    calls = 0

    async def handler(ctx: CommandContext) -> CommandResult:
        nonlocal calls
        calls += 1
        return CommandResult({"n": calls})

    result = await run_command(actor, handler, idempotency=_idem("key-legacy", {"a": 1}))
    assert (result.body, result.replayed) == ({"n": 1}, False)
    replay = await run_command(actor, handler, idempotency=_idem("key-legacy", {"a": 1}))
    assert (replay.body, replay.replayed) == ({"n": 1}, True)
    assert calls == 1
