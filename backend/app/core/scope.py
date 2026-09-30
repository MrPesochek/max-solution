import uuid
from dataclasses import dataclass

from app.core.actor import Actor, IntegrationActor, Side, UserActor
from app.core.errors import Forbidden


@dataclass(frozen=True, slots=True)
class AccessScope:
    organization_id: uuid.UUID
    side: Side
    location_ids: frozenset[uuid.UUID] | None = None

    def allows_location(self, location_id: uuid.UUID | None) -> bool:
        if self.location_ids is None or location_id is None:
            return self.location_ids is None
        return location_id in self.location_ids


def scope_of(actor: Actor) -> AccessScope:
    if isinstance(actor, UserActor):
        return AccessScope(actor.organization_id, actor.side, actor.location_ids)
    if isinstance(actor, IntegrationActor):
        return AccessScope(actor.organization_id, "provider", None)
    raise Forbidden()
