import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.core import ids
from app.db.enums import CancellationTarget, RequestRoute, Urgency, WarrantyDecision
from app.modules.identity.api import MembershipView, OrganizationRefView, UserView

BindingRespondDecision = Literal["confirm", "reject"]
CancellationResponseDecision = Literal["accept", "decline"]
CompletionOutcome = Literal["resolved", "not_resolved"]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def page_of[T](items: list[T], kind: str, next_cursor: uuid.UUID | None) -> Page[T]:
    return Page[T](items=items, next_cursor=ids.encode_opt(kind, next_cursor))


class InitDataLogin(BaseModel):
    init_data: Annotated[str, Field(min_length=1, max_length=8192)]


class DemoLogin(BaseModel):
    user_key: Annotated[str, Field(min_length=1, max_length=64)]


class LinkLogin(BaseModel):
    token: Annotated[str, Field(min_length=1, max_length=128)]


class AuthResponse(BaseModel):
    token: str
    expires_at: datetime
    user: UserView
    memberships: list[MembershipView]
    organizations: list[OrganizationRefView]


class LinkAuthResponse(AuthResponse):
    target: str | None = None


class MeResponse(BaseModel):
    user: UserView
    memberships: list[MembershipView]
    organizations: list[OrganizationRefView]


class FirstLocationBody(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    city_id: str
    address: Annotated[str, Field(min_length=1, max_length=500)]
    district_id: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class OrganizationCreateBody(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    kind: str
    contact_phone: Annotated[str, Field(min_length=1, max_length=40)]
    contact_name: str | None = None
    representative_position: Annotated[str, Field(max_length=200)] | None = None
    contact_email: str | None = None
    legal_form: str | None = None
    inn: str | None = None
    provider_kind: str = "company"
    first_location: FirstLocationBody | None = None


class ParticipationBody(BaseModel):
    kind: str
    provider_kind: str = "company"
    first_location: FirstLocationBody | None = None


class OrganizationUpdateBody(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    contact_name: str | None = None
    representative_position: Annotated[str, Field(max_length=200)] | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    legal_form: str | None = None
    inn: str | None = None


class LocationCreateBody(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    city_id: str
    address: Annotated[str, Field(min_length=1, max_length=500)]
    district_id: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class LocationUpdateBody(BaseModel):
    name: str | None = None
    city_id: str | None = None
    district_id: str | None = None
    address: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class EquipmentCreateBody(BaseModel):
    location_id: str
    equipment_category_id: str
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    notes: str | None = None


class EquipmentUpdateBody(BaseModel):
    location_id: str | None = None
    equipment_category_id: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    notes: str | None = None


class MembershipLocationsBody(BaseModel):
    location_ids: list[str]


class InvitationCreateBody(BaseModel):
    role: str
    location_ids: list[str] = Field(default_factory=list)
    recipient_max_user_id: Annotated[str, Field(max_length=64)] | None = None
    recipient_name: Annotated[str, Field(max_length=200)] | None = None


class InvitationAcceptBody(BaseModel):
    token: Annotated[str, Field(min_length=8, max_length=512)]


class ApiKeyCreateBody(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    scopes: list[str] = Field(default_factory=list)


class WebhookSubscriptionCreateBody(BaseModel):
    url: Annotated[str, Field(min_length=1, max_length=2000)]
    events: list[str] = Field(default_factory=list)
    client_id: str | None = None


class ServiceAreaBody(BaseModel):
    """Зона: город целиком (`district_ids` пуст) либо перечень его районов (D12)."""

    city_id: str
    district_ids: list[str] = Field(default_factory=list)


class BrandRestrictionBody(BaseModel):
    equipment_category_id: str
    brands: list[str] = Field(default_factory=list)


class ProviderProfileUpdateBody(BaseModel):
    provider_kind: str | None = None
    legal_form: str | None = None
    inn: str | None = None
    contact_name: Annotated[str, Field(max_length=200)] | None = None
    representative_position: Annotated[str, Field(max_length=200)] | None = None
    contact_phone: Annotated[str, Field(max_length=40)] | None = None
    contact_email: Annotated[str, Field(max_length=200)] | None = None
    visit_terms: Annotated[str, Field(max_length=2000)] | None = None
    visit_price_from_minor: Annotated[int, Field(ge=0)] | None = None
    can_provide_documents: bool | None = None
    description: Annotated[str, Field(max_length=4000)] | None = None
    category_ids: list[str] | None = None
    service_areas: list[ServiceAreaBody] | None = None
    brand_restrictions: list[BrandRestrictionBody] | None = None


class AcceptingRequestsBody(BaseModel):
    accepting: bool


class ProfileAppealBody(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=4000)]


class BindingRequestBody(BaseModel):
    provider_organization_id: str
    contract_number: Annotated[str, Field(min_length=1, max_length=200)]
    equipment_ids: list[str]
    basis: str = "service_contract"


class ContactBindingBody(BaseModel):
    equipment_id: str
    contact_name: Annotated[str, Field(min_length=1, max_length=200)]
    contact_phone: Annotated[str, Field(max_length=40)] | None = None


class BindingRespondBody(BaseModel):
    decision: Annotated[
        BindingRespondDecision,
        Field(description="confirm — подтвердить привязку, reject — отклонить"),
    ]
    reason: Annotated[str, Field(max_length=2000)] | None = None


class BindingRevokeBody(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class BindingInvitationItemBody(BaseModel):
    """Позиция оборудования по договору: у сервиса нет идентификатора карточки
    заказчика, только описание, модель и серийный номер."""

    description: Annotated[str, Field(min_length=1, max_length=500)]
    serial_number: Annotated[str | None, Field(default=None, max_length=500)]
    model: Annotated[str | None, Field(default=None, max_length=500)]


class BindingInvitationCreateBody(BaseModel):
    """ТЗ 6.6.2 п.2: приглашение несёт перечень оборудования по договору; при
    принятии руководитель заказчика сопоставляет каждую позицию со своей карточкой."""

    customer_inn: Annotated[str, Field(min_length=1, max_length=20)]
    contract_number: Annotated[str, Field(min_length=1, max_length=200)]
    basis: str = "service_contract"
    valid_from: date | None = None
    valid_until: date | None = None
    customer_name: Annotated[str | None, Field(default=None, max_length=500)]
    equipment_items: Annotated[list[BindingInvitationItemBody], Field(max_length=50)] = Field(
        default_factory=list
    )
    equipment_descriptions: list[str] = Field(
        default_factory=list,
        description="Прежний формат: позиции только с описанием",
    )
    guarantor_kind: Literal["manufacturer", "seller", "service_org"] | None = None
    guarantor_name: Annotated[str | None, Field(default=None, max_length=200)]


class BindingItemMatchBody(BaseModel):
    item_index: Annotated[int, Field(ge=0)]
    equipment_id: str


class BindingInvitationAcceptBody(BaseModel):
    token: Annotated[str, Field(min_length=8, max_length=512)]
    matches: list[BindingItemMatchBody] = Field(
        default_factory=list,
        description="Позиция приглашения ↔ карточка оборудования; нужна каждая позиция",
    )
    equipment_ids: list[str] = Field(
        default_factory=list,
        description="Если matches не передан: i-я карточка сопоставляется i-й позиции",
    )


class VerificationInformationBody(BaseModel):
    note: Annotated[str, Field(min_length=1, max_length=4000)]
    attachment_refs: list[str] = Field(default_factory=list)


class RequestDraftCreateBody(BaseModel):
    equipment_id: str
    route: Annotated[
        RequestRoute, Field(description="own_service — свой сервис, marketplace — биржа")
    ] = RequestRoute.OWN_SERVICE
    urgency: Annotated[Urgency, Field(description="Срочность заявки")] = Urgency.NORMAL
    symptom_description: str | None = None
    error_code: str | None = None


class RequestDraftUpdateBody(BaseModel):
    equipment_id: str | None = None
    urgency: Annotated[Urgency, Field(description="Срочность заявки")] | None = None
    symptom_description: str | None = None
    error_code: str | None = None
    photos_incomplete: bool | None = None
    photos_incomplete_reason: str | None = None
    expected_version: int


class VersionOnlyBody(BaseModel):
    expected_version: int


class RequestCancelDraftBody(BaseModel):
    reason: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class RequestApprovalBody(BaseModel):
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class RequestReturnToDraftBody(BaseModel):
    comment: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_version: int


class RequestSubmitToOwnServiceBody(BaseModel):
    photos_incomplete: bool = False
    photos_incomplete_reason: str | None = None
    expected_version: int


class RequestRevokeAssignmentBody(BaseModel):
    assignment_id: str
    reason: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class RequestPublicCardPreviewBody(BaseModel):
    """Экран раскрытия (ТЗ 14, п. 2): предпросмотр и публикация используют один набор полей.

    Предпросмотр заявку не меняет, поэтому версия для него необязательна.
    """

    published_description: Annotated[str, Field(max_length=4000)] | None = None
    district_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    confirm_sensitive: bool = False
    expected_version: int | None = None


class RequestPublicCardBody(RequestPublicCardPreviewBody):
    expected_version: int


class RequestUpdateDetailsBody(BaseModel):
    """T56: уточнение условий заявки в `action_required`; непереданное поле не меняется.

    Снимок оборудования и точки отправленной заявки не переписывается. Район и
    описание карточки меняются, только если заявка уже публиковалась.
    """

    symptom_description: Annotated[str, Field(max_length=4000)] | None = None
    urgency: Annotated[Urgency, Field(description="Срочность заявки")] | None = None
    district_id: str | None = None
    published_description: Annotated[str, Field(max_length=4000)] | None = None
    expected_version: int


class RequestSelectOfferBody(BaseModel):
    """ID и версия предложения, которое видел руководитель (ТЗ 10.1)."""

    offer_id: str
    offer_version: int
    expected_version: int


class RequestVisitDecisionBody(BaseModel):
    """Только id и версия предложения — сумма и время берутся с сервера (ТЗ 10.4)."""

    proposal_id: str
    proposal_version: int
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class RequestQuoteDecisionBody(BaseModel):
    """Только id и версия сметы — сумма берётся с сервера (ТЗ 10.4)."""

    quote_id: str
    quote_version: int
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class RequestCancellationBody(BaseModel):
    target: Annotated[
        CancellationTarget,
        Field(
            description="cancel_request — отменить заявку, change_provider — сменить исполнителя"
        ),
    ]
    reason: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class RequestCancellationIdBody(BaseModel):
    cancellation_id: str
    expected_version: int


class RequestRejectCompletionBody(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_version: int


class RequestFollowupBody(BaseModel):
    urgency: Annotated[Urgency, Field(description="Срочность новой заявки")] | None = None


class RequestMessageBody(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=4000)]
    assignment_id: str | None = None
    thread_provider_id: str | None = None
    expected_version: int | None = None


class DialogMessageBody(BaseModel):
    """Сообщение приватного треда до выбора исполнителя (S3.5)."""

    body: Annotated[str, Field(min_length=1, max_length=4000)]
    expected_version: int | None = None


class AssignmentAcceptBody(BaseModel):
    assignment_id: str
    expected_version: int


class AssignmentDeclineBody(BaseModel):
    assignment_id: str
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_version: int


class AssignmentWithdrawBody(BaseModel):
    assignment_id: str
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    expected_version: int


class AssignmentProposeVisitBody(BaseModel):
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
    expected_version: int


class RepairQuoteItemBody(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    amount_minor: Annotated[int, Field(ge=0)]


class AssignmentRepairQuoteBody(BaseModel):
    assignment_id: str
    description_of_work: Annotated[str, Field(min_length=1, max_length=4000)]
    items: Annotated[list[RepairQuoteItemBody], Field(max_length=50)] | None = None
    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    valid_until: datetime | None = None
    warranty_terms: Annotated[str, Field(max_length=1000)] | None = None
    expected_version: int


class AssignmentStartWorkBody(BaseModel):
    assignment_id: str
    expected_version: int


class AssignmentMarkEnRouteBody(BaseModel):
    assignment_id: str
    expected_version: int


class AssignmentReportCompletionBody(BaseModel):
    assignment_id: str
    outcome: Annotated[
        CompletionOutcome, Field(description="resolved — устранено, not_resolved — не устранено")
    ]
    summary: Annotated[str, Field(min_length=1, max_length=4000)]
    expected_version: int


class AssignmentCancellationResponseBody(BaseModel):
    assignment_id: str
    cancellation_id: str
    decision: Annotated[
        CancellationResponseDecision,
        Field(description="accept — согласиться с отменой, decline — оспорить"),
    ]
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class AssignmentWarrantyDecisionBody(BaseModel):
    assignment_id: str
    decision: Annotated[WarrantyDecision, Field(description="Решение исполнителя о гарантийности")]
    comment: Annotated[str, Field(max_length=2000)] | None = None
    expected_version: int


class AssignmentFieldWorkerBody(BaseModel):
    assignment_id: str
    membership_id: str | None = None
    display_name: Annotated[str, Field(max_length=200)] | None = None
    contact_phone: Annotated[str, Field(max_length=40)] | None = None
    expected_version: int


class MarketplaceOfferSubmitBody(BaseModel):
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


class MarketplaceOfferWithdrawBody(BaseModel):
    expected_version: int | None = None
