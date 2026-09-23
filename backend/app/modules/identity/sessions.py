import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import Actor, BareUserActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, NotFound, Unauthenticated
from app.db import session as db_session
from app.db.enums import MembershipRole, MembershipStatus
from app.db.models import (
    Membership,
    MembershipLocation,
    Organization,
    PlatformRole,
    Session,
    UsedInitData,
    User,
)
from app.infra.config import get_settings
from app.infra.crypto import generate_token, hash_token, token_prefix
from app.infra.max.init_data import InitDataError, validate_init_data
from app.modules.identity.views import (
    MembershipView,
    OrganizationRefView,
    UserView,
    organizations_of,
    to_membership_view,
    to_user_view,
)

log = structlog.get_logger(__name__)

_LAST_SEEN_PRECISION = timedelta(minutes=1)

DEMO_USER_PREFIX = "demo:"
DEMO_USER_KEYS = (
    "manager",
    "employee",
    "provider_admin",
    "provider_dispatcher",
    "ext_provider_1",
    "ext_provider_2",
    "ext_provider_3",
    "ext_provider_4",
    "bakery_manager",
    "outsider_manager",
    "dual_manager",
    "operator",
)


@dataclass(frozen=True, slots=True)
class SessionIssued:
    token: str
    expires_at: datetime
    user: UserView
    memberships: list[MembershipView]

    @property
    def organizations(self) -> list[OrganizationRefView]:
        return organizations_of(self.memberships)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    expires_at: datetime


def demo_login_enabled() -> bool:
    """Только явным флагом и только в нерабочем окружении: в prod — никогда."""
    settings = get_settings()
    return settings.demo_login_enabled and settings.is_demo_environment


def _display_name(first: str | None, last: str | None, username: str | None) -> str:
    parts = [p for p in (first, last) if p]
    if parts:
        return " ".join(parts)
    return username or "Пользователь MAX"


def _init_data_rejected() -> Unauthenticated:
    return Unauthenticated(
        "Не удалось подтвердить запуск мини-приложения", code="INIT_DATA_INVALID"
    )


async def login_with_init_data(raw_init_data: str) -> SessionIssued:
    settings = get_settings()
    now = utcnow()
    if not settings.max_bot_token:
        log.warning("init_data_rejected", reason="no_bot_token")
        raise _init_data_rejected()
    try:
        data = validate_init_data(
            raw_init_data,
            settings.max_bot_token,
            max_age=settings.init_data_max_age_seconds,
            clock_skew=settings.init_data_clock_skew_seconds,
            now=now,
        )
    except InitDataError as exc:
        log.warning("init_data_rejected", reason=exc.reason.value)
        raise _init_data_rejected() from exc

    lifetime = timedelta(
        seconds=settings.init_data_max_age_seconds + 2 * settings.init_data_clock_skew_seconds
    )
    return await _issue_session(
        str(data.user_id),
        _display_name(data.first_name, data.last_name, data.username),
        now,
        used_init_data=(hash_token(data.signature), now + lifetime),
    )


def is_demo_user(max_user_id: str) -> bool:
    return max_user_id.startswith(DEMO_USER_PREFIX)


async def login_demo(user_key: str) -> SessionIssued:
    """Изолированный вход для локальной разработки и демо (ТЗ 10.4).

    Только ключи демо-сида. Пользователь с платформенной ролью (оператор) входит
    так лишь на локальном стенде без настоящего бота: на любом стенде, который
    видят другие, demo-вход оператором открыл бы модерацию и выдачу ролей.
    """
    if not demo_login_enabled():
        raise Unauthenticated("Вход недоступен", code="INIT_DATA_INVALID")
    key = user_key.strip()
    if key not in DEMO_USER_KEYS:
        log.warning("demo_login_rejected", reason="unknown_key")
        raise Unauthenticated("Вход недоступен", code="INIT_DATA_INVALID")
    max_user_id = f"{DEMO_USER_PREFIX}{key}"
    if not get_settings().operator_demo_login_allowed and await _has_platform_role(max_user_id):
        log.warning("demo_login_rejected", reason="platform_role")
        raise Unauthenticated("Вход недоступен", code="INIT_DATA_INVALID")
    return await _issue_session(max_user_id, f"Демо {key}", utcnow())


async def _has_platform_role(max_user_id: str) -> bool:
    async with db_session.transaction() as session:
        row = (
            await session.execute(
                select(PlatformRole.id)
                .join(User, User.id == PlatformRole.user_id)
                .where(User.max_user_id == max_user_id, PlatformRole.revoked_at.is_(None))
                .limit(1)
            )
        ).scalar_one_or_none()
    return row is not None


async def _issue_session(
    max_user_id: str,
    display_name: str,
    now: datetime,
    *,
    used_init_data: tuple[bytes, datetime] | None = None,
) -> SessionIssued:
    init_data_key = used_init_data[0] if used_init_data is not None else None
    async with db_session.transaction() as session:
        if used_init_data is not None:
            await _claim_init_data(session, *used_init_data, now=now)
        user = (
            await session.execute(select(User).where(User.max_user_id == max_user_id))
        ).scalar_one_or_none()
        if user is None:
            user = User(max_user_id=max_user_id, display_name=display_name)
            session.add(user)
            await session.flush()
        elif user.display_name != display_name:
            user.display_name = display_name
        issued = await open_session(session, user, now, init_data_key=init_data_key)
    log.info("session_issued", user_id=str(user.id))
    return issued


