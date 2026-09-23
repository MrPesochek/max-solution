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
    """Имена команд — дословно из таблицы переходов."""

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
    """Строка таблицы: команда × допустимые исходные статусы → целевой статус.

    `to_status=None` — команда меняет агрегат, но не статус заявки (колонка «≠»).
    `initial=True` — заявки ещё нет, исходный статус не проверяется.
    `versioned=False` — переписка, отклики биржи и напоминания: они не входят в
    согласуемое состояние заявки и не должны обесценивать открытые формы с
    `expected_version`. Актуальность отклика проверяет сама команда выбора.
    """

    rows: str
    command: RequestCommand
    from_statuses: frozenset[str]
    to_status: str | None
    event_type: str
    initial: bool = False
    versioned: bool = True


def _t(
    rows: str,
    command: RequestCommand,
    from_statuses: tuple[str, ...],
    to_status: str | None,
    event_type: str,
    *,
    initial: bool = False,
    versioned: bool = True,
) -> Transition:
    return Transition(
        rows, command, frozenset(from_statuses), to_status, event_type, initial, versioned
    )


_ACTIVE_WORK = (S.ACCEPTED, S.SCHEDULED, S.IN_PROGRESS)
_NON_TERMINAL = tuple(s for s in S if s not in (S.CLOSED, S.CANCELLED))

