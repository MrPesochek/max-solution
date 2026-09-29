import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import BareUserActor
from app.core.pipeline import (
    SECRET_MASK,
    CommandContext,
    CommandResult,
    Idempotency,
    IdempotentSecretNotReplayable,
    hash_body,
    run_command,
)
from app.db import session as db_session
from app.db.models import IdempotencyKey, User
from app.modules.integration import api as integration
from tests.integration_module.conftest import provider_admin, provider_org

pytestmark = pytest.mark.usefixtures("clean_db")


def _idem(key: str, operation: str = "test.secret") -> Idempotency:
    return Idempotency(key=key, operation=operation, body_hash=hash_body({}))


async def _stored_rows() -> list[IdempotencyKey]:
    async with db_session.transaction() as s:
        return list((await s.execute(select(IdempotencyKey))).scalars())


async def test_secret_fields_are_masked_in_storage_and_replay_is_refused() -> None:
    async with db_session.transaction() as s:
        user = User(max_user_id=uuid.uuid4().hex, display_name="Тест")
        s.add(user)
        await s.flush()
        actor = BareUserActor(user.id)

    async def handler(ctx: CommandContext) -> CommandResult:
        return CommandResult(
            {"id": "x1", "token": "very-secret-token", "link": None},
            status=201,
            secret_fields=("token", "link"),
        )

    first = await run_command(actor, handler, idempotency=_idem("secret-0001"))
    assert first.body["token"] == "very-secret-token"

    (row,) = await _stored_rows()
    assert row.response_secret_redacted is True
    assert row.response_body == {"id": "x1", "token": SECRET_MASK, "link": None}

    with pytest.raises(IdempotentSecretNotReplayable) as exc:
        await run_command(actor, handler, idempotency=_idem("secret-0001"))
    assert exc.value.status == 409
    assert exc.value.code == "IDEMPOTENT_SECRET_NOT_REPLAYABLE"
    assert exc.value.details["response"]["id"] == "x1"
    assert "very-secret-token" not in json.dumps(exc.value.details)


async def test_api_key_is_not_kept_in_idempotency_keys(db_session: AsyncSession) -> None:
    org = await provider_org(db_session)
    admin = await provider_admin(db_session, org)
    await db_session.commit()
    idem = _idem("create-key-0001", "POST /integration/api-keys")

    result = await integration.create_api_key(
        admin, integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]), idem=idem
    )
    raw = result.body["key"]

    stored = json.dumps([r.response_body for r in await _stored_rows()])
    assert raw not in stored
    assert result.body["key_prefix"] in stored

    with pytest.raises(IdempotentSecretNotReplayable):
        await integration.create_api_key(
            admin, integration.ApiKeyCreateData(name="CRM", scopes=["requests:read"]), idem=idem
        )
