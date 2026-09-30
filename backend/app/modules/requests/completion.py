import uuid

from app.core import ids
from app.core.errors import Conflict
from app.core.pipeline import CommandContext, CommandResult, Handler
from app.db.enums import AssignmentState, ClosureKind, IntegrationEventType, RequestStatus
from app.db.models import Assignment, RepairRequest
from app.modules.requests import queries, recipients, support
from app.modules.requests.transitions import RequestCommand as C
from app.modules.requests.transitions import apply_transition

COMPLETION_REPORTED_EVENT = "CompletionReported"
REMINDER_EVENT = "CompletionReminderSent"


def report_completion(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    outcome: str,
    summary: str,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        support.one_of(outcome, support.OUTCOMES, "outcome")
        text = support.required_text(summary, "Опишите результат работ", "summary")
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.COMPLETE_WORK, expected_version
        )
        await support.supersede_children(ctx, request, keep_approved=True)
        apply_transition(
            ctx,
            request,
            C.COMPLETE_WORK,
            RequestStatus.COMPLETION_REPORTED,
            outcome=outcome,
            summary=text,
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="completion_reported",
            extra={"outcome": outcome, "summary": text},
        )
        await recipients.notify_customer(
            ctx, request, "completion.reported", managers_only=True, payload={"outcome": outcome}
        )
        support.audit(ctx, C.COMPLETE_WORK, request, outcome=outcome)
        return await support.provider_result(ctx, request, assignment)

    return handler


async def close_request(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment,
    *,
    command: C,
    closure_kind: ClosureKind,
) -> None:
    assignment.state = AssignmentState.COMPLETED
    await support.supersede_children(ctx, request, keep_approved=True)
    request.closure_kind = closure_kind
    apply_transition(
        ctx,
        request,
        command,
        RequestStatus.CLOSED,
        assignment_id=ids.encode("assignment", assignment.id),
        closure_kind=str(closure_kind),
    )
    recipients.emit_provider_event(ctx, IntegrationEventType.REQUEST_CLOSED, request, assignment)
    await recipients.notify_provider(ctx, request, assignment, "request.closed")


def confirm_completion(request_id: uuid.UUID, *, expected_version: int | None) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.CONFIRM_COMPLETION, expected_version
        )
        assignment = await queries.active_assignment(ctx.session, request.id)
        if assignment is None:
            raise Conflict("По заявке нет активного назначения", code="ASSIGNMENT_NOT_ACTIVE")
        await close_request(
            ctx,
            request,
            assignment,
            command=C.CONFIRM_COMPLETION,
            closure_kind=ClosureKind.CUSTOMER_CONFIRMED,
        )
        support.audit(ctx, C.CONFIRM_COMPLETION, request)
        return await support.customer_result(ctx, request, assignment=assignment)

    return handler


def reject_completion(
    request_id: uuid.UUID, *, reason: str, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        text = support.required_text(reason, "Укажите, что осталось нерешённым", "reason")
        request, _ = await support.customer_command(
            ctx, request_id, C.REJECT_COMPLETION, expected_version
        )
        assignment = await queries.active_assignment(ctx.session, request.id)
        if assignment is None:
            raise Conflict("По заявке нет активного назначения", code="ASSIGNMENT_NOT_ACTIVE")

        apply_transition(ctx, request, C.REJECT_COMPLETION, RequestStatus.IN_PROGRESS, reason=text)
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="completion_rejected",
            extra={"reason": text},
        )
        await recipients.notify_provider(ctx, request, assignment, "completion.rejected")
        support.audit(ctx, C.REJECT_COMPLETION, request)
        return await support.customer_result(ctx, request, assignment=assignment)

    return handler
