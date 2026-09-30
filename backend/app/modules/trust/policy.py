from app.core.actor import (
    Actor,
    IntegrationActor,
    OperatorActor,
    SystemActor,
    UserActor,
    require_roles,
)
from app.core.errors import Forbidden, ValidationFailed
from app.db.enums import MembershipRole

BINDING_SCOPE = "service_bindings:write"
PROVIDER_BINDING_ROLES = (MembershipRole.PROVIDER_ADMIN, MembershipRole.PROVIDER_DISPATCHER)


def require_operator(actor: Actor) -> OperatorActor:
    if not isinstance(actor, OperatorActor):
        raise Forbidden()
    return actor


def require_operator_or_system(actor: Actor) -> OperatorActor | SystemActor:
    if isinstance(actor, OperatorActor | SystemActor):
        return actor
    raise Forbidden()


def require_customer_manager(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.CUSTOMER_MANAGER)


def require_provider_admin(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.PROVIDER_ADMIN)


def require_binding_actor(actor: Actor) -> UserActor | IntegrationActor:
    if isinstance(actor, IntegrationActor):
        if BINDING_SCOPE not in actor.scopes:
            raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=BINDING_SCOPE)
        return actor
    return require_roles(actor, *PROVIDER_BINDING_ROLES)


def organization_of(actor: UserActor | IntegrationActor) -> object:
    return actor.organization_id


def require_reason(value: str | None, field: str = "reason") -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationFailed("Укажите основание решения", field=field)
    return text


def require_text(value: str | None, field: str, message: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationFailed(message, field=field)
    return text
