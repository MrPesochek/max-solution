import uuid

from app.core.actor import Actor, UserActor, require_roles
from app.core.errors import Forbidden, NotFound
from app.core.scope import AccessScope
from app.db.enums import MembershipRole


def require_customer_side(scope: AccessScope) -> None:
    if scope.side != "customer":
        raise Forbidden()


def require_customer_manager(actor: Actor) -> UserActor:
    manager = require_roles(actor, MembershipRole.CUSTOMER_MANAGER)
    return manager


def check_location_visible(scope: AccessScope, location_id: uuid.UUID) -> None:
    if not scope.allows_location(location_id):
        raise NotFound()
