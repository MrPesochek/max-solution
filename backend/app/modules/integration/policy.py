import uuid
from collections.abc import Collection
from dataclasses import dataclass

from app.core.actor import Actor, IntegrationActor, OperatorActor, UserActor, require_roles
from app.core.errors import Forbidden, ValidationFailed
from app.db.enums import IntegrationEventType, MembershipRole
from app.db.models import WebhookSubscription

SCOPES: frozenset[str] = frozenset(
    {
        "requests:read",
        "requests:write",
        "marketplace:read",
        "marketplace:write",
        "equipment:read",
        "service_bindings:read",
        "service_bindings:write",
        "reviews:read",
        "reviews:write",
        "webhooks:manage",
        "events:read",
    }
)

REQUESTS_READ = "requests:read"
MARKETPLACE_READ = "marketplace:read"
EQUIPMENT_READ = "equipment:read"
SERVICE_BINDINGS_READ = "service_bindings:read"
WEBHOOKS_MANAGE = "webhooks:manage"
EVENTS_READ = "events:read"

EVENT_TYPES: frozenset[str] = frozenset(str(t) for t in IntegrationEventType)

SERVICE_BINDINGS_WRITE = "service_bindings:write"
_SEPARATE_FROM_BINDINGS_WRITE: frozenset[str] = frozenset({"requests:write", "marketplace:write"})
SCOPE_CONFLICT_WARNING = "service_bindings_write_shared"

_EVENT_SCOPES: dict[IntegrationEventType, str] = {
    IntegrationEventType.REQUEST_ASSIGNED: REQUESTS_READ,
    IntegrationEventType.REQUEST_CHANGED: REQUESTS_READ,
    IntegrationEventType.MESSAGE_CREATED: REQUESTS_READ,
    IntegrationEventType.OFFER_SELECTED: REQUESTS_READ,
    IntegrationEventType.ASSIGNMENT_REVOKED: REQUESTS_READ,
    IntegrationEventType.VISIT_PROPOSAL_RESPONDED: REQUESTS_READ,
    IntegrationEventType.REPAIR_QUOTE_RESPONDED: REQUESTS_READ,
    IntegrationEventType.CANCELLATION_REQUESTED: REQUESTS_READ,
    IntegrationEventType.REQUEST_CLOSED: REQUESTS_READ,
    IntegrationEventType.SERVICE_BINDING_CHANGED: SERVICE_BINDINGS_READ,
    IntegrationEventType.MARKETPLACE_REQUEST_AVAILABLE: MARKETPLACE_READ,
    IntegrationEventType.MARKETPLACE_REQUEST_CLOSED: MARKETPLACE_READ,
}
EVENT_SCOPES: dict[str, str] = {str(t): scope for t, scope in _EVENT_SCOPES.items()}

PING_EVENT_TYPE = "ping"


@dataclass(frozen=True, slots=True)
class WebhookAccess:
    organization_id: uuid.UUID
    integration_client_id: uuid.UUID | None = None
    membership_id: uuid.UUID | None = None


def readable_event_types(scopes: Collection[str]) -> list[str]:
    return sorted(t for t, scope in EVENT_SCOPES.items() if scope in scopes)


def can_read_event(scopes: Collection[str], event_type: str) -> bool:
    scope = EVENT_SCOPES.get(event_type)
    return scope is not None and scope in scopes


def require_scope(actor: IntegrationActor, *scopes: str) -> None:
    if scopes and not any(scope in actor.scopes for scope in scopes):
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=" | ".join(scopes))


def owns_subscription(access: "WebhookAccess", subscription: WebhookSubscription) -> bool:
    if subscription.provider_org_id != access.organization_id:
        return False
    return (
        access.integration_client_id is None
        or subscription.integration_client_id == access.integration_client_id
    )


def require_provider_admin(actor: Actor) -> UserActor:
    return require_roles(actor, MembershipRole.PROVIDER_ADMIN)


def webhook_access(actor: Actor) -> WebhookAccess:
    if isinstance(actor, IntegrationActor):
        if WEBHOOKS_MANAGE not in actor.scopes:
            raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=WEBHOOKS_MANAGE)
        return WebhookAccess(
            organization_id=actor.organization_id, integration_client_id=actor.integration_client_id
        )
    admin = require_provider_admin(actor)
    return WebhookAccess(organization_id=admin.organization_id, membership_id=admin.membership_id)


def delivery_access(actor: Actor) -> WebhookAccess | None:
    if isinstance(actor, OperatorActor):
        return None
    return webhook_access(actor)


def check_scopes(scopes: list[str]) -> list[str]:
    unique = list(dict.fromkeys(scopes))
    if not unique:
        raise ValidationFailed("Укажите хотя бы один scope", field="scopes")
    unknown = [s for s in unique if s not in SCOPES]
    if unknown:
        raise ValidationFailed("Неизвестный scope", field="scopes", unknown=unknown)
    conflicting = scope_conflicts(unique)
    if conflicting:
        raise ValidationFailed(
            "Право создавать привязки выдаётся отдельным ключом",
            code="SCOPE_CONFLICT",
            field="scopes",
            conflicting=conflicting,
        )
    return unique


def scope_conflicts(scopes: Collection[str]) -> list[str]:
    if SERVICE_BINDINGS_WRITE not in scopes:
        return []
    return sorted(s for s in scopes if s in _SEPARATE_FROM_BINDINGS_WRITE)


def key_warnings(scopes: Collection[str]) -> list[str]:
    return [SCOPE_CONFLICT_WARNING] if scope_conflicts(scopes) else []


def check_event_types(events: list[str]) -> list[str]:
    if not events:
        return sorted(EVENT_TYPES)
    unique = list(dict.fromkeys(events))
    unknown = [e for e in unique if e not in EVENT_TYPES]
    if unknown:
        raise ValidationFailed("Неизвестный тип события", field="events", unknown=unknown)
    return unique
