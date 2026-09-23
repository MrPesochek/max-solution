import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.core import ids
from app.db.models import (
    Assignment,
    CancellationRequest,
    Equipment,
    EquipmentCategory,
    Location,
    Message,
    Offer,
    RepairQuote,
    RepairRequest,
    RequestEvent,
    RequestPublicCard,
    VisitProposal,
)
from app.modules.files.api import AttachmentView


class PriceView(BaseModel):
    """`amount_minor=None` — цена неизвестна и согласованной не считается (I3)."""

    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    is_known: bool = False


class EquipmentView(BaseModel):
    id: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    notes: str | None = None


class LocationView(BaseModel):
    id: str | None = None
    name: str | None = None
    city_id: str | None = None
    district_id: str | None = None
    address: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class FieldWorkerView(BaseModel):
    membership_id: str | None = None
    display_name: str | None = None
    contact_phone: str | None = None
    stated_by_company: bool = False


class ProviderSummaryRatingView(BaseModel):
    """Сводка исполнителя в карточке заказчика: проверки и рейтинг (ТЗ 8.3.3).

    При менее чем трёх уникальных организациях-оценщиках `rating` пуст,
    а `rating_label` — «Мало отзывов»."""

    id: str
    display_name: str
    verification_marks: list[str] = []
    rating: float | None = None
    rating_label: str | None = None
    reviews_count: int = 0
    unique_reviewer_orgs_count: int = 0


class AssignmentView(BaseModel):
    id: str
    request_id: str
    provider_organization_id: str
    provider_display_name: str | None = None
    provider_contact_phone: str | None = None
    route: str
    state: str
    warranty_decision: str
    warranty_decision_comment: str | None = None
    field_worker: FieldWorkerView | None = None
    decline_reason: str | None = None
    revoke_reason: str | None = None
    withdrawal_reason: str | None = None
    expires_at: datetime | None = None
    responded_at: datetime | None = None
    created_at: datetime
    en_route_at: datetime | None = None
    provider: ProviderSummaryRatingView | None = None
    reminder_at: datetime | None = None


class VisitProposalView(BaseModel):
    id: str
    assignment_id: str
    version: int
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    price: PriceView
    scope_description: str | None = None
    comment: str | None = None
    access_requirements: str | None = None
    valid_until: datetime
    status: str
    responded_at: datetime | None = None
    response_comment: str | None = None
    created_at: datetime


class RepairQuoteItemView(BaseModel):
    title: str
    amount_minor: int


class RepairQuoteView(BaseModel):
    id: str
    assignment_id: str
    version: int
    description_of_work: str
    price: PriceView
    items: list[RepairQuoteItemView] = []
    valid_until: datetime
    status: str
    responded_at: datetime | None = None
    response_comment: str | None = None
    created_at: datetime
    warranty_terms: str | None = None


class CancellationRequestView(BaseModel):
    id: str
    assignment_id: str
    target: str
    previous_status: str
    status: str
    reason: str | None = None
    provider_response: str | None = None
    disputed: bool
    dispute_deadline_at: datetime | None = None
    resolution_kind: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class MessageView(BaseModel):
    id: str
    request_id: str
    author_kind: str
    author_membership_id: str | None = None
    thread_provider_id: str | None = None
    body: str
    created_at: datetime
    author_display_name: str | None = None
    author_organization_name: str | None = None
    author_label: str | None = None
    delivery: "DeliveryStatusView | None" = None


class MessagesReadView(BaseModel):
    """Ответ на отметку прочтения переписки заявки."""

    request_id: str
    last_read_message_id: str | None = None
    unread_messages_count: int


class RequestEventView(BaseModel):
    """Лента экрана «История»: событие, смена статуса и ссылки на объекты."""

    id: str
    occurred_at: datetime
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor_kind: str
    actor_display_name: str | None = None
    payload: dict[str, Any]


