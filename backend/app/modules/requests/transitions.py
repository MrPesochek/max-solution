import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.actor import Actor, IntegrationActor, OperatorActor, UserActor
from app.core.errors import InvalidTransition
from app.core.pipeline import CommandContext
from app.db.enums import RequestStatus as S
from app.db.models import RepairRequest, RequestEvent


class RequestCommand(StrEnum):
    CREATE_DRAFT = "CreateDraft"
    UPDATE_DRAFT = "UpdateDraft"
    SUBMIT_FOR_APPROVAL = "SubmitForApproval"
    SUBMIT_TO_OWN_SERVICE = "SubmitToOwnService"
    PUBLISH_SEARCH = "PublishSearch"
    CANCEL_REQUEST = "CancelRequest"
    RETURN_TO_DRAFT = "ReturnToDraft"
    ACCEPT_REQUEST = "AcceptRequest"
    DECLINE_REQUEST = "DeclineRequest"
    REVOKE_ASSIGNMENT = "RevokeAssignment"
    REMIND_OWN_SERVICE_NO_ANSWER = "RemindOwnServiceNoAnswer"
    SUBMIT_OFFER = "SubmitOffer"
    WITHDRAW_OFFER = "WithdrawOffer"
    EXPIRE_OFFER = "ExpireOffer"
    SELECT_OFFER = "SelectOffer"
    EXPIRE_SEARCH = "ExpireSearch"
    CONFIRM_ASSIGNMENT = "ConfirmAssignment"
    DECLINE_ASSIGNMENT = "DeclineAssignment"
    EXPIRE_ASSIGNMENT_CONFIRMATION = "ExpireAssignmentConfirmation"
    PROPOSE_VISIT = "ProposeVisit"
    APPROVE_VISIT_PROPOSAL = "ApproveVisitProposal"
    REJECT_VISIT_PROPOSAL = "RejectVisitProposal"
    EXPIRE_VISIT_PROPOSAL = "ExpireVisitProposal"
    WITHDRAW_ASSIGNMENT = "WithdrawAssignment"
    REQUEST_CANCELLATION = "RequestCancellation"
    FORCE_CANCELLATION = "ForceCancellation"
    START_WORK = "StartWork"
    COMPLETE_WORK = "CompleteWork"
    CONFIRM_COMPLETION = "ConfirmCompletion"
    REJECT_COMPLETION = "RejectCompletion"
    AUTO_CLOSE_COMPLETION = "AutoCloseCompletion"
    REMIND_CUSTOMER_CONFIRMATION = "RemindCustomerConfirmation"
    ACCEPT_CANCELLATION = "RespondCancellationAccept"
    DECLINE_CANCELLATION = "RespondCancellationDecline"
    WITHDRAW_CANCELLATION_REQUEST = "WithdrawCancellationRequest"
    UPDATE_REQUEST_DETAILS = "UpdateRequestDetails"
    CREATE_LINKED_REQUEST = "CreateLinkedRequest"
    POST_MESSAGE = "PostMessage"
    POST_OFFER_DIALOG_MESSAGE = "PostOfferDialogMessage"
    LINK_EXTERNAL_REFERENCE = "LinkExternalReference"
    CREATE_REPAIR_QUOTE = "CreateRepairQuote"
    APPROVE_REPAIR_QUOTE = "RespondRepairQuoteApprove"
    REJECT_REPAIR_QUOTE = "RespondRepairQuoteReject"
    EXPIRE_REPAIR_QUOTE = "ExpireRepairQuote"
    SUBMIT_WARRANTY_DECISION = "SubmitWarrantyDecision"
    ASSIGN_FIELD_WORKER = "AssignFieldWorker"
    MARK_EN_ROUTE = "MarkEnRoute"


C = RequestCommand


@dataclass(frozen=True, slots=True)
class Transition:
    command: RequestCommand
    from_statuses: frozenset[str]
    to_status: str | None
    event_type: str
    initial: bool = False
    versioned: bool = True


def _t(
    command: RequestCommand,
    from_statuses: tuple[str, ...],
    to_status: str | None,
    event_type: str,
    *,
    initial: bool = False,
    versioned: bool = True,
) -> Transition:
    return Transition(command, frozenset(from_statuses), to_status, event_type, initial, versioned)


_ACTIVE_WORK = (S.ACCEPTED, S.SCHEDULED, S.IN_PROGRESS)
_NON_TERMINAL = tuple(s for s in S if s not in (S.CLOSED, S.CANCELLED))

