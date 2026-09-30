import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, UserActor
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.locking import check_version
from app.core.money import Price, validate_price
from app.core.pipeline import CommandContext, CommandResult
from app.db.enums import (
    OfferStatus,
    ProviderProfileStatus,
    RepairQuoteStatus,
    RequestStatus,
    VatMode,
    VisitProposalStatus,
)
from app.db.models import (
    Assignment,
    CancellationRequest,
    Message,
    Offer,
    Organization,
    ProviderProfile,
    RepairQuote,
    RepairRequest,
    VisitProposal,
)
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.requests import details, policy, queries, views
from app.modules.requests.transitions import RequestCommand as C

OUTCOMES = frozenset({"resolved", "not_resolved"})
SUPERSEDABLE = (VisitProposalStatus.PENDING, VisitProposalStatus.APPROVED)

_UNIQUE_CONFLICTS: dict[str, tuple[str, str]] = {
    "ux_cancellation_requests_one_open": (
        "Запрос отмены уже открыт",
        "CANCELLATION_ALREADY_OPEN",
    ),
    "ux_visit_proposals_one_pending": (
        "Есть более новая версия условий",
        "PROPOSAL_NOT_CURRENT",
    ),
    "ux_repair_quotes_one_pending": ("Есть более новая версия сметы", "QUOTE_NOT_CURRENT"),
    "ux_offers_one_active": ("Предложение уже подано", "OFFER_ALREADY_ACTIVE"),
    "ux_assignments_one_active_per_request": (
        "По заявке уже есть активное назначение",
        "ASSIGNMENT_ALREADY_ACTIVE",
    ),
}


