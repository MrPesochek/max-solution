import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.db.enums import (
    AssignmentState,
    BindingStatus,
    PublicCardStatus,
    RequestRoute,
    RequestStatus,
    Urgency,
)
from app.db.models import (
    Assignment,
    IntegrationClient,
    Membership,
    Message,
    Organization,
    RepairRequest,
    RequestEvent,
    ServiceBinding,
    ServiceContract,
    User,
)
from app.infra.config import get_settings
from app.modules.files.api import AttachmentView
from app.modules.integration import api as integration
from app.modules.providers import api as providers
from app.modules.reputation import api as reputation
from app.modules.requests import policy, queries, views

COMPLETION_REPORTED_EVENT = "CompletionReported"
SEARCH_RESULT_EVENTS = ("SearchPublished", "SearchFoundNoProviders")

REPORT_SLOT_BEFORE = "before"
REPORT_SLOT_AFTER = "after"

OPERATOR_DISPLAY_NAME = "Оператор платформы"

_CURRENT_STATES = (AssignmentState.PENDING, AssignmentState.ACCEPTED, AssignmentState.COMPLETED)


async def provider_contact_phone(session: AsyncSession, assignment: Assignment) -> str | None:
    """Кнопка «Позвонить в сервис»: телефон из профиля — только по раскрытому назначению (I7)."""
    if not policy.discloses_contacts(assignment):
        return None
    org = await session.get(Organization, assignment.provider_org_id)
    return org.contact_phone if org is not None else None


async def delivery_status(
    session: AsyncSession, request: RepairRequest, assignment: Assignment | None
) -> views.DeliveryStatusView | None:
    if assignment is None or assignment.state not in _CURRENT_STATES:
        return None
    status = await integration.request_delivery_status(
        session,
        request_id=request.id,
        provider_org_id=assignment.provider_org_id,
        since=assignment.created_at,
    )
    return views.DeliveryStatusView(
        state=status.state,
        channel=status.channel,
        delivered_at=status.delivered_at,
        last_attempt_at=status.last_attempt_at,
        next_attempt_at=status.next_attempt_at,
    )