TRANSITIONS: tuple[Transition, ...] = (
    _t(C.CREATE_DRAFT, (), S.DRAFT, "RequestDrafted", initial=True),
    _t(C.UPDATE_DRAFT, (S.DRAFT,), None, "RequestDraftUpdated"),
    _t(C.SUBMIT_FOR_APPROVAL, (S.DRAFT,), S.APPROVAL_REQUIRED, "RequestSubmittedForApproval"),
    _t(
        C.SUBMIT_TO_OWN_SERVICE,
        (S.DRAFT, S.APPROVAL_REQUIRED, S.ACTION_REQUIRED),
        S.AWAITING_PROVIDER,
        "RequestSubmittedToOwnService",
    ),
    _t(
        C.PUBLISH_SEARCH,
        (S.DRAFT, S.APPROVAL_REQUIRED, S.ACTION_REQUIRED),
        S.SEARCHING,
        "SearchPublished",
    ),
    _t(
        C.PUBLISH_SEARCH,
        (S.DRAFT, S.APPROVAL_REQUIRED, S.ACTION_REQUIRED),
        S.ACTION_REQUIRED,
        "SearchFoundNoProviders",
    ),
    _t(
        C.CANCEL_REQUEST,
        (
            S.DRAFT,
            S.APPROVAL_REQUIRED,
            S.AWAITING_PROVIDER,
            S.SEARCHING,
            S.AWAITING_ASSIGNMENT_CONFIRMATION,
            S.ACTION_REQUIRED,
        ),
        S.CANCELLED,
        "RequestCancelled",
    ),
    _t(
        C.REQUEST_CANCELLATION,
        (S.SEARCHING, S.AWAITING_ASSIGNMENT_CONFIRMATION),
        S.ACTION_REQUIRED,
        "SearchStopped",
    ),
    _t(C.RETURN_TO_DRAFT, (S.APPROVAL_REQUIRED,), S.DRAFT, "RequestReturnedToDraft"),
    _t(C.ACCEPT_REQUEST, (S.AWAITING_PROVIDER,), S.ACCEPTED, "AssignmentAccepted"),
    _t(C.DECLINE_REQUEST, (S.AWAITING_PROVIDER,), S.ACTION_REQUIRED, "AssignmentDeclined"),
    _t(C.REVOKE_ASSIGNMENT, (S.AWAITING_PROVIDER,), S.ACTION_REQUIRED, "AssignmentRevoked"),
    _t(C.REMIND_OWN_SERVICE_NO_ANSWER, (S.AWAITING_PROVIDER,), None, "OwnServiceReminded"),
    _t(C.SUBMIT_OFFER, (S.SEARCHING,), None, "OfferSubmitted", versioned=False),
    _t(C.WITHDRAW_OFFER, (S.SEARCHING,), None, "OfferWithdrawn", versioned=False),
    _t(
        C.EXPIRE_OFFER,
        (S.SEARCHING, S.AWAITING_ASSIGNMENT_CONFIRMATION),
        None,
        "OfferExpired",
        versioned=False,
    ),
    _t(
        C.SELECT_OFFER,
        (S.SEARCHING,),
        S.AWAITING_ASSIGNMENT_CONFIRMATION,
        "OfferSelected",
    ),
    _t(C.EXPIRE_SEARCH, (S.SEARCHING,), S.ACTION_REQUIRED, "SearchExpired"),
    _t(
        C.CONFIRM_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.SCHEDULED,
        "AssignmentConfirmed",
    ),
    _t(
        C.CONFIRM_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.ACCEPTED,
        "AssignmentConfirmed",
    ),
    _t(
        C.DECLINE_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.SEARCHING,
        "AssignmentDeclined",
    ),
    _t(
        C.DECLINE_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.ACTION_REQUIRED,
        "AssignmentDeclined",
    ),
    _t(
        C.EXPIRE_ASSIGNMENT_CONFIRMATION,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.SEARCHING,
        "AssignmentExpired",
    ),
    _t(
        C.EXPIRE_ASSIGNMENT_CONFIRMATION,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.ACTION_REQUIRED,
        "AssignmentExpired",
    ),
    _t(C.PROPOSE_VISIT, (S.ACCEPTED, S.IN_PROGRESS), None, "VisitProposed"),
    _t(C.PROPOSE_VISIT, (S.SCHEDULED,), S.ACCEPTED, "VisitProposalSuperseded"),
    _t(C.APPROVE_VISIT_PROPOSAL, (S.ACCEPTED,), S.SCHEDULED, "VisitAgreed"),
    _t(C.APPROVE_VISIT_PROPOSAL, (S.IN_PROGRESS,), None, "VisitAgreed"),
    _t(
        C.REJECT_VISIT_PROPOSAL,
        (S.ACCEPTED, S.IN_PROGRESS),
        None,
        "VisitProposalRejected",
    ),
    _t(
        C.EXPIRE_VISIT_PROPOSAL,
        (S.ACCEPTED, S.IN_PROGRESS, S.CANCELLATION_PENDING),
        None,
        "VisitProposalExpired",
    ),
    _t(
        C.WITHDRAW_ASSIGNMENT,
        (S.ACCEPTED, S.SCHEDULED),
        S.ACTION_REQUIRED,
        "AssignmentWithdrawn",
    ),
    _t(
        C.REQUEST_CANCELLATION,
        _ACTIVE_WORK,
        S.CANCELLATION_PENDING,
        "CancellationRequested",
    ),
    _t(
        C.FORCE_CANCELLATION,
        (*_ACTIVE_WORK, S.CANCELLATION_PENDING),
        S.CANCELLED,
        "CancellationForced",
    ),
    _t(
        C.FORCE_CANCELLATION,
        (*_ACTIVE_WORK, S.CANCELLATION_PENDING),
        S.ACTION_REQUIRED,
        "CancellationForced",
    ),
    _t(C.START_WORK, (S.SCHEDULED,), S.IN_PROGRESS, "WorkStarted"),
    _t(C.COMPLETE_WORK, (S.IN_PROGRESS,), S.COMPLETION_REPORTED, "CompletionReported"),
    _t(C.CONFIRM_COMPLETION, (S.COMPLETION_REPORTED,), S.CLOSED, "RequestClosed"),
    _t(C.REJECT_COMPLETION, (S.COMPLETION_REPORTED,), S.IN_PROGRESS, "CompletionRejected"),
    _t(C.AUTO_CLOSE_COMPLETION, (S.COMPLETION_REPORTED,), S.CLOSED, "RequestClosed"),
    _t(
        C.REMIND_CUSTOMER_CONFIRMATION,
        (S.COMPLETION_REPORTED,),
        None,
        "CompletionReminderSent",
        versioned=False,
    ),
    _t(C.ACCEPT_CANCELLATION, (S.CANCELLATION_PENDING,), S.CANCELLED, "RequestCancelled"),
    _t(
        C.ACCEPT_CANCELLATION,
        (S.CANCELLATION_PENDING,),
        S.ACTION_REQUIRED,
        "AssignmentRevoked",
    ),
    _t(C.DECLINE_CANCELLATION, (S.CANCELLATION_PENDING,), S.ACCEPTED, "CancellationDisputed"),
    _t(
        C.DECLINE_CANCELLATION,
        (S.CANCELLATION_PENDING,),
        S.SCHEDULED,
        "CancellationDisputed",
    ),
    _t(
        C.DECLINE_CANCELLATION,
        (S.CANCELLATION_PENDING,),
        S.IN_PROGRESS,
        "CancellationDisputed",
    ),
    _t(
        C.WITHDRAW_CANCELLATION_REQUEST,
        (S.CANCELLATION_PENDING,),
        S.ACCEPTED,
        "CancellationWithdrawn",
    ),
    _t(
        C.WITHDRAW_CANCELLATION_REQUEST,
        (S.CANCELLATION_PENDING,),
        S.SCHEDULED,
        "CancellationWithdrawn",
    ),
    _t(
        C.WITHDRAW_CANCELLATION_REQUEST,
        (S.CANCELLATION_PENDING,),
        S.IN_PROGRESS,
        "CancellationWithdrawn",
    ),
    _t(
        C.WITHDRAW_CANCELLATION_REQUEST,
        _ACTIVE_WORK,
        None,
        "CancellationWithdrawn",
    ),
    _t(C.UPDATE_REQUEST_DETAILS, (S.ACTION_REQUIRED,), None, "RequestDetailsUpdated"),
    _t(C.CREATE_LINKED_REQUEST, (), S.DRAFT, "LinkedRequestCreated", initial=True),
    _t(
        C.POST_MESSAGE,
        (
            S.AWAITING_PROVIDER,
            S.AWAITING_ASSIGNMENT_CONFIRMATION,
            S.ACCEPTED,
            S.SCHEDULED,
            S.IN_PROGRESS,
            S.COMPLETION_REPORTED,
            S.CANCELLATION_PENDING,
        ),
        None,
        "MessageCreated",
        versioned=False,
    ),
    _t(
        C.POST_OFFER_DIALOG_MESSAGE,
        (S.SEARCHING,),
        None,
        "MessageCreated",
        versioned=False,
    ),
    _t(C.LINK_EXTERNAL_REFERENCE, _NON_TERMINAL, None, "ExternalReferenceLinked"),
    _t(C.CREATE_REPAIR_QUOTE, _ACTIVE_WORK, None, "RepairQuoteCreated"),
    _t(C.APPROVE_REPAIR_QUOTE, _ACTIVE_WORK, None, "RepairQuoteApproved"),
    _t(C.REJECT_REPAIR_QUOTE, _ACTIVE_WORK, None, "RepairQuoteRejected"),
    _t(
        C.EXPIRE_REPAIR_QUOTE,
        (*_ACTIVE_WORK, S.CANCELLATION_PENDING),
        None,
        "RepairQuoteExpired",
    ),
    _t(
        C.SUBMIT_WARRANTY_DECISION,
        (*_ACTIVE_WORK, S.COMPLETION_REPORTED),
        None,
        "WarrantyDecisionStated",
    ),
    _t(
        C.ASSIGN_FIELD_WORKER,
        (*_ACTIVE_WORK, S.COMPLETION_REPORTED),
        None,
        "FieldWorkerAssigned",
    ),
    _t(C.MARK_EN_ROUTE, (S.SCHEDULED,), None, "FieldWorkerEnRoute"),
)