TRANSITIONS: tuple[Transition, ...] = (
    _t("T1", C.CREATE_DRAFT, (), S.DRAFT, "RequestDrafted", initial=True),
    _t("T2", C.UPDATE_DRAFT, (S.DRAFT,), None, "RequestDraftUpdated"),
    _t("T3", C.SUBMIT_FOR_APPROVAL, (S.DRAFT,), S.APPROVAL_REQUIRED, "RequestSubmittedForApproval"),
    _t(
        "T4,T9,T55",
        C.SUBMIT_TO_OWN_SERVICE,
        (S.DRAFT, S.APPROVAL_REQUIRED, S.ACTION_REQUIRED),
        S.AWAITING_PROVIDER,
        "RequestSubmittedToOwnService",
    ),
    _t(
        "T5,T8,T54",
        C.PUBLISH_SEARCH,
        (S.DRAFT, S.APPROVAL_REQUIRED, S.ACTION_REQUIRED),
        S.SEARCHING,
        "SearchPublished",
    ),
    _t(
        "T5,S5",
        C.PUBLISH_SEARCH,
        (S.DRAFT, S.APPROVAL_REQUIRED, S.ACTION_REQUIRED),
        S.ACTION_REQUIRED,
        "SearchFoundNoProviders",
    ),
    _t(
        "T6,T10,T14,T21,T27,T57",
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
        "T21,T27,S4",
        C.REQUEST_CANCELLATION,
        (S.SEARCHING, S.AWAITING_ASSIGNMENT_CONFIRMATION),
        S.ACTION_REQUIRED,
        "SearchStopped",
    ),
    _t("T7", C.RETURN_TO_DRAFT, (S.APPROVAL_REQUIRED,), S.DRAFT, "RequestReturnedToDraft"),
    _t("T11", C.ACCEPT_REQUEST, (S.AWAITING_PROVIDER,), S.ACCEPTED, "AssignmentAccepted"),
    _t("T12", C.DECLINE_REQUEST, (S.AWAITING_PROVIDER,), S.ACTION_REQUIRED, "AssignmentDeclined"),
    _t("T13", C.REVOKE_ASSIGNMENT, (S.AWAITING_PROVIDER,), S.ACTION_REQUIRED, "AssignmentRevoked"),
    _t("T15", C.REMIND_OWN_SERVICE_NO_ANSWER, (S.AWAITING_PROVIDER,), None, "OwnServiceReminded"),
    _t("T16", C.SUBMIT_OFFER, (S.SEARCHING,), None, "OfferSubmitted", versioned=False),
    _t("T17", C.WITHDRAW_OFFER, (S.SEARCHING,), None, "OfferWithdrawn", versioned=False),
    _t(
        "T18",
        C.EXPIRE_OFFER,
        (S.SEARCHING, S.AWAITING_ASSIGNMENT_CONFIRMATION),
        None,
        "OfferExpired",
        versioned=False,
    ),
    _t(
        "T19",
        C.SELECT_OFFER,
        (S.SEARCHING,),
        S.AWAITING_ASSIGNMENT_CONFIRMATION,
        "OfferSelected",
    ),
    _t("T20", C.EXPIRE_SEARCH, (S.SEARCHING,), S.ACTION_REQUIRED, "SearchExpired"),
    _t(
        "T22",
        C.CONFIRM_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.SCHEDULED,
        "AssignmentConfirmed",
    ),
    _t(
        "T23",
        C.CONFIRM_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.ACCEPTED,
        "AssignmentConfirmed",
    ),
    _t(
        "T24",
        C.DECLINE_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.SEARCHING,
        "AssignmentDeclined",
    ),
    _t(
        "T24,D21",
        C.DECLINE_ASSIGNMENT,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.ACTION_REQUIRED,
        "AssignmentDeclined",
    ),
    _t(
        "T25",
        C.EXPIRE_ASSIGNMENT_CONFIRMATION,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.SEARCHING,
        "AssignmentExpired",
    ),
    _t(
        "T26",
        C.EXPIRE_ASSIGNMENT_CONFIRMATION,
        (S.AWAITING_ASSIGNMENT_CONFIRMATION,),
        S.ACTION_REQUIRED,
        "AssignmentExpired",
    ),
    _t("T28,T42", C.PROPOSE_VISIT, (S.ACCEPTED, S.IN_PROGRESS), None, "VisitProposed"),
    _t("T36", C.PROPOSE_VISIT, (S.SCHEDULED,), S.ACCEPTED, "VisitProposalSuperseded"),
    _t("T29", C.APPROVE_VISIT_PROPOSAL, (S.ACCEPTED,), S.SCHEDULED, "VisitAgreed"),
    _t("T43", C.APPROVE_VISIT_PROPOSAL, (S.IN_PROGRESS,), None, "VisitAgreed"),
    _t(
        "T30,T43",
        C.REJECT_VISIT_PROPOSAL,
        (S.ACCEPTED, S.IN_PROGRESS),
        None,
        "VisitProposalRejected",
    ),
    _t(
        "T31",
        C.EXPIRE_VISIT_PROPOSAL,
        (S.ACCEPTED, S.IN_PROGRESS, S.CANCELLATION_PENDING),
        None,
        "VisitProposalExpired",
    ),
    _t(
        "T32,T38",
        C.WITHDRAW_ASSIGNMENT,
        (S.ACCEPTED, S.SCHEDULED),
        S.ACTION_REQUIRED,
        "AssignmentWithdrawn",
    ),
    _t(
        "T33,T39,T44",
        C.REQUEST_CANCELLATION,
        _ACTIVE_WORK,
        S.CANCELLATION_PENDING,
        "CancellationRequested",
    ),
    _t(
        "T34,T40,T45",
        C.FORCE_CANCELLATION,
        (*_ACTIVE_WORK, S.CANCELLATION_PENDING),
        S.CANCELLED,
        "CancellationForced",
    ),
    _t(
        "T35,T40,T45",
        C.FORCE_CANCELLATION,
        (*_ACTIVE_WORK, S.CANCELLATION_PENDING),
        S.ACTION_REQUIRED,
        "CancellationForced",
    ),
    _t("T37", C.START_WORK, (S.SCHEDULED,), S.IN_PROGRESS, "WorkStarted"),
    _t("T41", C.COMPLETE_WORK, (S.IN_PROGRESS,), S.COMPLETION_REPORTED, "CompletionReported"),
    _t("T46", C.CONFIRM_COMPLETION, (S.COMPLETION_REPORTED,), S.CLOSED, "RequestClosed"),
    _t("T47", C.REJECT_COMPLETION, (S.COMPLETION_REPORTED,), S.IN_PROGRESS, "CompletionRejected"),
    _t("T48", C.AUTO_CLOSE_COMPLETION, (S.COMPLETION_REPORTED,), S.CLOSED, "RequestClosed"),
    _t(
        "T49",
        C.REMIND_CUSTOMER_CONFIRMATION,
        (S.COMPLETION_REPORTED,),
        None,
        "CompletionReminderSent",
        versioned=False,
    ),
    _t("T50", C.ACCEPT_CANCELLATION, (S.CANCELLATION_PENDING,), S.CANCELLED, "RequestCancelled"),
    _t(
        "T51",
        C.ACCEPT_CANCELLATION,
        (S.CANCELLATION_PENDING,),
        S.ACTION_REQUIRED,
        "AssignmentRevoked",
    ),
    _t(
        "T52", C.DECLINE_CANCELLATION, (S.CANCELLATION_PENDING,), S.ACCEPTED, "CancellationDisputed"
    ),
    _t(
        "T52",
        C.DECLINE_CANCELLATION,
        (S.CANCELLATION_PENDING,),
        S.SCHEDULED,
        "CancellationDisputed",
    ),
    _t(
        "T52",
        C.DECLINE_CANCELLATION,
        (S.CANCELLATION_PENDING,),
        S.IN_PROGRESS,
        "CancellationDisputed",
    ),
    _t(
        "T53",
        C.WITHDRAW_CANCELLATION_REQUEST,
        (S.CANCELLATION_PENDING,),
        S.ACCEPTED,
        "CancellationWithdrawn",
    ),
    _t(
        "T53",
        C.WITHDRAW_CANCELLATION_REQUEST,
        (S.CANCELLATION_PENDING,),
        S.SCHEDULED,
        "CancellationWithdrawn",
    ),
    _t(
        "T53",
        C.WITHDRAW_CANCELLATION_REQUEST,
        (S.CANCELLATION_PENDING,),
        S.IN_PROGRESS,
        "CancellationWithdrawn",
    ),
    _t(
        "T53",
        C.WITHDRAW_CANCELLATION_REQUEST,
        _ACTIVE_WORK,
        None,
        "CancellationWithdrawn",
    ),
    _t("T56", C.UPDATE_REQUEST_DETAILS, (S.ACTION_REQUIRED,), None, "RequestDetailsUpdated"),
    _t("T58", C.CREATE_LINKED_REQUEST, (), S.DRAFT, "LinkedRequestCreated", initial=True),
    _t(
        "T59",
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
        "T60",
        C.POST_OFFER_DIALOG_MESSAGE,
        (S.SEARCHING,),
        None,
        "MessageCreated",
        versioned=False,
    ),
    _t("T63", C.LINK_EXTERNAL_REFERENCE, _NON_TERMINAL, None, "ExternalReferenceLinked"),
    _t("T64", C.CREATE_REPAIR_QUOTE, _ACTIVE_WORK, None, "RepairQuoteCreated"),
    _t("T65", C.APPROVE_REPAIR_QUOTE, _ACTIVE_WORK, None, "RepairQuoteApproved"),
    _t("T66", C.REJECT_REPAIR_QUOTE, _ACTIVE_WORK, None, "RepairQuoteRejected"),
    _t(
        "T67",
        C.EXPIRE_REPAIR_QUOTE,
        (*_ACTIVE_WORK, S.CANCELLATION_PENDING),
        None,
        "RepairQuoteExpired",
    ),
    _t(
        "T68",
        C.SUBMIT_WARRANTY_DECISION,
        (*_ACTIVE_WORK, S.COMPLETION_REPORTED),
        None,
        "WarrantyDecisionStated",
    ),
    _t(
        "T69",
        C.ASSIGN_FIELD_WORKER,
        (*_ACTIVE_WORK, S.COMPLETION_REPORTED),
        None,
        "FieldWorkerAssigned",
    ),
    _t("T70", C.MARK_EN_ROUTE, (S.SCHEDULED,), None, "FieldWorkerEnRoute"),
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
    """Проверяет допустимость по таблице, меняет статус, версию и пишет request_events."""
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
