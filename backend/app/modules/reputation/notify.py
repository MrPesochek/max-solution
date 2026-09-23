import uuid

from sqlalchemy import select

from app.core import ids
from app.core.pipeline import CommandContext
from app.db.enums import MembershipRole, MembershipStatus
from app.db.models import Membership


async def notify_provider(
    ctx: CommandContext, provider_org_id: uuid.UUID, kind: str, review_id: uuid.UUID
) -> None:
    memberships = list(
        (
            await ctx.session.execute(
                select(Membership).where(
                    Membership.organization_id == provider_org_id,
                    Membership.status == MembershipStatus.ACTIVE,
                    Membership.role.in_(
                        [
                            MembershipRole.PROVIDER_ADMIN.value,
                            MembershipRole.PROVIDER_DISPATCHER.value,
                        ]
                    ),
                )
            )
        ).scalars()
    )
    for membership in memberships:
        ctx.notify(
            membership.user_id,
            kind,
            {"review_id": ids.encode("review", review_id)},
            membership_id=membership.id,
            organization_id=provider_org_id,
        )
