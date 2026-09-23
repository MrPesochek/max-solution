import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select

from app.core import ids
from app.core.actor import Actor
from app.core.errors import InvalidTransition, NotFound, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db.enums import (
    GuarantorKind,
    VerificationDecision,
    WarrantyAuthorizationStatus,
)
from app.db.models import (
    City,
    EquipmentCategory,
    Organization,
    ProviderProfile,
    VerificationCase,
    WarrantyAuthorization,
)
from app.modules.trust import policy
from app.modules.trust.verification import SUBJECT_REPRESENTATIVE, resolve_is_demo
from app.modules.trust.views import CHECK_WARRANTY_AUTHORIZATION, to_warranty_view


@dataclass(slots=True)
class WarrantyAuthorizationData:
    provider_organization_id: str
    guarantor_kind: str
    source: str
    reason: str
    guarantor_name: str | None = None
    guarantor_organization_id: str | None = None
    equipment_category_id: str | None = None
    brands: list[str] = field(default_factory=list)
    city_id: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    is_demo: bool = False


async def create_warranty_authorization(
    actor: Actor, data: WarrantyAuthorizationData, *, idem: Idempotency | None
) -> CommandResult:
    operator = policy.require_operator(actor)
    provider_org_id = ids.decode("organization", data.provider_organization_id)
    guarantor_org_id = (
        ids.decode("organization", data.guarantor_organization_id)
        if data.guarantor_organization_id
        else None
    )
    category_id = (
        ids.decode("category", data.equipment_category_id) if data.equipment_category_id else None
    )
    city_id = ids.decode("city", data.city_id) if data.city_id else None
    reason = policy.require_reason(data.reason)
    source = policy.require_text(data.source, "source", "Укажите источник полномочий")
    if data.guarantor_kind not in {k.value for k in GuarantorKind}:
        raise ValidationFailed("Неизвестная гарантирующая сторона", field="guarantor_kind")
    if not data.guarantor_name and guarantor_org_id is None:
        raise ValidationFailed("Укажите гарантирующую сторону", field="guarantor_name")
    brands = [b.strip() for b in data.brands if b.strip()]
    if data.valid_from and data.valid_until and data.valid_until < data.valid_from:
        raise ValidationFailed("Срок полномочий задан неверно", field="valid_until")

    async def handler(ctx: CommandContext) -> CommandResult:
        provider = await ctx.session.get(Organization, provider_org_id)
        if provider is None or not provider.is_provider:
            raise NotFound()
        profile = (
            await ctx.session.execute(
                select(ProviderProfile).where(ProviderProfile.organization_id == provider_org_id)
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound()
        if (
            category_id is not None
            and await ctx.session.get(EquipmentCategory, category_id) is None
        ):
            raise ValidationFailed("Неизвестная категория", field="equipment_category_id")
        if city_id is not None and await ctx.session.get(City, city_id) is None:
            raise ValidationFailed("Неизвестный город", field="city_id")
        if (
            guarantor_org_id is not None
            and await ctx.session.get(Organization, guarantor_org_id) is None
        ):
            raise NotFound()

        case = VerificationCase(
            organization_id=provider_org_id,
            subject_type=SUBJECT_REPRESENTATIVE,
            check_kind=CHECK_WARRANTY_AUTHORIZATION,
            source=source,
            is_demo=resolve_is_demo(data.is_demo),
            evidence_note=reason,
            operator_user_id=operator.user_id,
            decision=VerificationDecision.APPROVED.value,
            decision_reason=reason,
            checked_at=ctx.now,
        )
        ctx.session.add(case)
        await ctx.session.flush()

        row = WarrantyAuthorization(
            guarantor_kind=data.guarantor_kind,
            guarantor_org_id=guarantor_org_id,
            guarantor_name=data.guarantor_name,
            authorized_provider_org_id=provider_org_id,
            equipment_category_id=category_id,
            brand_scope=brands,
            territory_city_id=city_id,
            source_verification_case_id=case.id,
            valid_from=data.valid_from,
            valid_until=data.valid_until,
            status=WarrantyAuthorizationStatus.ACTIVE.value,
        )
        ctx.session.add(row)
        await ctx.session.flush()
        ctx.audit(
            "warranty_authorization.create",
            "warranty_authorization",
            row.id,
            organization_id=provider_org_id,
            reason=reason,
            brands=brands,
        )
        return CommandResult(
            to_warranty_view(row, source=case.source, is_demo=case.is_demo).model_dump(mode="json"),
            status=201,
        )

    return await run_command(actor, handler, idempotency=idem)


async def revoke_warranty_authorization(
    actor: Actor, authorization_public_id: str, reason: str, *, idem: Idempotency | None
) -> CommandResult:
    policy.require_operator(actor)
    authorization_id = ids.decode("warranty_authorization", authorization_public_id)
    checked_reason = policy.require_reason(reason)

    async def handler(ctx: CommandContext) -> CommandResult:
        row = await lock_by_id(ctx.session, WarrantyAuthorization, authorization_id)
        if row.status == WarrantyAuthorizationStatus.REVOKED:
            raise InvalidTransition("Полномочия уже отозваны")
        row.status = WarrantyAuthorizationStatus.REVOKED.value
        ctx.audit(
            "warranty_authorization.revoke",
            "warranty_authorization",
            row.id,
            organization_id=row.authorized_provider_org_id,
            reason=checked_reason,
        )
        return CommandResult(to_warranty_view(row).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def match_warranty_authorization(
    ctx: CommandContext,
    provider_org_id: uuid.UUID,
    equipment_category_id: uuid.UUID,
    brand: str | None,
) -> WarrantyAuthorization | None:
    """Источник полномочий для привязки по гарантии; при отсутствии метки нет."""
    rows = list(
        (
            await ctx.session.execute(
                select(WarrantyAuthorization)
                .where(
                    WarrantyAuthorization.authorized_provider_org_id == provider_org_id,
                    WarrantyAuthorization.status == WarrantyAuthorizationStatus.ACTIVE,
                )
                .order_by(WarrantyAuthorization.id)
            )
        ).scalars()
    )
    normalized = (brand or "").strip().casefold()
    for row in rows:
        if row.equipment_category_id not in (None, equipment_category_id):
            continue
        if row.brand_scope and normalized not in {b.strip().casefold() for b in row.brand_scope}:
            continue
        if row.valid_until is not None and row.valid_until < ctx.now.date():
            continue
        return row
    return None
