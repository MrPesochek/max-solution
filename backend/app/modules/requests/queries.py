import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, and_, column, false, func, or_, select, values
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.clock import utcnow
from app.core.errors import ValidationFailed
from app.core.scope import AccessScope
from app.db.enums import (
    CancellationStatus,
    MembershipRole,
    MembershipStatus,
    OfferStatus,
    PublicCardStatus,
    RepairQuoteStatus,
    RequestStatus,
    VisitProposalStatus,
)
from app.db.models import (
    Assignment,
    Attachment,
    CancellationRequest,
    City,
    District,
    Equipment,
    EquipmentCategory,
    Location,
    Membership,
    Message,
    MessageRead,
    Offer,
    RepairQuote,
    RepairRequest,
    RequestEvent,
    RequestPublicCard,
    Review,
    User,
    VisitProposal,
)
from app.modules.requests import policy

MAX_PAGE = 100
DEFAULT_PAGE = 20

TERMINAL_STATUSES = (RequestStatus.CLOSED, RequestStatus.CANCELLED)
ACTIVE_ASSIGNMENT_STATES = tuple(sorted(policy.ACTIVE_ASSIGNMENT_STATES))
READABLE_ASSIGNMENT_STATES = tuple(sorted(policy.READABLE_ASSIGNMENT_STATES))


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RequestRow:
    request: RepairRequest
    location_name: str | None
    equipment_title: str | None
    assignment: Assignment | None
    equipment_id: uuid.UUID | None = None
    equipment_category_name: str | None = None
    equipment_brand: str | None = None
    equipment_model: str | None = None
    timezone: str | None = None


def page_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE
    if limit < 1 or limit > MAX_PAGE:
        raise ValidationFailed(f"Размер страницы — от 1 до {MAX_PAGE}", field="limit")
    return limit


def decode_cursor(kind: str, cursor: str | None) -> uuid.UUID | None:
    if cursor is None:
        return None
    try:
        return ids.decode(kind, cursor)
    except (ids.InvalidPublicId, ValueError) as exc:
        raise ValidationFailed("Некорректный курсор", field="cursor") from exc


