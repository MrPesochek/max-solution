import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.core import ids
from app.db.enums import BindingStatus, InvitationState, VerificationDecision
from app.db.models import (
    Equipment,
    Invitation,
    Organization,
    ServiceBinding,
    ServiceContract,
    VerificationCase,
    WarrantyAuthorization,
)

CHECK_REQUISITES = "requisites"
CHECK_REPRESENTATIVE = "representative"
CHECK_CUSTOMER_REPRESENTATIVE = "customer_representative"
CHECK_WARRANTY_AUTHORIZATION = "warranty_authorization"

BADGE_TEXTS: dict[str, tuple[str, str, str]] = {
    CHECK_REQUISITES: (
        "Реквизиты проверены",
        "Организация, ИП или статус НПД найдены в официальном источнике на дату проверки",
        "Не подтверждает владение аккаунтом этой организацией",
    ),
    CHECK_REPRESENTATIVE: (
        "Представитель подтверждён",
        "Установлена связь аккаунта с действительным представителем компании",
        "Не подтверждает право выполнять ремонт любого бренда",
    ),
    CHECK_CUSTOMER_REPRESENTATIVE: (
        "Представитель заказчика подтверждён",
        "Установлена связь аккаунта с действительным представителем организации-заказчика",
        "Не подтверждает договорные отношения с конкретным исполнителем",
    ),
    CHECK_WARRANTY_AUTHORIZATION: (
        "Полномочия на гарантийное обслуживание подтверждены",
        "Есть проверенный источник полномочий, область действия и срок",
        "Не является универсальной авторизацией на все бренды и модели",
    ),
}

BINDING_STATUS_TEXTS: dict[str, str] = {
    BindingStatus.PENDING: "Ожидает подтверждения второй стороной",
    BindingStatus.CONFIRMED: "Обслуживание подтверждено компанией",
    BindingStatus.REJECTED: "Компания не подтвердила связь",
    BindingStatus.REVOKED: "Связь прекращена",
}

CONTACT_ONLY_TEXT = (
    "Личный контакт. Платформа не подтверждала обслуживание и не доставляет обращения этой компании"
)


class VerificationBadgeView(BaseModel):
    kind: str
    confirmed: bool
    title: str
    explanation: str
    limitation: str
    source: str | None
    checked_at: datetime | None
    valid_until: datetime | None
    is_demo: bool


class WarrantyAuthorizationView(BaseModel):
    id: str
    guarantor_kind: str
    guarantor_name: str | None
    provider_organization_id: str
    equipment_category_id: str | None
    brands: list[str]
    city_id: str | None
    valid_from: date | None
    valid_until: date | None
    status: str
    is_demo: bool


class VerificationCaseView(BaseModel):
    id: str
    subject_type: str
    check_kind: str
    decision: str
    decision_reason: str | None
    source: str | None
    evidence_note: str | None
    checked_at: datetime | None
    expires_at: datetime | None
    is_demo: bool
    created_at: datetime


class VerificationInformationSubmittedView(BaseModel):
    items: list[VerificationCaseView]


class VerificationCaseOperatorView(VerificationCaseView):
    organization_id: str
    organization_name: str
    organization_inn: str | None
    membership_id: str | None
    provider_profile_status: str | None


class BindingPartyView(BaseModel):
    organization_id: str | None
    name: str
    is_platform_member: bool


class BindingEquipmentView(BaseModel):
    id: str
    equipment_category_id: str
    brand: str | None
    model: str | None
    serial_number: str | None


class ServiceBindingView(BaseModel):
    id: str
    equipment_id: str
    status: str
    status_explanation: str
    status_reason: str | None
    is_contact_only: bool
    basis: str
    contract_number: str | None
    invitation_item_index: int | None
    provider: BindingPartyView
    guarantor_kind: str | None
    guarantor_name: str | None
    warranty_authorization: WarrantyAuthorizationView | None
    valid_from: date | None
    valid_until: date | None
    customer_confirmed_at: datetime | None
    provider_confirmed_at: datetime | None
    created_at: datetime
    contact_name: str | None = None
    contact_phone: str | None = None
    invitation_item_description: str | None = None
    guarantor_stated_by_provider: bool = False


