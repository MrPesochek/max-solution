import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import MembershipRole, MembershipStatus
from app.db.models import Membership

PROVIDER_NOTIFY_ROLES = (MembershipRole.PROVIDER_ADMIN, MembershipRole.PROVIDER_DISPATCHER)
CUSTOMER_NOTIFY_ROLES = (MembershipRole.CUSTOMER_MANAGER,)


async def active_memberships(
    session: AsyncSession, organization_id: uuid.UUID, roles: tuple[str, ...]
) -> list[Membership]:
    return list(
        (
            await session.execute(
                select(Membership)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.status == MembershipStatus.ACTIVE,
                    Membership.role.in_(list(roles)),
                )
                .order_by(Membership.id)
            )
        ).scalars()
    )


async def provider_recipients(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[Membership]:
    return await active_memberships(session, organization_id, PROVIDER_NOTIFY_ROLES)


async def customer_recipients(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[Membership]:
    return await active_memberships(session, organization_id, CUSTOMER_NOTIFY_ROLES)