async def lock_request(session: AsyncSession, request_id: uuid.UUID) -> RepairRequest | None:
    stmt = select(RepairRequest).where(RepairRequest.id == request_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_assignment(session: AsyncSession, assignment_id: uuid.UUID) -> Assignment | None:
    return (
        await session.execute(select(Assignment).where(Assignment.id == assignment_id))
    ).scalar_one_or_none()


async def active_assignment(session: AsyncSession, request_id: uuid.UUID) -> Assignment | None:
    stmt = select(Assignment).where(
        Assignment.request_id == request_id,
        Assignment.state.in_(ACTIVE_ASSIGNMENT_STATES),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def last_assignment(session: AsyncSession, request_id: uuid.UUID) -> Assignment | None:
    stmt = (
        select(Assignment)
        .where(Assignment.request_id == request_id)
        .order_by(Assignment.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def last_assignments(
    session: AsyncSession, request_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Assignment]:
    if not request_ids:
        return {}
    stmt = (
        select(Assignment)
        .where(Assignment.request_id.in_(tuple(request_ids)))
        .distinct(Assignment.request_id)
        .order_by(Assignment.request_id, Assignment.id.desc())
    )
    return {row.request_id: row for row in (await session.execute(stmt)).scalars()}


async def provider_assignment(
    session: AsyncSession, request_id: uuid.UUID, provider_org_id: uuid.UUID
) -> Assignment | None:
    stmt = (
        select(Assignment)
        .where(
            Assignment.request_id == request_id,
            Assignment.provider_org_id == provider_org_id,
        )
        .order_by(Assignment.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_visit_proposal(session: AsyncSession, proposal_id: uuid.UUID) -> VisitProposal | None:
    return (
        await session.execute(select(VisitProposal).where(VisitProposal.id == proposal_id))
    ).scalar_one_or_none()


async def get_repair_quote(session: AsyncSession, quote_id: uuid.UUID) -> RepairQuote | None:
    return (
        await session.execute(select(RepairQuote).where(RepairQuote.id == quote_id))
    ).scalar_one_or_none()


async def visit_proposals(
    session: AsyncSession, request_id: uuid.UUID, *, assignment_id: uuid.UUID | None = None
) -> list[VisitProposal]:
    stmt = select(VisitProposal).where(VisitProposal.request_id == request_id)
    if assignment_id is not None:
        stmt = stmt.where(VisitProposal.assignment_id == assignment_id)
    stmt = stmt.order_by(VisitProposal.version.desc())
    return list((await session.execute(stmt)).scalars().all())


async def repair_quotes(
    session: AsyncSession, request_id: uuid.UUID, *, assignment_id: uuid.UUID | None = None
) -> list[RepairQuote]:
    stmt = select(RepairQuote).where(RepairQuote.request_id == request_id)
    if assignment_id is not None:
        stmt = stmt.where(RepairQuote.assignment_id == assignment_id)
    stmt = stmt.order_by(RepairQuote.version.desc())
    return list((await session.execute(stmt)).scalars().all())


async def next_proposal_version(
    session: AsyncSession, request_id: uuid.UUID, assignment_id: uuid.UUID
) -> int:
    stmt = select(VisitProposal.version).where(
        VisitProposal.request_id == request_id, VisitProposal.assignment_id == assignment_id
    )
    versions = list((await session.execute(stmt)).scalars().all())
    return max(versions, default=0) + 1


async def next_quote_version(
    session: AsyncSession, request_id: uuid.UUID, assignment_id: uuid.UUID
) -> int:
    stmt = select(RepairQuote.version).where(
        RepairQuote.request_id == request_id, RepairQuote.assignment_id == assignment_id
    )
    versions = list((await session.execute(stmt)).scalars().all())
    return max(versions, default=0) + 1


async def pending_visit_proposals(
    session: AsyncSession, request_id: uuid.UUID
) -> list[VisitProposal]:
    stmt = select(VisitProposal).where(
        VisitProposal.request_id == request_id,
        VisitProposal.status == VisitProposalStatus.PENDING,
    )
    return list((await session.execute(stmt)).scalars().all())


async def pending_repair_quotes(session: AsyncSession, request_id: uuid.UUID) -> list[RepairQuote]:
    stmt = select(RepairQuote).where(
        RepairQuote.request_id == request_id, RepairQuote.status == RepairQuoteStatus.PENDING
    )
    return list((await session.execute(stmt)).scalars().all())


async def open_cancellation(
    session: AsyncSession, request_id: uuid.UUID
) -> CancellationRequest | None:
    stmt = (
        select(CancellationRequest)
        .where(
            CancellationRequest.request_id == request_id,
            CancellationRequest.status.in_(
                (CancellationStatus.PENDING, CancellationStatus.DISPUTED)
            ),
        )
        .order_by(CancellationRequest.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_cancellation(
    session: AsyncSession, cancellation_id: uuid.UUID
) -> CancellationRequest | None:
    return (
        await session.execute(
            select(CancellationRequest).where(CancellationRequest.id == cancellation_id)
        )
    ).scalar_one_or_none()


async def last_cancellation(
    session: AsyncSession, request_id: uuid.UUID, *, assignment_id: uuid.UUID | None = None
) -> CancellationRequest | None:
    stmt = select(CancellationRequest).where(CancellationRequest.request_id == request_id)
    if assignment_id is not None:
        stmt = stmt.where(CancellationRequest.assignment_id == assignment_id)
    else:
        current = (
            select(Assignment.id)
            .where(Assignment.request_id == request_id)
            .order_by(Assignment.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = stmt.where(CancellationRequest.assignment_id == current)
    stmt = stmt.order_by(CancellationRequest.id.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def equipment_with_category(
    session: AsyncSession, equipment_id: uuid.UUID
) -> tuple[Equipment, EquipmentCategory | None] | None:
    stmt = (
        select(Equipment, EquipmentCategory)
        .join(
            EquipmentCategory,
            EquipmentCategory.id == Equipment.equipment_category_id,
            isouter=True,
        )
        .where(Equipment.id == equipment_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return row[0], row[1]


async def get_location(session: AsyncSession, location_id: uuid.UUID) -> Location | None:
    return (
        await session.execute(select(Location).where(Location.id == location_id))
    ).scalar_one_or_none()


async def card_place_names(session: AsyncSession, card: RequestPublicCard) -> dict[str, str | None]:
    city = await session.get(City, card.city_id)
    district = await session.get(District, card.district_id) if card.district_id else None
    return {
        "city_name": city.name if city is not None else None,
        "district_name": district.name if district is not None else None,
    }


async def get_public_card(session: AsyncSession, request_id: uuid.UUID) -> RequestPublicCard | None:
    return (
        await session.execute(
            select(RequestPublicCard).where(RequestPublicCard.request_id == request_id)
        )
    ).scalar_one_or_none()


async def open_public_cards(
    session: AsyncSession, *, after: uuid.UUID | None = None, limit: int = 100
) -> list[tuple[RepairRequest, RequestPublicCard]]:
    stmt = (
        select(RepairRequest, RequestPublicCard)
        .join(RequestPublicCard, RequestPublicCard.request_id == RepairRequest.id)
        .where(
            RepairRequest.status == RequestStatus.SEARCHING,
            RequestPublicCard.status == PublicCardStatus.OPEN,
        )
    )
    if after is not None:
        stmt = stmt.where(RepairRequest.id < after)
    stmt = stmt.order_by(RepairRequest.id.desc()).limit(limit)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def get_offer(session: AsyncSession, offer_id: uuid.UUID) -> Offer | None:
    return (await session.execute(select(Offer).where(Offer.id == offer_id))).scalar_one_or_none()


async def offers(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    provider_org_id: uuid.UUID | None = None,
    states: Sequence[str] | None = None,
) -> list[Offer]:
    stmt = select(Offer).where(Offer.request_id == request_id)
    if provider_org_id is not None:
        stmt = stmt.where(Offer.provider_org_id == provider_org_id)
    if states:
        stmt = stmt.where(Offer.state.in_(tuple(states)))
    stmt = stmt.order_by(Offer.id)
    return list((await session.execute(stmt)).scalars().all())


async def active_offers(session: AsyncSession, request_id: uuid.UUID) -> list[Offer]:
    return await offers(session, request_id, states=(OfferStatus.ACTIVE,))


async def next_offer_version(
    session: AsyncSession, request_id: uuid.UUID, provider_org_id: uuid.UUID
) -> int:
    stmt = select(Offer.version).where(
        Offer.request_id == request_id, Offer.provider_org_id == provider_org_id
    )
    versions = list((await session.execute(stmt)).scalars().all())
    return max(versions, default=0) + 1


async def published_attachment_ids(session: AsyncSession, request_id: uuid.UUID) -> list[str]:
    stmt = select(RequestPublicCard.published_attachment_ids).where(
        RequestPublicCard.request_id == request_id
    )
    values = (await session.execute(stmt)).scalar_one_or_none()
    return [ids.encode("attachment", value) for value in values or ()]


async def published_source_attachment_ids(
    session: AsyncSession, copy_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    if not copy_ids:
        return []
    stmt = select(Attachment.id, Attachment.source_attachment_id).where(Attachment.id.in_(copy_ids))
    sources = {copy_id: source for copy_id, source in (await session.execute(stmt)).all()}
    return [source for copy_id in copy_ids if (source := sources.get(copy_id)) is not None]


def _scoped_customer(scope: AccessScope) -> Select[tuple[RepairRequest, Location, Equipment]]:
    stmt = (
        select(RepairRequest, Location, Equipment)
        .join(Location, Location.id == RepairRequest.location_id)
        .join(Equipment, Equipment.id == RepairRequest.equipment_id)
        .where(RepairRequest.customer_org_id == scope.organization_id)
    )
    if scope.location_ids is not None:
        stmt = stmt.where(RepairRequest.location_id.in_(tuple(scope.location_ids) or (None,)))
    return stmt


async def customer_request_rows(
    scope: AccessScope,
    session: AsyncSession,
    *,
    statuses: Sequence[str] | None = None,
    location_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    active: bool | None = None,
    updated_since: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[RequestRow]:
    size = page_limit(limit)
    stmt = _scoped_customer(scope)
    if statuses:
        stmt = stmt.where(RepairRequest.status.in_(tuple(statuses)))
    if location_id is not None:
        stmt = stmt.where(RepairRequest.location_id == location_id)
    if equipment_id is not None:
        stmt = stmt.where(RepairRequest.equipment_id == equipment_id)
    if active is True:
        stmt = stmt.where(RepairRequest.status.not_in(TERMINAL_STATUSES))
    elif active is False:
        stmt = stmt.where(RepairRequest.status.in_(TERMINAL_STATUSES))
    if updated_since is not None:
        stmt = stmt.where(RepairRequest.updated_at >= updated_since)
    after = decode_cursor("request", cursor)
    if after is not None:
        stmt = stmt.where(RepairRequest.id < after)
    stmt = stmt.order_by(RepairRequest.id.desc()).limit(size + 1)

    rows = (await session.execute(stmt)).all()
    return await _to_page(session, [(r[0], r[1], r[2]) for r in rows], size)


async def customer_request(
    scope: AccessScope, session: AsyncSession, request_id: uuid.UUID
) -> RequestRow | None:
    stmt = _scoped_customer(scope).where(RepairRequest.id == request_id)
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    assignment = await last_assignment(session, request_id)
    return RequestRow(row[0], row[1].name, _title(row[2]), assignment)


async def provider_request_rows(
    scope: AccessScope,
    session: AsyncSession,
    *,
    states: Sequence[str] | None = None,
    equipment_id: uuid.UUID | None = None,
    updated_since: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> Page[RequestRow]:
    size = page_limit(limit)
    wanted = tuple(states) if states else READABLE_ASSIGNMENT_STATES
    if any(state not in READABLE_ASSIGNMENT_STATES for state in wanted):
        raise ValidationFailed(
            "Допустимые состояния назначения: pending, accepted, completed",
            field="assignment_state",
        )
    stmt = (
        select(RepairRequest, Assignment)
        .join(Assignment, Assignment.request_id == RepairRequest.id)
        .where(
            Assignment.provider_org_id == scope.organization_id,
            Assignment.state.in_(wanted),
        )
    )
    if equipment_id is not None:
        stmt = stmt.where(RepairRequest.equipment_id == equipment_id)
    if updated_since is not None:
        stmt = stmt.where(RepairRequest.updated_at >= updated_since)
    after = decode_cursor("request", cursor)
    if after is not None:
        stmt = stmt.where(RepairRequest.id < after)
    stmt = stmt.order_by(RepairRequest.id.desc()).limit(size + 1)

    rows = (await session.execute(stmt)).all()
    items = [
        RequestRow(
            request=row[0],
            location_name=row[0].location_snapshot.get("name"),
            equipment_title=None,
            assignment=row[1],
            equipment_id=row[0].equipment_id,
            equipment_category_name=row[0].equipment_snapshot.get("category_name"),
            equipment_brand=row[0].equipment_snapshot.get("brand"),
            equipment_model=row[0].equipment_snapshot.get("model"),
            timezone=row[0].location_snapshot.get("timezone"),
        )
        for row in rows[:size]
    ]
    next_cursor = (
        ids.encode("request", items[-1].request.id) if len(rows) > size and items else None
    )
    return Page(items, next_cursor)


async def _to_page(
    session: AsyncSession,
    rows: list[tuple[RepairRequest, Location, Equipment]],
    size: int,
) -> Page[RequestRow]:
    visible = rows[:size]
    categories = await _category_names(session, {row[2].equipment_category_id for row in visible})
    assignments = await last_assignments(session, [row[0].id for row in visible])
    items: list[RequestRow] = []
    for request, location, equipment in visible:
        items.append(
            RequestRow(
                request=request,
                location_name=location.name,
                equipment_title=_title(equipment),
                assignment=assignments.get(request.id),
                equipment_id=equipment.id,
                equipment_category_name=categories.get(equipment.equipment_category_id),
                equipment_brand=equipment.brand,
                equipment_model=equipment.model,
                timezone=location.timezone,
            )
        )
    next_cursor = (
        ids.encode("request", items[-1].request.id) if len(rows) > size and items else None
    )
    return Page(items, next_cursor)


async def _category_names(
    session: AsyncSession, category_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not category_ids:
        return {}
    stmt = select(EquipmentCategory.id, EquipmentCategory.name).where(
        EquipmentCategory.id.in_(tuple(category_ids))
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


def _title(equipment: Equipment) -> str | None:
    return " ".join(part for part in (equipment.brand, equipment.model) if part) or None


@dataclass(frozen=True, slots=True)
class MessageChannel:
    provider_org_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None


WHOLE_CHANNEL = MessageChannel()

MessageDirection = Literal["forward", "backward"]


async def message_page(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    channel: MessageChannel = WHOLE_CHANNEL,
    cursor: str | None = None,
    limit: int | None = None,
    direction: MessageDirection = "forward",
) -> Page[Message]:
    size = page_limit(limit)
    stmt = select(Message).where(_visible_messages(request_id, channel))
    boundary = decode_cursor("message", cursor)
    if direction == "backward":
        if boundary is not None:
            stmt = stmt.where(Message.id < boundary)
        stmt = stmt.order_by(Message.id.desc()).limit(size + 1)
        rows = list((await session.execute(stmt)).scalars().all())
        items = list(reversed(rows[:size]))
        older = ids.encode("message", items[0].id) if len(rows) > size and items else None
        return Page(items, older)
    if boundary is not None:
        stmt = stmt.where(Message.id > boundary)
    stmt = stmt.order_by(Message.id).limit(size + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    items = rows[:size]
    next_cursor = ids.encode("message", items[-1].id) if len(rows) > size and items else None
    return Page(items, next_cursor)


def _visible_messages(request_id: uuid.UUID, channel: MessageChannel) -> ColumnElement[bool]:
    condition = Message.request_id == request_id
    if channel.provider_org_id is not None:
        shared = (
            Message.assignment_id == channel.assignment_id
            if channel.assignment_id is not None
            else false()
        )
        condition = and_(
            condition, or_(shared, Message.thread_provider_org_id == channel.provider_org_id)
        )
    return condition


async def message_read(
    session: AsyncSession, request_id: uuid.UUID, membership_id: uuid.UUID
) -> MessageRead | None:
    stmt = select(MessageRead).where(
        MessageRead.request_id == request_id, MessageRead.membership_id == membership_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def advance_message_read(
    session: AsyncSession,
    request_id: uuid.UUID,
    membership_id: uuid.UUID,
    message_id: uuid.UUID | None,
    now: datetime,
) -> None:
    insert = pg_insert(MessageRead).values(
        request_id=request_id,
        membership_id=membership_id,
        last_read_message_id=message_id,
        last_read_at=now,
    )
    current = MessageRead.__table__.c.last_read_message_id
    excluded = insert.excluded.last_read_message_id
    await session.execute(
        insert.on_conflict_do_update(
            constraint="ux_message_reads_request_membership",
            set_={
                "last_read_message_id": func.greatest(current, excluded),
                "last_read_at": now,
            },
        )
    )


async def unread_messages_count(
    session: AsyncSession,
    request_id: uuid.UUID,
    membership_id: uuid.UUID,
    *,
    channel: MessageChannel = WHOLE_CHANNEL,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Message)
        .where(
            _visible_messages(request_id, channel),
            or_(
                Message.author_membership_id.is_(None),
                Message.author_membership_id != membership_id,
            ),
        )
    )
    read = await message_read(session, request_id, membership_id)
    if read is not None and read.last_read_message_id is not None:
        stmt = stmt.where(Message.id > read.last_read_message_id)
    return int((await session.execute(stmt)).scalar_one())


async def last_visible_message_id(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    channel: MessageChannel = WHOLE_CHANNEL,
) -> uuid.UUID | None:
    stmt = (
        select(Message.id)
        .where(_visible_messages(request_id, channel))
        .order_by(Message.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class MessageCounters:
    unread: int = 0
    last_message_at: datetime | None = None


async def message_counters(
    session: AsyncSession,
    channels: Sequence[tuple[uuid.UUID, MessageChannel]],
    *,
    membership_id: uuid.UUID | None,
) -> dict[tuple[uuid.UUID, uuid.UUID | None], MessageCounters]:
    if not channels:
        return {}
    provider_orgs = {channel.provider_org_id for _, channel in channels}
    if len(provider_orgs) != 1:
        raise ValueError("Каналы страницы должны принадлежать одной стороне")
    provider_org_id = next(iter(provider_orgs))
    pairs = list(
        dict.fromkeys((request_id, channel.assignment_id) for request_id, channel in channels)
    )
    table = values(
        column("request_id", PG_UUID(as_uuid=True)),
        column("assignment_id", PG_UUID(as_uuid=True)),
        name="list_channels",
    ).data(pairs)
    joined = Message.request_id == table.c.request_id
    if provider_org_id is not None:
        joined = and_(
            joined,
            or_(
                Message.assignment_id == table.c.assignment_id,
                Message.thread_provider_org_id == provider_org_id,
            ),
        )
    columns: list[Any] = [
        table.c.request_id,
        table.c.assignment_id,
        func.max(Message.created_at),
    ]
    stmt_from = table.join(Message, joined)
    if membership_id is not None:
        stmt_from = stmt_from.outerjoin(
            MessageRead,
            and_(
                MessageRead.request_id == table.c.request_id,
                MessageRead.membership_id == membership_id,
            ),
        )
        columns.append(
            func.count(Message.id).filter(
                or_(
                    Message.author_membership_id.is_(None),
                    Message.author_membership_id != membership_id,
                ),
                or_(
                    MessageRead.last_read_message_id.is_(None),
                    Message.id > MessageRead.last_read_message_id,
                ),
            )
        )
    stmt = (
        select(*columns).select_from(stmt_from).group_by(table.c.request_id, table.c.assignment_id)
    )
    found: dict[tuple[uuid.UUID, uuid.UUID | None], MessageCounters] = {}
    for row in (await session.execute(stmt)).all():
        found[(row[0], row[1])] = MessageCounters(
            unread=int(row[3]) if membership_id is not None else 0,
            last_message_at=row[2],
        )
    return found


async def approved_visit_windows(
    session: AsyncSession, assignment_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, VisitProposal]:
    if not assignment_ids:
        return {}
    stmt = (
        select(VisitProposal)
        .where(
            VisitProposal.assignment_id.in_(tuple(assignment_ids)),
            VisitProposal.status == VisitProposalStatus.APPROVED,
        )
        .order_by(VisitProposal.assignment_id, VisitProposal.version.desc())
    )
    found: dict[uuid.UUID, VisitProposal] = {}
    for proposal in (await session.execute(stmt)).scalars():
        found.setdefault(proposal.assignment_id, proposal)
    return found


async def membership_names(
    session: AsyncSession, membership_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not membership_ids:
        return {}
    stmt = (
        select(Membership.id, User.display_name)
        .join(User, User.id == Membership.user_id)
        .where(Membership.id.in_(tuple(membership_ids)))
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


async def own_review_ratings(
    session: AsyncSession, customer_org_id: uuid.UUID, request_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not request_ids:
        return {}
    stmt = (
        select(Review.request_id, Review.rating)
        .where(
            Review.customer_org_id == customer_org_id,
            Review.request_id.in_(tuple(request_ids)),
        )
        .order_by(Review.request_id, Review.id.desc())
    )
    found: dict[uuid.UUID, int] = {}
    for request_id, rating in (await session.execute(stmt)).all():
        found.setdefault(request_id, rating)
    return found


async def approver_name(session: AsyncSession, customer_org_id: uuid.UUID) -> str | None:
    stmt = (
        select(User.display_name)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.organization_id == customer_org_id,
            Membership.role == MembershipRole.CUSTOMER_MANAGER,
            Membership.status == MembershipStatus.ACTIVE,
        )
        .order_by(Membership.created_at, Membership.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


OFFER_EVENTS = ("OfferSubmitted", "OfferWithdrawn", "OfferExpired", "OfferSelected")


async def provider_visible_events(
    session: AsyncSession, request_id: uuid.UUID, assignment: Assignment
) -> ColumnElement[bool]:
    start_id = (
        await session.execute(
            select(RequestEvent.id)
            .where(
                RequestEvent.request_id == request_id,
                RequestEvent.payload["assignment_id"].astext
                == ids.encode("assignment", assignment.id),
            )
            .order_by(RequestEvent.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    own_offers = [
        ids.encode("offer", offer.id)
        for offer in await offers(session, request_id, provider_org_id=assignment.provider_org_id)
    ]
    offer_event = RequestEvent.event_type.in_(OFFER_EVENTS)
    own_offer = RequestEvent.payload["offer_id"].astext.in_(own_offers) if own_offers else false()
    window = RequestEvent.id >= start_id if start_id is not None else false()
    return or_(and_(offer_event, own_offer), and_(~offer_event, window))


async def event_page(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    cursor: str | None = None,
    limit: int | None = None,
    visible: ColumnElement[bool] | None = None,
) -> Page[RequestEvent]:
    size = page_limit(limit)
    stmt = select(RequestEvent).where(RequestEvent.request_id == request_id)
    if visible is not None:
        stmt = stmt.where(visible)
    after = decode_cursor("event", cursor)
    if after is not None:
        stmt = stmt.where(RequestEvent.id > after)
    stmt = stmt.order_by(RequestEvent.id).limit(size + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    items = rows[:size]
    next_cursor = ids.encode("event", items[-1].id) if len(rows) > size and items else None
    return Page(items, next_cursor)


@dataclass(frozen=True, slots=True)
class PendingApprovalRow:
    kind: str
    request: RepairRequest
    object_id: uuid.UUID | None = None
    object_kind: str | None = None
    object_version: int | None = None
    due_at: datetime | None = None
    amount_minor: int | None = None
    currency: str | None = None
    thread_provider_org_id: uuid.UUID | None = None


_PENDING_REQUEST_STATUS_KIND: dict[str, str] = {
    RequestStatus.APPROVAL_REQUIRED: "draft_approval",
    RequestStatus.COMPLETION_REPORTED: "completion_reported",
    RequestStatus.ACTION_REQUIRED: "action_required",
}


async def pending_approvals(
    scope: AccessScope, session: AsyncSession, *, manager: bool = True
) -> list[PendingApprovalRow]:
    org_id = scope.organization_id
    rows: list[PendingApprovalRow] = [
        PendingApprovalRow(
            kind="question",
            request=request,
            object_id=message.id,
            object_kind="message",
            thread_provider_org_id=message.thread_provider_org_id,
        )
        for request, message in await unanswered_questions(scope, session)
    ]
    if not manager:
        return rows

    by_status = (
        await session.execute(
            select(RepairRequest).where(
                RepairRequest.customer_org_id == org_id,
                RepairRequest.status.in_(_PENDING_REQUEST_STATUS_KIND),
            )
        )
    ).scalars()
    for request in by_status:
        rows.append(
            PendingApprovalRow(kind=_PENDING_REQUEST_STATUS_KIND[request.status], request=request)
        )

    now = utcnow()

    proposals = (
        await session.execute(
            select(VisitProposal, RepairRequest)
            .join(RepairRequest, RepairRequest.id == VisitProposal.request_id)
            .where(
                RepairRequest.customer_org_id == org_id,
                VisitProposal.status == VisitProposalStatus.PENDING,
                VisitProposal.valid_until > now,
            )
        )
    ).all()
    for proposal, request in proposals:
        rows.append(
            PendingApprovalRow(
                kind="visit_proposal",
                request=request,
                object_id=proposal.id,
                object_kind="visit_proposal",
                object_version=proposal.version,
                due_at=proposal.valid_until,
                amount_minor=proposal.visit_amount_minor,
                currency=proposal.currency,
            )
        )

    quotes = (
        await session.execute(
            select(RepairQuote, RepairRequest)
            .join(RepairRequest, RepairRequest.id == RepairQuote.request_id)
            .where(
                RepairRequest.customer_org_id == org_id,
                RepairQuote.status == RepairQuoteStatus.PENDING,
                RepairQuote.valid_until > now,
            )
        )
    ).all()
    for quote, request in quotes:
        rows.append(
            PendingApprovalRow(
                kind="repair_quote",
                request=request,
                object_id=quote.id,
                object_kind="repair_quote",
                object_version=quote.version,
                due_at=quote.valid_until,
                amount_minor=quote.amount_minor,
                currency=quote.currency,
            )
        )

    cancellations = (
        await session.execute(
            select(CancellationRequest, RepairRequest)
            .join(RepairRequest, RepairRequest.id == CancellationRequest.request_id)
            .where(
                RepairRequest.customer_org_id == org_id,
                CancellationRequest.status == CancellationStatus.DISPUTED,
            )
        )
    ).all()
    for cancellation, request in cancellations:
        rows.append(
            PendingApprovalRow(
                kind="cancellation_disputed",
                request=request,
                object_id=cancellation.id,
                object_kind="cancellation",
                due_at=cancellation.dispute_deadline_at,
            )
        )

    rows.sort(key=lambda row: (row.due_at is None, row.due_at or now, row.request.request_number))
    return rows


@dataclass(frozen=True, slots=True)
class PendingDecision:
    kind: str
    amount_minor: int | None = None
    currency: str | None = None
    respond_by: datetime | None = None
    offers_count: int | None = None


_STATUS_DECISION_KIND: dict[str, str] = {
    RequestStatus.APPROVAL_REQUIRED: "approval",
    RequestStatus.COMPLETION_REPORTED: "completion_reported",
    RequestStatus.ACTION_REQUIRED: "action_required",
}


async def pending_decisions(
    session: AsyncSession, requests: Sequence[RepairRequest]
) -> dict[uuid.UUID, PendingDecision]:
    if not requests:
        return {}
    request_ids = tuple(request.id for request in requests)
    now = utcnow()
    found: dict[uuid.UUID, PendingDecision] = {}

    proposals = (
        await session.execute(
            select(VisitProposal)
            .where(
                VisitProposal.request_id.in_(request_ids),
                VisitProposal.status == VisitProposalStatus.PENDING,
                VisitProposal.valid_until > now,
            )
            .order_by(VisitProposal.id.desc())
        )
    ).scalars()
    for proposal in proposals:
        found.setdefault(
            proposal.request_id,
            PendingDecision(
                kind="visit_proposal",
                amount_minor=proposal.visit_amount_minor,
                currency=proposal.currency,
                respond_by=proposal.valid_until,
            ),
        )

    quotes = (
        await session.execute(
            select(RepairQuote)
            .where(
                RepairQuote.request_id.in_(request_ids),
                RepairQuote.status == RepairQuoteStatus.PENDING,
                RepairQuote.valid_until > now,
            )
            .order_by(RepairQuote.id.desc())
        )
    ).scalars()
    for quote in quotes:
        found.setdefault(
            quote.request_id,
            PendingDecision(
                kind="repair_quote",
                amount_minor=quote.amount_minor,
                currency=quote.currency,
                respond_by=quote.valid_until,
            ),
        )

    searching = [r.id for r in requests if r.status == RequestStatus.SEARCHING]
    if searching:
        active = (
            await session.execute(
                select(Offer).where(
                    Offer.request_id.in_(tuple(searching)),
                    Offer.state == OfferStatus.ACTIVE,
                    Offer.valid_until > now,
                )
            )
        ).scalars()
        by_request: dict[uuid.UUID, list[Offer]] = {}
        for offer in active:
            by_request.setdefault(offer.request_id, []).append(offer)
        for request_id, items in by_request.items():
            priced = [o for o in items if o.visit_amount_minor is not None]
            cheapest = min(priced, key=lambda o: o.visit_amount_minor or 0) if priced else None
            found.setdefault(
                request_id,
                PendingDecision(
                    kind="offers",
                    amount_minor=cheapest.visit_amount_minor if cheapest else None,
                    currency=cheapest.currency if cheapest else None,
                    respond_by=min(o.valid_until for o in items),
                    offers_count=len(items),
                ),
            )

    disputed = (
        await session.execute(
            select(CancellationRequest).where(
                CancellationRequest.request_id.in_(request_ids),
                CancellationRequest.status == CancellationStatus.DISPUTED,
            )
        )
    ).scalars()
    for cancellation in disputed:
        found.setdefault(
            cancellation.request_id,
            PendingDecision(
                kind="cancellation_disputed", respond_by=cancellation.dispute_deadline_at
            ),
        )

    for request in requests:
        kind = _STATUS_DECISION_KIND.get(request.status)
        if kind is not None:
            found.setdefault(request.id, PendingDecision(kind=kind))
    return found


PROVIDER_AUTHOR_KINDS = ("provider_membership", "integration_client")


async def active_offer_counts(
    session: AsyncSession, request_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not request_ids:
        return {}
    stmt = (
        select(Offer.request_id, func.count())
        .where(Offer.request_id.in_(tuple(request_ids)), Offer.state == OfferStatus.ACTIVE)
        .group_by(Offer.request_id)
    )
    return {row[0]: int(row[1]) for row in (await session.execute(stmt)).all()}


async def last_thread_author_kinds(
    session: AsyncSession, request_ids: Sequence[uuid.UUID], provider_org_id: uuid.UUID
) -> dict[uuid.UUID, str]:
    if not request_ids:
        return {}
    stmt = (
        select(Message.request_id, Message.author_kind)
        .where(
            Message.request_id.in_(tuple(request_ids)),
            Message.thread_provider_org_id == provider_org_id,
        )
        .distinct(Message.request_id)
        .order_by(Message.request_id, Message.id.desc())
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


async def unanswered_questions(
    scope: AccessScope, session: AsyncSession
) -> list[tuple[RepairRequest, Message]]:
    last = (
        select(Message.id)
        .join(RepairRequest, RepairRequest.id == Message.request_id)
        .where(
            RepairRequest.customer_org_id == scope.organization_id,
            RepairRequest.status.not_in(TERMINAL_STATUSES),
        )
        .distinct(Message.request_id, Message.thread_provider_org_id)
        .order_by(Message.request_id, Message.thread_provider_org_id, Message.id.desc())
    )
    if scope.location_ids is not None:
        last = last.where(RepairRequest.location_id.in_(tuple(scope.location_ids) or (None,)))
    stmt = (
        select(RepairRequest, Message)
        .join(Message, Message.request_id == RepairRequest.id)
        .where(
            Message.id.in_(last.scalar_subquery()),
            Message.author_kind.in_(PROVIDER_AUTHOR_KINDS),
            or_(
                Message.thread_provider_org_id.is_(None),
                RepairRequest.status == RequestStatus.SEARCHING,
            ),
        )
        .order_by(Message.id)
    )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def has_event(session: AsyncSession, request_id: uuid.UUID, event_type: str) -> bool:
    stmt = (
        select(RequestEvent.id)
        .where(RequestEvent.request_id == request_id, RequestEvent.event_type == event_type)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def event_payloads(
    session: AsyncSession, request_id: uuid.UUID, event_type: str
) -> list[dict[str, Any]]:
    stmt = select(RequestEvent.payload).where(
        RequestEvent.request_id == request_id, RequestEvent.event_type == event_type
    )
    return list((await session.execute(stmt)).scalars().all())
