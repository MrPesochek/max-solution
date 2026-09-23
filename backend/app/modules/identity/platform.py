from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, OperatorActor, SystemActor
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db import session as db_session
from app.db.enums import PlatformRoleName
from app.db.models import PlatformRole, User
from app.modules.identity.sessions import SessionInfo, is_demo_user


def _require_platform_actor(actor: Actor) -> OperatorActor | SystemActor:
    """Роль оператора выдаёт другой оператор либо CLI платформы."""
    if isinstance(actor, OperatorActor | SystemActor):
        return actor
    raise Forbidden()


async def _check_demo_scope(
    session: AsyncSession, actor: OperatorActor | SystemActor, max_user_id: str
) -> None:
    """Демо-оператор (вошёл demo-входом) управляет ролями только демо-пользователей:
    выдать роль настоящему аккаунту MAX или отозвать её у настоящего оператора
    он не может."""
    if not isinstance(actor, OperatorActor) or is_demo_user(max_user_id):
        return
    actor_max_user_id = (
        await session.execute(select(User.max_user_id).where(User.id == actor.user_id))
    ).scalar_one_or_none()
    if actor_max_user_id is None or is_demo_user(actor_max_user_id):
        raise Forbidden()


async def grant_operator(
    actor: Actor, max_user_id: str, *, idem: Idempotency | None
) -> CommandResult:
    granter = _require_platform_actor(actor)
    key = max_user_id.strip()
    if not key:
        raise NotFound()

    async def handler(ctx: CommandContext) -> CommandResult:
        await _check_demo_scope(ctx.session, granter, key)
        user = (
            await ctx.session.execute(select(User).where(User.max_user_id == key).with_for_update())
        ).scalar_one_or_none()
        if user is None:
            user = User(max_user_id=key, display_name="Оператор")
            ctx.session.add(user)
            await ctx.session.flush()
        existing = (
            await ctx.session.execute(
                select(PlatformRole).where(
                    PlatformRole.user_id == user.id,
                    PlatformRole.role == PlatformRoleName.OPERATOR,
                    PlatformRole.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise Conflict("Роль оператора уже выдана")
        row = PlatformRole(
            user_id=user.id,
            role=PlatformRoleName.OPERATOR.value,
            granted_by_user_id=granter.user_id if isinstance(granter, OperatorActor) else None,
            granted_at=ctx.now,
        )
        ctx.session.add(row)
        await ctx.session.flush()
        ctx.audit("platform_role.grant", "platform_role", row.id, role=PlatformRoleName.OPERATOR)
        return CommandResult({"max_user_id": key, "role": PlatformRoleName.OPERATOR.value}, 201)

    return await run_command(actor, handler, idempotency=idem)


async def revoke_operator(
    actor: Actor, max_user_id: str, *, idem: Idempotency | None
) -> CommandResult:
    revoker = _require_platform_actor(actor)
    key = max_user_id.strip()

    async def handler(ctx: CommandContext) -> CommandResult:
        await _check_demo_scope(ctx.session, revoker, key)
        row = (
            await ctx.session.execute(
                select(PlatformRole)
                .join(User, User.id == PlatformRole.user_id)
                .where(
                    User.max_user_id == key,
                    PlatformRole.role == PlatformRoleName.OPERATOR,
                    PlatformRole.revoked_at.is_(None),
                )
                .with_for_update(of=PlatformRole)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound()
        row.revoked_at = ctx.now
        ctx.audit("platform_role.revoke", "platform_role", row.id, role=PlatformRoleName.OPERATOR)
        return CommandResult({"max_user_id": key, "role": PlatformRoleName.OPERATOR.value})

    return await run_command(actor, handler, idempotency=idem)


async def resolve_operator(info: SessionInfo) -> OperatorActor:
    """Роль перечитывается на каждый запрос: отзыв действует со следующей операции."""
    async with db_session.transaction() as session:
        row = (
            await session.execute(
                select(PlatformRole).where(
                    PlatformRole.user_id == info.user_id,
                    PlatformRole.role == PlatformRoleName.OPERATOR,
                    PlatformRole.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise Forbidden()
        return OperatorActor(user_id=info.user_id)


async def operator_actor_by_max_user_id(max_user_id: str) -> OperatorActor:
    async with db_session.transaction() as session:
        row = (
            await session.execute(
                select(PlatformRole)
                .join(User, User.id == PlatformRole.user_id)
                .where(
                    User.max_user_id == max_user_id.strip(),
                    PlatformRole.role == PlatformRoleName.OPERATOR,
                    PlatformRole.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise Forbidden()
        return OperatorActor(user_id=row.user_id)