async def open_session(
    session: AsyncSession, user: User, now: datetime, *, init_data_key: bytes | None = None
) -> SessionIssued:
    """Новая сессия пользователя в транзакции вызывающего — общая для всех способов входа."""
    settings = get_settings()
    token = generate_token()
    expires_at = now + timedelta(seconds=settings.session_absolute_ttl_seconds)
    session.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            token_prefix=token_prefix(token),
            issued_at=now,
            expires_at=expires_at,
            last_seen_at=now,
            init_data_key=init_data_key,
        )
    )
    memberships = await load_memberships(session, user.id)
    return SessionIssued(
        token=token, expires_at=expires_at, user=to_user_view(user), memberships=memberships
    )


async def _claim_init_data(
    session: AsyncSession, digest: bytes, expires_at: datetime, *, now: datetime
) -> None:
    """D-S2: повтор той же строки в пределах TTL допустим (перезагрузка Web App,
    потерянный ответ), но выданные по ней раньше сессии отзываются.

    Строка ключа блокируется upsert-ом: параллельные входы с одной строкой
    выстраиваются друг за другом, и живой остаётся только последняя сессия.
    """
    await session.execute(delete(UsedInitData).where(UsedInitData.expires_at <= now))
    stmt = pg_insert(UsedInitData).values(digest=digest, expires_at=expires_at)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["digest"], set_={"expires_at": stmt.excluded.expires_at}
        )
    )
    revoked = (
        await session.execute(
            update(Session)
            .where(Session.init_data_key == digest, Session.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(Session.id)
        )
    ).all()
    if revoked:
        log.info("init_data_reused", revoked_sessions=len(revoked))


async def authenticate_session(token: str) -> SessionInfo:
    now = utcnow()
    settings = get_settings()
    idle_limit = timedelta(seconds=settings.session_idle_ttl_seconds)

    async with db_session.transaction() as session:
        row = (
            await session.execute(
                select(Session, User)
                .join(User, User.id == Session.user_id)
                .where(Session.token_hash == hash_token(token))
            )
        ).one_or_none()
        if row is None:
            raise Unauthenticated()
        sess, user = row
        if sess.revoked_at is not None or sess.expires_at <= now:
            raise Unauthenticated()
        if now - sess.last_seen_at > idle_limit:
            raise Unauthenticated()
        if now - sess.last_seen_at >= _LAST_SEEN_PRECISION:
            sess.last_seen_at = now
        return SessionInfo(
            session_id=sess.id,
            user_id=user.id,
            display_name=user.display_name,
            expires_at=sess.expires_at,
        )


async def logout(info: SessionInfo) -> None:
    now = utcnow()
    async with db_session.transaction() as session:
        await session.execute(
            update(Session)
            .where(Session.id == info.session_id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )


async def resolve_actor(
    info: SessionInfo,
    organization_public_id: str | None,
    membership_public_id: str | None = None,
) -> Actor:
    """Членство перечитывается на каждый запрос: отзыв роли действует сразу (A27).

    Контекст задаёт членство: у одного человека в организации их может быть два —
    по одному на сторону. Организации достаточно, пока членство в ней одно.
    """
    organization_id = (
        ids.decode("organization", organization_public_id)
        if organization_public_id is not None
        else None
    )
    membership_id = (
        ids.decode("membership", membership_public_id) if membership_public_id is not None else None
    )
    return await actor_for_user(info.user_id, organization_id, membership_id)


async def actor_for_user(
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    membership_id: uuid.UUID | None = None,
) -> Actor:
    """Актор по пользователю и членству (или организации) — в том числе для бота.

    Членство читается заново на каждое событие: отзыв роли действует сразу (A27).
    """
    if organization_id is None and membership_id is None:
        return BareUserActor(user_id)

    async with db_session.transaction() as session:
        stmt = select(Membership).where(
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
        if membership_id is not None:
            stmt = stmt.where(Membership.id == membership_id)
        if organization_id is not None:
            stmt = stmt.where(Membership.organization_id == organization_id)
        memberships = list((await session.execute(stmt.limit(2))).scalars())
        if not memberships:
            raise NotFound()
        if len(memberships) > 1:
            raise Conflict(
                "В организации несколько ролей: выберите членство",
                code="MEMBERSHIP_AMBIGUOUS",
            )
        membership = memberships[0]
        location_ids: frozenset[uuid.UUID] | None = None
        if membership.role == MembershipRole.CUSTOMER_EMPLOYEE:
            rows = (
                await session.execute(
                    select(MembershipLocation.location_id).where(
                        MembershipLocation.membership_id == membership.id
                    )
                )
            ).scalars()
            location_ids = frozenset(rows)
        return UserActor(
            user_id=user_id,
            membership_id=membership.id,
            organization_id=membership.organization_id,
            role=membership.role,
            location_ids=location_ids,
        )


async def load_memberships(session: AsyncSession, user_id: uuid.UUID) -> list[MembershipView]:
    rows = (
        await session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(
                Membership.user_id == user_id,
                Membership.status.in_(
                    [MembershipStatus.ACTIVE.value, MembershipStatus.PENDING.value]
                ),
            )
            .order_by(Membership.created_at)
        )
    ).all()
    membership_ids = [m.id for m, _ in rows]
    locations: dict[uuid.UUID, list[uuid.UUID]] = {mid: [] for mid in membership_ids}
    if membership_ids:
        for membership_id, location_id in (
            await session.execute(
                select(MembershipLocation.membership_id, MembershipLocation.location_id).where(
                    MembershipLocation.membership_id.in_(membership_ids)
                )
            )
        ).all():
            locations[membership_id].append(location_id)
    return [to_membership_view(m, org, locations[m.id]) for m, org in rows]
