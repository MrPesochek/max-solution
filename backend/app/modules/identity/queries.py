import uuid
from collections.abc import Callable

from sqlalchemy import ColumnElement, or_, select

from app.core.actor import CUSTOMER_ROLES, PROVIDER_ROLES
from app.core.clock import utcnow
from app.core.errors import NotFound
from app.core.scope import AccessScope
from app.db import session as db_session
from app.db.enums import InvitationKind
from app.db.models import (
    Invitation,
    Location,
    Membership,
    MembershipLocation,
    Organization,
    User,
)
from app.infra.crypto import hash_token
from app.modules.identity.sessions import load_memberships
from app.modules.identity.views import (
    InvitationPreviewForBotView,
    InvitationPreviewView,
    InvitationView,
    MembershipView,
    MemberView,
    OrganizationView,
    to_invitation_preview,
    to_invitation_preview_for_bot,
    to_invitation_view,
    to_member_view,
    to_organization_view,
)

DEFAULT_LIMIT = 50


def _paginate[T](
    rows: list[T], limit: int, key: Callable[[T], uuid.UUID]
) -> tuple[list[T], uuid.UUID | None]:
    if len(rows) <= limit:
        return rows, None
    page = rows[:limit]
    return page, key(page[-1])


def _side_roles(scope: AccessScope) -> frozenset[str]:
    return CUSTOMER_ROLES if scope.side == "customer" else PROVIDER_ROLES


def _invitation_side(scope: AccessScope) -> ColumnElement[bool]:
    condition = Invitation.role.in_(_side_roles(scope))
    if scope.side == "customer":
        return or_(condition, Invitation.role.is_(None))
    return condition


async def get_organization(scope: AccessScope) -> OrganizationView:
    async with db_session.transaction() as session:
        org = await session.get(Organization, scope.organization_id)
        if org is None:
            raise NotFound()
        return to_organization_view(org)


async def list_user_memberships(user_id: uuid.UUID) -> list[MembershipView]:
    async with db_session.transaction() as session:
        return await load_memberships(session, user_id)


async def list_members(
    scope: AccessScope, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[MemberView], uuid.UUID | None]:
    async with db_session.transaction() as session:
        stmt = (
            select(Membership, User, Invitation)
            .join(User, User.id == Membership.user_id)
            .outerjoin(Invitation, Invitation.id == Membership.invitation_id)
            .where(
                Membership.organization_id == scope.organization_id,
                Membership.role.in_(_side_roles(scope)),
            )
            .order_by(Membership.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(Membership.id > cursor)
        rows: list[tuple[Membership, User, Invitation | None]] = [
            (m, u, inv) for m, u, inv in (await session.execute(stmt)).all()
        ]
        page, next_cursor = _paginate(rows, limit, lambda row: row[0].id)
        membership_ids = [m.id for m, _, _ in page]
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
        return [to_member_view(m, u, locations[m.id], inv) for m, u, inv in page], next_cursor


async def list_invitations(
    scope: AccessScope, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[InvitationView], uuid.UUID | None]:
    now = utcnow()
    async with db_session.transaction() as session:
        stmt = (
            select(Invitation)
            .where(
                Invitation.organization_id == scope.organization_id,
                Invitation.kind == InvitationKind.MEMBERSHIP,
                _invitation_side(scope),
            )
            .order_by(Invitation.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(Invitation.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda inv: inv.id)
        return [to_invitation_view(inv, now) for inv in page], next_cursor


async def preview_invitation(token: str) -> InvitationPreviewView:
    return await _preview(token, to_invitation_preview)


async def preview_invitation_for_bot(token: str) -> InvitationPreviewForBotView:
    return await _preview(token, to_invitation_preview_for_bot)


async def _preview[V](token: str, build: Callable[..., V]) -> V:
    now = utcnow()
    async with db_session.transaction() as session:
        invitation = (
            await session.execute(
                select(Invitation).where(
                    Invitation.token_hash == hash_token(token),
                    Invitation.kind == InvitationKind.MEMBERSHIP,
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFound()
        org = await session.get(Organization, invitation.organization_id)
        assert org is not None
        inviter_name = None
        if invitation.created_by_membership_id is not None:
            inviter_name = (
                await session.execute(
                    select(User.display_name)
                    .join(Membership, Membership.user_id == User.id)
                    .where(Membership.id == invitation.created_by_membership_id)
                )
            ).scalar_one_or_none()
        location_names: list[str] = []
        if invitation.location_ids:
            location_names = list(
                (
                    await session.execute(
                        select(Location.name)
                        .where(
                            Location.id.in_(invitation.location_ids),
                            Location.customer_org_id == invitation.organization_id,
                        )
                        .order_by(Location.name)
                    )
                ).scalars()
            )
        return build(invitation, org, now, inviter_name=inviter_name, location_names=location_names)
