from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import conversations
from app.core import ids
from app.core.pipeline import Idempotency, hash_body
from app.db.models import BotAction
from app.infra.config import get_settings
from app.infra.crypto import generate_token

if TYPE_CHECKING:
    from app.adapters.bot.context import BotContext

CODE_BYTES = 12
RECIPIENT_MEMBERSHIP_PARAM = "recipient_membership_id"
CONSUMED_BY_PARAM = "consumed_by_update"
OPEN_APP_ACTION = "app.open"
OPEN_APP_TARGET_PARAM = "target"


class ActionRejection(StrEnum):
    UNKNOWN = "unknown"
    FOREIGN = "foreign"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class RejectedAction:
    reason: ActionRejection
    object_type: str | None = None
    object_id: uuid.UUID | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def request_id(self) -> uuid.UUID | None:
        return request_ref(self.object_type, self.object_id, self.params)


def request_ref(
    object_type: str | None, object_id: uuid.UUID | None, params: dict[str, Any]
) -> uuid.UUID | None:
    if object_type == "request":
        return object_id
    value = params.get("request_id")
    if not isinstance(value, str):
        return None
    try:
        return ids.decode("request", value)
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class ClaimedAction:
    id: uuid.UUID
    action_type: str
    object_type: str | None
    object_id: uuid.UUID | None
    expected_version: int | None
    proposal_version: int | None
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def request_id(self) -> uuid.UUID | None:
        return request_ref(self.object_type, self.object_id, self.params)

    @property
    def membership_id(self) -> uuid.UUID | None:
        value = self.params.get(RECIPIENT_MEMBERSHIP_PARAM)
        if not isinstance(value, str):
            return None
        try:
            return uuid.UUID(value)
        except ValueError:
            return None

    @property
    def idempotency(self) -> Idempotency:
        return Idempotency(
            key=f"bot-action-{self.id.hex}",
            operation=f"bot:{self.action_type}",
            body_hash=hash_body({"action": self.action_type, "object": str(self.object_id)}),
        )


async def make_action(
    session: AsyncSession,
    recipient_user_id: uuid.UUID,
    action_type: str,
    now: datetime,
    *,
    conversation_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    expected_version: int | None = None,
    proposal_version: int | None = None,
    params: dict[str, Any] | None = None,
    ttl: timedelta | None = None,
    membership_id: uuid.UUID | None = None,
) -> str:
    lifetime = ttl or timedelta(seconds=get_settings().bot_action_ttl_seconds)
    code = generate_token(CODE_BYTES)
    stored = dict(params or {})
    if membership_id is not None:
        stored[RECIPIENT_MEMBERSHIP_PARAM] = str(membership_id)
    session.add(
        BotAction(
            code=code,
            action_type=action_type,
            object_type=object_type,
            object_id=object_id,
            expected_version=expected_version,
            proposal_version=proposal_version,
            recipient_user_id=recipient_user_id,
            params=stored,
            created_by_bot_conversation_id=conversation_id,
            expires_at=now + lifetime,
        )
    )
    await session.flush()
    return code


async def claim(
    session: AsyncSession, code: str, user_id: uuid.UUID, now: datetime
) -> ClaimedAction | RejectedAction:
    row = (
        await session.execute(select(BotAction).where(BotAction.code == code).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        return RejectedAction(ActionRejection.UNKNOWN)
    params = {k: v for k, v in (row.params or {}).items() if k != CONSUMED_BY_PARAM}
    update_key = conversations.current_update.get()
    reclaimed = (
        row.consumed_at is not None
        and update_key is not None
        and (row.params or {}).get(CONSUMED_BY_PARAM) == update_key
    )
    reason: ActionRejection | None = None
    if row.recipient_user_id is None or row.recipient_user_id != user_id:
        reason = ActionRejection.FOREIGN
    elif reclaimed:
        pass
    elif row.consumed_at is not None:
        reason = ActionRejection.CONSUMED
    elif row.expires_at <= now:
        reason = ActionRejection.EXPIRED
    if reason is not None:
        return RejectedAction(
            reason,
            object_type=row.object_type,
            object_id=row.object_id,
            params=params,
        )

    if not reclaimed:
        row.consumed_at = now
    if update_key is not None:
        row.params = {**params, CONSUMED_BY_PARAM: update_key}
    return ClaimedAction(
        id=row.id,
        action_type=row.action_type,
        object_type=row.object_type,
        object_id=row.object_id,
        expected_version=row.expected_version,
        proposal_version=row.proposal_version,
        params=params,
    )


async def release(session: AsyncSession, action_id: uuid.UUID) -> None:
    await session.execute(
        update(BotAction)
        .where(BotAction.id == action_id, BotAction.consumed_at.is_not(None))
        .values(consumed_at=None)
    )


ActionHandler = Callable[["BotContext", ClaimedAction], Awaitable[None]]

_HANDLERS: dict[str, ActionHandler] = {}


def action(action_type: str) -> Callable[[ActionHandler], ActionHandler]:

    def decorator(fn: ActionHandler) -> ActionHandler:
        _HANDLERS[action_type] = fn
        return fn

    return decorator


def handler_for(action_type: str) -> ActionHandler | None:
    return _HANDLERS.get(action_type)
