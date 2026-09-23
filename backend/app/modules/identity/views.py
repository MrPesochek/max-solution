import uuid
from datetime import datetime

from pydantic import BaseModel

from app.core import ids
from app.core.actor import Side
from app.db.enums import InvitationState
from app.db.models import Invitation, Membership, Organization, User
from app.modules.identity.policy import role_side


class UserView(BaseModel):
    id: str
    display_name: str


class OrganizationRefView(BaseModel):
    id: str
    name: str
    kinds: list[str]


class OrganizationView(BaseModel):
    id: str
    name: str
    kinds: list[str]
    legal_form: str | None
    inn: str | None
    contact_name: str | None
    representative_position: str | None = None
    contact_phone: str | None
    contact_email: str | None
    details_verification_status: str
    representative_verification_status: str
    created_at: datetime


class MembershipView(BaseModel):
    id: str
    organization: OrganizationRefView
    role: str
    side: Side
    status: str
    location_ids: list[str]


class MemberView(BaseModel):
    """Участник в списке сотрудников организации."""

    id: str
    user: UserView
    role: str
    side: Side
    status: str
    location_ids: list[str]
    accepted_at: datetime | None = None
    expected_name: str | None = None


class OrganizationCreatedView(BaseModel):
    organization: OrganizationView
    membership: MembershipView


class InvitationView(BaseModel):
    id: str
    role: str | None
    state: str
    expires_at: datetime
    location_ids: list[str]
    token_prefix: str
    created_at: datetime
    named: bool = False
    recipient_name: str | None = None


class InvitationIssuedView(InvitationView):
    token: str
    webapp_link: str | None
    bot_link: str | None


class InvitationPreviewView(BaseModel):
    """Сведения приглашения — только пока оно действует; иначе только состояние."""

    organization_name: str | None
    role: str | None
    expires_at: datetime | None
    state: str
    inviter_name: str | None = None
    location_names: list[str] = []


class InvitationPreviewForBotView(InvitationPreviewView):
    """Предпросмотр для бота: к нему добавлен id, чтобы приём шёл без хранения токена."""

    id: str


def organization_kinds(org: Organization) -> list[str]:
    kinds = []
    if org.is_customer:
        kinds.append("customer")
    if org.is_provider:
        kinds.append("provider")
    return kinds


def organizations_of(memberships: list[MembershipView]) -> list[OrganizationRefView]:
    seen: dict[str, OrganizationRefView] = {}
    for membership in memberships:
        seen.setdefault(membership.organization.id, membership.organization)
    return list(seen.values())


def to_user_view(user: User) -> UserView:
    return UserView(id=ids.encode("user", user.id), display_name=user.display_name)


def to_organization_ref(org: Organization) -> OrganizationRefView:
    return OrganizationRefView(
        id=ids.encode("organization", org.id),
        name=org.display_name,
        kinds=organization_kinds(org),
    )


def to_organization_view(org: Organization) -> OrganizationView:
    return OrganizationView(
        id=ids.encode("organization", org.id),
        name=org.display_name,
        kinds=organization_kinds(org),
        legal_form=org.legal_form,
        inn=org.inn_normalized,
        contact_name=org.contact_name,
        representative_position=org.representative_position,
        contact_phone=org.contact_phone,
        contact_email=org.contact_email,
        details_verification_status=org.details_verification_status,
        representative_verification_status=org.representative_verification_status,
        created_at=org.created_at,
    )


def to_membership_view(
    membership: Membership, org: Organization, location_ids: list[uuid.UUID]
) -> MembershipView:
    return MembershipView(
        id=ids.encode("membership", membership.id),
        organization=to_organization_ref(org),
        role=membership.role,
        side=role_side(membership.role),
        status=membership.status,
        location_ids=[ids.encode("location", lid) for lid in location_ids],
    )


def to_member_view(
    membership: Membership,
    user: User,
    location_ids: list[uuid.UUID],
    invitation: Invitation | None = None,
) -> MemberView:
    return MemberView(
        id=ids.encode("membership", membership.id),
        user=to_user_view(user),
        role=membership.role,
        side=role_side(membership.role),
        status=membership.status,
        location_ids=[ids.encode("location", lid) for lid in location_ids],
        accepted_at=invitation.accepted_at if invitation is not None else None,
        expected_name=invitation.recipient_name if invitation is not None else None,
    )


def invitation_state(invitation: Invitation, now: datetime) -> str:
    """Состояние наружу: active/expired/revoked/used (в БД — pending/accepted/revoked/expired)."""
    if invitation.status == InvitationState.ACCEPTED:
        return "used"
    if invitation.status == InvitationState.REVOKED:
        return "revoked"
    if invitation.status == InvitationState.EXPIRED or invitation.expires_at <= now:
        return "expired"
    return "active"


def to_invitation_view(invitation: Invitation, now: datetime) -> InvitationView:
    return InvitationView(
        id=ids.encode("invitation", invitation.id),
        role=invitation.role,
        state=invitation_state(invitation, now),
        expires_at=invitation.expires_at,
        location_ids=[ids.encode("location", lid) for lid in invitation.location_ids],
        token_prefix=invitation.token_prefix,
        created_at=invitation.created_at,
        named=invitation.recipient_max_user_id is not None,
        recipient_name=invitation.recipient_name,
    )


def to_invitation_issued_view(
    invitation: Invitation,
    now: datetime,
    *,
    token: str,
    webapp_link: str | None,
    bot_link: str | None,
) -> InvitationIssuedView:
    base = to_invitation_view(invitation, now)
    return InvitationIssuedView(
        **base.model_dump(),
        token=token,
        webapp_link=webapp_link,
        bot_link=bot_link,
    )


def to_invitation_preview(
    invitation: Invitation,
    org: Organization,
    now: datetime,
    *,
    inviter_name: str | None = None,
    location_names: list[str] | None = None,
) -> InvitationPreviewView:
    state = invitation_state(invitation, now)
    if state != "active":
        return InvitationPreviewView(
            organization_name=None, role=None, expires_at=None, state=state
        )
    return InvitationPreviewView(
        organization_name=org.display_name,
        role=invitation.role,
        expires_at=invitation.expires_at,
        state=state,
        inviter_name=inviter_name,
        location_names=location_names or [],
    )


def to_invitation_preview_for_bot(
    invitation: Invitation,
    org: Organization,
    now: datetime,
    *,
    inviter_name: str | None = None,
    location_names: list[str] | None = None,
) -> InvitationPreviewForBotView:
    base = to_invitation_preview(
        invitation, org, now, inviter_name=inviter_name, location_names=location_names
    )
    return InvitationPreviewForBotView(
        **base.model_dump(), id=ids.encode("invitation", invitation.id)
    )
