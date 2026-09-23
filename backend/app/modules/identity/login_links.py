import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, SystemActor
from app.core.clock import utcnow
from app.core.errors import Forbidden, NotFound, Unauthenticated, ValidationFailed
from app.core.pipeline import CommandContext, CommandResult, run_command
from app.db import session as db_session
from app.db.models import AuditEntry, LoginLink, PlatformRole, User
from app.infra.config import get_settings
from app.infra.crypto import generate_token, hash_token
from app.infra.max.deeplinks import is_webapp_target
from app.modules.identity.sessions import (
    DEMO_USER_KEYS,
    DEMO_USER_PREFIX,
    SessionIssued,
    open_session,
)

log = structlog.get_logger(__name__)

LINK_PATH = "/#/auth/link?t="
DEMO_LINK_MAX_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True, slots=True)
class LoginLinkIssued:
    url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class LinkSessionIssued:
    issued: SessionIssued
    target: str | None


def login_links_enabled() -> bool:
    """Вход по ссылке — только при работающем боте: выпускать ссылки больше некому."""
    return get_settings().bot_enabled


def _link_rejected() -> Unauthenticated:
    return Unauthenticated(
        "Ссылка для входа устарела или уже использована", code="LOGIN_LINK_INVALID"
    )


def _audit(
    user_id: uuid.UUID, link_id: uuid.UUID, action: str, result: str, now: datetime, **details: Any
) -> AuditEntry:
    return AuditEntry(
        actor_kind="user",
        actor_user_id=user_id,
        object_type="login_link",
        object_id=link_id,
        action=action,
        result=result,
        details=details,
        occurred_at=now,
    )


async def issue_login_link(max_user_id: str, target: str | None = None) -> LoginLinkIssued:
    """Выпускает ссылку входа для пользователя MAX — вызывается только ботом."""
    settings = get_settings()
    if not login_links_enabled():
        raise NotFound()
    now = utcnow()
    token = generate_token()
    stored_target = target if target and is_webapp_target(target) else None
    expires_at = now + timedelta(seconds=settings.login_link_ttl_seconds)
    async with db_session.transaction() as session:
        user = (
            await session.execute(select(User).where(User.max_user_id == max_user_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFound()
        link = LoginLink(
            user_id=user.id,
            token_hash=hash_token(token),
            target=stored_target,
            expires_at=expires_at,
        )
        session.add(link)
        await session.flush()
        session.add(
            _audit(user.id, link.id, "login_link.issue", "success", now, target=stored_target)
        )
    log.info("login_link_issued", user_id=str(user.id), link_id=str(link.id))
    base = settings.public_base_url.rstrip("/")
    return LoginLinkIssued(url=f"{base}{LINK_PATH}{token}", expires_at=expires_at)


async def issue_demo_login_link(
    actor: Actor, user_key: str, *, ttl_seconds: int | None = None
) -> LoginLinkIssued:
    """Ссылка входа демо-пользователю для проверяющих — только из CLI оператора.

    Только ключи демо-сида и только на стенде с демо-данными (APP_ENV local/demo):
    в prod демо-пользователей нет, а настоящему аккаунту MAX ссылку выпускает лишь
    бот. Пользователь с платформенной ролью так не входит — как и при demo-входе.
    Выпуск и отказ попадают в аудит (actor — CLI оператора).
    """
    if not isinstance(actor, SystemActor):
        raise Forbidden()
    settings = get_settings()
    key = user_key.strip()
    ttl = settings.login_link_ttl_seconds if ttl_seconds is None else ttl_seconds
    if not 60 <= ttl <= DEMO_LINK_MAX_TTL_SECONDS:
        raise ValidationFailed(
            "Срок ссылки — от 60 секунд до 7 суток", field="ttl_seconds", ttl_seconds=ttl
        )

    async def handler(ctx: CommandContext) -> CommandResult:
        if not settings.is_demo_environment:
            raise Forbidden("Ссылки демо-пользователям — только на demo-стенде", code="DEMO_ONLY")
        if key not in DEMO_USER_KEYS:
            raise Forbidden("Ключ не из демо-сида", code="DEMO_ONLY", user_key=key)
        if not login_links_enabled():
            raise Forbidden("Вход по ссылке выключен: бот не подключён", code="LOGIN_LINKS_OFF")
        user = (
            await ctx.session.execute(
                select(User).where(User.max_user_id == f"{DEMO_USER_PREFIX}{key}")
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFound("Демо-пользователь не найден — сид демо-данных запускался?")
        has_role = (
            await ctx.session.execute(
                select(PlatformRole.id)
                .where(PlatformRole.user_id == user.id, PlatformRole.revoked_at.is_(None))
                .limit(1)
            )
        ).scalar_one_or_none()
        if has_role is not None and not settings.operator_demo_login_allowed:
            raise Forbidden("Демо-пользователь с платформенной ролью", code="DEMO_ONLY")
        token = generate_token()
        expires_at = ctx.now + timedelta(seconds=ttl)
        link = LoginLink(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at)
        ctx.session.add(link)
        await ctx.session.flush()
        ctx.audit(
            "login_link.issue_demo",
            "login_link",
            link.id,
            user_key=key,
            expires_at=expires_at.isoformat(),
        )
        base = settings.public_base_url.rstrip("/")
        return CommandResult(
            body={"url": f"{base}{LINK_PATH}{token}", "expires_at": expires_at.isoformat()},
            secret_fields=("url",),
        )

    result = await run_command(actor, handler, action="login_link.issue_demo")
    return LoginLinkIssued(
        url=result.body["url"], expires_at=datetime.fromisoformat(result.body["expires_at"])
    )


async def login_with_link(raw_token: str) -> LinkSessionIssued:
    """Гасит ссылку одним UPDATE: из двух одновременных входов проходит ровно один.

    Истёкшая, использованная и неизвестная ссылка неразличимы снаружи; причина — в журнал.
    """
    if not login_links_enabled():
        log.warning("login_link_rejected", reason="bot_disabled")
        raise _link_rejected()
    now = utcnow()
    digest = hash_token(raw_token)
    async with db_session.transaction() as session:
        claimed = (
            await session.execute(
                update(LoginLink)
                .where(
                    LoginLink.token_hash == digest,
                    LoginLink.used_at.is_(None),
                    LoginLink.expires_at > now,
                )
                .values(used_at=now)
                .returning(LoginLink.id, LoginLink.user_id, LoginLink.target)
            )
        ).one_or_none()
        if claimed is None:
            await _record_rejection(session, digest, now)
            result: LinkSessionIssued | None = None
        else:
            link_id, user_id, target = claimed
            user = await session.get(User, user_id)
            if user is None:
                raise _link_rejected()
            issued = await open_session(session, user, now)
            session.add(_audit(user.id, link_id, "login_link.redeem", "success", now))
            result = LinkSessionIssued(issued=issued, target=target)
    if result is None:
        raise _link_rejected()
    log.info("session_issued", user_id=str(user_id), via="login_link")
    return result


async def _record_rejection(session: AsyncSession, digest: bytes, now: datetime) -> None:
    row = (
        await session.execute(select(LoginLink).where(LoginLink.token_hash == digest))
    ).scalar_one_or_none()
    if row is None:
        log.warning("login_link_rejected", reason="unknown")
        return
    reason = "used" if row.used_at is not None else "expired"
    log.warning("login_link_rejected", reason=reason, link_id=str(row.id))
    session.add(_audit(row.user_id, row.id, "login_link.redeem", "failure", now, reason=reason))