class DeliveryStatusView(BaseModel):
    """Доставка назначения в CRM исполнителя (ТЗ 8.2) — отдельно от его принятия.

    `none` + `channel="app"` — у исполнителя нет CRM, заявка приходит в бот и
    мини-приложение. Технические подробности ошибок CRM сюда не попадают.
    """

    state: Literal["queued", "delivered", "retrying", "failed", "none"]
    channel: Literal["crm", "app"]
    delivered_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None


class CompletionReportView(BaseModel):
    """Отчёт мастера о завершении: итог, описание и фото «до/после»."""

    outcome: str | None = None
    summary: str | None = None
    reported_at: datetime | None = None
    photos_before: list[AttachmentView] = []
    photos_after: list[AttachmentView] = []


class RequestCustomerView(BaseModel):
    id: str
    request_number: int
    status: str
    route: str
    urgency: str
    version: int
    symptom_description: str | None = None
    error_code: str | None = None
    equipment: EquipmentView
    location: LocationView
    photos_incomplete: bool = False
    photos_incomplete_reason: str | None = None
    closure_kind: str | None = None
    cancellation_reason: str | None = None
    disputed: bool = False
    submitted_at: datetime | None = None
    accepted_at: datetime | None = None
    scheduled_at: datetime | None = None
    work_started_at: datetime | None = None
    completion_reported_at: datetime | None = None
    closed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    assignment: AssignmentView | None = None
    visit_proposals: list[VisitProposalView] = []
    repair_quotes: list[RepairQuoteView] = []
    cancellation: CancellationRequestView | None = None
    attachments: list[AttachmentView] = []
    search: "SearchStateView | None" = None
    equipment_category_name: str | None = None
    unread_messages_count: int | None = None
    approver_name: str | None = None
    delivery: DeliveryStatusView | None = None
    completion_report: CompletionReportView | None = None


class RequestProviderView(BaseModel):
    id: str
    request_number: int
    status: str
    route: str
    urgency: str
    version: int
    symptom_description: str | None = None
    error_code: str | None = None
    equipment: EquipmentView
    location: LocationView
    contacts_disclosed: bool
    photos_incomplete: bool = False
    photos_incomplete_reason: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    assignment: AssignmentView
    visit_proposals: list[VisitProposalView] = []
    repair_quotes: list[RepairQuoteView] = []
    cancellation: CancellationRequestView | None = None
    attachments: list[AttachmentView] = []
    equipment_category_name: str | None = None
    unread_messages_count: int | None = None
    completion_report: CompletionReportView | None = None
    customer_org_name: str | None = None


class RequestFormerProviderView(BaseModel):
    """ТЗ 14: у прекращённого исполнителя остаётся запись о назначении без содержимого заявки."""

    request_id: str
    assignment: AssignmentView


class RequestPublicCardView(BaseModel):
    """Публичная карточка внешнего поиска — белый список (ТЗ 9, S2.4, I7).

    Точный адрес, телефон, серийный номер, гарантийные документы и история
    обслуживания сюда не попадают: карточка собирается из выбранных полей, а не
    вычёркиванием из полной заявки.
    """

    request_id: str
    request_number: int
    equipment_category_id: str
    equipment_category_name: str | None = None
    brand: str | None = None
    model: str | None = None
    city_id: str
    district_id: str | None = None
    city_name: str | None = None
    district_name: str | None = None
    city_timezone: str | None = None
    urgency: str
    published_description: str | None = None
    published_attachment_ids: list[str] = []
    status: str
    published_at: datetime
    search_expires_at: datetime | None = None


class MarketplaceListItemView(RequestPublicCardView):
    """Строка биржи: карточка плюс число уже поданных откликов (без их содержания)
    и состояние своего треда вопросов — свой вопрос без ответа или ответ заказчика."""

    offers_count: int = 0
    has_open_question: bool = False
    has_clarification: bool = False


class OfferProviderView(BaseModel):
    """Краткая карточка исполнителя при показе оффера заказчику."""

    id: str
    display_name: str
    verification_marks: list[str]
    rating: float | None = None
    rating_label: str | None = None
    unique_reviewer_orgs_count: int = 0
    reviews_count: int = 0


