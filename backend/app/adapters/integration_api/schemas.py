from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.db.enums import WarrantyDecision
from app.modules.integration.api import WebhookSubscriptionView

CancellationResponseDecision = Literal["accept", "decline"]
BindingResponseDecision = Literal["confirm", "reject"]

ExpectedVersion = Annotated[
    int,
    Field(ge=1, description="Версия заявки, которую видел клиент (`version` карточки)."),
]
CompletionOutcome = Literal["resolved", "not_resolved"]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class MeResponse(BaseModel):
    organization_id: str
    organization_name: str
    client_id: str
    client_name: str
    key_prefix: str
    scopes: list[str]


class WebhookSubscriptionCreateBody(BaseModel):
    url: Annotated[str, Field(min_length=1, max_length=2000)]
    events: list[str] = Field(default_factory=list)


class WebhookSubscriptionTestBody(BaseModel):
    event_type: str | None = None


class WebhookSubscriptionListResponse(BaseModel):
    items: list[WebhookSubscriptionView]
    next_cursor: str | None = None
    has_more: bool = False


class ExternalReferenceBody(BaseModel):
    external_id: Annotated[str, Field(min_length=1, max_length=200)]
    expected_version: ExpectedVersion


class AcceptRequestBody(BaseModel):
    assignment_id: str
    expected_version: ExpectedVersion


class DeclineRequestBody(BaseModel):
    assignment_id: str
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_version: ExpectedVersion


class WithdrawAssignmentBody(BaseModel):
    assignment_id: str
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_version: ExpectedVersion


class MessageCreateBody(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=4000)]
    author_label: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    assignment_id: str | None = None
    thread_provider_id: str | None = None
    expected_version: int | None = None


class VisitProposalBody(BaseModel):
    assignment_id: str
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    scope_description: str | None = None
    comment: str | None = None
    access_requirements: str | None = None
    valid_until: datetime | None = None
    expected_version: ExpectedVersion


class RepairQuoteItemBody(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    amount_minor: Annotated[int, Field(ge=0)]


class RepairQuoteBody(BaseModel):
    assignment_id: str
    description_of_work: Annotated[str, Field(min_length=1, max_length=4000)]
    items: Annotated[list[RepairQuoteItemBody], Field(max_length=50)] | None = None
    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    valid_until: datetime | None = None
    warranty_terms: Annotated[str, Field(max_length=1000)] | None = None
    expected_version: ExpectedVersion


class StartWorkBody(BaseModel):
    assignment_id: str
    expected_version: ExpectedVersion


class EnRouteBody(BaseModel):
    assignment_id: str
    expected_version: ExpectedVersion


class CompleteWorkBody(BaseModel):
    assignment_id: str
    outcome: Annotated[
        CompletionOutcome, Field(description="resolved — устранено, not_resolved — не устранено")
    ]
    summary: Annotated[str, Field(min_length=1, max_length=4000)]
    expected_version: ExpectedVersion


class CancellationResponseBody(BaseModel):
    assignment_id: str
    cancellation_id: str
    decision: Annotated[
        CancellationResponseDecision,
        Field(description="accept — согласиться с отменой, decline — оспорить"),
    ]
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: ExpectedVersion


class WarrantyDecisionBody(BaseModel):
    assignment_id: str
    decision: Annotated[WarrantyDecision, Field(description="Решение исполнителя о гарантийности")]
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: ExpectedVersion


class FieldWorkerBody(BaseModel):
    assignment_id: str
    membership_id: str | None = None
    display_name: Annotated[str, Field(max_length=200)] | None = None
    contact_phone: Annotated[str, Field(max_length=40)] | None = None
    expected_version: ExpectedVersion


class OfferSubmitBody(BaseModel):
    visit_window_start: datetime | None = None
    visit_window_end: datetime | None = None
    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    scope_description: str | None = None
    comment: str | None = None
    access_requirements: str | None = None
    valid_until: datetime | None = None
    expected_version: int | None = None


class OfferWithdrawBody(BaseModel):
    expected_version: int | None = None


class BindingResponseBody(BaseModel):
    decision: Annotated[
        BindingResponseDecision,
        Field(description="confirm — подтвердить привязку, reject — отклонить"),
    ]
    reason: Annotated[
        str | None, Field(default=None, max_length=2000, description="Обязательна при reject.")
    ]


class BindingInvitationItemBody(BaseModel):
    """Позиция оборудования по договору так, как её знает сервис: сопоставляет её
    с карточкой своего оборудования руководитель заказчика при принятии."""

    description: Annotated[str, Field(min_length=1, max_length=500)]
    serial_number: Annotated[str | None, Field(default=None, max_length=200)]
    model: Annotated[str | None, Field(default=None, max_length=200)]


class BindingInvitationCreateBody(BaseModel):
    customer_inn: Annotated[str, Field(min_length=1, max_length=20)]
    contract_number: Annotated[str, Field(min_length=1, max_length=200)]
    basis: str = "service_contract"
    valid_from: date | None = None
    valid_until: date | None = None
    customer_name: Annotated[str | None, Field(default=None, max_length=500)]
    equipment_items: Annotated[list[BindingInvitationItemBody], Field(max_length=100)] = Field(
        default_factory=list
    )
    guarantor_kind: Literal["manufacturer", "seller", "service_org"] | None = None
    guarantor_name: Annotated[str | None, Field(default=None, max_length=200)]
