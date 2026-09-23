import uuid
from datetime import datetime, timedelta

from app.core import ids
from app.core.errors import Conflict, NotFound
from app.core.locking import check_version
from app.core.pipeline import CommandContext, CommandResult, Handler
from app.db.enums import (
    AssignmentState,
    CancellationResolutionKind,
    CancellationStatus,
    CancellationTarget,
    IntegrationEventType,
    RequestStatus,
)
from app.db.models import Assignment, CancellationRequest, RepairRequest
from app.infra.config import get_settings
from app.modules.requests import policy, queries, recipients, search, support, views
from app.modules.requests.transitions import RequestCommand as C
from app.modules.requests.transitions import apply_transition


def request_cancellation(
    request_id: uuid.UUID,
    *,
    target: str,
    reason: str | None,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        support.one_of(target, {str(t) for t in CancellationTarget}, "target")
        policy.ensure_command_allowed(ctx.actor, C.REQUEST_CANCELLATION)
        request = await support.locked_request(ctx, request_id)
        user = policy.ensure_customer_request(ctx.actor, request)
        check_version(request.version, expected_version)

        assignment = await queries.active_assignment(ctx.session, request.id)
        if assignment is None or assignment.state == AssignmentState.PENDING:
            if target == CancellationTarget.CHANGE_PROVIDER:
                return await _change_provider_before_acceptance(ctx, request, assignment, reason)
            return await _cancel_before_acceptance(ctx, request, assignment, reason)

        if await queries.open_cancellation(ctx.session, request.id) is not None:
            raise Conflict("Запрос отмены уже открыт", code="CANCELLATION_ALREADY_OPEN")

        cancellation = CancellationRequest(
            request_id=request.id,
            assignment_id=assignment.id,
            target=target,
            previous_status=request.status,
            initiated_by_membership_id=user.membership_id,
            reason=reason,
            status=CancellationStatus.PENDING,
            disputed=False,
            dispute_deadline_at=ctx.now + dispute_timeout(),
        )
        ctx.session.add(cancellation)
        await support.flush_unique(ctx)

        apply_transition(
            ctx,
            request,
            C.REQUEST_CANCELLATION,
            RequestStatus.CANCELLATION_PENDING,
            cancellation_id=ids.encode("cancellation", cancellation.id),
            target=target,
            reason=reason,
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.CANCELLATION_REQUESTED,
            request,
            assignment,
            extra={
                "cancellation": views.to_cancellation_view(cancellation).model_dump(mode="json")
            },
        )
        await recipients.notify_provider(
            ctx,
            request,
            assignment,
            "cancellation.requested",
            payload={"cancellation_id": ids.encode("cancellation", cancellation.id)},
        )
        support.audit(ctx, C.REQUEST_CANCELLATION, request, target=target)
        return await support.customer_result(
            ctx, request, assignment=assignment, cancellation=cancellation
        )

    return handler


async def _cancel_before_acceptance(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment | None,
    reason: str | None,
) -> CommandResult:
    """I14/A15: до принятия исполнителем отмена применяется сразу."""
    request.cancellation_reason = reason
    if assignment is not None:
        _revoke(ctx, assignment, reason)
    apply_transition(
        ctx,
        request,
        C.CANCEL_REQUEST,
        RequestStatus.CANCELLED,
        reason=reason,
        assignment_id=ids.encode_opt(
            "assignment", assignment.id if assignment is not None else None
        ),
    )
    await search.close_search(ctx, request, reason="request_cancelled")
    await support.supersede_children(ctx, request)
    if assignment is not None:
        recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="customer_revoked")
        await recipients.notify_provider(ctx, request, assignment, "request.cancelled")
    support.audit(ctx, C.CANCEL_REQUEST, request)
    return await support.customer_result(ctx, request, assignment=assignment)


async def _change_provider_before_acceptance(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment | None,
    reason: str | None,
) -> CommandResult:
    """ТЗ 8.1/S4: смена исполнителя до принятия не отменяет заявку.

    Ожидающее назначение отзывается, подбор закрывается, заявка переходит в
    `action_required` — новый маршрут выбирает руководитель (A11).
    """
    if request.status == RequestStatus.AWAITING_PROVIDER:
        if assignment is None:
            raise Conflict("По заявке нет активного назначения", code="ASSIGNMENT_NOT_ACTIVE")
        return await revoke_pending(ctx, request, assignment, reason)

    if assignment is not None:
        _revoke(ctx, assignment, reason)
    apply_transition(
        ctx,
        request,
        C.REQUEST_CANCELLATION,
        RequestStatus.ACTION_REQUIRED,
        target=str(CancellationTarget.CHANGE_PROVIDER),
        reason=reason,
        assignment_id=ids.encode_opt(
            "assignment", assignment.id if assignment is not None else None
        ),
    )
    await search.close_search(ctx, request, reason="provider_change")
    await support.supersede_children(ctx, request)
    if assignment is not None:
        recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="customer_revoked")
        await recipients.notify_provider(ctx, request, assignment, "assignment.revoked")
    support.audit(
        ctx, C.REQUEST_CANCELLATION, request, target=str(CancellationTarget.CHANGE_PROVIDER)
    )
    return await support.customer_result(ctx, request, assignment=assignment)