class OfferView(BaseModel):
    id: str
    request_id: str
    provider_organization_id: str
    version: int
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    price: PriceView
    scope_description: str | None = None
    comment: str | None = None
    access_requirements: str | None = None
    valid_until: datetime
    state: str
    created_at: datetime
    provider: OfferProviderView | None = None


class SearchStateView(BaseModel):
    """Итог публикации: что раскрыто и скольким исполнителям ушла карточка."""

    published: bool
    matched_providers: int
    search_expires_at: datetime | None = None
    public_card: RequestPublicCardView | None = None
    published_source_attachment_ids: list[str] = []


class ExistingBindingView(BaseModel):
    """ТЗ S2.2: для оборудования со своим сервисом показывается действующая привязка."""

    service_binding_id: str
    provider_organization_id: str | None = None
    provider_name: str | None = None
    status: str


class PublicCardPreviewView(BaseModel):
    """Экран раскрытия перед публикацией (ТЗ 14, п. 2)."""

    public_card: RequestPublicCardView
    withheld_fields: list[str]
    matched_providers: int
    existing_binding: ExistingBindingView | None = None


class MarketplaceCardView(BaseModel):
    card: RequestPublicCardView
    my_offers: list[OfferView] = []


PendingDecisionKind = Literal[
    "approval",
    "visit_proposal",
    "repair_quote",
    "offers",
    "completion_reported",
    "cancellation_disputed",
    "action_required",
]


class PendingDecisionView(BaseModel):
    """Что по заявке ждёт решения руководителя: сумма, срок ответа, число откликов."""

    kind: PendingDecisionKind
    amount_minor: int | None = None
    currency: str | None = None
    respond_by: datetime | None = None
    offers_count: int | None = None


class RequestListItemView(BaseModel):
    id: str
    request_number: int
    status: str
    route: str
    urgency: str
    version: int
    location_id: str | None = None
    location_name: str | None = None
    equipment_title: str | None = None
    symptom_description: str | None = None
    assignment_id: str | None = None
    assignment_state: str | None = None
    provider_organization_id: str | None = None
    updated_at: datetime
    created_at: datetime
    equipment_id: str | None = None
    equipment_category_name: str | None = None
    equipment_brand: str | None = None
    equipment_model: str | None = None
    pending_decision: PendingDecisionView | None = None
    customer_org_name: str | None = None
    contract_number: str | None = None
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    timezone: str | None = None
    en_route_at: datetime | None = None
    field_worker_name: str | None = None
    unread_messages_count: int | None = None
    last_message_at: datetime | None = None
    my_review_rating: int | None = None
    closed_at: datetime | None = None
    cancelled_at: datetime | None = None


PendingApprovalKind = Literal[
    "draft_approval",
    "visit_proposal",
    "repair_quote",
    "completion_reported",
    "cancellation_disputed",
    "action_required",
    "question",
]


class PendingApprovalRequestView(BaseModel):
    id: str
    request_number: int
    status: str
    version: int


class PendingApprovalObjectView(BaseModel):
    id: str
    version: int | None = None


class PendingApprovalItemView(BaseModel):
    """Один элемент агрегата «ждёт согласования менеджера» (GET /requests/pending-approvals)."""

    kind: PendingApprovalKind
    request: PendingApprovalRequestView
    object: PendingApprovalObjectView | None = None
    due_at: datetime | None = None
    amount_minor: int | None = None
    currency: str | None = None
    thread_provider_id: str | None = None


def price_view(
    amount_minor: int | None,
    currency: str | None,
    vat_mode: str | None,
    zero_cost_reason: str | None,
) -> PriceView:
    return PriceView(
        amount_minor=amount_minor,
        currency=currency,
        vat_mode=vat_mode,
        zero_cost_reason=zero_cost_reason,
        is_known=amount_minor is not None,
    )


