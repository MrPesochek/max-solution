import uuid

from app.core.actor import Actor, IntegrationActor, OperatorActor, SystemActor, UserActor
from app.core.errors import Conflict, Forbidden, NotFound
from app.db.enums import AssignmentState
from app.db.models import Assignment, RepairRequest
from app.modules.requests.transitions import RequestCommand as C

CUSTOMER_EMPLOYEE = "customer_employee"
CUSTOMER_MANAGER = "customer_manager"
PROVIDER_ADMIN = "provider_admin"
PROVIDER_DISPATCHER = "provider_dispatcher"
INTEGRATION_CLIENT = "integration_client"
OPERATOR = "operator"
SYSTEM = "system"

REQUESTS_READ = "requests:read"
REQUESTS_WRITE = "requests:write"
MARKETPLACE_READ = "marketplace:read"
MARKETPLACE_WRITE = "marketplace:write"

_CUSTOMER_ANY = frozenset({CUSTOMER_EMPLOYEE, CUSTOMER_MANAGER})
_MANAGER_ONLY = frozenset({CUSTOMER_MANAGER})
_PROVIDER_ANY = frozenset({PROVIDER_ADMIN, PROVIDER_DISPATCHER, INTEGRATION_CLIENT})
_SYSTEM_ONLY = frozenset({SYSTEM})

ACTIVE_ASSIGNMENT_STATES = frozenset({AssignmentState.PENDING, AssignmentState.ACCEPTED})
READABLE_ASSIGNMENT_STATES = ACTIVE_ASSIGNMENT_STATES | {AssignmentState.COMPLETED}

ROLE_MATRIX: dict[C, frozenset[str]] = {
    C.CREATE_DRAFT: _CUSTOMER_ANY,
    C.UPDATE_DRAFT: _CUSTOMER_ANY,
    C.SUBMIT_FOR_APPROVAL: _CUSTOMER_ANY,
    C.SUBMIT_TO_OWN_SERVICE: _CUSTOMER_ANY,
    C.PUBLISH_SEARCH: _MANAGER_ONLY,
    C.CANCEL_REQUEST: _CUSTOMER_ANY,
    C.RETURN_TO_DRAFT: _MANAGER_ONLY,
    C.REVOKE_ASSIGNMENT: _MANAGER_ONLY,
    C.SELECT_OFFER: _MANAGER_ONLY,
    C.APPROVE_VISIT_PROPOSAL: _MANAGER_ONLY,
    C.REJECT_VISIT_PROPOSAL: _MANAGER_ONLY,
    C.APPROVE_REPAIR_QUOTE: _MANAGER_ONLY,
    C.REJECT_REPAIR_QUOTE: _MANAGER_ONLY,
    C.REQUEST_CANCELLATION: _MANAGER_ONLY,
    C.WITHDRAW_CANCELLATION_REQUEST: _MANAGER_ONLY,
    C.FORCE_CANCELLATION: _MANAGER_ONLY,
    C.CONFIRM_COMPLETION: _MANAGER_ONLY,
    C.REJECT_COMPLETION: _MANAGER_ONLY,
    C.UPDATE_REQUEST_DETAILS: _MANAGER_ONLY,
    C.ACCEPT_REQUEST: _PROVIDER_ANY,
    C.DECLINE_REQUEST: _PROVIDER_ANY,
    C.CONFIRM_ASSIGNMENT: _PROVIDER_ANY,
    C.DECLINE_ASSIGNMENT: _PROVIDER_ANY,
    C.WITHDRAW_ASSIGNMENT: _PROVIDER_ANY,
    C.PROPOSE_VISIT: _PROVIDER_ANY,
    C.CREATE_REPAIR_QUOTE: _PROVIDER_ANY,
    C.START_WORK: _PROVIDER_ANY,
    C.COMPLETE_WORK: _PROVIDER_ANY,
    C.ACCEPT_CANCELLATION: _PROVIDER_ANY,
    C.DECLINE_CANCELLATION: _PROVIDER_ANY,
    C.SUBMIT_WARRANTY_DECISION: _PROVIDER_ANY,
    C.ASSIGN_FIELD_WORKER: _PROVIDER_ANY,
    C.MARK_EN_ROUTE: _PROVIDER_ANY,
    C.SUBMIT_OFFER: _PROVIDER_ANY,
    C.WITHDRAW_OFFER: _PROVIDER_ANY,
    C.LINK_EXTERNAL_REFERENCE: frozenset({INTEGRATION_CLIENT}),
    C.POST_MESSAGE: _CUSTOMER_ANY | _PROVIDER_ANY,
    C.POST_OFFER_DIALOG_MESSAGE: _CUSTOMER_ANY | _PROVIDER_ANY,
    C.CREATE_LINKED_REQUEST: _CUSTOMER_ANY,
    C.REMIND_OWN_SERVICE_NO_ANSWER: _SYSTEM_ONLY,
    C.REMIND_CUSTOMER_CONFIRMATION: _SYSTEM_ONLY,
    C.AUTO_CLOSE_COMPLETION: _SYSTEM_ONLY,
    C.EXPIRE_OFFER: _SYSTEM_ONLY,
    C.EXPIRE_SEARCH: _SYSTEM_ONLY,
    C.EXPIRE_ASSIGNMENT_CONFIRMATION: _SYSTEM_ONLY,
    C.EXPIRE_VISIT_PROPOSAL: _SYSTEM_ONLY,
    C.EXPIRE_REPAIR_QUOTE: _SYSTEM_ONLY,
}


