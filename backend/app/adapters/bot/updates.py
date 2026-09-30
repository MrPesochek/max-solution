from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from maxapi.dispatcher import Dispatcher
from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types.error_event import ErrorEvent
from maxapi.types.updates import UpdateUnion
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.updates.message_edited import MessageEdited
from maxapi.types.updates.message_removed import MessageRemoved
from sqlalchemy import and_, or_
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.adapters.bot import conversations
from app.adapters.bot.context import is_personal_dialog
from app.adapters.bot.conversations import ConversationState
from app.core.clock import utcnow
from app.core.pipeline import Idempotency, hash_body
from app.db import session as db_session
from app.db.models import MaxUpdate
from app.db.models.max import MaxUpdateStatus
from app.infra.config import get_settings
from app.infra.max.transport import MaxRetryableError, MaxTransport
from app.infra.max.types import NewMessageBody, OutgoingAttachment, TextFormat

log = structlog.get_logger("bot")

SUPERSEDED = "superseded"


class ReplyNotDelivered(Exception):
    pass


_handler_error: ContextVar[BaseException | None] = ContextVar("bot_handler_error", default=None)


def update_key(event: UpdateUnion) -> str:
    if isinstance(event, MessageCreated):
        body = event.message.body
        if body is not None and body.mid:
            return f"message_created:{body.mid}"
    elif isinstance(event, MessageEdited):
        body = event.message.body
        if body is not None and body.mid:
            return f"message_edited:{body.mid}:{event.timestamp}"
    elif isinstance(event, MessageCallback):
        return f"message_callback:{event.callback.callback_id}"
    elif isinstance(event, MessageRemoved):
        return f"message_removed:{event.message_id}"

    chat_id = getattr(event, "chat_id", None)
    user = getattr(event, "user", None)
    user_id = getattr(user, "user_id", None) if user is not None else None
    if chat_id is not None or user_id is not None:
        return f"{event.update_type}:{chat_id}:{user_id}:{event.timestamp}"
    return f"{event.update_type}:{_digest(event)}"


def _digest(event: UpdateUnion) -> str:
    raw = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Outcome:
    duplicate: bool = False
    failed: bool = False


@dataclass(slots=True)
class Attempt:
    key: str
    number: int
    previous_replies: list[dict[str, Any]]
    snapshot: dict[str, Any] | None
    received_at: datetime | None = None
    recovered: bool = False
    replies: list[dict[str, Any]] = field(default_factory=list)
    diverged: bool = False
    counters: dict[str, int] = field(default_factory=dict)
    superseded: bool = False
    undelivered: bool = False

    def replayed(self, fingerprint: str) -> dict[str, Any] | None:
        index = len(self.replies)
        if (
            not self.diverged
            and index < len(self.previous_replies)
            and self.previous_replies[index].get("fp") == fingerprint
        ):
            entry = self.previous_replies[index]
            if entry.get("failed"):
                return None
            self.replies.append(entry)
            return entry
        self.diverged = True
        return None

    async def remember(self, fingerprint: str, mid: str | None) -> None:
        self.replies.append({"fp": fingerprint, "mid": mid})
        await self._store(replies=list(self.replies))

    async def remember_failed(self, fingerprint: str) -> None:
        self.undelivered = True
        self.replies.append({"fp": fingerprint, "failed": True})
        await self._store(replies=list(self.replies))

    async def _store(self, **values: Any) -> None:
        try:
            async with db_session.transaction() as session:
                await session.execute(
                    sql_update(MaxUpdate)
                    .where(
                        MaxUpdate.max_update_id == self.key,
                        MaxUpdate.status == MaxUpdateStatus.PROCESSING.value,
                        MaxUpdate.attempts == self.number,
                    )
                    .values(**values)
                )
        except Exception:
            log.exception("max_update_journal_failed")


_attempt: ContextVar[Attempt | None] = ContextVar("bot_update_attempt", default=None)


def current_attempt() -> Attempt | None:
    return _attempt.get()


def event_idempotency(operation: str, body: Any) -> Idempotency | None:
    attempt = _attempt.get()
    if attempt is None:
        return None
    ordinal = attempt.counters.get(operation, 0)
    attempt.counters[operation] = ordinal + 1
    digest = hashlib.sha256(attempt.key.encode("utf-8")).hexdigest()[:32]
    return Idempotency(
        key=f"max-update-{digest}-{operation}-{ordinal}",
        operation=f"bot:{operation}",
        body_hash=hash_body(body),
    )