def _build_index() -> dict[tuple[RequestCommand, str | None], Transition]:
    index: dict[tuple[RequestCommand, str | None], Transition] = {}
    for row in TRANSITIONS:
        key = (row.command, row.to_status)
        if key in index:
            raise RuntimeError(f"дубль перехода {row.command} → {row.to_status}")
        index[key] = row
    return index


INDEX = _build_index()

_STATUS_TIMESTAMPS: dict[str, str] = {
    S.AWAITING_PROVIDER: "submitted_at",
    S.SEARCHING: "submitted_at",
    S.ACCEPTED: "accepted_at",
    S.SCHEDULED: "scheduled_at",
    S.IN_PROGRESS: "work_started_at",
    S.COMPLETION_REPORTED: "completion_reported_at",
    S.CLOSED: "closed_at",
    S.CANCELLED: "cancelled_at",
}


def allowed_from(command: RequestCommand, to_status: str | None) -> frozenset[str]:
    row = INDEX.get((command, to_status))
    return row.from_statuses if row is not None else frozenset()


def event_actor_fields(actor: Actor) -> dict[str, Any]:
    if isinstance(actor, UserActor):
        kind = "customer_membership" if actor.side == "customer" else "provider_membership"
        return {
            "actor_kind": kind,
            "actor_membership_id": actor.membership_id,
            "actor_user_id": actor.user_id,
        }
    if isinstance(actor, IntegrationActor):
        return {
            "actor_kind": "integration_client",
            "actor_integration_client_id": actor.integration_client_id,
        }
    if isinstance(actor, OperatorActor):
        return {"actor_kind": "operator", "actor_user_id": actor.user_id}
    return {"actor_kind": "system"}


def apply_transition(
    ctx: CommandContext,
    request: RepairRequest,
    command: RequestCommand,
    to_status: str | None = None,
    **event_payload: Any,
) -> RequestEvent:
    row = INDEX.get((command, to_status))
    if row is None or (not row.initial and request.status not in row.from_statuses):
        raise InvalidTransition(status=request.status, command=str(command), to_status=to_status)

    from_status = None if row.initial else request.status
    if to_status is not None and to_status != request.status:
        request.status = to_status
        field = _STATUS_TIMESTAMPS.get(to_status)
        if field is not None and getattr(request, field) is None:
            setattr(request, field, ctx.now)
    if not row.initial and row.versioned:
        request.version += 1

    event = RequestEvent(
        request_id=request.id,
        occurred_at=ctx.now,
        event_type=row.event_type,
        from_status=from_status,
        to_status=to_status,
        payload=_json_payload(event_payload),
        **event_actor_fields(ctx.actor),
    )
    ctx.session.add(event)
    return event


def _json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in payload.items() if v is not None
    }