class ProviderBindingView(BaseModel):
    id: str
    status: str
    status_explanation: str
    status_reason: str | None
    basis: str
    contract_number: str | None
    customer: BindingPartyView
    equipment: BindingEquipmentView | None
    valid_from: date | None
    valid_until: date | None
    created_at: datetime


class BindingInvitationItemView(BaseModel):
    index: int
    description: str | None
    serial_number: str | None
    model: str | None


class BindingInvitationView(BaseModel):
    id: str
    state: str
    customer_organization_id: str | None
    contract_number: str | None
    basis: str | None
    equipment_ids: list[str]
    equipment_descriptions: list[str]
    equipment_items: list[BindingInvitationItemView]
    expires_at: datetime
    token_prefix: str
    created_at: datetime
    customer_name: str | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    guarantor_kind: str | None = None
    guarantor_name: str | None = None


class BindingInvitationIssuedView(BindingInvitationView):
    token: str
    webapp_link: str | None
    bot_link: str | None


class BindingInvitationPreviewView(BaseModel):
    provider_name: str
    contract_number: str | None
    basis: str | None
    equipment_descriptions: list[str]
    equipment_items: list[BindingInvitationItemView]
    equipment_ids: list[str]
    valid_from: date | None
    valid_until: date | None
    expires_at: datetime | None
    state: str
    requisites_verified: bool = False
    representative_verified: bool = False
    details_disclosed: bool = False
    guarantor_kind: str | None = None
    guarantor_name: str | None = None


class BindingInvitationAcceptedView(BaseModel):
    items: list[ServiceBindingView]


class BindingRequestAcceptedView(BaseModel):
    status: str = "submitted"
    message: str = "Запрос отправлен на проверку"
    remaining_attempts: int | None = None