def _snapshot_of(state: ConversationState) -> dict[str, Any]:
    return {
        "id": str(state.id),
        "current_step": state.current_step,
        "context": state.context,
        "active_organization_id": _str(state.active_organization_id),
        "active_membership_id": _str(state.active_membership_id),
    }


def _str(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(value) if isinstance(value, str) else None


def _comparable(snapshot: dict[str, Any]) -> dict[str, Any]:
    context = {
        k: v for k, v in (snapshot.get("context") or {}).items() if k != conversations.UPDATE_KEY
    }
    return {**snapshot, "context": context}


def _moved_since_received(state: ConversationState, attempt: Attempt) -> bool:
    if conversations.UPDATE_KEY not in state.context:
        return False
    if state.updated_at is None or attempt.received_at is None:
        return True
    return state.updated_at > attempt.received_at


async def bind_conversation(state: ConversationState) -> bool:
    attempt = _attempt.get()
    if attempt is None:
        return True
    snapshot = attempt.snapshot
    touched_by_us = state.context.get(conversations.UPDATE_KEY) == attempt.key
    if snapshot is None:
        stale_start = attempt.number > 1 or attempt.recovered
        if stale_start and (touched_by_us or _moved_since_received(state, attempt)):
            attempt.superseded = True
            log.info("max_update_superseded", attempt=attempt.number, reason="no_snapshot")
            return False
        attempt.snapshot = _snapshot_of(state)
        await attempt._store(conversation_snapshot=attempt.snapshot)
        return True
    same_dialog = snapshot.get("id") == str(state.id)
    if not same_dialog or (
        not touched_by_us and _comparable(_snapshot_of(state)) != _comparable(snapshot)
    ):
        attempt.superseded = True
        log.info("max_update_superseded", attempt=attempt.number)
        return False
    state.current_step = snapshot.get("current_step")
    state.context = dict(snapshot.get("context") or {})
    state.active_organization_id = _uuid(snapshot.get("active_organization_id"))
    state.active_membership_id = _uuid(snapshot.get("active_membership_id"))
    async with db_session.transaction() as session:
        await conversations.save(session, state)
    return True


def _fingerprint(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class InboxTransport:
    def __init__(self, inner: MaxTransport) -> None:
        self._inner = inner

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> str:
        attempt = _attempt.get()
        fingerprint = _fingerprint("send", user_id, chat_id, text)
        if attempt is not None:
            done = attempt.replayed(fingerprint)
            if done is not None:
                log.info("max_update_reply_skipped")
                return str(done.get("mid") or "")
        try:
            mid = await self._inner.send_message(
                user_id=user_id,
                chat_id=chat_id,
                text=text,
                format=format,
                attachments=attachments,
            )
        except MaxRetryableError:
            if attempt is not None:
                await attempt.remember_failed(fingerprint)
            raise
        if attempt is not None:
            await attempt.remember(fingerprint, mid)
        return mid

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        format: TextFormat | None = None,
        attachments: list[OutgoingAttachment] | None = None,
    ) -> None:
        await self._inner.edit_message(
            message_id, text=text, format=format, attachments=attachments
        )

    async def answer_callback(
        self,
        callback_id: str,
        *,
        message: NewMessageBody | None = None,
        notification: str | None = None,
    ) -> None:
        attempt = _attempt.get()
        fingerprint = _fingerprint("answer", callback_id, notification)
        if attempt is not None and attempt.replayed(fingerprint) is not None:
            return
        await self._inner.answer_callback(callback_id, message=message, notification=notification)
        if attempt is not None:
            await attempt.remember(fingerprint, None)

    async def download_attachment(self, url: str, *, max_bytes: int) -> bytes:
        return await self._inner.download_attachment(url, max_bytes=max_bytes)


async def record(event: UpdateUnion, now: datetime | None = None) -> bool:
    payload: dict[str, Any] = event.model_dump(mode="json") if is_personal_dialog(event) else {}
    stmt = (
        pg_insert(MaxUpdate)
        .values(
            max_update_id=update_key(event),
            update_type=str(event.update_type),
            raw_payload=payload,
            received_at=now or utcnow(),
            status=MaxUpdateStatus.RECEIVED.value,
        )
        .on_conflict_do_nothing(index_elements=["max_update_id"])
        .returning(MaxUpdate.id)
    )
    async with db_session.transaction() as session:
        return (await session.execute(stmt)).scalar_one_or_none() is not None


async def acquire(key: str, now: datetime, *, fresh: bool = True) -> Attempt | None:
    settings = get_settings()
    stmt = (
        sql_update(MaxUpdate)
        .where(
            MaxUpdate.max_update_id == key,
            MaxUpdate.attempts < settings.max_update_max_attempts,
            or_(
                MaxUpdate.status.in_(
                    [MaxUpdateStatus.RECEIVED.value, MaxUpdateStatus.FAILED.value]
                ),
                and_(
                    MaxUpdate.status == MaxUpdateStatus.PROCESSING.value,
                    MaxUpdate.lease_until < now,
                ),
            ),
        )
        .values(
            status=MaxUpdateStatus.PROCESSING.value,
            attempts=MaxUpdate.attempts + 1,
            lease_until=now + timedelta(seconds=settings.max_update_lease_seconds),
            next_retry_at=None,
        )
        .returning(
            MaxUpdate.attempts,
            MaxUpdate.replies,
            MaxUpdate.conversation_snapshot,
            MaxUpdate.received_at,
        )
    )
    async with db_session.transaction() as session:
        row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    attempts, replies, snapshot, received_at = row
    return Attempt(
        key=key,
        number=int(attempts),
        previous_replies=list(replies or []),
        snapshot=snapshot,
        received_at=received_at,
        recovered=not fresh,
    )


def retry_delay(attempt: int) -> timedelta:
    settings = get_settings()
    seconds = settings.max_update_retry_base_seconds * (2 ** max(0, attempt - 1))
    return timedelta(seconds=min(seconds, settings.max_update_retry_max_seconds))


async def complete(attempt: Attempt, error: BaseException | None, now: datetime) -> None:
    values: dict[str, Any] = {"lease_until": None}
    if attempt.superseded:
        error = None
    if error is None:
        values.update(
            status=MaxUpdateStatus.PROCESSED.value,
            processed_at=now,
            processing_error=SUPERSEDED if attempt.superseded else None,
            next_retry_at=None,
            raw_payload={},
            replies=[],
            conversation_snapshot=None,
        )
    else:
        exhausted = attempt.number >= get_settings().max_update_max_attempts
        values.update(
            status=(MaxUpdateStatus.DEAD if exhausted else MaxUpdateStatus.FAILED).value,
            processing_error=type(error).__name__,
            next_retry_at=None if exhausted else now + retry_delay(attempt.number),
        )
        if exhausted:
            log.error("max_update_dead", attempts=attempt.number, reason=type(error).__name__)
    try:
        async with db_session.transaction() as session:
            await session.execute(
                sql_update(MaxUpdate)
                .where(
                    MaxUpdate.max_update_id == attempt.key,
                    MaxUpdate.status == MaxUpdateStatus.PROCESSING.value,
                    MaxUpdate.attempts == attempt.number,
                )
                .values(**values)
            )
    except Exception:
        log.exception("max_update_mark_failed")


async def run_attempt(attempt: Attempt, call: Callable[[], Awaitable[Any]]) -> BaseException | None:
    attempt_token = _attempt.set(attempt)
    update_token = conversations.current_update.set(attempt.key)
    error_token = _handler_error.set(None)
    try:
        await call()
        error = _handler_error.get()
        if error is None and attempt.undelivered:
            error = ReplyNotDelivered()
    except Exception as exc:
        error = exc
    finally:
        _handler_error.reset(error_token)
        conversations.current_update.reset(update_token)
        _attempt.reset(attempt_token)
    if attempt.superseded:
        return None
    if isinstance(error, ReplyNotDelivered):
        log.warning("bot_reply_not_delivered", attempt=attempt.number)
    elif error is not None:
        log.error("bot_handler_failed", reason=type(error).__name__, attempt=attempt.number)
    return error


async def process(
    dispatcher: Dispatcher, event: UpdateUnion, *, now: datetime | None = None
) -> Outcome:
    now = now or utcnow()
    key = update_key(event)
    fresh = await record(event, now)
    attempt = await acquire(key, now, fresh=fresh)
    if attempt is None:
        log.info("max_update_duplicate", update_type=str(event.update_type))
        return Outcome(duplicate=True)

    error = await run_attempt(attempt, lambda: dispatcher.handle(event))
    await complete(attempt, error, now)
    return Outcome(failed=error is not None)


async def capture_error(event: ErrorEvent) -> None:
    _handler_error.set(event.exception)


class DedupMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        now = utcnow()
        fresh = await record(event_object, now)
        attempt = await acquire(update_key(event_object), now, fresh=fresh)
        if attempt is None:
            log.info("max_update_duplicate", update_type=str(event_object.update_type))
            return None
        result: list[Any] = []

        async def call() -> None:
            result.append(await handler(event_object, data))

        error = await run_attempt(attempt, call)
        await complete(attempt, error, utcnow())
        return result[0] if result else None
