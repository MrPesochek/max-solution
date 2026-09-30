import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.core.errors import Forbidden

CUSTOMER_ROLES = frozenset({"customer_manager", "customer_employee"})
PROVIDER_ROLES = frozenset({"provider_admin", "provider_dispatcher"})

Side = Literal["customer", "provider"]


@dataclass(frozen=True, slots=True)
class UserActor:
    user_id: uuid.UUID
    membership_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    location_ids: frozenset[uuid.UUID] | None = None

    kind: Literal["user"] = "user"

    @property
    def side(self) -> Side:
        return "customer" if self.role in CUSTOMER_ROLES else "provider"

    @property
    def is_manager(self) -> bool:
        return self.role == "customer_manager"

    @property
    def idempotency_scope(self) -> str:
        return f"user:{self.user_id}:{self.organization_id}:{self.side}"


@dataclass(frozen=True, slots=True)
class BareUserActor:
    user_id: uuid.UUID
    kind: Literal["bare_user"] = "bare_user"

    @property
    def idempotency_scope(self) -> str:
        return f"user:{self.user_id}"


@dataclass(frozen=True, slots=True)
class IntegrationActor:
    integration_client_id: uuid.UUID
    organization_id: uuid.UUID
    scopes: frozenset[str] = field(default_factory=frozenset)
    kind: Literal["integration_client"] = "integration_client"
    side: Side = "provider"

    @property
    def idempotency_scope(self) -> str:
        return f"ic:{self.integration_client_id}"


@dataclass(frozen=True, slots=True)
class OperatorActor:
    user_id: uuid.UUID
    kind: Literal["operator"] = "operator"

    @property
    def idempotency_scope(self) -> str:
        return f"op:{self.user_id}"


@dataclass(frozen=True, slots=True)
class SystemActor:
    name: str
    kind: Literal["system"] = "system"

    @property
    def idempotency_scope(self) -> str:
        return f"sys:{self.name}"


Actor = UserActor | BareUserActor | IntegrationActor | OperatorActor | SystemActor
OrgActor = UserActor | IntegrationActor


def require_roles(actor: Actor, *roles: str) -> UserActor:
    if not isinstance(actor, UserActor) or actor.role not in roles:
        raise Forbidden()
    return actor


def require_scope(actor: Actor, scope: str) -> IntegrationActor:
    if not isinstance(actor, IntegrationActor) or scope not in actor.scopes:
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=scope)
    return actor