def equipment_snapshot(equipment: Equipment, category: EquipmentCategory | None) -> dict[str, Any]:
    """Снимок оборудования на момент отправки (ТЗ 10.1, I26)."""
    return {
        "id": ids.encode("equipment", equipment.id),
        "category_id": ids.encode("category", equipment.equipment_category_id),
        "category_name": category.name if category is not None else None,
        "brand": equipment.brand,
        "model": equipment.model,
        "serial_number": equipment.serial_number,
        "notes": equipment.notes,
    }


def location_snapshot(location: Location) -> dict[str, Any]:
    return {
        "id": ids.encode("location", location.id),
        "name": location.name,
        "city_id": ids.encode("city", location.city_id),
        "district_id": ids.encode_opt("district", location.district_id),
        "address": location.address,
        "timezone": location.timezone,
        "contact_name": location.contact_name,
        "contact_phone": location.contact_phone,
    }


WITHHELD_FROM_PUBLIC_CARD = (
    "location.address",
    "location.name",
    "location.contact_name",
    "location.contact_phone",
    "equipment.serial_number",
    "equipment.notes",
    "warranty_documents",
    "service_history",
)


def to_public_card_view(
    request: RepairRequest,
    card: RequestPublicCard,
    *,
    attachment_ids: Sequence[str] = (),
    city_name: str | None = None,
    district_name: str | None = None,
) -> RequestPublicCardView:
    snapshot = request.equipment_snapshot
    return RequestPublicCardView(
        request_id=ids.encode("request", request.id),
        request_number=request.request_number,
        equipment_category_id=ids.encode("category", card.equipment_category_id),
        equipment_category_name=snapshot.get("category_name"),
        brand=snapshot.get("brand"),
        model=snapshot.get("model"),
        city_id=ids.encode("city", card.city_id),
        district_id=ids.encode_opt("district", card.district_id),
        city_name=city_name,
        district_name=district_name,
        city_timezone=request.location_snapshot.get("timezone"),
        urgency=card.urgency,
        published_description=card.published_description,
        published_attachment_ids=list(attachment_ids),
        status=card.status,
        published_at=card.published_at,
        search_expires_at=request.search_expires_at,
    )


def to_offer_view(offer: Offer, *, provider: OfferProviderView | None = None) -> OfferView:
    return OfferView(
        id=ids.encode("offer", offer.id),
        request_id=ids.encode("request", offer.request_id),
        provider_organization_id=ids.encode("organization", offer.provider_org_id),
        version=offer.version,
        visit_window_start=offer.visit_window_start,
        visit_window_end=offer.visit_window_end,
        price=price_view(
            offer.visit_amount_minor, offer.currency, offer.vat_mode, offer.zero_cost_reason
        ),
        scope_description=offer.scope_description,
        comment=offer.comment,
        access_requirements=offer.access_requirements,
        valid_until=offer.valid_until,
        state=offer.state,
        created_at=offer.created_at,
        provider=provider,
    )


def to_assignment_view(
    assignment: Assignment,
    *,
    field_worker_name: str | None = None,
    provider_display_name: str | None = None,
    provider_contact_phone: str | None = None,
    provider: ProviderSummaryRatingView | None = None,
    reminder_at: datetime | None = None,
) -> AssignmentView:
    worker: FieldWorkerView | None = None
    if (
        assignment.field_worker_membership_id is not None
        or assignment.field_worker_display_name is not None
    ):
        worker = FieldWorkerView(
            membership_id=ids.encode_opt("membership", assignment.field_worker_membership_id),
            display_name=(
                field_worker_name
                if assignment.field_worker_membership_id
                else assignment.field_worker_display_name
            ),
            contact_phone=assignment.field_worker_contact_phone,
            stated_by_company=assignment.field_worker_membership_id is None,
        )
    return AssignmentView(
        id=ids.encode("assignment", assignment.id),
        request_id=ids.encode("request", assignment.request_id),
        provider_organization_id=ids.encode("organization", assignment.provider_org_id),
        provider_display_name=provider_display_name,
        provider_contact_phone=provider_contact_phone,
        route=assignment.route,
        state=assignment.state,
        warranty_decision=assignment.warranty_decision,
        warranty_decision_comment=assignment.warranty_decision_comment,
        field_worker=worker,
        decline_reason=assignment.decline_reason,
        revoke_reason=assignment.revoke_reason,
        withdrawal_reason=assignment.withdrawal_reason,
        expires_at=assignment.expires_at,
        responded_at=assignment.responded_at,
        created_at=assignment.created_at,
        en_route_at=assignment.en_route_at,
        provider=provider,
        reminder_at=reminder_at,
    )


