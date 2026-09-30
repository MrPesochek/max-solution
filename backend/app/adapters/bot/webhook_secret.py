from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.locking import advisory_xact_lock
from app.db import session as db_session
from app.db.models import SettingsKv
from app.infra.config import get_settings
from app.infra.crypto import constant_time_equals

if TYPE_CHECKING:
    from app.adapters.bot.runtime import BotRuntime

log = structlog.get_logger("bot")

STATE_KEY = "max_webhook_subscription"
_LOCK_KEY = "max.webhook_subscription"
_FINGERPRINT_LABEL = b"max-webhook-secret"
_DATETIME_FIELDS = ("subscribed_at", "switched_at", "rotation_started_at")


def fingerprint(secret: str) -> str:
    return hmac.new(_FINGERPRINT_LABEL, secret.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class SubscriptionState:
    url: str | None = None
    secret_fp: str | None = None
    subscribed_at: datetime | None = None
    replaced_fp: str | None = None
    switched_at: datetime | None = None
    pending_fp: str | None = None
    rotation_started_at: datetime | None = None

    def matches(self, url: str, secret_fp: str) -> bool:
        return self.url == url and self.secret_fp == secret_fp

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for name in _DATETIME_FIELDS:
            if data[name] is not None:
                data[name] = data[name].isoformat()
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> SubscriptionState:
        if not data:
            return cls()
        values: dict[str, Any] = {name: data.get(name) for name in cls.__dataclass_fields__}
        for name in _DATETIME_FIELDS:
            if values[name] is not None:
                values[name] = datetime.fromisoformat(values[name])
        return cls(**values)


async def load_state(session: AsyncSession | None = None) -> SubscriptionState:
    if session is not None:
        return SubscriptionState.from_json(await session.scalar(_state_query()))
    async with db_session.transaction() as own:
        return SubscriptionState.from_json(await own.scalar(_state_query()))


def _state_query() -> Any:
    return select(SettingsKv.value).where(SettingsKv.key == STATE_KEY)


async def _store(session: AsyncSession, state: SubscriptionState) -> None:
    value = state.to_json()
    statement = pg_insert(SettingsKv).values(key=STATE_KEY, value=value)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[SettingsKv.key], set_={"value": value, "updated_at": utcnow()}
        )
    )


@asynccontextmanager
async def subscription_lock() -> AsyncIterator[AsyncSession]:
    async with db_session.transaction() as session:
        await advisory_xact_lock(session, _LOCK_KEY)
        yield session


async def mark_rotation_started(url: str, secret_fp: str) -> SubscriptionState:
    async with subscription_lock() as session:
        state = await load_state(session)
        if state.matches(url, secret_fp) or state.pending_fp == secret_fp:
            return state
        state = replace(state, pending_fp=secret_fp, rotation_started_at=utcnow())
        await _store(session, state)
        log.info("bot_webhook_rotation_started")
        return state


async def save_subscribed(
    session: AsyncSession, previous: SubscriptionState, url: str, secret_fp: str
) -> SubscriptionState:
    now = utcnow()
    state = replace(
        previous,
        url=url,
        secret_fp=secret_fp,
        subscribed_at=now,
        pending_fp=None,
        rotation_started_at=None,
    )
    if previous.secret_fp != secret_fp:
        state = replace(state, replaced_fp=previous.secret_fp, switched_at=now)
    await _store(session, state)
    return state


async def previous_secret_allowed(runtime: BotRuntime) -> bool:
    settings = get_settings()
    state = await load_state()
    now = utcnow()
    current_fp = fingerprint(runtime.secret)
    previous_fp = fingerprint(runtime.previous_secret)

    if state.secret_fp == current_fp:
        grace = timedelta(seconds=settings.max_webhook_rotation_grace_seconds)
        allowed = (
            state.replaced_fp == previous_fp
            and state.switched_at is not None
            and now < state.switched_at + grace
        )
        stage = "resubscribed"
    elif state.pending_fp == current_fp and state.rotation_started_at is not None:
        window = timedelta(seconds=settings.max_webhook_rotation_window_seconds)
        allowed = state.secret_fp in (None, previous_fp) and now < (
            state.rotation_started_at + window
        )
        stage = "pending"
    else:
        allowed = False
        stage = "not_rotating"

    if allowed:
        log.warning("max_webhook_previous_secret_used", stage=stage)
    else:
        log.warning("max_webhook_previous_secret_rejected", stage=stage)
    return allowed


async def secret_ok(runtime: BotRuntime, provided: str | None) -> bool:
    if not runtime.secret:
        return get_settings().app_env == "test"
    if provided is None:
        return False
    if constant_time_equals(provided, runtime.secret):
        return True
    if not runtime.previous_secret or not constant_time_equals(provided, runtime.previous_secret):
        return False
    return await previous_secret_allowed(runtime)
