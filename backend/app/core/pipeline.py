import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import (
    Actor,
    BareUserActor,
    IntegrationActor,
    OperatorActor,
    UserActor,
)
from app.core.clock import utcnow
from app.core.errors import Conflict, DomainError, Forbidden, IdempotencyConflict
from app.db import session as db_session
from app.db.models import AuditEntry, IdempotencyKey, IntegrationEvent, Notification
from app.infra.config import get_settings

log = structlog.get_logger(__name__)

SECRET_MASK = "***"  # noqa: S105 — маска, не секрет
INVITATION_SECRET_FIELDS = ("token", "webapp_link", "bot_link")


class IdempotentSecretNotReplayable(Conflict):
    """Повтор команды, чей ответ содержал одноразовый секрет: сам секрет не хранится."""

    code = "IDEMPOTENT_SECRET_NOT_REPLAYABLE"
    default_message = (
        "Запрос уже выполнен; секрет показывается только один раз и повторно не выдаётся"
    )


@dataclass(frozen=True, slots=True)
class Idempotency:
    key: str
    operation: str
    body_hash: bytes


def hash_body(payload: Any) -> bytes:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).digest()


@dataclass(slots=True)
class CommandResult:
    body: dict[str, Any]
    status: int = 200
    replayed: bool = False
    secret_fields: tuple[str, ...] = ()

    def stored_body(self) -> dict[str, Any]:
        if not self.secret_fields:
            return self.body
        return {
            key: SECRET_MASK if key in self.secret_fields and value is not None else value
            for key, value in self.body.items()
        }


@dataclass(slots=True)
class CommandContext:
    session: AsyncSession
    actor: Actor
    now: datetime
    _after_commit: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    def audit(
        self,
        action: str,
        object_type: str,
        object_id: uuid.UUID | None = None,
        *,
        organization_id: uuid.UUID | None = None,
        **details: Any,
    ) -> None:
        self.session.add(
            _audit_row(
                self.actor,
                action,
                object_type,
                object_id,
                "success",
                organization_id=organization_id,
                details=details,
                now=self.now,
            )
        )

    def emit_integration_event(
        self,
        event_type: str,
        *,
        recipient_org_id: uuid.UUID,
        resource_kind: str,
        resource_id: uuid.UUID,
        resource_version: int | None,
        payload: dict[str, Any],
    ) -> None:
        """Событие для CRM получателя. payload — уже разрешённое получателю представление."""
        self.session.add(
            IntegrationEvent(
                event_type=event_type,
                recipient_org_id=recipient_org_id,
                resource_kind=resource_kind,
                resource_id=resource_id,
                resource_version=resource_version,
                occurred_at=self.now,
                payload=payload,
            )
        )

    def notify(
        self,
        user_id: uuid.UUID,
        notification_type: str,
        payload: dict[str, Any],
        *,
        membership_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        request_id: uuid.UUID | None = None,
    ) -> None:
        """Уведомление в MAX. В payload только ссылки на объекты, текст рендерится при отправке."""
        self.session.add(
            Notification(
                recipient_user_id=user_id,
                recipient_membership_id=membership_id,
                organization_id=organization_id,
                request_id=request_id,
                notification_type=notification_type,
                payload=payload,
                next_attempt_at=self.now,
            )
        )

    def after_commit(self, fn: Callable[[], Awaitable[None]]) -> None:
        self._after_commit.append(fn)


Handler = Callable[[CommandContext], Awaitable[CommandResult]]


