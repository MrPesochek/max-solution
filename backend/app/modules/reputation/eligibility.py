import uuid
from dataclasses import dataclass
from typing import Literal

from app.db.enums import AssignmentState
from app.db.models import RepairRequest

ReviewMode = Literal["create", "edit", "needs_admission"]

REVIEW_NOT_ALLOWED = "REVIEW_NOT_ALLOWED"
NO_ASSIGNMENT = "NO_ASSIGNMENT"

EVENT_WORK_STARTED = "WorkStarted"
EVENT_COMPLETION_REPORTED = "CompletionReported"
EVENT_REQUEST_CLOSED = "RequestClosed"
EVENT_VISIT_AGREED = "VisitAgreed"
EVENT_ASSIGNMENT_CONFIRMED = "AssignmentConfirmed"
WORK_EVENTS = (
    EVENT_WORK_STARTED,
    EVENT_COMPLETION_REPORTED,
    EVENT_REQUEST_CLOSED,
    EVENT_VISIT_AGREED,
)


@dataclass(slots=True)
class ReviewTarget:
    assignment_id: uuid.UUID
    provider_org_id: uuid.UUID
    mode: Literal["create", "needs_admission"]


@dataclass(slots=True)
class ReviewEligibility:
    allowed: bool
    mode: ReviewMode | None
    reason_code: str | None
    reason_message: str | None
    allow_no_show_complaint: bool
    assignment_id: uuid.UUID | None = None


def classify_assignment(state: str, marks: set[str]) -> Literal["create", "needs_admission"] | None:
    if (
        state == AssignmentState.COMPLETED
        or EVENT_COMPLETION_REPORTED in marks
        or EVENT_REQUEST_CLOSED in marks
    ):
        return "create"
    if EVENT_WORK_STARTED in marks:
        return "needs_admission"
    return None


def _not_allowed(code: str, message: str, *, allow_no_show: bool) -> ReviewEligibility:
    return ReviewEligibility(
        allowed=False,
        mode=None,
        reason_code=code,
        reason_message=message,
        allow_no_show_complaint=allow_no_show,
    )


def assess_review_eligibility(
    request: RepairRequest, target: ReviewTarget | None
) -> ReviewEligibility:
    if request.accepted_at is None:
        return _not_allowed(
            NO_ASSIGNMENT,
            "Отзыв доступен только по заявке с принятым назначением исполнителя",
            allow_no_show=False,
        )
    if target is None:
        return _not_allowed(
            REVIEW_NOT_ALLOWED,
            "Отмена до начала работ не даёт права на отзыв о качестве ремонта",
            allow_no_show=request.scheduled_at is not None,
        )
    if target.mode == "create":
        return ReviewEligibility(
            allowed=True,
            mode="create",
            reason_code=None,
            reason_message=None,
            allow_no_show_complaint=False,
            assignment_id=target.assignment_id,
        )
    return ReviewEligibility(
        allowed=True,
        mode="needs_admission",
        reason_code=None,
        reason_message="Допуск отзыва решает модератор по истории взаимодействия",
        allow_no_show_complaint=False,
        assignment_id=target.assignment_id,
    )