def to_visit_proposal_view(proposal: VisitProposal) -> VisitProposalView:
    return VisitProposalView(
        id=ids.encode("visit_proposal", proposal.id),
        assignment_id=ids.encode("assignment", proposal.assignment_id),
        version=proposal.version,
        visit_window_start=proposal.visit_window_start,
        visit_window_end=proposal.visit_window_end,
        price=price_view(
            proposal.visit_amount_minor,
            proposal.currency,
            proposal.vat_mode,
            proposal.zero_cost_reason,
        ),
        scope_description=proposal.scope_description,
        comment=proposal.comment,
        access_requirements=proposal.access_requirements,
        valid_until=proposal.valid_until,
        status=proposal.status,
        responded_at=proposal.responded_at,
        response_comment=proposal.response_comment,
        created_at=proposal.created_at,
    )


def to_repair_quote_view(quote: RepairQuote) -> RepairQuoteView:
    return RepairQuoteView(
        id=ids.encode("repair_quote", quote.id),
        assignment_id=ids.encode("assignment", quote.assignment_id),
        version=quote.version,
        description_of_work=quote.description_of_work,
        price=price_view(
            quote.amount_minor, quote.currency, quote.vat_mode, quote.zero_cost_reason
        ),
        items=[RepairQuoteItemView(**item) for item in quote.items or ()],
        valid_until=quote.valid_until,
        status=quote.status,
        responded_at=quote.responded_at,
        response_comment=quote.response_comment,
        created_at=quote.created_at,
        warranty_terms=quote.warranty_terms,
    )


def to_cancellation_view(row: CancellationRequest) -> CancellationRequestView:
    return CancellationRequestView(
        id=ids.encode("cancellation", row.id),
        assignment_id=ids.encode("assignment", row.assignment_id),
        target=row.target,
        previous_status=row.previous_status,
        status=row.status,
        reason=row.reason,
        provider_response=row.provider_response,
        disputed=row.disputed,
        dispute_deadline_at=row.dispute_deadline_at,
        resolution_kind=row.resolution_kind,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
    )


@dataclass(frozen=True, slots=True)
class MessageAuthor:
    display_name: str | None = None
    organization_name: str | None = None
    label: str | None = None


def to_message_view(
    message: Message,
    *,
    author: MessageAuthor | None = None,
    delivery: "DeliveryStatusView | None" = None,
) -> MessageView:
    shown = author or MessageAuthor()
    return MessageView(
        id=ids.encode("message", message.id),
        request_id=ids.encode("request", message.request_id),
        author_kind=message.author_kind,
        author_membership_id=ids.encode_opt("membership", message.author_membership_id),
        thread_provider_id=ids.encode_opt("organization", message.thread_provider_org_id),
        body=message.body,
        created_at=message.created_at,
        author_display_name=shown.display_name,
        author_organization_name=shown.organization_name,
        author_label=shown.label,
        delivery=delivery,
    )


_ASSIGNMENT = frozenset({"assignment_id"})
_REASONED = frozenset({"assignment_id", "reason"})
_OFFER = frozenset({"offer_id", "offer_version"})
_PROPOSAL = frozenset({"visit_proposal_id", "proposal_version"})
_QUOTE = frozenset({"repair_quote_id", "quote_version"})
_CANCELLATION = frozenset({"cancellation_id", "target", "reason", "comment", "assignment_id"})