async def run_command(
    actor: Actor,
    handler: Handler,
    *,
    idempotency: Idempotency | None = None,
    action: str | None = None,
) -> CommandResult:
    """`action` — имя действия для записи аудита об отказе; без него берётся
    операция ключа идемпотентности, а уже потом имя обработчика."""
    now = utcnow()
    try:
        async with db_session.transaction() as session:
            ctx = CommandContext(session=session, actor=actor, now=now)
            key_row_id: uuid.UUID | None = None
            if idempotency is not None:
                replay, key_row_id = await _claim_key(session, actor, idempotency, now)
                if replay is not None:
                    return replay
            result = await handler(ctx)
            if key_row_id is not None:
                row = await session.get(IdempotencyKey, key_row_id)
                assert row is not None
                row.response_status = result.status
                row.response_body = result.stored_body()
                row.response_secret_redacted = bool(result.secret_fields)
    except Forbidden as exc:
        denied_action = (
            action
            or (idempotency.operation if idempotency is not None else None)
            or str(getattr(handler, "__qualname__", "command"))
        )
        await _audit_denied(actor, denied_action, exc, now)
        raise

    for fn in ctx._after_commit:
        try:
            await fn()
        except Exception:
            log.exception("after_commit_failed")
    return result


async def _claim_key(
    session: AsyncSession, actor: Actor, idem: Idempotency, now: datetime
) -> tuple[CommandResult | None, uuid.UUID | None]:
    scope = actor.idempotency_scope
    ttl = timedelta(seconds=get_settings().idempotency_ttl_seconds)

    for _ in range(2):
        stmt = (
            pg_insert(IdempotencyKey)
            .values(
                scope=scope,
                key=idem.key,
                organization_id=getattr(actor, "organization_id", None),
                integration_client_id=getattr(actor, "integration_client_id", None),
                membership_id=getattr(actor, "membership_id", None),
                request_path=idem.operation,
                request_body_hash=idem.body_hash,
                expires_at=now + ttl,
            )
            .on_conflict_do_nothing(index_elements=["scope", "key"])
            .returning(IdempotencyKey.id)
        )
        inserted = (await session.execute(stmt)).scalar_one_or_none()
        if inserted is not None:
            return None, inserted

        existing = (
            await session.execute(
                select(IdempotencyKey)
                .where(IdempotencyKey.scope == scope, IdempotencyKey.key == idem.key)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is None:
            continue
        if existing.expires_at <= now:
            await session.execute(delete(IdempotencyKey).where(IdempotencyKey.id == existing.id))
            continue
        return _replay(existing, idem), None
    raise IdempotencyConflict("Не удалось обработать ключ идемпотентности, повторите запрос")


def _replay(existing: IdempotencyKey, idem: Idempotency) -> CommandResult:
    if existing.request_body_hash != idem.body_hash or existing.request_path != idem.operation:
        raise IdempotencyConflict()
    if existing.response_secret_redacted:
        raise IdempotentSecretNotReplayable(response=existing.response_body or {})
    return CommandResult(
        body=existing.response_body or {},
        status=existing.response_status or 200,
        replayed=True,
    )


def _audit_row(
    actor: Actor,
    action: str,
    object_type: str,
    object_id: uuid.UUID | None,
    result: str,
    *,
    organization_id: uuid.UUID | None,
    details: dict[str, Any],
    now: datetime,
) -> AuditEntry:
    user_id = (
        actor.user_id if isinstance(actor, UserActor | BareUserActor | OperatorActor) else None
    )
    client_id = actor.integration_client_id if isinstance(actor, IntegrationActor) else None
    kind = "user" if isinstance(actor, BareUserActor) else actor.kind
    return AuditEntry(
        actor_kind=kind,
        actor_user_id=user_id,
        actor_integration_client_id=client_id,
        organization_id=organization_id or getattr(actor, "organization_id", None),
        object_type=object_type,
        object_id=object_id,
        action=action,
        result=result,
        details=details,
        occurred_at=now,
    )


async def _audit_denied(actor: Actor, action: str, exc: DomainError, now: datetime) -> None:
    try:
        async with db_session.transaction() as session:
            session.add(
                _audit_row(
                    actor,
                    action,
                    "command",
                    None,
                    "denied",
                    organization_id=None,
                    details={"code": exc.code},
                    now=now,
                )
            )
    except Exception:
        log.exception("audit_denied_failed")