def badge(
    kind: str,
    *,
    confirmed: bool,
    source: str | None = None,
    is_demo: bool = False,
    checked_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> VerificationBadgeView:
    title, explanation, limitation = BADGE_TEXTS[kind]
    return VerificationBadgeView(
        kind=kind,
        confirmed=confirmed,
        title=title,
        explanation=explanation,
        limitation=limitation,
        source=source if confirmed else None,
        checked_at=checked_at if confirmed else None,
        valid_until=valid_until if confirmed else None,
        is_demo=is_demo and confirmed,
    )


def to_verification_case_view(case: VerificationCase) -> VerificationCaseView:
    return VerificationCaseView(
        id=ids.encode("verification_case", case.id),
        subject_type=case.subject_type,
        check_kind=case.check_kind,
        decision=case.decision,
        decision_reason=case.decision_reason,
        source=case.source,
        evidence_note=case.evidence_note,
        checked_at=case.checked_at,
        expires_at=case.expires_at,
        is_demo=case.is_demo and case.decision == VerificationDecision.APPROVED,
        created_at=case.created_at,
    )


def to_verification_case_operator_view(
    case: VerificationCase, org: Organization, profile_status: str | None
) -> VerificationCaseOperatorView:
    base = to_verification_case_view(case)
    return VerificationCaseOperatorView(
        **base.model_dump(),
        organization_id=ids.encode("organization", case.organization_id),
        organization_name=org.display_name,
        organization_inn=org.inn_normalized,
        membership_id=ids.encode_opt("membership", case.membership_id),
        provider_profile_status=profile_status,
    )


def to_warranty_view(
    row: WarrantyAuthorization, *, source: str | None = None, is_demo: bool = False
) -> WarrantyAuthorizationView:
    return WarrantyAuthorizationView(
        id=ids.encode("warranty_authorization", row.id),
        guarantor_kind=row.guarantor_kind,
        guarantor_name=row.guarantor_name,
        provider_organization_id=ids.encode("organization", row.authorized_provider_org_id),
        equipment_category_id=ids.encode_opt("category", row.equipment_category_id),
        brands=list(row.brand_scope),
        city_id=ids.encode_opt("city", row.territory_city_id),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        status=row.status,
        is_demo=is_demo,
    )


def _party(org: Organization | None, fallback_name: str | None) -> BindingPartyView:
    if org is not None:
        return BindingPartyView(
            organization_id=ids.encode("organization", org.id),
            name=org.display_name,
            is_platform_member=True,
        )
    return BindingPartyView(
        organization_id=None, name=fallback_name or "Контакт", is_platform_member=False
    )


def binding_status_explanation(binding: ServiceBinding) -> str:
    if binding.provider_org_id is None:
        return CONTACT_ONLY_TEXT
    return BINDING_STATUS_TEXTS.get(binding.status, binding.status)


def to_binding_view(
    binding: ServiceBinding,
    *,
    provider: Organization | None,
    contract: ServiceContract | None,
    warranty: WarrantyAuthorization | None,
    guarantor: Organization | None = None,
    invitation: Invitation | None = None,
) -> ServiceBindingView:
    contact_only = binding.provider_org_id is None
    return ServiceBindingView(
        id=ids.encode("service_binding", binding.id),
        equipment_id=ids.encode("equipment", binding.equipment_id),
        status=binding.status,
        status_explanation=binding_status_explanation(binding),
        status_reason=binding.status_reason,
        is_contact_only=binding.provider_org_id is None,
        basis=binding.basis,
        contract_number=contract.contract_number if contract else binding.claimed_contract_number,
        invitation_item_index=binding.invitation_item_index,
        provider=_party(provider, binding.personal_contact_name),
        guarantor_kind=binding.guarantor_kind,
        guarantor_name=(
            guarantor.display_name if guarantor is not None else binding.stated_guarantor_name
        ),
        warranty_authorization=to_warranty_view(warranty) if warranty else None,
        valid_from=binding.valid_from,
        valid_until=binding.valid_until,
        customer_confirmed_at=binding.customer_confirmed_at,
        provider_confirmed_at=binding.provider_confirmed_at,
        created_at=binding.created_at,
        contact_name=binding.personal_contact_name if contact_only else None,
        contact_phone=binding.personal_contact_phone if contact_only else None,
        invitation_item_description=invitation_item_description(
            invitation, binding.invitation_item_index
        ),
        guarantor_stated_by_provider=(
            binding.guarantor_kind is not None and binding.warranty_authorization_id is None
        ),
    )


def invitation_item_description(invitation: Invitation | None, index: int | None) -> str | None:
    if invitation is None or index is None:
        return None
    items = invitation_item_views(invitation)
    return items[index].description if 0 <= index < len(items) else None


_CLOSED_BINDING_STATUSES = frozenset({BindingStatus.REJECTED.value, BindingStatus.REVOKED.value})


def to_provider_binding_view(
    binding: ServiceBinding,
    *,
    customer: Organization,
    equipment: Equipment | None,
    contract: ServiceContract | None,
) -> ProviderBindingView:
    closed = binding.status in _CLOSED_BINDING_STATUSES
    return ProviderBindingView(
        id=ids.encode("service_binding", binding.id),
        status=binding.status,
        status_explanation=binding_status_explanation(binding),
        status_reason=binding.status_reason,
        basis=binding.basis,
        contract_number=contract.contract_number if contract else binding.claimed_contract_number,
        customer=_party(customer, None),
        equipment=(
            BindingEquipmentView(
                id=ids.encode("equipment", equipment.id),
                equipment_category_id=ids.encode("category", equipment.equipment_category_id),
                brand=equipment.brand,
                model=equipment.model,
                serial_number=None if closed else equipment.serial_number,
            )
            if equipment is not None
            else None
        ),
        valid_from=binding.valid_from,
        valid_until=binding.valid_until,
        created_at=binding.created_at,
    )


def invitation_state(invitation: Invitation, now: datetime) -> str:
    if invitation.status == InvitationState.ACCEPTED:
        return "used"
    if invitation.status == InvitationState.REVOKED:
        return "revoked"
    if invitation.status == InvitationState.DECLINED:
        return "declined"
    if invitation.status == InvitationState.EXPIRED or invitation.expires_at <= now:
        return "expired"
    return "active"


def _details_date(details: dict[str, Any], key: str) -> date | None:
    value = details.get(key)
    return date.fromisoformat(value) if isinstance(value, str) else None


def invitation_item_views(invitation: Invitation) -> list[BindingInvitationItemView]:
    details = invitation.binding_details or {}
    items = details.get("equipment_items")
    if not isinstance(items, list):
        items = [{"description": d} for d in details.get("equipment_descriptions") or []]
    return [
        BindingInvitationItemView(
            index=index,
            description=item.get("description"),
            serial_number=item.get("serial_number"),
            model=item.get("model"),
        )
        for index, item in enumerate(items)
        if isinstance(item, dict)
    ]


def to_binding_invitation_view(invitation: Invitation, now: datetime) -> BindingInvitationView:
    details = invitation.binding_details or {}
    state = invitation_state(invitation, now)
    return BindingInvitationView(
        id=ids.encode("invitation", invitation.id),
        state=state,
        customer_organization_id=(
            ids.encode_opt("organization", invitation.target_organization_id)
            if state == "used"
            else None
        ),
        contract_number=details.get("contract_number"),
        basis=details.get("basis"),
        equipment_ids=[ids.encode("equipment", eid) for eid in invitation.equipment_ids],
        equipment_descriptions=list(details.get("equipment_descriptions") or []),
        equipment_items=invitation_item_views(invitation),
        expires_at=invitation.expires_at,
        token_prefix=invitation.token_prefix,
        created_at=invitation.created_at,
        customer_name=details.get("customer_name"),
        declined_at=invitation.declined_at,
        decline_reason=invitation.decline_reason,
        guarantor_kind=details.get("guarantor_kind"),
        guarantor_name=details.get("guarantor_name"),
    )


def to_binding_invitation_issued_view(
    base: BindingInvitationView, *, token: str, webapp_link: str | None, bot_link: str | None
) -> BindingInvitationIssuedView:
    return BindingInvitationIssuedView(
        **base.model_dump(), token=token, webapp_link=webapp_link, bot_link=bot_link
    )


def to_binding_invitation_preview(
    invitation: Invitation,
    provider: Organization,
    now: datetime,
    *,
    provider_checks: set[str] | frozenset[str] = frozenset(),
    disclose: bool = False,
) -> BindingInvitationPreviewView:
    state = invitation_state(invitation, now)
    requisites_verified = CHECK_REQUISITES in provider_checks
    representative_verified = CHECK_REPRESENTATIVE in provider_checks
    if not disclose:
        return BindingInvitationPreviewView(
            provider_name=provider.display_name,
            contract_number=None,
            basis=None,
            equipment_descriptions=[],
            equipment_items=[],
            equipment_ids=[],
            valid_from=None,
            valid_until=None,
            expires_at=None,
            state=state,
            requisites_verified=requisites_verified,
            representative_verified=representative_verified,
        )
    details = invitation.binding_details or {}
    return BindingInvitationPreviewView(
        provider_name=provider.display_name,
        contract_number=details.get("contract_number"),
        basis=details.get("basis"),
        equipment_descriptions=list(details.get("equipment_descriptions") or []),
        equipment_items=invitation_item_views(invitation),
        equipment_ids=[ids.encode("equipment", eid) for eid in invitation.equipment_ids],
        valid_from=_details_date(details, "valid_from"),
        valid_until=_details_date(details, "valid_until"),
        expires_at=invitation.expires_at,
        state=state,
        requisites_verified=requisites_verified,
        representative_verified=representative_verified,
        details_disclosed=True,
        guarantor_kind=details.get("guarantor_kind"),
        guarantor_name=details.get("guarantor_name"),
    )


def binding_event_payload(
    binding: ServiceBinding, contract_number: str | None
) -> dict[str, str | None]:
    return {
        "service_binding_id": ids.encode("service_binding", binding.id),
        "equipment_id": ids.encode("equipment", binding.equipment_id),
        "customer_organization_id": ids.encode("organization", binding.customer_org_id),
        "status": binding.status,
        "basis": binding.basis,
        "contract_number": contract_number,
    }


def uuid_or_none(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None