EVENT_PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "RequestDrafted": frozenset(),
    "RequestDraftUpdated": frozenset(),
    "RequestSubmittedForApproval": frozenset({"comment"}),
    "RequestReturnedToDraft": frozenset({"comment"}),
    "RequestSubmittedToOwnService": frozenset(
        {"assignment_id", "service_binding_id", "photos_incomplete", "photos_incomplete_reason"}
    ),
    "SearchPublished": frozenset({"matched_providers", "attachment_ids"}),
    "SearchFoundNoProviders": frozenset({"matched_providers"}),
    "SearchExpired": frozenset(),
    "SearchStopped": frozenset({"target", "reason", "assignment_id"}),
    "RequestCancelled": _CANCELLATION,
    "AssignmentAccepted": _ASSIGNMENT,
    "AssignmentDeclined": _REASONED,
    "AssignmentRevoked": _CANCELLATION,
    "AssignmentWithdrawn": _REASONED,
    "AssignmentConfirmed": frozenset({"assignment_id", "visit_agreed"}),
    "AssignmentExpired": _REASONED,
    "OwnServiceReminded": _ASSIGNMENT,
    "OfferSubmitted": _OFFER,
    "OfferWithdrawn": _OFFER,
    "OfferExpired": _OFFER,
    "OfferSelected": frozenset({"offer_id", "assignment_id"}),
    "VisitProposed": _PROPOSAL,
    "VisitProposalSuperseded": _PROPOSAL,
    "VisitAgreed": _PROPOSAL,
    "VisitProposalRejected": _PROPOSAL,
    "VisitProposalExpired": _PROPOSAL,
    "RepairQuoteCreated": _QUOTE,
    "RepairQuoteApproved": _QUOTE,
    "RepairQuoteRejected": _QUOTE,
    "RepairQuoteExpired": _QUOTE,
    "CancellationRequested": _CANCELLATION,
    "CancellationDisputed": _CANCELLATION,
    "CancellationWithdrawn": _CANCELLATION,
    "CancellationForced": _CANCELLATION,
    "WorkStarted": frozenset(),
    "CompletionReported": frozenset({"outcome", "summary"}),
    "CompletionRejected": frozenset({"reason"}),
    "CompletionReminderSent": frozenset({"reminder"}),
    "RequestClosed": frozenset({"assignment_id", "closure_kind"}),
    "RequestDetailsUpdated": frozenset({"changed_fields", "changes"}),
    "LinkedRequestCreated": frozenset({"parent_request_id"}),
    "MessageCreated": frozenset({"message_id"}),
    "ExternalReferenceLinked": frozenset({"external_id"}),
    "WarrantyDecisionStated": frozenset({"warranty_decision"}),
    "FieldWorkerAssigned": frozenset(),
    "FieldWorkerEnRoute": _ASSIGNMENT,
}
_HIDDEN_FROM: dict[str, frozenset[str]] = {
    "customer": frozenset({"external_id"}),
    "provider": frozenset(
        {"matched_providers", "attachment_ids", "service_binding_id", "changes", "changed_fields"}
    ),
}


def to_event_view(
    event: RequestEvent,
    *,
    side: Literal["customer", "provider"],
    actor_display_name: str | None = None,
) -> RequestEventView:
    allowed = EVENT_PAYLOAD_KEYS.get(event.event_type, frozenset()) - _HIDDEN_FROM[side]
    return RequestEventView(
        id=ids.encode("event", event.id),
        occurred_at=event.occurred_at,
        event_type=event.event_type,
        from_status=event.from_status,
        to_status=event.to_status,
        actor_kind=event.actor_kind,
        actor_display_name=actor_display_name,
        payload={key: value for key, value in event.payload.items() if key in allowed},
    )


def _snapshot_equipment(request: RepairRequest) -> EquipmentView:
    return EquipmentView(**{k: v for k, v in request.equipment_snapshot.items() if v is not None})


def _snapshot_location(request: RepairRequest) -> LocationView:
    return LocationView(**{k: v for k, v in request.location_snapshot.items() if v is not None})