def _revoke(ctx: CommandContext, assignment: Assignment, reason: str | None) -> None:
    assignment.state = AssignmentState.REVOKED
    assignment.revoke_reason = reason
    assignment.responded_at = ctx.now


async def revoke_pending(
    ctx: CommandContext, request: RepairRequest, assignment: Assignment, reason: str | None
) -> CommandResult:
    """T13: отзыв ещё не принятого назначения своего сервиса."""
    if assignment.state != AssignmentState.PENDING:
        raise Conflict(
            "Назначение уже не ожидает ответа",
            code="ASSIGNMENT_NOT_ACTIVE",
            assignment_state=assignment.state,
        )
    _revoke(ctx, assignment, reason)
    apply_transition(
        ctx,
        request,
        C.REVOKE_ASSIGNMENT,
        RequestStatus.ACTION_REQUIRED,
        assignment_id=ids.encode("assignment", assignment.id),
        reason=reason,
    )
    recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="customer_revoked")
    await recipients.notify_provider(ctx, request, assignment, "assignment.revoked")
    support.audit(ctx, C.REVOKE_ASSIGNMENT, request)
    return await support.customer_result(ctx, request, assignment=assignment)


def revoke_pending_assignment(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    reason: str | None,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        policy.ensure_command_allowed(ctx.actor, C.REVOKE_ASSIGNMENT)
        request = await support.locked_request(ctx, request_id)
        policy.ensure_customer_request(ctx.actor, request)
        check_version(request.version, expected_version)

        assignment = await queries.get_assignment(ctx.session, assignment_id)
        if assignment is None or assignment.request_id != request.id:
            raise NotFound()
        return await revoke_pending(ctx, request, assignment, reason)

    return handler


def withdraw_cancellation(
    request_id: uuid.UUID, *, cancellation_id: uuid.UUID, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.WITHDRAW_CANCELLATION_REQUEST, expected_version
        )
        cancellation = await _open_cancellation(ctx, request, cancellation_id)
        cancellation.status = CancellationStatus.WITHDRAWN
        cancellation.resolved_at = ctx.now
        cancellation.resolution_kind = CancellationResolutionKind.MANUAL

        to_status = (
            cancellation.previous_status
            if request.status == RequestStatus.CANCELLATION_PENDING
            else None
        )
        apply_transition(
            ctx,
            request,
            C.WITHDRAW_CANCELLATION_REQUEST,
            to_status,
            cancellation_id=ids.encode("cancellation", cancellation.id),
        )

        assignment = await queries.get_assignment(ctx.session, cancellation.assignment_id)
        assert assignment is not None
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="cancellation_withdrawn",
        )
        await recipients.notify_provider(ctx, request, assignment, "cancellation.withdrawn")
        support.audit(ctx, C.WITHDRAW_CANCELLATION_REQUEST, request)
        return await support.customer_result(
            ctx, request, assignment=assignment, cancellation=cancellation
        )

    return handler


def force_cancellation(
    request_id: uuid.UUID, *, cancellation_id: uuid.UUID, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.FORCE_CANCELLATION, expected_version
        )
        cancellation = await _open_cancellation(ctx, request, cancellation_id)
        provider_silent = cancellation.status == CancellationStatus.PENDING
        deadline = response_deadline(cancellation)
        if deadline is None or deadline > ctx.now:
            raise Conflict(
                "Срок ожидания ответа исполнителя ещё не истёк",
                code="DISPUTE_PERIOD_ACTIVE",
                dispute_deadline_at=deadline.isoformat() if deadline else None,
            )

        assignment = await queries.get_assignment(ctx.session, cancellation.assignment_id)
        assert assignment is not None

        cancellation.status = CancellationStatus.FORCE_CLOSED
        cancellation.disputed = not provider_silent
        cancellation.resolution_kind = CancellationResolutionKind.CUSTOMER_UNILATERAL
        cancellation.resolved_at = ctx.now
        assignment.state = AssignmentState.REVOKED
        assignment.responded_at = ctx.now
        request.disputed = True
        await support.supersede_children(ctx, request)

        to_status = (
            RequestStatus.CANCELLED
            if cancellation.target == CancellationTarget.CANCEL_REQUEST
            else RequestStatus.ACTION_REQUIRED
        )
        if to_status == RequestStatus.CANCELLED:
            request.cancellation_reason = cancellation.reason
        apply_transition(
            ctx,
            request,
            C.FORCE_CANCELLATION,
            to_status,
            cancellation_id=ids.encode("cancellation", cancellation.id),
            target=cancellation.target,
            provider_silent=provider_silent,
        )
        recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="cancellation")
        await recipients.notify_provider(ctx, request, assignment, "cancellation.forced")
        support.audit(
            ctx,
            C.FORCE_CANCELLATION,
            request,
            target=cancellation.target,
            provider_silent=provider_silent,
        )
        return await support.customer_result(
            ctx, request, assignment=assignment, cancellation=cancellation
        )

    return handler


