import secrets as sysrandom
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import IntegrationActor
from app.core.clock import utcnow
from app.core.errors import Unauthenticated
from app.db import session as db_session
from app.db.enums import IntegrationClientStatus
from app.db.models import IntegrationClient
from app.infra.config import get_settings
from app.infra.crypto import SecretBox, constant_time_equals, generate_token, hash_token

log = structlog.get_logger(__name__)

KEY_SCHEME = "rk"
JURY_KEY_SCHEME = "max"
PREFIX_BYTES = 6
SECRET_BYTES = 32

_TOUCH_PRECISION = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class IssuedKey:
    raw: str
    prefix: str
    digest: bytes


@dataclass(frozen=True, slots=True)
class ParsedKey:
    env: str
    prefix: str


def secret_box() -> SecretBox:
    return SecretBox(get_settings().secrets_encryption_key)


def issue_api_key(env: str | None = None) -> IssuedKey:
    environment = env or get_settings().app_env
    prefix = sysrandom.token_hex(PREFIX_BYTES)
    raw = f"{KEY_SCHEME}_{environment}_{prefix}_{generate_token(SECRET_BYTES)}"
    return IssuedKey(raw=raw, prefix=prefix, digest=hash_token(raw))


def parse_api_key(raw: str) -> ParsedKey | None:
    jury_parts = raw.strip().split("_", 1)
    if (
        len(jury_parts) == 2
        and jury_parts[0] == JURY_KEY_SCHEME
        and jury_parts[1].isalnum()
    ):
        return ParsedKey(env="*", prefix=jury_parts[1])

    parts = raw.strip().split("_", 3)
    if len(parts) != 4:
        return None
    scheme, env, prefix, secret = parts
    if scheme != KEY_SCHEME or not env or not secret or not prefix.isalnum():
        return None
    return ParsedKey(env=env, prefix=prefix)


_COMPATIBLE_ENVS = frozenset({"local", "demo"})


def env_matches(key_env: str, app_env: str) -> bool:
    """Ключ выпущен для этого окружения: demo-ключ не открывает рабочий контур."""
    return (
        key_env == "*"
        or key_env == app_env
        or {key_env, app_env} <= _COMPATIBLE_ENVS
    )


async def authenticate_api_key(raw: str) -> IntegrationActor:
    """Ключ → актор интеграции. Причина отказа наружу не раскрывается (ТЗ 10.3)."""
    parsed = parse_api_key(raw)
    if parsed is None:
        raise Unauthenticated("Неверный ключ интеграции", code="API_KEY_INVALID")
    if not env_matches(parsed.env, get_settings().app_env):
        log.warning("api_key_env_mismatch", key_env=parsed.env)
        raise Unauthenticated("Неверный ключ интеграции", code="API_KEY_INVALID")

    digest = hash_token(raw)
    now = utcnow()
    async with db_session.transaction() as session:
        rows = list(
            (
                await session.execute(
                    select(IntegrationClient).where(
                        IntegrationClient.api_key_prefix == parsed.prefix
                    )
                )
            ).scalars()
        )
        matched: IntegrationClient | None = None
        for row in rows:
            if constant_time_equals(row.api_key_hash, digest):
                matched = row
        if matched is None:
            raise Unauthenticated("Неверный ключ интеграции", code="API_KEY_INVALID")
        if matched.status != IntegrationClientStatus.ACTIVE or matched.revoked_at is not None:
            log.warning("api_key_revoked", integration_client_id=str(matched.id))
            raise Unauthenticated("Неверный ключ интеграции", code="API_KEY_INVALID")

        await _touch(session, matched.id, now)
        return IntegrationActor(
            integration_client_id=matched.id,
            organization_id=matched.provider_org_id,
            scopes=frozenset(matched.scopes),
        )


async def _touch(session: AsyncSession, client_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(IntegrationClient)
        .where(
            IntegrationClient.id == client_id,
            or_(
                IntegrationClient.last_used_at.is_(None),
                IntegrationClient.last_used_at < now - _TOUCH_PRECISION,
            ),
        )
        .values(last_used_at=now)
    )