COMMAND_SCOPES: dict[C, str] = {
    C.SUBMIT_OFFER: MARKETPLACE_WRITE,
    C.WITHDRAW_OFFER: MARKETPLACE_WRITE,
    C.POST_OFFER_DIALOG_MESSAGE: MARKETPLACE_WRITE,
}


def actor_role(actor: Actor) -> str:
    if isinstance(actor, UserActor):
        return actor.role
    if isinstance(actor, IntegrationActor):
        return INTEGRATION_CLIENT
    if isinstance(actor, OperatorActor):
        return OPERATOR
    if isinstance(actor, SystemActor):
        return SYSTEM
    raise Forbidden()


def ensure_command_allowed(actor: Actor, command: C) -> None:
    """Роль актора против матрицы § 5; для CRM дополнительно проверяется scope."""
    allowed = ROLE_MATRIX.get(command, frozenset())
    if actor_role(actor) not in allowed:
        raise Forbidden("Действие недоступно для вашей роли")
    if isinstance(actor, IntegrationActor):
        required = COMMAND_SCOPES.get(command, REQUESTS_WRITE)
        if required not in actor.scopes:
            raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=required)


def require_customer(actor: Actor) -> UserActor:
    if not isinstance(actor, UserActor) or actor.side != "customer":
        raise Forbidden("Действие доступно только стороне заказчика")
    return actor


def require_manager(actor: Actor) -> UserActor:
    user = require_customer(actor)
    if not user.is_manager:
        raise Forbidden("Действие доступно только руководителю заказчика")
    return user


def provider_org_id(actor: Actor) -> uuid.UUID:
    if isinstance(actor, IntegrationActor):
        return actor.organization_id
    if isinstance(actor, UserActor) and actor.side == "provider":
        return actor.organization_id
    raise Forbidden("Действие доступно только стороне исполнителя")


def acting_membership_id(actor: Actor) -> uuid.UUID | None:
    return actor.membership_id if isinstance(actor, UserActor) else None


def ensure_customer_request(actor: Actor, request: RepairRequest) -> UserActor:
    """Заявка своей организации и — для сотрудника — своей точки, иначе `NotFound`."""
    user = require_customer(actor)
    if user.organization_id != request.customer_org_id:
        raise NotFound()
    if user.location_ids is not None and request.location_id not in user.location_ids:
        raise NotFound()
    return user


def ensure_location_allowed(actor: UserActor, location_id: uuid.UUID) -> None:
    if actor.location_ids is not None and location_id not in actor.location_ids:
        raise NotFound()


def ensure_own_draft(actor: UserActor, request: RepairRequest) -> None:
    """Сотрудник отменяет только собственный черновик (§ 5, «(а) только draft»)."""
    if actor.is_manager:
        return
    if request.author_membership_id != actor.membership_id:
        raise Forbidden("Черновик создан другим сотрудником")


def ensure_assignment_belongs(
    actor: Actor, request: RepairRequest, assignment: Assignment | None
) -> Assignment:
    if assignment is None or assignment.request_id != request.id:
        raise NotFound()
    if assignment.provider_org_id != provider_org_id(actor):
        raise NotFound()
    return assignment


def ensure_assignment_active(assignment: Assignment) -> None:
    """I2/A12: поздний ответ по неактивному назначению отклоняется как устаревший."""
    if assignment.state == AssignmentState.EXPIRED:
        raise Conflict("Срок подтверждения назначения истёк", code="ASSIGNMENT_EXPIRED")
    if assignment.state not in ACTIVE_ASSIGNMENT_STATES:
        raise Conflict(
            "Назначение больше не активно",
            code="ASSIGNMENT_NOT_ACTIVE",
            assignment_state=assignment.state,
        )


def ensure_provider_read(
    actor: Actor, request: RepairRequest, assignment: Assignment | None
) -> Assignment:
    """Чтение заявки исполнителем: только по своему ещё не прекращённому назначению."""
    found = ensure_assignment_belongs(actor, request, assignment)
    if found.state not in READABLE_ASSIGNMENT_STATES:
        raise NotFound()
    return found


def discloses_contacts(assignment: Assignment) -> bool:
    """I7: адрес и рабочие контакты — после подтверждённого назначения.

    Исключение — прямое обращение своему сервису: договорной подрядчик знает
    объект и адрес до ответа, скрывать их бессмысленно (ТЗ 6.3).
    """
    if assignment.state in (AssignmentState.ACCEPTED, AssignmentState.COMPLETED):
        return True
    return assignment.state == AssignmentState.PENDING and assignment.route == "own_service"