async def completion_report(
    session: AsyncSession,
    request: RepairRequest,
    assignment: Assignment | None,
    attachments: Sequence[AttachmentView],
) -> views.CompletionReportView | None:
    """Последний отчёт текущего назначения; фото — из уже отфильтрованных для актора вложений."""
    if assignment is None:
        return None
    event = (
        await session.execute(
            select(RequestEvent)
            .where(
                RequestEvent.request_id == request.id,
                RequestEvent.event_type == COMPLETION_REPORTED_EVENT,
                RequestEvent.occurred_at >= assignment.created_at,
            )
            .order_by(RequestEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if event is None:
        return None
    return views.CompletionReportView(
        outcome=event.payload.get("outcome"),
        summary=event.payload.get("summary"),
        reported_at=event.occurred_at,
        photos_before=[a for a in attachments if a.slot == REPORT_SLOT_BEFORE],
        photos_after=[a for a in attachments if a.slot == REPORT_SLOT_AFTER],
    )


_SIDE_OF_KIND = {"customer_membership": "customer", "provider_membership": "provider"}


async def event_actor_names(
    session: AsyncSession,
    events: Sequence[RequestEvent],
    *,
    side: Literal["customer", "provider"],
    other_side_disclosed: bool = True,
) -> dict[uuid.UUID, str | None]:
    """Люди своей стороны — по имени, другая сторона — названием организации,
    CRM — «CRM <сервис>». События уже отфильтрованы правилами видимости.

    Исполнителю до раскрытия контактов название заказчика не показывается (I7)."""
    membership_ids = {e.actor_membership_id for e in events if e.actor_membership_id is not None}
    client_ids = {
        e.actor_integration_client_id
        for e in events
        if e.actor_kind == "integration_client" and e.actor_integration_client_id is not None
    }
    people: dict[uuid.UUID, tuple[str, str]] = {}
    if membership_ids:
        rows = await session.execute(
            select(Membership.id, User.display_name, Organization.display_name)
            .join(User, User.id == Membership.user_id)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.id.in_(tuple(membership_ids)))
        )
        people = {row[0]: (row[1], row[2]) for row in rows.all()}
    crm: dict[uuid.UUID, str] = {}
    if client_ids:
        rows = await session.execute(
            select(IntegrationClient.id, Organization.display_name)
            .join(Organization, Organization.id == IntegrationClient.provider_org_id)
            .where(IntegrationClient.id.in_(tuple(client_ids)))
        )
        crm = {row[0]: f"CRM {row[1]}" for row in rows.all()}

    names: dict[uuid.UUID, str | None] = {}
    for event in events:
        name: str | None = None
        if event.actor_kind in _SIDE_OF_KIND and event.actor_membership_id in people:
            person, organization = people[event.actor_membership_id]
            if _SIDE_OF_KIND[event.actor_kind] == side:
                name = person
            elif other_side_disclosed:
                name = organization
        elif event.actor_kind == "integration_client" and event.actor_integration_client_id:
            name = crm.get(event.actor_integration_client_id)
        elif event.actor_kind == "operator":
            name = OPERATOR_DISPLAY_NAME
        names[event.id] = name
    return names


async def customer_names(
    session: AsyncSession, customer_org_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not customer_org_ids:
        return {}
    rows = await session.execute(
        select(Organization.id, Organization.display_name).where(
            Organization.id.in_(tuple(customer_org_ids))
        )
    )
    return {row[0]: row[1] for row in rows.all()}


async def disclosed_customer_name(
    session: AsyncSession, request: RepairRequest, *, disclose: bool
) -> str | None:
    """Название заказчика для карточки исполнителя — только после раскрытия (I7)."""
    if not disclose:
        return None
    return (await customer_names(session, {request.customer_org_id})).get(request.customer_org_id)


async def contract_numbers(
    session: AsyncSession, provider_org_id: uuid.UUID, requests: Sequence[RepairRequest]
) -> dict[uuid.UUID, str]:
    """Номер договора подтверждённой привязки оборудования заявки к этому сервису."""
    equipment_ids = {r.equipment_id for r in requests}
    if not equipment_ids:
        return {}
    rows = await session.execute(
        select(
            ServiceBinding.equipment_id,
            ServiceBinding.customer_org_id,
            ServiceContract.contract_number,
            ServiceBinding.claimed_contract_number,
        )
        .join(ServiceContract, ServiceContract.id == ServiceBinding.contract_id, isouter=True)
        .where(
            ServiceBinding.provider_org_id == provider_org_id,
            ServiceBinding.status == BindingStatus.CONFIRMED.value,
            ServiceBinding.equipment_id.in_(tuple(equipment_ids)),
        )
    )
    by_equipment: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
    for equipment_id, customer_org_id, number, claimed in rows.all():
        value = number or claimed
        if value:
            by_equipment[(equipment_id, customer_org_id)] = value
    found: dict[uuid.UUID, str] = {}
    for request in requests:
        value = by_equipment.get((request.equipment_id, request.customer_org_id))
        if value is not None:
            found[request.id] = value
    return found


async def search_state(
    session: AsyncSession, request: RepairRequest
) -> views.SearchStateView | None:
    """Состояние внешнего поиска для карточки заказчика (ТЗ S2, S5).

    Собирается из публичной карточки: пока она открыта, поиск идёт. Число
    исполнителей берётся из события последней публикации, а не пересчитывается,
    чтобы смена профилей исполнителей не меняла итог задним числом."""
    card = await queries.get_public_card(session, request.id)
    if card is None:
        return None
    event = (
        await session.execute(
            select(RequestEvent)
            .where(
                RequestEvent.request_id == request.id,
                RequestEvent.event_type.in_(SEARCH_RESULT_EVENTS),
            )
            .order_by(RequestEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    matched = event.payload.get("matched_providers") if event is not None else None
    published = card.status == PublicCardStatus.OPEN
    sources = await queries.published_source_attachment_ids(
        session, list(card.published_attachment_ids or ())
    )
    return views.SearchStateView(
        published=published,
        matched_providers=matched if isinstance(matched, int) else 0,
        search_expires_at=request.search_expires_at if published else None,
        published_source_attachment_ids=[ids.encode("attachment", value) for value in sources],
        public_card=views.to_public_card_view(
            request,
            card,
            attachment_ids=[
                ids.encode("attachment", value) for value in card.published_attachment_ids or ()
            ]
            if published
            else (),
            **await queries.card_place_names(session, card),
        ),
    )


class CustomerCardExtras(TypedDict):
    provider_contact_phone: str | None
    delivery: views.DeliveryStatusView | None
    completion_report: views.CompletionReportView | None
    provider_summary: views.ProviderSummaryRatingView | None
    reminder_at: datetime | None
    search: views.SearchStateView | None


def own_service_reminder_at(
    request: RepairRequest, assignment: Assignment | None
) -> datetime | None:
    """Время напоминания своему сервису — по той же настройке, что у планировщика."""
    if (
        assignment is None
        or assignment.route != RequestRoute.OWN_SERVICE
        or assignment.state != AssignmentState.PENDING
        or assignment.reminded_at is not None
        or request.status != RequestStatus.AWAITING_PROVIDER
    ):
        return None
    settings = get_settings()
    seconds = (
        settings.own_service_reminder_critical_seconds
        if request.urgency == Urgency.CRITICAL
        else settings.own_service_reminder_seconds
    )
    return assignment.created_at + timedelta(seconds=seconds)


async def provider_summary(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> views.ProviderSummaryRatingView | None:
    """Проверки и рейтинг исполнителя назначения — те же, что в публичном профиле."""
    summaries = await providers.get_provider_summaries(session, [provider_org_id])
    summary = summaries.get(provider_org_id)
    if summary is None:
        return None
    rating = (await reputation.get_rating_summaries(session, [provider_org_id]))[provider_org_id]
    return views.ProviderSummaryRatingView(
        id=summary.id,
        display_name=summary.display_name,
        verification_marks=summary.verification_marks,
        rating=rating.average,
        rating_label=rating.label,
        reviews_count=rating.published_reviews_count,
        unique_reviewer_orgs_count=rating.unique_customers,
    )


async def customer_card_extras(
    session: AsyncSession,
    request: RepairRequest,
    assignment: Assignment | None,
    attachments: Sequence[AttachmentView],
    *,
    search: views.SearchStateView | None = None,
) -> CustomerCardExtras:
    """Поля карточки заказчика, общие для чтения и ответа на команду.

    `search` — итог только что выполненной публикации; без него состояние поиска
    читается из публичной карточки, чтобы GET и ответы команд совпадали."""
    return {
        "provider_contact_phone": (
            await provider_contact_phone(session, assignment) if assignment is not None else None
        ),
        "delivery": await delivery_status(session, request, assignment),
        "completion_report": await completion_report(session, request, assignment, attachments),
        "provider_summary": (
            await provider_summary(session, assignment.provider_org_id)
            if assignment is not None
            else None
        ),
        "reminder_at": own_service_reminder_at(request, assignment),
        "search": search if search is not None else await search_state(session, request),
    }


_CRM_SUFFIX = "CRM"
_NEVER_ACCEPTED = (AssignmentState.PENDING, AssignmentState.DECLINED, AssignmentState.EXPIRED)


async def message_authors(
    session: AsyncSession,
    messages: Sequence[Message],
    *,
    side: Literal["customer", "provider"],
    provider_disclosed: bool = False,
) -> dict[uuid.UUID, views.MessageAuthor]:
    """Подписи авторов переписки для читателя стороны `side` (ТЗ 14, I7).

    Своя сторона — имя сотрудника и название организации. Другая сторона:
    заказчику имя сотрудника исполнителя — только в общем канале принятого назначения,
    в треде до выбора — название компании; исполнителю имя и название заказчика —
    только после раскрытия контактов его назначения (`provider_disclosed`).
    Подпись CRM (`author_label`) — неподтверждённая строка и до назначения тоже
    не показывается."""
    membership_ids = {m.author_membership_id for m in messages if m.author_membership_id}
    client_ids = {
        m.author_integration_client_id for m in messages if m.author_integration_client_id
    }
    people: dict[uuid.UUID, tuple[str, str]] = {}
    if membership_ids:
        rows = await session.execute(
            select(Membership.id, User.display_name, Organization.display_name)
            .join(User, User.id == Membership.user_id)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.id.in_(tuple(membership_ids)))
        )
        people = {row[0]: (row[1], row[2]) for row in rows.all()}
    crm: dict[uuid.UUID, str] = {}
    if client_ids:
        rows = await session.execute(
            select(IntegrationClient.id, Organization.display_name)
            .join(Organization, Organization.id == IntegrationClient.provider_org_id)
            .where(IntegrationClient.id.in_(tuple(client_ids)))
        )
        crm = {row[0]: row[1] for row in rows.all()}
    unaccepted: set[uuid.UUID] = set()
    assignment_ids = {m.assignment_id for m in messages if m.assignment_id is not None}
    if side == "customer" and assignment_ids:
        rows = await session.execute(
            select(Assignment.id).where(
                Assignment.id.in_(tuple(assignment_ids)),
                Assignment.state.in_(_NEVER_ACCEPTED),
            )
        )
        unaccepted = set(rows.scalars().all())

    result: dict[uuid.UUID, views.MessageAuthor] = {}
    for message in messages:
        after_assignment = message.assignment_id is not None
        if message.author_kind == "integration_client":
            organization = crm.get(message.author_integration_client_id)  # type: ignore[arg-type]
            other_side = side == "customer"
            visible = not other_side or after_assignment
            result[message.id] = views.MessageAuthor(
                display_name=f"{_CRM_SUFFIX} {organization}" if organization else None,
                organization_name=organization,
                label=message.author_label if visible else None,
            )
            continue
        author_side = _SIDE_OF_KIND.get(message.author_kind)
        person = people.get(message.author_membership_id)  # type: ignore[arg-type]
        if author_side is None or person is None:
            result[message.id] = views.MessageAuthor()
            continue
        name, organization = person
        if author_side == side:
            result[message.id] = views.MessageAuthor(name, organization)
        elif side == "customer":
            accepted = after_assignment and message.assignment_id not in unaccepted
            result[message.id] = views.MessageAuthor(name if accepted else None, organization)
        elif provider_disclosed and after_assignment:
            result[message.id] = views.MessageAuthor(name, organization)
        else:
            result[message.id] = views.MessageAuthor()
    return result


async def message_deliveries(
    session: AsyncSession,
    request_id: uuid.UUID,
    messages: Sequence[Message],
    *,
    side: Literal["customer", "provider"],
) -> dict[uuid.UUID, views.DeliveryStatusView]:
    """«Доставлено в CRM» — заказчику по его сообщениям; адресат — назначение
    сообщения либо исполнитель приватного треда."""
    if side != "customer":
        return {}
    by_provider: dict[uuid.UUID, list[Message]] = {}
    assignment_ids = {m.assignment_id for m in messages if m.assignment_id is not None}
    providers_of: dict[uuid.UUID, uuid.UUID] = {}
    if assignment_ids:
        rows = await session.execute(
            select(Assignment.id, Assignment.provider_org_id).where(
                Assignment.id.in_(tuple(assignment_ids))
            )
        )
        providers_of = {row[0]: row[1] for row in rows.all()}
    for message in messages:
        if message.author_kind != "customer_membership":
            continue
        provider_org_id = message.thread_provider_org_id or (
            providers_of.get(message.assignment_id) if message.assignment_id else None
        )
        if provider_org_id is not None:
            by_provider.setdefault(provider_org_id, []).append(message)
    found: dict[uuid.UUID, views.DeliveryStatusView] = {}
    for provider_org_id, rows_of in by_provider.items():
        public_ids = {ids.encode("message", m.id): m.id for m in rows_of}
        statuses = await integration.message_delivery_statuses(
            session,
            request_id=request_id,
            provider_org_id=provider_org_id,
            message_public_ids=list(public_ids),
        )
        for public_id, status in statuses.items():
            found[public_ids[public_id]] = views.DeliveryStatusView(
                state=status.state,
                channel=status.channel,
                delivered_at=status.delivered_at,
                last_attempt_at=status.last_attempt_at,
                next_attempt_at=status.next_attempt_at,
            )
    return found
