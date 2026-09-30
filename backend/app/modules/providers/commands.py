import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select

from app.core import ids
from app.core.actor import Actor
from app.core.errors import NotFound, ValidationFailed
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.core.unset import UNSET, UnsetType
from app.db.enums import ProviderKind, ProviderProfileStatus, VerificationStatus
from app.db.models import (
    City,
    District,
    EquipmentCategory,
    Organization,
    ProviderBrandRestriction,
    ProviderCategory,
    ProviderProfile,
    ProviderServiceArea,
)
from app.modules.identity.api import require_valid_inn
from app.modules.providers import policy, queries
from app.modules.trust.api import CHECK_REPRESENTATIVE, CHECK_REQUISITES, open_verification_cases

LEGAL_FORMS = ("ooo", "ip", "self_employed")


@dataclass(slots=True)
class ServiceAreaInput:
    city_id: str
    district_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BrandRestrictionInput:
    equipment_category_id: str
    brands: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderProfileUpdateData:
    provider_kind: str | UnsetType | None = UNSET
    legal_form: str | UnsetType | None = UNSET
    inn: str | UnsetType | None = UNSET
    contact_name: str | UnsetType | None = UNSET
    representative_position: str | UnsetType | None = UNSET
    contact_phone: str | UnsetType | None = UNSET
    contact_email: str | UnsetType | None = UNSET
    visit_terms: str | UnsetType | None = UNSET
    visit_price_from_minor: int | UnsetType | None = UNSET
    can_provide_documents: bool | UnsetType | None = UNSET
    description: str | UnsetType | None = UNSET
    category_ids: list[str] | None = None
    service_areas: list[ServiceAreaInput] | None = None
    brand_restrictions: list[BrandRestrictionInput] | None = None


def _touches_requisites(data: ProviderProfileUpdateData) -> bool:
    return any(
        not isinstance(value, UnsetType)
        for value in (
            data.provider_kind,
            data.legal_form,
            data.inn,
            data.contact_name,
            data.representative_position,
            data.contact_phone,
            data.contact_email,
        )
    )