def dispute_timeout() -> timedelta:
    return timedelta(seconds=get_settings().cancel_dispute_timeout_seconds)


def response_deadline(cancellation: CancellationRequest) -> datetime | None:
    """Когда руководитель может прекратить работы сам.

    В споре — срок из ответа исполнителя; без ответа — срок от запроса (запросы,
    открытые до появления срока в строке, считаются от `created_at`)."""
    if cancellation.status == CancellationStatus.DISPUTED:
        return cancellation.dispute_deadline_at
    if cancellation.status == CancellationStatus.PENDING:
        return cancellation.dispute_deadline_at or cancellation.created_at + dispute_timeout()
    return None


async def _open_cancellation(
    ctx: CommandContext, request: RepairRequest, cancellation_id: uuid.UUID
) -> CancellationRequest:
    cancellation = await queries.get_cancellation(ctx.session, cancellation_id)
    if cancellation is None or cancellation.request_id != request.id:
        raise NotFound()
    if cancellation.status not in (CancellationStatus.PENDING, CancellationStatus.DISPUTED):
        raise Conflict("Запрос отмены уже закрыт", code="CANCELLATION_CLOSED")
    return cancellation


def respond_cancellation(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    cancellation_id: uuid.UUID,
    decision: str,
    comment: str | None,
    expected_version: int | None,
) -> Handler:
    accept = decision == "accept"
    command = C.ACCEPT_CANCELLATION if accept else C.DECLINE_CANCELLATION

    async def handler(ctx: CommandContext) -> CommandResult:
        support.one_of(decision, {"accept", "decline"}, "decision")
        text = comment
        if not accept:
            text = support.required_text(comment, "Укажите причину несогласия", "comment")
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, command, expected_version
        )
        cancellation = await queries.get_cancellation(ctx.session, cancellation_id)
        if cancellation is None or cancellation.request_id != request.id:
            raise NotFound()
        if cancellation.status != CancellationStatus.PENDING:
            raise Conflict("Запрос отмены уже обработан", code="CANCELLATION_CLOSED")
        cancellation.provider_response = text

        if accept:
            cancellation.status = CancellationStatus.ACCEPTED
            cancellation.resolution_kind = CancellationResolutionKind.PROVIDER_CONFIRMED
            cancellation.resolved_at = ctx.now
            cancellation.resolved_by_membership_id = policy.acting_membership_id(ctx.actor)
            assignment.state = AssignmentState.REVOKED
            assignment.responded_at = ctx.now
            await support.supersede_children(ctx, request)
            to_status = (
                RequestStatus.CANCELLED
                if cancellation.target == CancellationTarget.CANCEL_REQUEST
                else RequestStatus.ACTION_REQUIRED
            )
            if to_status == RequestStatus.CANCELLED:
                request.cancellation_reason = cancellation.reason
            apply_transition(
                ctx,
                request,
                C.ACCEPT_CANCELLATION,
                to_status,
                cancellation_id=ids.encode("cancellation", cancellation.id),
                target=cancellation.target,
            )
            recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="cancellation")
            await recipients.notify_customer(ctx, request, "cancellation.accepted")
        else:
            cancellation.status = CancellationStatus.DISPUTED
            cancellation.disputed = True
            cancellation.dispute_deadline_at = ctx.now + dispute_timeout()
            apply_transition(
                ctx,
                request,
                C.DECLINE_CANCELLATION,
                cancellation.previous_status,
                cancellation_id=ids.encode("cancellation", cancellation.id),
                comment=text,
            )
            recipients.emit_provider_event(
                ctx,
                IntegrationEventType.REQUEST_CHANGED,
                request,
                assignment,
                change_kind="cancellation_disputed",
            )
            await recipients.notify_customer(
                ctx, request, "cancellation.disputed", managers_only=True
            )
        support.audit(ctx, command, request, decision=decision)
        return await support.provider_result(ctx, request, assignment, cancellation=cancellation)

    return handler
