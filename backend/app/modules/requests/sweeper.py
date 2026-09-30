import uuid
from collections.abc import Awaitable, Callable, Collection
from datetime import datetime, timedelta

import structlog
from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.sql.expression import Exists

from app.core import ids
from app.core.actor import SystemActor
from app.core.clock import utcnow
from app.core.pipeline import CommandContext, CommandResult, run_command
from app.core.quarantine import Quarantine
from app.db import session as db_session
from app.db.enums import (
    AssignmentState,
    CancellationStatus,
    ClosureKind,
    OfferStatus,
    RepairQuoteStatus,
    RequestRoute,
    RequestStatus,
    Urgency,
    VisitProposalStatus,
)
from app.db.models import (
    Assignment,
    CancellationRequest,
    Offer,
    RepairQuote,
    RepairRequest,
    RequestEvent,
    VisitProposal,
)
from app.infra.config import get_settings
from app.modules.requests import completion, queries, recipients, search, support
from app.modules.requests.transitions import RequestCommand as C
from app.modules.requests.transitions import allowed_from, apply_transition

log = structlog.get_logger("requests.sweeper")

REMINDER_EVENT = "OwnServiceReminded"
COMPLETION_REMINDERS: tuple[tuple[str, timedelta], ...] = (
    ("24h", timedelta(hours=24)),
    ("72h", timedelta(hours=72)),
)

QUARANTINE_BASE = timedelta(minutes=1)
QUARANTINE_MAX = timedelta(hours=1)

_quarantine = Quarantine(base=QUARANTINE_BASE, maximum=QUARANTINE_MAX)

Due = Callable[[datetime, int, Collection[uuid.UUID]], Awaitable[list[uuid.UUID]]]
Apply = Callable[[uuid.UUID], Awaitable[int | None]]


async def expire_due(now: datetime | None = None, *, batch: int = 50) -> dict[str, int]:
    moment = now or utcnow()
    stages: list[tuple[str, Due, Apply]] = [
        ("visit_proposals", _due_proposals, _expire_proposals),
        ("repair_quotes", _due_quotes, _expire_quotes),
        ("offers", _due_offers, _expire_offers),
        ("reservations", _due_reservations, _release_reservation),
        ("searches", _due_searches, _close_search_window),
        ("reminders", _due_reminders, _remind_own_service),
        ("cancellation_reminders", _due_cancellation_reminders, _remind_cancellation),
    ]
    if get_settings().auto_close_days > 0:
        stages.append(("auto_closed", _due_auto_close, _auto_close))
    stages.append(("completion_reminders", _due_completion_reminders, _remind_completion))

    counters = {"auto_closed": 0}
    for kind, due, apply in stages:
        counters[kind] = await _run_stage(kind, due, apply, moment, batch)
    return counters


async def expire_request(request_id: uuid.UUID) -> None:

    async def handler(ctx: CommandContext) -> CommandResult:
        request = await _lock_skipping(ctx.session, request_id)
        if request is None:
            return CommandResult({})
        await _expire_children(ctx, request, kind="visit")
        await _expire_children(ctx, request, kind="quote")
        await _expire_request_offers(ctx, request)
        await _release_due_reservation(ctx, request)
        return CommandResult({})

    try:
        await run_command(_system(), handler)
    except Exception:
        log.exception("lazy_expiry_failed", request_id=str(request_id))


def reset_quarantine() -> None:
    _quarantine.clear()


async def _run_stage(kind: str, due: Due, apply: Apply, moment: datetime, batch: int) -> int:
    held = _quarantine.held(kind, moment)
    total = 0
    for request_id in await due(moment, batch, held):
        try:
            done = await apply(request_id)
        except Exception:
            log.exception("sweeper_item_failed", kind=kind, request_id=str(request_id))
            _quarantine.hold(kind, request_id, moment)
            continue
        if done is None:
            continue
        if done == 0:
            _quarantine.hold(kind, request_id, moment)
            continue
        _quarantine.release(kind, request_id)
        total += done
    return total