async def _load_profile(ctx: CommandContext, organization_id: uuid.UUID) -> ProviderProfile:
    profile = (
        await ctx.session.execute(
            select(ProviderProfile)
            .where(ProviderProfile.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if profile is None:
        raise NotFound()
    return profile


async def update_profile(
    actor: Actor, data: ProviderProfileUpdateData, *, idem: Idempotency | None
) -> CommandResult:
    admin = policy.require_provider_admin(actor)
    if data.provider_kind is None:
        raise ValidationFailed("Тип исполнителя обязателен", field="provider_kind")
    if data.can_provide_documents is None:
        raise ValidationFailed(
            "Укажите готовность предоставлять документы", field="can_provide_documents"
        )
    inn_normalized = require_valid_inn(data.inn) if isinstance(data.inn, str) else None
    if isinstance(data.provider_kind, str) and data.provider_kind not in {
        k.value for k in ProviderKind
    }:
        raise ValidationFailed("Неизвестный тип исполнителя", field="provider_kind")
    if isinstance(data.legal_form, str) and data.legal_form not in LEGAL_FORMS:
        raise ValidationFailed("Неизвестная правовая форма", field="legal_form")
    if isinstance(data.visit_price_from_minor, int) and data.visit_price_from_minor < 0:
        raise ValidationFailed(
            "Стоимость выезда не может быть отрицательной", field="visit_price_from_minor"
        )

    async def handler(ctx: CommandContext) -> CommandResult:
        profile = await _load_profile(ctx, admin.organization_id)
        policy.check_editable(profile.status)
        if _touches_requisites(data):
            policy.check_requisites_editable(profile.status)
        org = await ctx.session.get(Organization, admin.organization_id)
        assert org is not None

        if isinstance(data.provider_kind, str):
            profile.provider_kind = data.provider_kind
        if not isinstance(data.legal_form, UnsetType):
            org.legal_form = data.legal_form
        if not isinstance(data.inn, UnsetType):
            org.inn_raw = data.inn
            org.inn_normalized = inn_normalized
        if not isinstance(data.contact_name, UnsetType):
            org.contact_name = data.contact_name
        if not isinstance(data.representative_position, UnsetType):
            org.representative_position = data.representative_position
        if not isinstance(data.contact_phone, UnsetType):
            org.contact_phone = data.contact_phone
        if not isinstance(data.contact_email, UnsetType):
            org.contact_email = data.contact_email
        if not isinstance(data.visit_terms, UnsetType):
            profile.visit_terms = data.visit_terms
        if not isinstance(data.visit_price_from_minor, UnsetType):
            profile.visit_price_from_minor = data.visit_price_from_minor
        if isinstance(data.can_provide_documents, bool):
            profile.can_provide_documents = data.can_provide_documents
        if not isinstance(data.description, UnsetType):
            profile.description = data.description

        if data.category_ids is not None:
            await _replace_categories(ctx, org.id, data.category_ids)
        if data.service_areas is not None:
            await _replace_service_areas(ctx, org.id, data.service_areas)
        if data.brand_restrictions is not None:
            await _replace_brand_restrictions(ctx, org.id, data.brand_restrictions)

        ctx.audit(
            "provider_profile.update",
            "provider_profile",
            profile.id,
            organization_id=org.id,
            requisites=_touches_requisites(data),
        )
        view = await queries.build_profile_view(ctx.session, profile, org)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def _replace_categories(
    ctx: CommandContext, organization_id: uuid.UUID, category_public_ids: list[str]
) -> None:
    category_ids = [ids.decode("category", pid) for pid in category_public_ids]
    if category_ids:
        found = set(
            (
                await ctx.session.execute(
                    select(EquipmentCategory.id).where(EquipmentCategory.id.in_(category_ids))
                )
            ).scalars()
        )
        if found != set(category_ids):
            raise ValidationFailed("Неизвестная категория оборудования", field="category_ids")
    await ctx.session.execute(
        delete(ProviderCategory).where(ProviderCategory.provider_org_id == organization_id)
    )
    for category_id in dict.fromkeys(category_ids):
        ctx.session.add(
            ProviderCategory(provider_org_id=organization_id, equipment_category_id=category_id)
        )
    await ctx.session.flush()


async def _replace_service_areas(
    ctx: CommandContext, organization_id: uuid.UUID, areas: list[ServiceAreaInput]
) -> None:
    rows: list[tuple[uuid.UUID, uuid.UUID | None]] = []
    for area in areas:
        city_id = ids.decode("city", area.city_id)
        city = await ctx.session.get(City, city_id)
        if city is None:
            raise ValidationFailed("Неизвестный город", field="city_id")
        if not area.district_ids:
            rows.append((city_id, None))
            continue
        for district_public_id in area.district_ids:
            district_id = ids.decode("district", district_public_id)
            district = await ctx.session.get(District, district_id)
            if district is None or district.city_id != city_id:
                raise ValidationFailed("Район не принадлежит городу", field="district_ids")
            rows.append((city_id, district_id))
    await ctx.session.execute(
        delete(ProviderServiceArea).where(ProviderServiceArea.provider_org_id == organization_id)
    )
    for area_city_id, area_district_id in dict.fromkeys(rows):
        ctx.session.add(
            ProviderServiceArea(
                provider_org_id=organization_id,
                city_id=area_city_id,
                district_id=area_district_id,
            )
        )
    await ctx.session.flush()


async def _replace_brand_restrictions(
    ctx: CommandContext, organization_id: uuid.UUID, restrictions: list[BrandRestrictionInput]
) -> None:
    rows: list[tuple[uuid.UUID, str]] = []
    for restriction in restrictions:
        category_id = ids.decode("category", restriction.equipment_category_id)
        if await ctx.session.get(EquipmentCategory, category_id) is None:
            raise ValidationFailed(
                "Неизвестная категория оборудования", field="equipment_category_id"
            )
        for brand in restriction.brands:
            cleaned = brand.strip()
            if cleaned:
                rows.append((category_id, cleaned))
    await ctx.session.execute(
        delete(ProviderBrandRestriction).where(
            ProviderBrandRestriction.provider_org_id == organization_id
        )
    )
    for category_id, brand in dict.fromkeys(rows):
        ctx.session.add(
            ProviderBrandRestriction(
                provider_org_id=organization_id,
                equipment_category_id=category_id,
                brand=brand,
            )
        )
    await ctx.session.flush()


async def submit_for_review(actor: Actor, *, idem: Idempotency | None) -> CommandResult:
    admin = policy.require_provider_admin(actor)

    async def handler(ctx: CommandContext) -> CommandResult:
        profile = await _load_profile(ctx, admin.organization_id)
        policy.check_submittable(profile.status)
        org = await ctx.session.get(Organization, admin.organization_id)
        assert org is not None
        _check_ready(org, profile)
        await _check_completeness(ctx, org.id)

        profile.status = ProviderProfileStatus.PENDING_REVIEW.value
        profile.status_reason = None
        profile.accepting_new_requests = False
        await open_verification_cases(
            ctx,
            org.id,
            admin.membership_id,
            (CHECK_REQUISITES, CHECK_REPRESENTATIVE),
        )
        ctx.audit("provider_profile.submit", "provider_profile", profile.id, organization_id=org.id)
        view = await queries.build_profile_view(ctx.session, profile, org)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


def _check_ready(org: Organization, profile: ProviderProfile) -> None:
    if not org.inn_normalized:
        raise ValidationFailed("Укажите ИНН для проверки реквизитов", field="inn")
    if not (org.contact_phone or "").strip():
        raise ValidationFailed("Укажите контакт для проверки", field="contact_phone")
    if not profile.provider_kind:
        raise ValidationFailed("Выберите тип исполнителя", field="provider_kind")


async def _check_completeness(ctx: CommandContext, organization_id: uuid.UUID) -> None:
    categories = (
        await ctx.session.execute(
            select(ProviderCategory.id).where(ProviderCategory.provider_org_id == organization_id)
        )
    ).first()
    if categories is None:
        raise ValidationFailed("Выберите хотя бы одну категорию", field="category_ids")
    areas = (
        await ctx.session.execute(
            select(ProviderServiceArea.id).where(
                ProviderServiceArea.provider_org_id == organization_id
            )
        )
    ).first()
    if areas is None:
        raise ValidationFailed("Укажите территорию обслуживания", field="service_areas")


async def set_accepting_new_requests(
    actor: Actor, accepting: bool, *, idem: Idempotency | None
) -> CommandResult:
    admin = policy.require_provider_admin(actor)

    async def handler(ctx: CommandContext) -> CommandResult:
        profile = await _load_profile(ctx, admin.organization_id)
        policy.check_accepting_allowed(profile.status)
        profile.accepting_new_requests = accepting
        org = await ctx.session.get(Organization, admin.organization_id)
        assert org is not None
        ctx.audit(
            "provider_profile.accepting",
            "provider_profile",
            profile.id,
            organization_id=org.id,
            accepting=accepting,
        )
        view = await queries.build_profile_view(ctx.session, profile, org)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def apply_verification_result(
    ctx: CommandContext,
    organization_id: uuid.UUID,
    *,
    decision: str,
    reason: str,
    details_verified: bool,
    representative_verified: bool,
) -> None:
    profile = (
        await ctx.session.execute(
            select(ProviderProfile)
            .where(ProviderProfile.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if profile is None:
        return
    if decision == "rejected":
        profile.status = ProviderProfileStatus.REJECTED.value
        profile.status_reason = reason
        profile.accepting_new_requests = False
        return
    if decision == "needs_information":
        profile.status = ProviderProfileStatus.NEEDS_INFORMATION.value
        profile.status_reason = reason
        return
    if (
        details_verified
        and representative_verified
        and profile.status
        in (ProviderProfileStatus.PENDING_REVIEW, ProviderProfileStatus.NEEDS_INFORMATION)
    ):
        profile.status = ProviderProfileStatus.ACTIVE.value
        profile.status_reason = None
        profile.accepting_new_requests = True


async def apply_verification_expiry(
    ctx: CommandContext, organization_id: uuid.UUID, *, reason: str
) -> None:
    profile = (
        await ctx.session.execute(
            select(ProviderProfile)
            .where(ProviderProfile.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if profile is None or profile.status not in (
        ProviderProfileStatus.ACTIVE,
        ProviderProfileStatus.PENDING_REVIEW,
    ):
        return
    profile.status = ProviderProfileStatus.NEEDS_INFORMATION.value
    profile.status_reason = reason


async def set_profile_status(
    ctx: CommandContext, organization_id: uuid.UUID, status: str, reason: str
) -> dict[str, object]:
    profile = (
        await ctx.session.execute(
            select(ProviderProfile)
            .where(ProviderProfile.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if profile is None:
        raise NotFound()
    org = await ctx.session.get(Organization, organization_id)
    assert org is not None
    if status == ProviderProfileStatus.SUSPENDED:
        if profile.status == ProviderProfileStatus.SUSPENDED:
            raise ValidationFailed("Профиль уже заблокирован", field="status")
        profile.status = ProviderProfileStatus.SUSPENDED.value
        profile.accepting_new_requests = False
    elif status == ProviderProfileStatus.ACTIVE:
        if profile.status != ProviderProfileStatus.SUSPENDED:
            raise ValidationFailed("Профиль не заблокирован", field="status")
        verified = (
            org.details_verification_status == VerificationStatus.VERIFIED
            and org.representative_verification_status == VerificationStatus.VERIFIED
        )
        profile.status = (
            ProviderProfileStatus.ACTIVE.value
            if verified
            else ProviderProfileStatus.PENDING_REVIEW.value
        )
    else:
        raise ValidationFailed("Недопустимое состояние профиля", field="status")
    profile.status_reason = reason
    view = await queries.build_profile_view(ctx.session, profile, org)
    return view.model_dump(mode="json")