def to_customer_view(
    request: RepairRequest,
    *,
    equipment: Equipment | None = None,
    category: EquipmentCategory | None = None,
    location: Location | None = None,
    assignment: Assignment | None = None,
    field_worker_name: str | None = None,
    provider_display_name: str | None = None,
    proposals: Sequence[VisitProposal] = (),
    quotes: Sequence[RepairQuote] = (),
    cancellation: CancellationRequest | None = None,
    attachments: Sequence[AttachmentView] = (),
    search: SearchStateView | None = None,
    unread_messages_count: int | None = None,
    approver_name: str | None = None,
    provider_contact_phone: str | None = None,
    delivery: DeliveryStatusView | None = None,
    completion_report: CompletionReportView | None = None,
    provider_summary: ProviderSummaryRatingView | None = None,
    reminder_at: datetime | None = None,
) -> RequestCustomerView:
    equipment_view = (
        EquipmentView(
            id=ids.encode("equipment", equipment.id),
            category_id=ids.encode("category", equipment.equipment_category_id),
            category_name=category.name if category is not None else None,
            brand=equipment.brand,
            model=equipment.model,
            serial_number=equipment.serial_number,
            notes=equipment.notes,
        )
        if equipment is not None
        else _snapshot_equipment(request)
    )
    location_view = (
        LocationView(
            id=ids.encode("location", location.id),
            name=location.name,
            city_id=ids.encode("city", location.city_id),
            district_id=ids.encode_opt("district", location.district_id),
            address=location.address,
            timezone=location.timezone,
            contact_name=location.contact_name,
            contact_phone=location.contact_phone,
        )
        if location is not None
        else _snapshot_location(request)
    )
    return RequestCustomerView(
        id=ids.encode("request", request.id),
        request_number=request.request_number,
        status=request.status,
        route=request.route,
        urgency=request.urgency,
        version=request.version,
        symptom_description=request.symptom_description,
        error_code=request.error_code,
        equipment=equipment_view,
        location=location_view,
        photos_incomplete=request.photos_incomplete,
        photos_incomplete_reason=request.photos_incomplete_reason,
        closure_kind=request.closure_kind,
        cancellation_reason=request.cancellation_reason,
        disputed=request.disputed,
        submitted_at=request.submitted_at,
        accepted_at=request.accepted_at,
        scheduled_at=request.scheduled_at,
        work_started_at=request.work_started_at,
        completion_reported_at=request.completion_reported_at,
        closed_at=request.closed_at,
        cancelled_at=request.cancelled_at,
        created_at=request.created_at,
        assignment=(
            to_assignment_view(
                assignment,
                field_worker_name=field_worker_name,
                provider_display_name=provider_display_name,
                provider_contact_phone=provider_contact_phone,
                provider=provider_summary,
                reminder_at=reminder_at,
            )
            if assignment is not None
            else None
        ),
        visit_proposals=[to_visit_proposal_view(p) for p in proposals],
        repair_quotes=[to_repair_quote_view(q) for q in quotes],
        cancellation=to_cancellation_view(cancellation) if cancellation is not None else None,
        attachments=list(attachments),
        search=search,
        equipment_category_name=equipment_view.category_name,
        unread_messages_count=unread_messages_count,
        approver_name=approver_name,
        delivery=delivery,
        completion_report=completion_report,
    )


