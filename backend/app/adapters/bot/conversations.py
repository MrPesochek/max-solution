from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotConversation, User

DATA_KEY = "data"
HISTORY_KEY = "history"
RUN_KEY = "run"
UPDATE_KEY = "update"

current_update: ContextVar[str | None] = ContextVar("bot_current_update", default=None)


def _stamped(context: dict[str, Any]) -> dict[str, Any]:
    stamped = dict(context)
    key = current_update.get()
    if key is not None:
        stamped[UPDATE_KEY] = key
    return stamped


@dataclass(slots=True)
class ConversationState:
    id: uuid.UUID
    user_id: uuid.UUID
    max_chat_id: str
    current_step: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    active_organization_id: uuid.UUID | None = None
    active_membership_id: uuid.UUID | None = None
    updated_at: datetime | None = None
    finishing: str | None = None

    @property
    def run(self) -> str:
        value = self.context.get(RUN_KEY)
        return value if isinstance(value, str) else ""

    @property
    def scenario(self) -> str | None:
        return self.current_step.partition(":")[0] if self.current_step else None

    @property
    def step(self) -> str | None:
        return self.current_step.partition(":")[2] if self.current_step else None

    @property
    def data(self) -> dict[str, Any]:
        value = self.context.get(DATA_KEY)
        if not isinstance(value, dict):
            value = {}
            self.context[DATA_KEY] = value
        return value

    @property
    def history(self) -> list[str]:
        value = self.context.get(HISTORY_KEY)
        if not isinstance(value, list):
            value = []
            self.context[HISTORY_KEY] = value
        return value

    def reset_dialog(self) -> None:
        self.current_step = None
        self.context = {}


async def touch_user(
    session: AsyncSession,
    max_user_id: str,
    display_name: str,
    now: datetime,
    *,
    started: bool = False,
    available: bool | None = True,
) -> User:
    values: dict[str, Any] = {"max_user_id": max_user_id, "display_name": display_name}
    if available is not None:
        values["bot_available"] = available
    if started:
        values["bot_started_at"] = now

    update_values = {k: v for k, v in values.items() if k != "max_user_id"}
    stmt = (
        pg_insert(User)
        .values(**values)
        .on_conflict_do_update(index_elements=["max_user_id"], set_=update_values)
        .returning(User.id)
    )
    user_id = (await session.execute(stmt)).scalar_one()
    user = await session.get(User, user_id)
    assert user is not None
    return user


async def load_or_create(
    session: AsyncSession, user_id: uuid.UUID, max_chat_id: str
) -> ConversationState:
    row = (
        await session.execute(
            select(BotConversation).where(BotConversation.max_chat_id == max_chat_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = BotConversation(user_id=user_id, max_chat_id=max_chat_id, context={})
        session.add(row)
        await session.flush()
    elif row.user_id != user_id:
        row.user_id = user_id
        row.current_step = None
        row.context = {}
        row.active_membership_id = None
        row.active_organization_id = None
    return ConversationState(
        id=row.id,
        user_id=row.user_id,
        max_chat_id=row.max_chat_id,
        current_step=row.current_step,
        context=dict(row.context or {}),
        active_organization_id=row.active_organization_id,
        active_membership_id=row.active_membership_id,
        updated_at=row.updated_at,
    )


async def save(session: AsyncSession, state: ConversationState) -> None:
    row = await session.get(BotConversation, state.id)
    if row is None:
        return
    row.user_id = state.user_id
    row.current_step = state.current_step
    row.context = _stamped(state.context)
    row.active_organization_id = state.active_organization_id
    row.active_membership_id = state.active_membership_id


async def close_if_current(
    session: AsyncSession, conversation_id: uuid.UUID, step: str | None, run: str
) -> bool:
    row = (
        await session.execute(
            select(BotConversation).where(BotConversation.id == conversation_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.current_step is None or row.current_step != step:
        return False
    current_run = (row.context or {}).get(RUN_KEY)
    if (current_run or "") != run:
        return False
    row.current_step = None
    row.context = _stamped({})
    return True