def _excluding(
    stmt: Select[tuple[uuid.UUID]],
    column: InstrumentedAttribute[uuid.UUID],
    held: Collection[uuid.UUID],
) -> Select[tuple[uuid.UUID]]:
    if not held:
        return stmt
    return stmt.where(column.not_in(tuple(held)))


async def _scalars(stmt: Select[tuple[uuid.UUID]]) -> list[uuid.UUID]:
    async with db_session.transaction() as session:
        return list((await session.execute(stmt)).scalars().all())


async def _due_proposals(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    stmt = select(VisitProposal.request_id).where(
        VisitProposal.status == VisitProposalStatus.PENDING, VisitProposal.valid_until <= moment
    )
    stmt = _excluding(stmt, VisitProposal.request_id, held)
    return await _scalars(
        stmt.group_by(VisitProposal.request_id)
        .order_by(func.min(VisitProposal.valid_until))
        .limit(batch)
    )


async def _due_quotes(moment: datetime, batch: int, held: Collection[uuid.UUID]) -> list[uuid.UUID]:
    stmt = select(RepairQuote.request_id).where(
        RepairQuote.status == RepairQuoteStatus.PENDING, RepairQuote.valid_until <= moment
    )
    stmt = _excluding(stmt, RepairQuote.request_id, held)
    return await _scalars(
        stmt.group_by(RepairQuote.request_id)
        .order_by(func.min(RepairQuote.valid_until))
        .limit(batch)
    )


async def _due_offers(moment: datetime, batch: int, held: Collection[uuid.UUID]) -> list[uuid.UUID]:
    stmt = select(Offer.request_id).where(
        Offer.state == OfferStatus.ACTIVE, Offer.valid_until <= moment
    )
    stmt = _excluding(stmt, Offer.request_id, held)
    return await _scalars(
        stmt.group_by(Offer.request_id).order_by(func.min(Offer.valid_until)).limit(batch)
    )


async def _due_reservations(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    stmt = select(Assignment.request_id).where(
        Assignment.state == AssignmentState.PENDING,
        Assignment.route == RequestRoute.MARKETPLACE,
        Assignment.expires_at.is_not(None),
        Assignment.expires_at <= moment,
    )
    stmt = _excluding(stmt, Assignment.request_id, held)
    return await _scalars(stmt.order_by(Assignment.expires_at).limit(batch))


async def _due_searches(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    live_offer = exists().where(
        Offer.request_id == RepairRequest.id,
        Offer.state == OfferStatus.ACTIVE,
        Offer.valid_until > moment,
    )
    stmt = select(RepairRequest.id).where(
        RepairRequest.status == RequestStatus.SEARCHING,
        RepairRequest.search_expires_at.is_not(None),
        RepairRequest.search_expires_at <= moment,
        ~live_offer,
    )
    stmt = _excluding(stmt, RepairRequest.id, held)
    return await _scalars(stmt.order_by(RepairRequest.search_expires_at).limit(batch))


async def _due_reminders(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    settings = get_settings()
    critical = and_(
        RepairRequest.urgency == Urgency.CRITICAL,
        Assignment.created_at
        <= moment - timedelta(seconds=settings.own_service_reminder_critical_seconds),
    )
    regular = and_(
        RepairRequest.urgency != Urgency.CRITICAL,
        Assignment.created_at <= moment - timedelta(seconds=settings.own_service_reminder_seconds),
    )
    stmt = (
        select(RepairRequest.id)
        .join(Assignment, Assignment.request_id == RepairRequest.id)
        .where(
            RepairRequest.status == RequestStatus.AWAITING_PROVIDER,
            Assignment.state == AssignmentState.PENDING,
            Assignment.reminded_at.is_(None),
            or_(critical, regular),
        )
    )
    stmt = _excluding(stmt, RepairRequest.id, held)
    return await _scalars(stmt.order_by(Assignment.created_at).limit(batch))


def _cancellation_deadline() -> ColumnElement[datetime]:
    timeout = timedelta(seconds=get_settings().cancel_dispute_timeout_seconds)
    return func.coalesce(
        CancellationRequest.dispute_deadline_at, CancellationRequest.created_at + timeout
    )


async def _due_cancellation_reminders(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    stmt = select(CancellationRequest.request_id).where(
        CancellationRequest.status == CancellationStatus.PENDING,
        CancellationRequest.reminded_at.is_(None),
        _cancellation_deadline() <= moment,
    )
    stmt = _excluding(stmt, CancellationRequest.request_id, held)
    return await _scalars(stmt.order_by(_cancellation_deadline()).limit(batch))


def _reported_at() -> Select[tuple[uuid.UUID, datetime]]:
    return (
        select(
            RequestEvent.request_id.label("request_id"),
            func.max(RequestEvent.occurred_at).label("reported_at"),
        )
        .where(RequestEvent.event_type == completion.COMPLETION_REPORTED_EVENT)
        .group_by(RequestEvent.request_id)
    )


async def _due_auto_close(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    reported = _reported_at().subquery()
    limit = moment - timedelta(days=get_settings().auto_close_days)
    stmt = (
        select(RepairRequest.id)
        .join(reported, reported.c.request_id == RepairRequest.id)
        .where(
            RepairRequest.status == RequestStatus.COMPLETION_REPORTED,
            reported.c.reported_at <= limit,
        )
    )
    stmt = _excluding(stmt, RepairRequest.id, held)
    return await _scalars(stmt.order_by(reported.c.reported_at).limit(batch))


async def _due_completion_reminders(
    moment: datetime, batch: int, held: Collection[uuid.UUID]
) -> list[uuid.UUID]:
    reported = _reported_at().subquery()
    reminder = aliased(RequestEvent)
    (_, first_after), (last_kind, last_after) = COMPLETION_REMINDERS

    def sent(kind: str | None) -> Exists:
        cond = [
            reminder.request_id == RepairRequest.id,
            reminder.event_type == completion.REMINDER_EVENT,
            reminder.occurred_at > reported.c.reported_at,
        ]
        if kind is not None:
            cond.append(reminder.payload["reminder"].astext == kind)
        return exists().where(*cond)

    stmt = (
        select(RepairRequest.id)
        .join(reported, reported.c.request_id == RepairRequest.id)
        .where(
            RepairRequest.status == RequestStatus.COMPLETION_REPORTED,
            reported.c.reported_at <= moment - first_after,
            or_(
                and_(reported.c.reported_at > moment - last_after, ~sent(None)),
                and_(reported.c.reported_at <= moment - last_after, ~sent(last_kind)),
            ),
        )
    )
    stmt = _excluding(stmt, RepairRequest.id, held)
    return await _scalars(stmt.order_by(reported.c.reported_at).limit(batch))


def _reminder_seconds(urgency: str) -> int:
    settings = get_settings()
    if urgency == Urgency.CRITICAL:
        return settings.own_service_reminder_critical_seconds
    return settings.own_service_reminder_seconds


async def _lock_skipping(session: AsyncSession, request_id: uuid.UUID) -> RepairRequest | None:
    stmt = (
        select(RepairRequest)
        .where(RepairRequest.id == request_id)
        .with_for_update(skip_locked=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _system() -> SystemActor:
    return SystemActor(name="sweeper")


async def _per_request(
    request_id: uuid.UUID, body: Callable[[CommandContext, RepairRequest], Awaitable[int]]
) -> int | None:

    async def handler(ctx: CommandContext) -> CommandResult:
        request = await _lock_skipping(ctx.session, request_id)
        if request is None:
            return CommandResult({"done": None})
        return CommandResult({"done": await body(ctx, request)})

    result = await run_command(_system(), handler)
    done = result.body["done"]
    return None if done is None else int(done)


async def _expire_children(ctx: CommandContext, request: RepairRequest, *, kind: str) -> int:
    expired = 0
    if kind == "visit":
        live = request.status in allowed_from(C.EXPIRE_VISIT_PROPOSAL, None)
        for proposal in await queries.pending_visit_proposals(ctx.session, request.id):
            if proposal.valid_until > ctx.now:
                continue
            proposal.status = VisitProposalStatus.EXPIRED
            expired += 1
            if not live:
                continue
            apply_transition(
                ctx,
                request,
                C.EXPIRE_VISIT_PROPOSAL,
                None,
                visit_proposal_id=ids.encode("visit_proposal", proposal.id),
                proposal_version=proposal.version,
            )
            await _notify_expiry(ctx, request, "visit_proposal.expired")
        return expired

    live = request.status in allowed_from(C.EXPIRE_REPAIR_QUOTE, None)
    for quote in await queries.pending_repair_quotes(ctx.session, request.id):
        if quote.valid_until > ctx.now:
            continue
        quote.status = RepairQuoteStatus.EXPIRED
        expired += 1
        if not live:
            continue
        apply_transition(
            ctx,
            request,
            C.EXPIRE_REPAIR_QUOTE,
            None,
            repair_quote_id=ids.encode("repair_quote", quote.id),
            quote_version=quote.version,
        )
        await _notify_expiry(ctx, request, "repair_quote.expired")
    return expired


async def _expire_proposals(request_id: uuid.UUID) -> int | None:
    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        return await _expire_children(ctx, request, kind="visit")

    return await _per_request(request_id, body)


async def _expire_quotes(request_id: uuid.UUID) -> int | None:
    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        return await _expire_children(ctx, request, kind="quote")

    return await _per_request(request_id, body)


async def _notify_expiry(ctx: CommandContext, request: RepairRequest, kind: str) -> None:
    assignment = await queries.active_assignment(ctx.session, request.id)
    if assignment is None:
        return
    await recipients.notify_provider(ctx, request, assignment, kind)


async def _expire_request_offers(ctx: CommandContext, request: RepairRequest) -> int:
    live = request.status in allowed_from(C.EXPIRE_OFFER, None)
    expired = 0
    for offer in await queries.active_offers(ctx.session, request.id):
        if offer.valid_until > ctx.now:
            continue
        offer.state = OfferStatus.EXPIRED
        expired += 1
        if not live:
            continue
        apply_transition(ctx, request, C.EXPIRE_OFFER, None, offer_id=ids.encode("offer", offer.id))
        await recipients.notify_provider_org(ctx, request, offer.provider_org_id, "offer.expired")
    return expired


async def _expire_offers(request_id: uuid.UUID) -> int | None:
    return await _per_request(request_id, _expire_request_offers)


async def _release_due_reservation(ctx: CommandContext, request: RepairRequest) -> int:
    if request.status != RequestStatus.AWAITING_ASSIGNMENT_CONFIRMATION:
        return 0
    assignment = await queries.active_assignment(ctx.session, request.id)
    if (
        assignment is None
        or assignment.state != AssignmentState.PENDING
        or assignment.expires_at is None
        or assignment.expires_at > ctx.now
    ):
        return 0
    await search.release_reservation(ctx, request, assignment, expired=True)
    return 1


async def _release_reservation(request_id: uuid.UUID) -> int | None:
    return await _per_request(request_id, _release_due_reservation)


async def _close_search_window(request_id: uuid.UUID) -> int | None:

    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        if request.status != RequestStatus.SEARCHING:
            return 0
        if request.search_expires_at is None or request.search_expires_at > ctx.now:
            return 0
        live = [
            offer
            for offer in await queries.active_offers(ctx.session, request.id)
            if offer.valid_until > ctx.now
        ]
        if live:
            return 0
        await search.close_search(ctx, request, reason="search_expired")
        apply_transition(ctx, request, C.EXPIRE_SEARCH, RequestStatus.ACTION_REQUIRED)
        await recipients.notify_customer(ctx, request, "search.expired", managers_only=True)
        return 1

    return await _per_request(request_id, body)


async def _remind_own_service(request_id: uuid.UUID) -> int | None:
    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        if request.status != RequestStatus.AWAITING_PROVIDER:
            return 0
        assignment = await queries.active_assignment(ctx.session, request.id)
        if (
            assignment is None
            or assignment.state != AssignmentState.PENDING
            or assignment.reminded_at is not None
        ):
            return 0
        if assignment.created_at + timedelta(seconds=_reminder_seconds(request.urgency)) > ctx.now:
            return 0

        assignment.reminded_at = ctx.now
        apply_transition(
            ctx,
            request,
            C.REMIND_OWN_SERVICE_NO_ANSWER,
            None,
            assignment_id=ids.encode("assignment", assignment.id),
        )
        await recipients.notify_customer(ctx, request, "own_service.no_answer", managers_only=True)
        return 1

    return await _per_request(request_id, body)


async def _remind_cancellation(request_id: uuid.UUID) -> int | None:

    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        if request.status != RequestStatus.CANCELLATION_PENDING:
            return 0
        cancellation = await queries.open_cancellation(ctx.session, request.id)
        if (
            cancellation is None
            or cancellation.status != CancellationStatus.PENDING
            or cancellation.reminded_at is not None
        ):
            return 0
        deadline = cancellation.dispute_deadline_at or (
            cancellation.created_at
            + timedelta(seconds=get_settings().cancel_dispute_timeout_seconds)
        )
        if deadline > ctx.now:
            return 0
        cancellation.reminded_at = ctx.now
        cancellation_public_id = ids.encode("cancellation", cancellation.id)
        assignment = await queries.get_assignment(ctx.session, cancellation.assignment_id)
        if assignment is not None and assignment.state == AssignmentState.ACCEPTED:
            await recipients.notify_provider(
                ctx,
                request,
                assignment,
                "cancellation.reminder",
                payload={"cancellation_id": cancellation_public_id},
            )
        await recipients.notify_customer(
            ctx,
            request,
            "cancellation.no_response",
            managers_only=True,
            payload={"cancellation_id": cancellation_public_id},
        )
        return 1

    return await _per_request(request_id, body)


async def _last_report(ctx: CommandContext, request: RepairRequest) -> RequestEvent | None:
    stmt = (
        select(RequestEvent)
        .where(
            RequestEvent.request_id == request.id,
            RequestEvent.event_type == completion.COMPLETION_REPORTED_EVENT,
        )
        .order_by(RequestEvent.occurred_at.desc(), RequestEvent.id.desc())
        .limit(1)
    )
    return (await ctx.session.execute(stmt)).scalar_one_or_none()


async def _remind_completion(request_id: uuid.UUID) -> int | None:

    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        if request.status != RequestStatus.COMPLETION_REPORTED:
            return 0
        report = await _last_report(ctx, request)
        if report is None:
            return 0
        elapsed = ctx.now - report.occurred_at
        due = [kind for kind, after in COMPLETION_REMINDERS if elapsed >= after]
        if not due:
            return 0
        sent_stmt = select(RequestEvent.payload).where(
            RequestEvent.request_id == request.id,
            RequestEvent.event_type == completion.REMINDER_EVENT,
            RequestEvent.occurred_at > report.occurred_at,
        )
        sent = {
            payload.get("reminder") for payload in (await ctx.session.execute(sent_stmt)).scalars()
        }
        kind = due[-1]
        if kind in sent or (kind == COMPLETION_REMINDERS[0][0] and sent):
            return 0
        outcome = report.payload.get("outcome")
        apply_transition(ctx, request, C.REMIND_CUSTOMER_CONFIRMATION, None, reminder=kind)
        await recipients.notify_customer(
            ctx,
            request,
            "completion.reminder",
            managers_only=True,
            payload={"reminder": kind, "outcome": outcome},
        )
        return 1

    return await _per_request(request_id, body)


async def _auto_close(request_id: uuid.UUID) -> int | None:

    async def body(ctx: CommandContext, request: RepairRequest) -> int:
        days = get_settings().auto_close_days
        if days <= 0 or request.status != RequestStatus.COMPLETION_REPORTED:
            return 0
        report = await _last_report(ctx, request)
        if report is None or report.occurred_at + timedelta(days=days) > ctx.now:
            return 0
        assignment = await queries.active_assignment(ctx.session, request.id)
        if assignment is None:
            return 0
        await completion.close_request(
            ctx,
            request,
            assignment,
            command=C.AUTO_CLOSE_COMPLETION,
            closure_kind=ClosureKind.AUTO_TIMEOUT,
        )
        await recipients.notify_customer(ctx, request, "request.auto_closed", managers_only=True)
        support.audit(ctx, C.AUTO_CLOSE_COMPLETION, request, closure_kind=ClosureKind.AUTO_TIMEOUT)
        return 1

    return await _per_request(request_id, body)