def to_provider_view(
    request: RepairRequest,
    assignment: Assignment,
    *,
    disclose: bool,
    field_worker_name: str | None = None,
    proposals: Sequence[VisitProposal] = (),
    quotes: Sequence[RepairQuote] = (),
    cancellation: CancellationRequest | None = None,
    attachments: Sequence[AttachmentView] = (),
    unread_messages_count: int | None = None,
    completion_report: CompletionReportView | None = None,
    customer_org_name: str | None = None,
) -> RequestProviderView:
    """Срез заявки для исполнителя; до раскрытия скрыты адрес, контакты и серийный номер."""
    equipment = _snapshot_equipment(request)
    location = _snapshot_location(request)
    if not disclose:
        equipment = equipment.model_copy(update={"serial_number": None, "notes": None})
        location = location.model_copy(
            update={"name": None, "address": None, "contact_name": None, "contact_phone": None}
        )
    return RequestProviderView(
        id=ids.encode("request", request.id),
        request_number=request.request_number,
        status=request.status,
        route=request.route,
        urgency=request.urgency,
        version=request.version,
        symptom_description=request.symptom_description,
        error_code=request.error_code,
        equipment=equipment,
        location=location,
        contacts_disclosed=disclose,
        photos_incomplete=request.photos_incomplete,
        photos_incomplete_reason=request.photos_incomplete_reason,
        submitted_at=request.submitted_at,
        created_at=request.created_at,
        assignment=to_assignment_view(assignment, field_worker_name=field_worker_name),
        visit_proposals=[to_visit_proposal_view(p) for p in proposals],
        repair_quotes=[to_repair_quote_view(q) for q in quotes],
        cancellation=to_cancellation_view(cancellation) if cancellation is not None else None,
        attachments=list(attachments),
        equipment_category_name=equipment.category_name,
        unread_messages_count=unread_messages_count,
        completion_report=completion_report,
        customer_org_name=customer_org_name if disclose else None,
    )


def to_former_provider_view(
    request_id: uuid.UUID, assignment: Assignment
) -> RequestFormerProviderView:
    return RequestFormerProviderView(
        request_id=ids.encode("request", request_id),
        assignment=to_assignment_view(assignment),
    )


def to_list_item(
    request: RepairRequest,
    *,
    location_name: str | None = None,
    equipment_title: str | None = None,
    assignment: Assignment | None = None,
    equipment_id: uuid.UUID | None = None,
    equipment_category_name: str | None = None,
    equipment_brand: str | None = None,
    equipment_model: str | None = None,
    pending_decision: PendingDecisionView | None = None,
    customer_org_name: str | None = None,
    contract_number: str | None = None,
    visit_proposal: VisitProposal | None = None,
    timezone: str | None = None,
    field_worker_name: str | None = None,
    unread_messages_count: int | None = None,
    last_message_at: datetime | None = None,
    my_review_rating: int | None = None,
) -> RequestListItemView:
    snapshot = request.equipment_snapshot
    title = equipment_title or " ".join(
        str(part) for part in (snapshot.get("brand"), snapshot.get("model")) if part
    )
    return RequestListItemView(
        id=ids.encode("request", request.id),
        request_number=request.request_number,
        status=request.status,
        route=request.route,
        urgency=request.urgency,
        version=request.version,
        location_id=ids.encode("location", request.location_id),
        location_name=location_name,
        equipment_title=title or None,
        symptom_description=request.symptom_description,
        assignment_id=ids.encode_opt(
            "assignment", assignment.id if assignment is not None else None
        ),
        assignment_state=assignment.state if assignment is not None else None,
        provider_organization_id=ids.encode_opt(
            "organization", assignment.provider_org_id if assignment is not None else None
        ),
        updated_at=request.updated_at,
        created_at=request.created_at,
        equipment_id=ids.encode_opt("equipment", equipment_id),
        equipment_category_name=equipment_category_name,
        equipment_brand=equipment_brand,
        equipment_model=equipment_model,
        pending_decision=pending_decision,
        customer_org_name=customer_org_name,
        contract_number=contract_number,
        visit_window_start=visit_proposal.visit_window_start if visit_proposal else None,
        visit_window_end=visit_proposal.visit_window_end if visit_proposal else None,
        timezone=timezone,
        en_route_at=assignment.en_route_at if assignment is not None else None,
        field_worker_name=field_worker_name,
        unread_messages_count=unread_messages_count,
        last_message_at=last_message_at,
        my_review_rating=my_review_rating,
        closed_at=request.closed_at,
        cancelled_at=request.cancelled_at,
    )
