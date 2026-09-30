import uuid

from app.core.actor import (
    CUSTOMER_ROLES,
    Actor,
    BareUserActor,
    OperatorActor,
    Side,
    UserActor,
    require_roles,
)
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.db.enums import MembershipRole, VerificationStatus
from app.db.models import Organization

MANAGER_ROLES = (MembershipRole.CUSTOMER_MANAGER, MembershipRole.PROVIDER_ADMIN)

CUSTOMER_INVITE_ROLES = frozenset(
    {MembershipRole.CUSTOMER_EMPLOYEE, MembershipRole.CUSTOMER_MANAGER}
)
PROVIDER_INVITE_ROLES = frozenset(
    {MembershipRole.PROVIDER_ADMIN, MembershipRole.PROVIDER_DISPATCHER}
)


def user_id_of(actor: Actor) -> uuid.UUID:
    if isinstance(actor, UserActor | BareUserActor | OperatorActor):
        return actor.user_id
    raise Forbidden()


def require_org_manager(actor: Actor) -> UserActor:
    return require_roles(actor, *MANAGER_ROLES)


def require_provider_admin(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.PROVIDER_ADMIN)


def require_customer_manager(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.CUSTOMER_MANAGER)


def allowed_invite_roles(actor: UserActor) -> frozenset[MembershipRole]:
    return CUSTOMER_INVITE_ROLES if actor.side == "customer" else PROVIDER_INVITE_ROLES


def check_invite_role(actor: UserActor, role: str) -> MembershipRole:
    allowed = allowed_invite_roles(actor)
    if role not in {r.value for r in allowed}:
        raise ValidationFailed("Недопустимая роль приглашения", field="role")
    return MembershipRole(role)


def check_organization_kind(kind: str) -> Side:
    if kind == "customer":
        return "customer"
    if kind == "provider":
        return "provider"
    raise ValidationFailed("Неизвестный тип организации", field="kind")


def founder_role(kind: Side) -> MembershipRole:
    return MembershipRole.CUSTOMER_MANAGER if kind == "customer" else MembershipRole.PROVIDER_ADMIN


def role_side(role: str) -> Side:
    return "customer" if role in CUSTOMER_ROLES else "provider"


def participates(org: Organization, side: Side) -> bool:
    return org.is_customer if side == "customer" else org.is_provider


def check_can_add_participation(org: Organization, kind: Side) -> None:
    if participates(org, kind):
        raise Conflict("Организация уже участвует в этом качестве", code="PARTICIPATION_EXISTS")


def membership_status_on_accept(*, named: bool) -> str:
    return "active" if named else "pending"


def check_locations_role(role: MembershipRole, location_ids: list[uuid.UUID]) -> None:
    if location_ids and role not in CUSTOMER_INVITE_ROLES:
        raise ValidationFailed(
            "Точки назначаются только сотрудникам заказчика", field="location_ids"
        )


def check_requisites_change(
    org: Organization, *, inn_changed: bool, legal_form_changed: bool
) -> None:
    status = org.details_verification_status
    if inn_changed and status == VerificationStatus.VERIFIED:
        raise Conflict(
            "ИНН проверенной организации изменить нельзя, обратитесь к оператору",
            code="INN_LOCKED",
        )
    if (inn_changed or legal_form_changed) and status == VerificationStatus.PENDING:
        raise Conflict(
            "Реквизиты на проверке, изменить их сейчас нельзя",
            code="REQUISITES_UNDER_REVIEW",
        )
