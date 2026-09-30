from app.core.actor import Actor, IntegrationActor, OperatorActor, UserActor, require_roles
from app.core.errors import Forbidden, ValidationFailed
from app.db.enums import MembershipRole

REVIEWS_READ = "reviews:read"
REVIEWS_WRITE = "reviews:write"


def require_customer_manager(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.CUSTOMER_MANAGER)


def require_provider_side(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.PROVIDER_ADMIN, MembershipRole.PROVIDER_DISPATCHER)


def require_org_member(actor: Actor) -> UserActor:
    if not isinstance(actor, UserActor):
        raise Forbidden()
    return actor


def require_operator(actor: Actor) -> OperatorActor:
    if not isinstance(actor, OperatorActor):
        raise Forbidden()
    return actor


def require_reviews_read(actor: IntegrationActor) -> None:
    if REVIEWS_READ not in actor.scopes:
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=REVIEWS_READ)


def require_reviews_write(actor: IntegrationActor) -> None:
    if REVIEWS_WRITE not in actor.scopes:
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=REVIEWS_WRITE)


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
