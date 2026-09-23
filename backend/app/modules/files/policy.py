import uuid
from dataclasses import dataclass

from app.core.actor import (
    Actor,
    BareUserActor,
    IntegrationActor,
    OperatorActor,
    UserActor,
)
from app.db.enums import (
    AssignmentState,
    AttachmentOwnerKind,
    AttachmentState,
    ModerationStatus,
    VisibilityClass,
)

REQUESTS_READ = "requests:read"
REQUESTS_WRITE = "requests:write"
MARKETPLACE_READ = "marketplace:read"

READABLE_ASSIGNMENT_STATES = frozenset(
    {AssignmentState.PENDING, AssignmentState.ACCEPTED, AssignmentState.COMPLETED}
)
CONFIRMED_ASSIGNMENT_STATES = frozenset({AssignmentState.ACCEPTED, AssignmentState.COMPLETED})

SENSITIVE_CLASSES = frozenset({VisibilityClass.REQUEST_SENSITIVE})


@dataclass(frozen=True, slots=True)
class AttachmentAccess:
    """Снимок состояния владельца, от которого зависит доступ."""

    attachment_id: uuid.UUID
    visibility_class: str
    processing_state: str
    owner_kind: str
    uploaded_by_user_id: uuid.UUID | None = None
    uploaded_by_membership_id: uuid.UUID | None = None
    uploaded_by_integration_client_id: uuid.UUID | None = None
    is_copy: bool = False
    customer_org_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    assignment_state: str | None = None
    assignment_route: str | None = None
    card_open: bool = False
    listed_in_card: bool = False
    provider_org_id: uuid.UUID | None = None
    review_customer_org_id: uuid.UUID | None = None
    verification_org_id: uuid.UUID | None = None
    publication_state: str | None = None
    service_binding_confirmed: bool = False
    within_assignment: bool = True


def is_ready(access: AttachmentAccess) -> bool:
    return access.processing_state == AttachmentState.READY


def is_uploader(actor: Actor, access: AttachmentAccess) -> bool:
    """Автор — в той же организации, от имени которой загружал: членство привязано к ней."""
    if access.is_copy:
        return False
    if isinstance(actor, UserActor):
        return (
            access.uploaded_by_user_id == actor.user_id
            and access.uploaded_by_membership_id == actor.membership_id
        )
    if isinstance(actor, IntegrationActor):
        return access.uploaded_by_integration_client_id == actor.integration_client_id
    return False


def can_read(actor: Actor, access: AttachmentAccess, *, marketplace_visible: bool = False) -> bool:
    """Правило видимости по классу. Готовность файла проверяется отдельно."""
    match access.visibility_class:
        case VisibilityClass.REQUEST_PRIVATE:
            if access.owner_kind == AttachmentOwnerKind.EQUIPMENT:
                return _equipment_private(actor, access)
            return _request_private(actor, access)
        case VisibilityClass.REQUEST_SENSITIVE:
            return _request_sensitive(actor, access)
        case VisibilityClass.PUBLIC_CARD:
            return _public_card(actor, access, marketplace_visible)
        case VisibilityClass.PROFILE_PUBLIC | VisibilityClass.REVIEW_PUBLIC:
            return _moderated_public(actor, access)
        case VisibilityClass.VERIFICATION_EVIDENCE:
            return _verification_evidence(actor, access)
    return False


def _request_private(actor: Actor, access: AttachmentAccess) -> bool:
    if _customer_participant(actor, access):
        return True
    if _provider_reader(actor, access, REQUESTS_READ):
        return access.assignment_state in READABLE_ASSIGNMENT_STATES and access.within_assignment
    return False


def _equipment_private(actor: Actor, access: AttachmentAccess) -> bool:
    """Фото карточки оборудования: точка заказчика либо подтверждённая привязка исполнителя."""
    if _customer_participant(actor, access):
        return True
    if isinstance(actor, IntegrationActor):
        return REQUESTS_READ in actor.scopes and access.service_binding_confirmed
    return (
        isinstance(actor, UserActor)
        and actor.side == "provider"
        and access.service_binding_confirmed
    )


def _request_sensitive(actor: Actor, access: AttachmentAccess) -> bool:
    if isinstance(actor, OperatorActor):
        return True
    if _customer_participant(actor, access):
        return True
    if _provider_reader(actor, access, REQUESTS_READ):
        if access.assignment_state not in READABLE_ASSIGNMENT_STATES:
            return False
        if not access.within_assignment:
            return False
        if access.assignment_route == "own_service":
            return True
        return access.assignment_state in CONFIRMED_ASSIGNMENT_STATES
    return False


def _public_card(actor: Actor, access: AttachmentAccess, marketplace_visible: bool) -> bool:
    if isinstance(actor, OperatorActor):
        return True
    if _customer_participant(actor, access):
        return True
    if not (access.card_open and access.listed_in_card):
        return False
    if access.publication_state == ModerationStatus.REMOVED:
        return False
    if isinstance(actor, IntegrationActor):
        return MARKETPLACE_READ in actor.scopes and marketplace_visible
    if isinstance(actor, UserActor) and actor.side == "provider":
        return marketplace_visible
    return False


def _moderated_public(actor: Actor, access: AttachmentAccess) -> bool:
    if isinstance(actor, OperatorActor):
        return True
    if access.publication_state != ModerationStatus.PUBLISHED:
        return _owns_moderated(actor, access)
    return isinstance(actor, UserActor | BareUserActor | IntegrationActor)


def _owns_moderated(actor: Actor, access: AttachmentAccess) -> bool:
    """До публикации своё изображение видит только его сторона: у организации в двух
    ролях портфолио исполнителя не видно её стороне заказчика, и наоборот."""
    if not isinstance(actor, UserActor):
        return False
    if (
        access.provider_org_id is not None
        and actor.side == "provider"
        and actor.organization_id == access.provider_org_id
    ):
        return True
    return (
        access.review_customer_org_id is not None
        and actor.side == "customer"
        and actor.organization_id == access.review_customer_org_id
    )


VERIFICATION_ROLES = frozenset({"provider_admin", "customer_manager"})


def _verification_evidence(actor: Actor, access: AttachmentAccess) -> bool:
    if isinstance(actor, OperatorActor):
        return True
    return (
        isinstance(actor, UserActor)
        and actor.role in VERIFICATION_ROLES
        and access.verification_org_id is not None
        and actor.organization_id == access.verification_org_id
    )


def _customer_participant(actor: Actor, access: AttachmentAccess) -> bool:
    if not isinstance(actor, UserActor) or actor.side != "customer":
        return False
    if access.customer_org_id is None or actor.organization_id != access.customer_org_id:
        return False
    return actor.location_ids is None or access.location_id in actor.location_ids


def _provider_reader(actor: Actor, access: AttachmentAccess, scope: str) -> bool:
    """Исполнитель читает только по собственному назначению: оно загружено для его организации."""
    if access.assignment_state is None:
        return False
    if isinstance(actor, IntegrationActor):
        return scope in actor.scopes
    return isinstance(actor, UserActor) and actor.side == "provider"