def required_text(value: str | None, message: str, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationFailed(message, field=field)
    return text


def one_of(value: str, allowed: frozenset[str] | set[str], field: str) -> str:
    if value not in allowed:
        raise ValidationFailed("Недопустимое значение", field=field)
    return value


def vat_mode_value(value: str | None) -> str | None:
    if value is None:
        return None
    return one_of(value, {str(m) for m in VatMode}, "vat_mode")


MAX_TERMS_TEXT = 2000


def aware(value: datetime | None, field: str) -> datetime | None:
    if value is not None and value.utcoffset() is None:
        raise ValidationFailed("Укажите время с часовым поясом", field=field)
    return value


def terms_text(value: str | None, field: str) -> str | None:
    if value is not None and len(value) > MAX_TERMS_TEXT:
        raise ValidationFailed(f"Не длиннее {MAX_TERMS_TEXT} символов", field=field)
    return value


def visit_window(
    now: datetime, start: datetime | None, end: datetime | None, *, required: bool
) -> tuple[datetime | None, datetime | None]:
    start = aware(start, "visit_window_start")
    end = aware(end, "visit_window_end")
    if start is None and end is None and not required:
        return None, None
    if start is None or end is None:
        raise ValidationFailed(
            "Укажите начало и конец окна выезда",
            code="VISIT_WINDOW_REQUIRED",
            field="visit_window_start" if start is None else "visit_window_end",
        )
    if start >= end:
        raise ValidationFailed(
            "Начало окна выезда должно быть раньше конца", field="visit_window_end"
        )
    if end <= now:
        raise ValidationFailed(
            "Окно выезда уже прошло", code="VISIT_WINDOW_PASSED", field="visit_window_end"
        )
    return start, end


def visit_window_problem(now: datetime, start: datetime | None, end: datetime | None) -> str | None:
    if start is None or end is None:
        return "VISIT_WINDOW_REQUIRED"
    if end <= now:
        return "VISIT_WINDOW_PASSED"
    return None


def valid_until_at(
    now: datetime,
    requested: datetime | None,
    default_seconds: int,
    *,
    max_seconds: int | None = None,
) -> datetime:
    limit = now + timedelta(seconds=max_seconds or get_settings().proposal_max_ttl_seconds)
    requested = aware(requested, "valid_until")
    if requested is None:
        return min(now + timedelta(seconds=default_seconds), limit)
    if requested <= now:
        raise ValidationFailed("Срок действия уже истёк", field="valid_until")
    if requested > limit:
        raise ValidationFailed("Срок действия превышает допустимый", field="valid_until")
    return requested


class PricedInput(Protocol):
    @property
    def amount_minor(self) -> int | None: ...
    @property
    def currency(self) -> str | None: ...
    @property
    def vat_mode(self) -> str | None: ...
    @property
    def zero_cost_reason(self) -> str | None: ...
    @property
    def valid_until(self) -> datetime | None: ...


def priced_terms(
    now: datetime,
    data: PricedInput,
    *,
    default_seconds: int,
    max_seconds: int | None = None,
) -> tuple[Price, datetime]:
    price = validate_price(
        Price(
            data.amount_minor, data.currency, data.zero_cost_reason, vat_mode_value(data.vat_mode)
        )
    )
    return price, valid_until_at(now, data.valid_until, default_seconds, max_seconds=max_seconds)


async def ensure_provider_active(session: AsyncSession, provider_org_id: uuid.UUID) -> None:
    stmt = select(ProviderProfile.status).where(ProviderProfile.organization_id == provider_org_id)
    status = (await session.execute(stmt)).scalar_one_or_none()
    if status != ProviderProfileStatus.ACTIVE:
        raise Conflict("Профиль исполнителя не активен", code="PROVIDER_NOT_ACTIVE")


_STATUS_LOST = frozenset({ProviderProfileStatus.SUSPENDED, ProviderProfileStatus.REJECTED})


async def ensure_provider_not_suspended(session: AsyncSession, provider_org_id: uuid.UUID) -> None:
    stmt = select(ProviderProfile.status).where(ProviderProfile.organization_id == provider_org_id)
    status = (await session.execute(stmt)).scalar_one_or_none()
    if status in _STATUS_LOST:
        raise Conflict(
            "Профиль исполнителя заблокирован: работы по заявке ведёт оператор",
            code="PROVIDER_NOT_ACTIVE",
        )


async def flush_unique(ctx: CommandContext) -> None:
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        text = str(exc.orig)
        known = next((value for name, value in _UNIQUE_CONFLICTS.items() if name in text), None)
        if known is None:
            raise
        raise Conflict(known[0], code=known[1]) from exc


async def locked_request(ctx: CommandContext, request_id: uuid.UUID) -> RepairRequest:
    request = await queries.lock_request(ctx.session, request_id)
    if request is None:
        raise NotFound()
    return request


def check_request_version(request: RepairRequest, expected_version: int | None) -> None:
    check_version(request.version, expected_version)


async def customer_command(
    ctx: CommandContext,
    request_id: uuid.UUID,
    command: C,
    expected_version: int | None,
) -> tuple[RepairRequest, UserActor]:
    policy.ensure_command_allowed(ctx.actor, command)
    request = await locked_request(ctx, request_id)
    user = policy.ensure_customer_request(ctx.actor, request)
    check_version(request.version, expected_version)
    return request, user


async def provider_command(
    ctx: CommandContext,
    request_id: uuid.UUID,
    assignment_id: uuid.UUID,
    command: C,
    expected_version: int | None,
) -> tuple[RepairRequest, Assignment]:
    policy.ensure_command_allowed(ctx.actor, command)
    request = await locked_request(ctx, request_id)
    assignment = policy.ensure_assignment_belongs(
        ctx.actor, request, await queries.get_assignment(ctx.session, assignment_id)
    )
    policy.ensure_assignment_active(assignment)
    await ensure_provider_not_suspended(ctx.session, assignment.provider_org_id)
    check_version(request.version, expected_version)
    return request, assignment


def audit(ctx: CommandContext, command: C, request: RepairRequest, **details: object) -> None:
    ctx.audit(
        str(command),
        "request",
        request.id,
        organization_id=getattr(ctx.actor, "organization_id", None),
        **details,
    )


async def supersede_children(
    ctx: CommandContext, request: RepairRequest, *, keep_approved: bool = False
) -> None:
    proposal_states = (VisitProposalStatus.PENDING,) if keep_approved else SUPERSEDABLE
    await ctx.session.execute(
        update(VisitProposal)
        .where(VisitProposal.request_id == request.id, VisitProposal.status.in_(proposal_states))
        .values(status=VisitProposalStatus.SUPERSEDED)
    )
    await ctx.session.execute(
        update(RepairQuote)
        .where(
            RepairQuote.request_id == request.id, RepairQuote.status == RepairQuoteStatus.PENDING
        )
        .values(status=RepairQuoteStatus.SUPERSEDED)
    )
    await ctx.session.execute(
        update(Offer)
        .where(
            Offer.request_id == request.id,
            Offer.state.in_((OfferStatus.ACTIVE, OfferStatus.SELECTED)),
        )
        .values(state=OfferStatus.CLOSED)
    )


async def fix_snapshots(ctx: CommandContext, request: RepairRequest) -> None:
    if request.equipment_snapshot and request.location_snapshot:
        return
    pair = await queries.equipment_with_category(ctx.session, request.equipment_id)
    location = await queries.get_location(ctx.session, request.location_id)
    if pair is None or location is None:
        raise NotFound()
    request.equipment_snapshot = views.equipment_snapshot(pair[0], pair[1])
    request.location_snapshot = views.location_snapshot(location)


def ensure_proposal_not_due(proposal: VisitProposal, now: datetime) -> None:
    if proposal.status == VisitProposalStatus.PENDING and proposal.valid_until <= now:
        raise Conflict("Срок предложения истёк", code="PROPOSAL_EXPIRED")


def ensure_quote_not_due(quote: RepairQuote, now: datetime) -> None:
    if quote.status == RepairQuoteStatus.PENDING and quote.valid_until <= now:
        raise Conflict("Срок сметы истёк", code="QUOTE_EXPIRED")


async def unread_for(
    session: AsyncSession,
    actor: Actor,
    request_id: uuid.UUID,
    *,
    channel: queries.MessageChannel = queries.WHOLE_CHANNEL,
) -> int | None:
    if not isinstance(actor, UserActor):
        return None
    return await queries.unread_messages_count(
        session, request_id, actor.membership_id, channel=channel
    )


def provider_channel(assignment: Assignment) -> queries.MessageChannel:
    return queries.MessageChannel(
        provider_org_id=assignment.provider_org_id, assignment_id=assignment.id
    )


async def approver_for(session: AsyncSession, request: RepairRequest) -> str | None:
    if request.status != RequestStatus.APPROVAL_REQUIRED:
        return None
    return await queries.approver_name(session, request.customer_org_id)


async def assignment_worker_name(
    session: AsyncSession, assignment: Assignment | None
) -> str | None:
    if assignment is None or assignment.field_worker_membership_id is None:
        return None
    names = await queries.membership_names(session, {assignment.field_worker_membership_id})
    return names.get(assignment.field_worker_membership_id)


async def customer_result(
    ctx: CommandContext,
    request: RepairRequest,
    *,
    assignment: Assignment | None = None,
    proposals: tuple[VisitProposal, ...] = (),
    quotes: tuple[RepairQuote, ...] = (),
    cancellation: CancellationRequest | None = None,
    search: views.SearchStateView | None = None,
    status: int = 200,
) -> CommandResult:
    pair = await queries.equipment_with_category(ctx.session, request.equipment_id)
    location = await queries.get_location(ctx.session, request.location_id)
    provider_display_name = None
    if assignment is not None:
        provider_org = await ctx.session.get(Organization, assignment.provider_org_id)
        provider_display_name = provider_org.display_name if provider_org else None
    attachments = await files.list_for_request_in(ctx.session, ctx.actor, request.id)
    view = views.to_customer_view(
        request,
        equipment=pair[0] if pair else None,
        category=pair[1] if pair else None,
        location=location,
        assignment=assignment,
        field_worker_name=await assignment_worker_name(ctx.session, assignment),
        provider_display_name=provider_display_name,
        proposals=proposals,
        quotes=quotes,
        cancellation=cancellation,
        attachments=attachments,
        unread_messages_count=await unread_for(ctx.session, ctx.actor, request.id),
        approver_name=await approver_for(ctx.session, request),
        **await details.customer_card_extras(
            ctx.session, request, assignment, attachments, search=search
        ),
    )
    return CommandResult(view.model_dump(mode="json"), status=status)


async def provider_result(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment,
    *,
    proposals: tuple[VisitProposal, ...] = (),
    quotes: tuple[RepairQuote, ...] = (),
    cancellation: CancellationRequest | None = None,
) -> CommandResult:
    attachments = await files.list_for_request_in(ctx.session, ctx.actor, request.id)
    if cancellation is None or cancellation.assignment_id != assignment.id:
        cancellation = await queries.last_cancellation(
            ctx.session, request.id, assignment_id=assignment.id
        )
    disclose = policy.discloses_contacts(assignment)
    view = views.to_provider_view(
        request,
        assignment,
        disclose=disclose,
        field_worker_name=await assignment_worker_name(ctx.session, assignment),
        proposals=proposals,
        quotes=quotes,
        cancellation=cancellation,
        attachments=attachments,
        unread_messages_count=await unread_for(
            ctx.session, ctx.actor, request.id, channel=provider_channel(assignment)
        ),
        completion_report=await details.completion_report(
            ctx.session, request, assignment, attachments
        ),
        customer_org_name=await details.disclosed_customer_name(
            ctx.session, request, disclose=disclose
        ),
    )
    return CommandResult(view.model_dump(mode="json"))


async def message_views_for(
    session: AsyncSession,
    side: Literal["customer", "provider"],
    request_id: uuid.UUID,
    messages: Sequence[Message],
    *,
    assignment_id: uuid.UUID | None = None,
) -> list[views.MessageView]:
    disclosed = False
    if side == "provider" and assignment_id is not None:
        assignment = await queries.get_assignment(session, assignment_id)
        disclosed = assignment is not None and policy.discloses_contacts(assignment)
    authors = await details.message_authors(
        session, messages, side=side, provider_disclosed=disclosed
    )
    deliveries = await details.message_deliveries(session, request_id, messages, side=side)
    return [
        views.to_message_view(m, author=authors.get(m.id), delivery=deliveries.get(m.id))
        for m in messages
    ]
