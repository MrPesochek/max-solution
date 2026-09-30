from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


WebhookEventType = Literal[
    "request.assigned",
    "request.changed",
    "message.created",
    "offer.selected",
    "assignment.revoked",
    "visit_proposal.responded",
    "repair_quote.responded",
    "cancellation.requested",
    "request.closed",
    "service_binding.changed",
    "marketplace.request.available",
    "marketplace.request.closed",
    "ping",
]


REQUEST_EVENTS: frozenset[WebhookEventType] = frozenset(
    {
        "request.assigned",
        "request.changed",
        "message.created",
        "offer.selected",
        "visit_proposal.responded",
        "repair_quote.responded",
        "cancellation.requested",
        "request.closed",
    }
)

SUBSCRIBED_EVENTS: frozenset[WebhookEventType] = REQUEST_EVENTS | {"assignment.revoked"}


class WebhookEnvelope(BaseModel):
    schema_version: str
    event_id: str
    type: WebhookEventType
    occurred_at: datetime
    recipient_organization_id: str
    resource_id: str
    resource_version: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class MoneyAmount(BaseModel):
    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    is_known: bool = False


class EquipmentSnapshot(BaseModel):
    id: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    notes: str | None = None


class LocationSnapshot(BaseModel):
    id: str | None = None
    name: str | None = None
    city_id: str | None = None
    district_id: str | None = None
    address: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class FieldWorker(BaseModel):
    membership_id: str | None = None
    display_name: str | None = None
    contact_phone: str | None = None
    stated_by_company: bool = False


class Assignment(BaseModel):
    id: str
    request_id: str
    provider_organization_id: str
    route: str
    state: Literal[
        "pending", "accepted", "declined", "expired", "revoked", "withdrawn", "completed"
    ]
    warranty_decision: Literal["not_stated", "warranty", "not_warranty", "undetermined"] = (
        "not_stated"
    )
    warranty_decision_comment: str | None = None
    field_worker: FieldWorker | None = None
    decline_reason: str | None = None
    revoke_reason: str | None = None
    withdrawal_reason: str | None = None
    expires_at: datetime | None = None
    responded_at: datetime | None = None
    created_at: datetime


class VisitProposal(BaseModel):
    id: str
    assignment_id: str
    version: int
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    price: MoneyAmount
    scope_description: str | None = None
    comment: str | None = None
    access_requirements: str | None = None
    valid_until: datetime
    status: Literal["pending", "approved", "rejected", "expired", "superseded"] = "pending"
    responded_at: datetime | None = None
    response_comment: str | None = None
    created_at: datetime


class RepairQuoteItem(BaseModel):
    title: str
    amount_minor: int


class RepairQuote(BaseModel):
    id: str
    assignment_id: str
    version: int
    description_of_work: str
    price: MoneyAmount
    items: list[RepairQuoteItem] = Field(default_factory=list)
    valid_until: datetime
    status: Literal["pending", "approved", "rejected", "expired", "superseded"] = "pending"
    responded_at: datetime | None = None
    response_comment: str | None = None
    created_at: datetime


class CancellationRequest(BaseModel):
    id: str
    assignment_id: str
    target: Literal["cancel_request", "change_provider"]
    previous_status: str
    status: Literal["pending", "accepted", "disputed", "withdrawn", "force_closed"] = "pending"
    reason: str | None = None
    provider_response: str | None = None
    disputed: bool = False
    dispute_deadline_at: datetime | None = None
    resolution_kind: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class RequestAttachment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    owner_kind: str
    request_id: str | None = None
    message_id: str | None = None
    equipment_id: str | None = None
    slot: str | None = None
    visibility_class: str
    processing_state: Literal["quarantined", "ready", "rejected"]
    publication_state: str | None = None
    rejected_reason: str | None = None
    mime_type: str
    byte_size: int
    pixel_width: int | None = None
    pixel_height: int | None = None
    created_at: datetime


class MessageItem(BaseModel):
    id: str
    request_id: str
    author_kind: str
    author_membership_id: str | None = None
    body: str
    created_at: datetime


class RequestCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    request_number: int
    status: str
    route: str
    urgency: str = "normal"
    version: int
    symptom_description: str | None = None
    error_code: str | None = None
    equipment: EquipmentSnapshot
    location: LocationSnapshot
    contacts_disclosed: bool = False
    photos_incomplete: bool = False
    photos_incomplete_reason: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    assignment: Assignment
    visit_proposals: list[VisitProposal] = Field(default_factory=list)
    repair_quotes: list[RepairQuote] = Field(default_factory=list)
    cancellation: CancellationRequest | None = None
    attachments: list[RequestAttachment] = Field(default_factory=list)


class FormerAssignmentCard(BaseModel):
    request_id: str
    assignment: Assignment


class RequestListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

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


class AcceptRequest(BaseModel):
    assignment_id: str
    expected_version: int | None = None


class DeclineRequest(BaseModel):
    assignment_id: str
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = None


class WithdrawAssignmentRequest(BaseModel):
    assignment_id: str
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = None


class MessageCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    assignment_id: str | None = None
    expected_version: int | None = None


class VisitProposalCreateRequest(BaseModel):
    assignment_id: str
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    amount_minor: int | None = None
    currency: str = "RUB"
    zero_cost_reason: str | None = None
    vat_mode: str | None = None
    scope_description: str | None = None
    comment: str | None = None
    access_requirements: str | None = None
    valid_until: datetime | None = None
    expected_version: int | None = None


class RepairQuoteItemBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(ge=0)


class RepairQuoteCreateRequest(BaseModel):
    assignment_id: str
    description_of_work: str = Field(min_length=1, max_length=4000)
    items: list[RepairQuoteItemBody] | None = Field(default=None, max_length=50)
    amount_minor: int | None = None
    currency: str = "RUB"
    zero_cost_reason: str | None = None
    valid_until: datetime | None = None
    expected_version: int | None = None


class StartWorkRequest(BaseModel):
    assignment_id: str
    expected_version: int | None = None


class CompleteRequest(BaseModel):
    assignment_id: str
    outcome: Literal["resolved", "not_resolved"]
    summary: str = Field(min_length=1, max_length=4000)
    expected_version: int | None = None


class CancellationResponseRequest(BaseModel):
    assignment_id: str
    cancellation_id: str
    decision: Literal["accept", "decline"]
    comment: str | None = Field(default=None, max_length=2000)
    expected_version: int | None = None


class WebhookSubscriptionCreateRequest(BaseModel):
    url: str
    events: list[str] = Field(default_factory=list)


class WebhookSubscriptionResponse(BaseModel):
    id: str
    url: str
    secret: str
    status: str
    events: list[str] = Field(default_factory=list)


class WebhookSubscriptionItem(BaseModel):
    id: str
    url: str
    status: str
    events: list[str] = Field(default_factory=list)


class WebhookSubscriptionsPage(BaseModel):
    items: list[WebhookSubscriptionItem]
    next_cursor: str | None = None
    has_more: bool = False


class EventsPage(BaseModel):
    events: list[WebhookEnvelope]
    next_cursor: str | None = None
    has_more: bool = False


class MeResponse(BaseModel):
    organization_id: str
    organization_name: str
    client_id: str
    client_name: str
    key_prefix: str
    scopes: list[str] = Field(default_factory=list)
