import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, literal_column, select, update
from sqlalchemy.exc import IntegrityError

from app.core import ids
from app.core.actor import Actor, IntegrationActor, OperatorActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Conflict, NotFound, RateLimited, ValidationFailed
from app.core.invitations import explain_failed_claim, invitation_invalid
from app.core.locking import advisory_xact_lock, lock_by_id
from app.core.pipeline import (
    INVITATION_SECRET_FIELDS,
    CommandContext,
    CommandResult,
    Idempotency,
    run_command,
)
from app.db import session as db_session
from app.db.enums import (
    BindingBasis,
    BindingStatus,
    GuarantorKind,
    IntegrationEventType,
    InvitationKind,
    InvitationState,
    ProviderProfileStatus,
    VerificationStatus,
)
from app.db.models import (
    AuditEntry,
    Equipment,
    Invitation,
    Organization,
    ProviderProfile,
    ServiceBinding,
    ServiceContract,
    WarrantyAuthorization,
)
from app.infra.config import get_settings
from app.infra.crypto import generate_token, hash_token, token_prefix
from app.infra.max.deeplinks import bot_start_link, build_start_param, webapp_start_link
from app.modules.identity.api import require_valid_inn
from app.modules.trust import notify, policy
from app.modules.trust.queries import active_checks, intended_recipient, verified_customer_by_inn
from app.modules.trust.views import (
    BindingRequestAcceptedView,
    binding_event_payload,
    invitation_item_views,
    to_binding_invitation_issued_view,
    to_binding_invitation_preview,
    to_binding_invitation_view,
    to_binding_view,
    to_provider_binding_view,
)
from app.modules.trust.warranty import match_warranty_authorization

BINDING_START_KIND = "sb"

REQUEST_AUDIT_ACTION = "service_binding.request"
REQUEST_REJECTED_ACTION = "service_binding.request_rejected"


MAX_INVITATION_ITEMS = 50
MAX_ITEM_FIELD_LENGTH = 500


@dataclass(slots=True)
class BindingInvitationItem:
    """Позиция оборудования по договору так, как её знает сервис.

    Идентификатора оборудования заказчика у сервиса нет — только описание,
    модель и серийный номер из договора; сопоставляет позицию руководитель
    заказчика при принятии."""

    description: str
    serial_number: str | None = None
    model: str | None = None


@dataclass(slots=True)
class BindingInvitationData:
    customer_inn: str
    contract_number: str
    basis: str = BindingBasis.SERVICE_CONTRACT.value
    valid_from: date | None = None
    valid_until: date | None = None
    customer_name: str | None = None
    equipment_items: list[BindingInvitationItem] = field(default_factory=list)
    equipment_descriptions: list[str] = field(default_factory=list)
    guarantor_kind: str | None = None
    guarantor_name: str | None = None


@dataclass(slots=True)
class BindingItemMatch:
    """Позиция приглашения (по индексу) ↔ карточка оборудования заказчика."""

    item_index: int
    equipment_id: str


@dataclass(slots=True)
class BindingRequestData:
    provider_organization_id: str
    contract_number: str
    equipment_ids: list[str]
    basis: str = BindingBasis.SERVICE_CONTRACT.value


@dataclass(slots=True)
class ContactBindingData:
    equipment_id: str
    contact_name: str
    contact_phone: str | None = None


class _RequestRateExceeded(RateLimited):
    def __init__(self, scope: str, retry_after_seconds: int) -> None:
        super().__init__("Слишком много запросов на привязку, попробуйте позже")
        self.scope = scope
        self.retry_after_seconds = retry_after_seconds


def _optional_text(value: str | None, field_name: str) -> str | None:
    text = (value or "").strip()
    if len(text) > MAX_ITEM_FIELD_LENGTH:
        raise ValidationFailed("Слишком длинное значение", field=field_name)
    return text or None


def _invitation_items(data: BindingInvitationData) -> list[dict[str, str | None]]:
    """ТЗ 6.6.2 п.2: приглашение несёт перечень оборудования по договору."""
    raw = list(data.equipment_items) + [
        BindingInvitationItem(description=d) for d in data.equipment_descriptions
    ]
    items: list[dict[str, str | None]] = []
    for index, item in enumerate(raw):
        field_name = f"equipment_items[{index}]"
        description = _optional_text(item.description, f"{field_name}.description")
        serial_number = _optional_text(item.serial_number, f"{field_name}.serial_number")
        model = _optional_text(item.model, f"{field_name}.model")
        if description is None and serial_number is None and model is None:
            continue
        items.append(
            {
                "description": description or model or serial_number,
                "serial_number": serial_number,
                "model": model,
            }
        )
    if not items:
        raise ValidationFailed(
            "Укажите оборудование, которое обслуживается по договору", field="equipment_items"
        )
    if len(items) > MAX_INVITATION_ITEMS:
        raise ValidationFailed("Слишком много позиций оборудования", field="equipment_items")
    return items


def _invitation_items_of(invitation: Invitation) -> list[dict[str, str | None]]:
    """Позиции приглашения; у выпущенных до перечня позиций — только описания."""
    return [item.model_dump(exclude={"index"}) for item in invitation_item_views(invitation)]


def _normalize_serial(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isalnum()).casefold()


def _check_basis(basis: str) -> str:
    if basis not in {b.value for b in BindingBasis}:
        raise ValidationFailed("Неизвестное основание обслуживания", field="basis")
    return basis


def _binding_links(token: str) -> tuple[str | None, str | None]:
    bot_username = get_settings().max_bot_username
    if not bot_username:
        return None, None
    payload = build_start_param(BINDING_START_KIND, token)
    return webapp_start_link(bot_username, payload), bot_start_link(bot_username, payload)


async def _active_provider_profile(
    ctx: CommandContext, organization_id: uuid.UUID
) -> ProviderProfile:
    profile = (
        await ctx.session.execute(
            select(ProviderProfile).where(ProviderProfile.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise NotFound()
    if profile.status != ProviderProfileStatus.ACTIVE:
        raise Conflict(
            "Приглашение на привязку доступно только допущенному исполнителю",
            code="PROVIDER_NOT_ACTIVE",
        )
    return profile


async def _customer_equipment(
    ctx: CommandContext, customer_org_id: uuid.UUID, equipment_ids: list[uuid.UUID]
) -> list[Equipment]:
    if not equipment_ids:
        return []
    rows = list(
        (
            await ctx.session.execute(
                select(Equipment)
                .where(
                    Equipment.id.in_(equipment_ids),
                    Equipment.customer_org_id == customer_org_id,
                )
                .order_by(Equipment.id)
            )
        ).scalars()
    )
    if len(rows) != len(set(equipment_ids)):
        raise NotFound()
    return rows


async def create_binding_invitation(
    actor: Actor, data: BindingInvitationData, *, idem: Idempotency | None
) -> CommandResult:
    """ТЗ 6.6.2: клиента, которого ещё нет на платформе, тоже можно пригласить —
    договор и привязка материализуются только при принятии приглашения его
    менеджером, а до этого момента реквизиты лежат в `binding_details`."""
    issuer = policy.require_binding_actor(actor)
    basis = _check_basis(data.basis)
    contract_number = policy.require_text(
        data.contract_number, "contract_number", "Укажите номер договора"
    )
    inn = require_valid_inn(
        policy.require_text(data.customer_inn, "customer_inn", "Укажите ИНН заказчика")
    )
    customer_name = (data.customer_name or "").strip() or None
    guarantor_kind, guarantor_name = _stated_guarantor(data)
    items = _invitation_items(data)
    token = generate_token()
    ttl = timedelta(seconds=get_settings().binding_invitation_ttl_seconds)

    async def handler(ctx: CommandContext) -> CommandResult:
        provider_org_id = issuer.organization_id
        await _active_provider_profile(ctx, provider_org_id)
        target = await _verified_customer_by_inn(ctx, inn) if inn else None

        invitation = Invitation(
            kind=InvitationKind.SERVICE_BINDING.value,
            organization_id=provider_org_id,
            created_by_membership_id=(
                issuer.membership_id if isinstance(issuer, UserActor) else None
            ),
            target_organization_id=target.id if target else None,
            location_ids=[],
            equipment_ids=[],
            binding_details={
                "contract_number": contract_number,
                "basis": basis,
                "valid_from": data.valid_from.isoformat() if data.valid_from else None,
                "valid_until": data.valid_until.isoformat() if data.valid_until else None,
                "customer_inn": inn,
                "customer_name": customer_name,
                "equipment_items": items,
                "equipment_descriptions": [item["description"] for item in items],
                "guarantor_kind": guarantor_kind,
                "guarantor_name": guarantor_name,
            },
            token_hash=hash_token(token),
            token_prefix=token_prefix(token),
            status=InvitationState.PENDING.value,
            expires_at=ctx.now + ttl,
            created_at=ctx.now,
        )
        ctx.session.add(invitation)
        await ctx.session.flush()
        ctx.audit(
            "binding_invitation.create",
            "invitation",
            invitation.id,
            organization_id=provider_org_id,
            has_target=target is not None,
            items=len(items),
        )
        base = to_binding_invitation_view(invitation, ctx.now)
        webapp_link, bot_link = _binding_links(token)
        view = to_binding_invitation_issued_view(
            base, token=token, webapp_link=webapp_link, bot_link=bot_link
        )
        return CommandResult(
            view.model_dump(mode="json"), status=201, secret_fields=INVITATION_SECRET_FIELDS
        )

    return await run_command(actor, handler, idempotency=idem)


MAX_GUARANTOR_NAME = 200


def _stated_guarantor(data: BindingInvitationData) -> tuple[str | None, str | None]:
    name = (data.guarantor_name or "").strip() or None
    if data.guarantor_kind is None:
        if name is not None:
            raise ValidationFailed("Укажите, кто даёт гарантию", field="guarantor_kind")
        return None, None
    if data.guarantor_kind not in {str(kind) for kind in GuarantorKind}:
        raise ValidationFailed("Неизвестная гарантирующая сторона", field="guarantor_kind")
    if name is not None and len(name) > MAX_GUARANTOR_NAME:
        raise ValidationFailed(
            f"Название — не длиннее {MAX_GUARANTOR_NAME} символов", field="guarantor_name"
        )
    return data.guarantor_kind, name


async def _verified_customer_by_inn(ctx: CommandContext, inn: str) -> Organization | None:
    return await verified_customer_by_inn(ctx.session, inn)


async def _upsert_contract(
    ctx: CommandContext,
    provider_org_id: uuid.UUID,
    customer_org_id: uuid.UUID,
    contract_number: str,
    basis: str,
    valid_from: date | None,
    valid_until: date | None,
) -> ServiceContract:
    contract = (
        await ctx.session.execute(
            select(ServiceContract)
            .where(
                ServiceContract.provider_org_id == provider_org_id,
                ServiceContract.contract_number == contract_number,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if contract is not None:
        if contract.customer_org_id != customer_org_id:
            raise Conflict(
                "Договор с этим номером уже заведён на другого заказчика",
                code="CONTRACT_NUMBER_TAKEN",
            )
        contract.basis = basis
        contract.valid_from = valid_from
        contract.valid_until = valid_until
        return contract
    contract = ServiceContract(
        provider_org_id=provider_org_id,
        customer_org_id=customer_org_id,
        contract_number=contract_number,
        basis=basis,
        valid_from=valid_from,
        valid_until=valid_until,
        created_by_membership_id=None,
    )
    ctx.session.add(contract)
    await ctx.session.flush()
    return contract


async def revoke_binding_invitation(
    actor: Actor, invitation_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    issuer = policy.require_binding_actor(actor)
    invitation_id = ids.decode("invitation", invitation_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        invitation = await lock_by_id(ctx.session, Invitation, invitation_id)
        if (
            invitation.organization_id != issuer.organization_id
            or invitation.kind != InvitationKind.SERVICE_BINDING
        ):
            raise NotFound()
        if invitation.status != InvitationState.PENDING:
            raise invitation_invalid()
        invitation.status = InvitationState.REVOKED.value
        invitation.revoked_at = ctx.now
        invitation.revoked_by_membership_id = (
            issuer.membership_id if isinstance(issuer, UserActor) else None
        )
        ctx.audit(
            "binding_invitation.revoke",
            "invitation",
            invitation.id,
            organization_id=issuer.organization_id,
        )
        view = to_binding_invitation_view(invitation, ctx.now)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def decline_binding_invitation(
    actor: Actor, token: str, reason: str | None, *, idem: Idempotency | None
) -> CommandResult:
    """Отказ руководителя заказчика от приглашения: сервис видит состояние `declined`.

    Отказывается только адресат (та же сверка, что при принятии, A32); повторный
    отказ той же организации ничего не меняет и отвечает текущим состоянием."""
    manager = policy.require_customer_manager(actor)
    token_hash = hash_token(token)
    checked_reason = _optional_text(reason, "reason")

    async def handler(ctx: CommandContext) -> CommandResult:
        invitation = (
            await ctx.session.execute(
                select(Invitation)
                .where(
                    Invitation.token_hash == token_hash,
                    Invitation.kind == InvitationKind.SERVICE_BINDING,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise invitation_invalid()
        customer = await ctx.session.get(Organization, manager.organization_id)
        assert customer is not None
        if invitation.status == InvitationState.DECLINED:
            if invitation.target_organization_id != customer.id:
                raise invitation_invalid()
        else:
            if invitation.status != InvitationState.PENDING or invitation.expires_at <= ctx.now:
                raise await explain_failed_claim(
                    ctx.session,
                    Invitation.id == invitation.id,
                    InvitationKind.SERVICE_BINDING,
                    ctx.now,
                )
            await _ensure_intended_recipient(ctx, invitation, customer)
            invitation.status = InvitationState.DECLINED.value
            invitation.declined_at = ctx.now
            invitation.declined_by_user_id = manager.user_id
            invitation.decline_reason = checked_reason
            invitation.target_organization_id = customer.id
            ctx.audit(
                "binding_invitation.decline",
                "invitation",
                invitation.id,
                organization_id=manager.organization_id,
                provider_org_id=str(invitation.organization_id),
            )
        provider = await ctx.session.get(Organization, invitation.organization_id)
        assert provider is not None
        checks = await active_checks(ctx.session, [provider.id])
        view = to_binding_invitation_preview(
            invitation, provider, ctx.now, provider_checks=checks.get(provider.id, set())
        )
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


def _parse_date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else None


async def accept_binding_invitation(
    actor: Actor, token: str, matches: list[BindingItemMatch], *, idem: Idempotency | None
) -> CommandResult:
    """ТЗ 6.6.2 п.4–5: руководитель сопоставляет каждую позицию приглашения со своим
    оборудованием; подтверждается ровно этот перечень и ничего сверх него."""
    manager = policy.require_customer_manager(actor)
    token_hash = hash_token(token)
    chosen = _decode_matches(matches)

    async def handler(ctx: CommandContext) -> CommandResult:
        claimed_id = (
            await ctx.session.execute(
                update(Invitation)
                .where(
                    Invitation.token_hash == token_hash,
                    Invitation.kind == InvitationKind.SERVICE_BINDING,
                    Invitation.status == InvitationState.PENDING,
                    Invitation.expires_at > ctx.now,
                )
                .values(
                    status=InvitationState.ACCEPTED.value,
                    accepted_at=ctx.now,
                    accepted_by_user_id=manager.user_id,
                )
                .returning(Invitation.id)
            )
        ).scalar_one_or_none()
        if claimed_id is None:
            raise await explain_failed_claim(
                ctx.session,
                Invitation.token_hash == token_hash,
                InvitationKind.SERVICE_BINDING,
                ctx.now,
            )
        invitation = (
            await ctx.session.execute(
                select(Invitation)
                .where(Invitation.id == claimed_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        customer = await ctx.session.get(Organization, manager.organization_id)
        assert customer is not None
        await _ensure_intended_recipient(ctx, invitation, customer)
        invitation.target_organization_id = manager.organization_id

        details = invitation.binding_details or {}
        contract_number = str(details.get("contract_number") or "") or None
        basis = str(details.get("basis") or BindingBasis.SERVICE_CONTRACT.value)
        valid_from = _parse_date(details.get("valid_from"))
        valid_until = _parse_date(details.get("valid_until"))

        items = _invitation_items_of(invitation)
        if not items:
            raise invitation_invalid()
        if sorted(index for index, _ in chosen) != list(range(len(items))):
            raise ValidationFailed(
                "Сопоставьте каждую позицию приглашения со своим оборудованием",
                field="matches",
                items=len(items),
            )
        equipment = {
            row.id: row
            for row in await _customer_equipment(
                ctx, manager.organization_id, [equipment_id for _, equipment_id in chosen]
            )
        }
        paired = sorted(
            ((index, equipment[equipment_id]) for index, equipment_id in chosen),
            key=lambda pair: pair[0],
        )
        for index, item in paired:
            expected = _normalize_serial(items[index].get("serial_number"))
            actual = _normalize_serial(item.serial_number)
            if expected and actual and expected != actual:
                raise ValidationFailed(
                    "Серийный номер оборудования не совпадает с позицией приглашения",
                    code="SERIAL_NUMBER_MISMATCH",
                    field="matches",
                    item_index=index,
                )

        contract = None
        if contract_number:
            contract = await _upsert_contract(
                ctx,
                invitation.organization_id,
                manager.organization_id,
                contract_number,
                basis,
                valid_from,
                valid_until,
            )

        status = (
            BindingStatus.CONFIRMED
            if customer.representative_verification_status == VerificationStatus.VERIFIED
            else BindingStatus.PENDING
        )
        created = []
        for index, item in paired:
            binding = await _create_binding(
                ctx,
                equipment=item,
                customer_org_id=manager.organization_id,
                provider_org_id=invitation.organization_id,
                basis=basis,
                contract=contract,
                created_by_membership_id=manager.membership_id,
                status=status,
                customer_confirmed_at=ctx.now,
                provider_confirmed_at=invitation.created_at,
                source_invitation_id=invitation.id,
                claimed_contract_number=None if contract else contract_number,
                invitation_item_index=index,
                stated_guarantor_kind=details.get("guarantor_kind"),
                stated_guarantor_name=details.get("guarantor_name"),
            )
            if binding is not None:
                created.append(binding)

        ctx.audit(
            "binding_invitation.accept",
            "invitation",
            invitation.id,
            organization_id=manager.organization_id,
            bindings=len(created),
        )
        await _announce(ctx, created, contract.contract_number if contract else contract_number)
        provider = await ctx.session.get(Organization, invitation.organization_id)
        views = []
        for binding in created:
            warranty = (
                await ctx.session.get(WarrantyAuthorization, binding.warranty_authorization_id)
                if binding.warranty_authorization_id
                else None
            )
            views.append(
                to_binding_view(
                    binding,
                    provider=provider,
                    contract=contract,
                    warranty=warranty,
                    invitation=invitation,
                ).model_dump(mode="json")
            )
        return CommandResult({"items": views}, status=201)

    return await run_command(actor, handler, idempotency=idem)


def _decode_matches(matches: list[BindingItemMatch]) -> list[tuple[int, uuid.UUID]]:
    chosen = [(m.item_index, ids.decode("equipment", m.equipment_id)) for m in matches]
    indexes = [index for index, _ in chosen]
    equipment_ids = [equipment_id for _, equipment_id in chosen]
    if len(set(indexes)) != len(indexes) or len(set(equipment_ids)) != len(equipment_ids):
        raise ValidationFailed(
            "Каждая позиция сопоставляется с одной карточкой оборудования", field="matches"
        )
    return chosen


async def _ensure_intended_recipient(
    ctx: CommandContext, invitation: Invitation, customer: Organization
) -> None:
    """ТЗ 6.6.2 п.4: сервер сверяет приглашение с организацией заказчика.

    Все отказы одинаковы и ничего не говорят о настоящем адресате (A32)."""
    if not await intended_recipient(ctx.session, invitation, customer):
        raise invitation_invalid()


async def _create_binding(
    ctx: CommandContext,
    *,
    equipment: Equipment,
    customer_org_id: uuid.UUID,
    provider_org_id: uuid.UUID,
    basis: str,
    contract: ServiceContract | None,
    created_by_membership_id: uuid.UUID,
    status: BindingStatus,
    customer_confirmed_at: object,
    provider_confirmed_at: object,
    source_invitation_id: uuid.UUID | None,
    claimed_contract_number: str | None = None,
    invitation_item_index: int | None = None,
    stated_guarantor_kind: str | None = None,
    stated_guarantor_name: str | None = None,
) -> ServiceBinding | None:
    if provider_org_id == customer_org_id:
        raise Conflict(
            "Организация не может быть собственным сервисом", code="SELF_BINDING_FORBIDDEN"
        )
    await advisory_xact_lock(ctx.session, f"service_binding.request:{provider_org_id}")
    existing = (
        await ctx.session.execute(
            select(ServiceBinding)
            .where(
                ServiceBinding.equipment_id == equipment.id,
                ServiceBinding.provider_org_id == provider_org_id,
                ServiceBinding.status.in_(
                    [BindingStatus.PENDING.value, BindingStatus.CONFIRMED.value]
                ),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    warranty = None
    guarantor_kind = None
    if basis == BindingBasis.WARRANTY:
        warranty = await match_warranty_authorization(
            ctx, provider_org_id, equipment.equipment_category_id, equipment.brand
        )
        guarantor_kind = warranty.guarantor_kind if warranty else GuarantorKind.SERVICE_ORG.value
    stated_name = None
    if warranty is None and stated_guarantor_kind is not None:
        guarantor_kind = stated_guarantor_kind
        stated_name = stated_guarantor_name
    binding = ServiceBinding(
        equipment_id=equipment.id,
        customer_org_id=customer_org_id,
        provider_org_id=provider_org_id,
        contract_id=contract.id if contract else None,
        claimed_contract_number=claimed_contract_number,
        basis=basis,
        guarantor_kind=guarantor_kind,
        guarantor_org_id=warranty.guarantor_org_id if warranty else None,
        warranty_authorization_id=warranty.id if warranty else None,
        stated_guarantor_name=stated_name,
        valid_from=contract.valid_from if contract else None,
        valid_until=contract.valid_until if contract else None,
        status=status.value,
        customer_confirmed_at=customer_confirmed_at,
        provider_confirmed_at=provider_confirmed_at,
        source_invitation_id=source_invitation_id,
        invitation_item_index=invitation_item_index,
        created_by_membership_id=created_by_membership_id,
    )
    try:
        async with ctx.session.begin_nested():
            ctx.session.add(binding)
            await ctx.session.flush()
    except IntegrityError as exc:
        if _LIVE_BINDING_INDEX not in str(exc.orig):
            raise
        return None
    return binding


_LIVE_BINDING_INDEX = "ux_service_bindings_live_equipment_provider"


async def _announce(
    ctx: CommandContext, bindings: list[ServiceBinding], contract_number: str | None
) -> None:
    """Событие исполнителю и уведомления сторонам (D18); токенов в полезной нагрузке нет."""
    for binding in bindings:
        if binding.provider_org_id is None:
            continue
        ctx.emit_integration_event(
            IntegrationEventType.SERVICE_BINDING_CHANGED.value,
            recipient_org_id=binding.provider_org_id,
            resource_kind="service_binding",
            resource_id=binding.id,
            resource_version=None,
            payload=binding_event_payload(binding, contract_number),
        )
        payload = {"service_binding_id": ids.encode("service_binding", binding.id)}
        for membership in await notify.provider_recipients(ctx.session, binding.provider_org_id):
            ctx.notify(
                membership.user_id,
                "service_binding.changed",
                payload,
                membership_id=membership.id,
                organization_id=binding.provider_org_id,
            )


async def request_binding(
    actor: Actor, data: BindingRequestData, *, idem: Idempotency | None
) -> CommandResult:
    """ТЗ 6.6.3: заказчик знает номер договора. Ответ всегда одинаково нейтрален."""
    manager = policy.require_customer_manager(actor)
    provider_org_id = ids.decode("organization", data.provider_organization_id)
    basis = _check_basis(data.basis)
    contract_number = policy.require_text(
        data.contract_number, "contract_number", "Укажите номер договора"
    )
    equipment_ids = [ids.decode("equipment", pid) for pid in data.equipment_ids]
    if not equipment_ids:
        raise ValidationFailed("Выберите оборудование", field="equipment_ids")

    async def handler(ctx: CommandContext) -> CommandResult:
        remaining = await _check_request_rate(ctx, manager, provider_org_id)
        provider = await ctx.session.get(Organization, provider_org_id)
        profile = (
            await ctx.session.execute(
                select(ProviderProfile).where(ProviderProfile.organization_id == provider_org_id)
            )
        ).scalar_one_or_none()
        if provider is None or profile is None or profile.status != ProviderProfileStatus.ACTIVE:
            raise NotFound()
        equipment = await _customer_equipment(ctx, manager.organization_id, equipment_ids)
        contract = (
            await ctx.session.execute(
                select(ServiceContract).where(
                    ServiceContract.provider_org_id == provider_org_id,
                    ServiceContract.contract_number == contract_number,
                    ServiceContract.customer_org_id == manager.organization_id,
                )
            )
        ).scalar_one_or_none()
        created = []
        for item in equipment:
            binding = await _create_binding(
                ctx,
                equipment=item,
                customer_org_id=manager.organization_id,
                provider_org_id=provider_org_id,
                basis=contract.basis if contract else basis,
                contract=contract,
                created_by_membership_id=manager.membership_id,
                status=BindingStatus.PENDING,
                customer_confirmed_at=ctx.now,
                provider_confirmed_at=None,
                source_invitation_id=None,
                claimed_contract_number=contract_number,
            )
            if binding is not None:
                created.append(binding)
        ctx.audit(
            REQUEST_AUDIT_ACTION,
            "service_binding",
            created[0].id if created else None,
            organization_id=manager.organization_id,
            provider_org_id=str(provider_org_id),
            bindings=len(created),
        )
        await _announce(ctx, created, contract_number)
        view = BindingRequestAcceptedView(remaining_attempts=remaining)
        return CommandResult(view.model_dump(mode="json"), status=202)

    try:
        return await run_command(actor, handler, idempotency=idem)
    except _RequestRateExceeded as exc:
        await _journal_rejected_request(manager, provider_org_id, exc.scope)
        raise RateLimited(exc.message, retry_after_seconds=exc.retry_after_seconds) from None


def request_attempts(provider_org_id: uuid.UUID, cutoff: datetime) -> Select[tuple[int]]:
    """Счёт попыток по получателю для индекса `ix_audit_entries_binding_request` (0008).

    Ключ JSON и действие — литералами, а не параметрами: asyncpg готовит запрос,
    и в общем плане `details ->> $1` не совпадает с выражением индекса, а
    `action = $2` не доказывает его условие `WHERE action = '...'`."""
    return (
        select(func.count())
        .select_from(AuditEntry)
        .where(
            AuditEntry.action == literal_column(f"'{REQUEST_AUDIT_ACTION}'"),
            AuditEntry.details.op("->>")(literal_column("'provider_org_id'"))
            == str(provider_org_id),
            AuditEntry.occurred_at > cutoff,
        )
    )


async def _check_request_rate(
    ctx: CommandContext, manager: UserActor, provider_org_id: uuid.UUID
) -> int:
    """ТЗ 6.6.3: 5 попыток за 15 минут на пару «пользователь — получатель» и на пару
    «организация — получатель», плюс общий, заметно более высокий порог на получателя.

    Лимит пары, а не получателя целиком: иначе один перебирающий номера аккаунт
    закрыл бы запросы всем клиентам сервиса. Подсчёт и запись попытки идут в одной
    транзакции под advisory-блокировкой получателя — параллельные запросы не
    проскакивают мимо лимита.

    Возвращает, сколько попыток останется у пользователя и его организации после
    текущей. Считаются все попытки, а не только совпавшие договоры, поэтому число
    ничего не говорит о существовании договора (A31).
    """
    await advisory_xact_lock(ctx.session, f"service_binding.request:{provider_org_id}")
    settings = get_settings()
    cutoff = ctx.now - timedelta(seconds=settings.binding_request_window_seconds)
    base = request_attempts(provider_org_id, cutoff)
    checks = (
        (
            "user",
            base.where(AuditEntry.actor_user_id == manager.user_id),
            settings.binding_request_limit,
        ),
        (
            "organization",
            base.where(AuditEntry.organization_id == manager.organization_id),
            settings.binding_request_limit,
        ),
        ("provider", base, settings.binding_request_provider_limit),
    )
    window = settings.binding_request_window_seconds
    remaining = settings.binding_request_limit
    for scope, stmt, limit in checks:
        used = await ctx.session.scalar(stmt) or 0
        if used >= limit:
            raise _RequestRateExceeded(scope, await _retry_after(ctx, scope, stmt, window))
        if scope != "provider":
            remaining = min(remaining, limit - used - 1)
    return max(remaining, 0)


async def _retry_after(
    ctx: CommandContext, scope: str, stmt: Select[tuple[int]], window: int
) -> int:
    """Когда самая старая попытка в окне выйдет из него. Для общего порога сервиса —
    всё окно: время чужих попыток заказчику не раскрывается."""
    if scope == "provider":
        return window
    oldest = await ctx.session.scalar(stmt.with_only_columns(func.min(AuditEntry.occurred_at)))
    if oldest is None:
        return window
    left = (oldest + timedelta(seconds=window) - ctx.now).total_seconds()
    return max(1, math.ceil(left))


async def _journal_rejected_request(
    manager: UserActor, provider_org_id: uuid.UUID, scope: str
) -> None:
    async with db_session.transaction() as session:
        session.add(
            AuditEntry(
                actor_kind="user",
                actor_user_id=manager.user_id,
                organization_id=manager.organization_id,
                object_type="service_binding",
                action=REQUEST_REJECTED_ACTION,
                result="denied",
                details={
                    "provider_org_id": str(provider_org_id),
                    "reason": "rate_limited",
                    "scope": scope,
                },
                occurred_at=utcnow(),
            )
        )


async def create_contact_binding(
    actor: Actor, data: ContactBindingData, *, idem: Idempotency | None
) -> CommandResult:
    """ТЗ 6.6.4 «Мой контакт»: сохранённый контакт не становится подтверждённой связью."""
    manager = policy.require_customer_manager(actor)
    equipment_id = ids.decode("equipment", data.equipment_id)
    contact_name = policy.require_text(data.contact_name, "contact_name", "Укажите контакт")

    async def handler(ctx: CommandContext) -> CommandResult:
        equipment = await _customer_equipment(ctx, manager.organization_id, [equipment_id])
        binding = ServiceBinding(
            equipment_id=equipment[0].id,
            customer_org_id=manager.organization_id,
            provider_org_id=None,
            personal_contact_name=contact_name,
            personal_contact_phone=data.contact_phone,
            basis=BindingBasis.PREFERRED_PROVIDER.value,
            status=BindingStatus.PENDING.value,
            customer_confirmed_at=ctx.now,
            created_by_membership_id=manager.membership_id,
        )
        ctx.session.add(binding)
        await ctx.session.flush()
        ctx.audit(
            "service_binding.contact",
            "service_binding",
            binding.id,
            organization_id=manager.organization_id,
        )
        view = to_binding_view(binding, provider=None, contract=None, warranty=None)
        return CommandResult(view.model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


async def respond_binding(
    actor: Actor,
    binding_public_id: str,
    decision: str,
    reason: str | None,
    *,
    idem: Idempotency | None,
) -> CommandResult:
    responder = policy.require_binding_actor(actor)
    binding_id = ids.decode("service_binding", binding_public_id)
    if decision not in ("confirm", "reject"):
        raise ValidationFailed("Неизвестное решение", field="decision")
    checked_reason = policy.require_reason(reason) if decision == "reject" else None

    async def handler(ctx: CommandContext) -> CommandResult:
        binding = await lock_by_id(ctx.session, ServiceBinding, binding_id)
        if binding.provider_org_id != responder.organization_id:
            raise NotFound()
        if binding.status != BindingStatus.PENDING:
            raise Conflict("Привязка уже обработана", code="INVALID_TRANSITION")
        if decision == "confirm":
            binding.provider_confirmed_at = ctx.now
            binding.status = BindingStatus.CONFIRMED.value
            if binding.basis == BindingBasis.WARRANTY and binding.warranty_authorization_id is None:
                equipment = await ctx.session.get(Equipment, binding.equipment_id)
                assert equipment is not None
                warranty = await match_warranty_authorization(
                    ctx, binding.provider_org_id, equipment.equipment_category_id, equipment.brand
                )
                if warranty is not None:
                    binding.warranty_authorization_id = warranty.id
                    binding.guarantor_kind = warranty.guarantor_kind
                    binding.guarantor_org_id = warranty.guarantor_org_id
        else:
            binding.status = BindingStatus.REJECTED.value
            binding.status_reason = checked_reason
        ctx.audit(
            f"service_binding.{decision}",
            "service_binding",
            binding.id,
            organization_id=responder.organization_id,
            reason=checked_reason,
        )
        contract = (
            await ctx.session.get(ServiceContract, binding.contract_id)
            if binding.contract_id
            else None
        )
        await _announce(
            ctx,
            [binding],
            contract.contract_number if contract else binding.claimed_contract_number,
        )
        await _notify_customer(ctx, binding)
        customer = await ctx.session.get(Organization, binding.customer_org_id)
        assert customer is not None
        equipment = await ctx.session.get(Equipment, binding.equipment_id)
        view = to_provider_binding_view(
            binding,
            customer=customer,
            equipment=equipment,
            contract=contract,
        )
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def _notify_customer(ctx: CommandContext, binding: ServiceBinding) -> None:
    payload = {"service_binding_id": ids.encode("service_binding", binding.id)}
    for membership in await notify.customer_recipients(ctx.session, binding.customer_org_id):
        ctx.notify(
            membership.user_id,
            "service_binding.changed",
            payload,
            membership_id=membership.id,
            organization_id=binding.customer_org_id,
        )


async def revoke_binding(
    actor: Actor, binding_public_id: str, reason: str, *, idem: Idempotency | None
) -> CommandResult:
    """Расторжение любой из сторон или оператором; полномочия не переносятся (I25)."""
    binding_id = ids.decode("service_binding", binding_public_id)
    checked_reason = policy.require_reason(reason)
    party = _revoking_party(actor)

    async def handler(ctx: CommandContext) -> CommandResult:
        binding = await lock_by_id(ctx.session, ServiceBinding, binding_id)
        if party is not None and party not in (binding.customer_org_id, binding.provider_org_id):
            raise NotFound()
        if binding.status not in (BindingStatus.PENDING, BindingStatus.CONFIRMED):
            raise Conflict("Привязка уже прекращена", code="INVALID_TRANSITION")
        binding.status = BindingStatus.REVOKED.value
        binding.status_reason = checked_reason
        ctx.audit(
            "service_binding.revoke",
            "service_binding",
            binding.id,
            organization_id=party or binding.customer_org_id,
            reason=checked_reason,
        )
        contract = (
            await ctx.session.get(ServiceContract, binding.contract_id)
            if binding.contract_id
            else None
        )
        await _announce(
            ctx,
            [binding],
            contract.contract_number if contract else binding.claimed_contract_number,
        )
        await _notify_customer(ctx, binding)
        provider = (
            await ctx.session.get(Organization, binding.provider_org_id)
            if binding.provider_org_id
            else None
        )
        invitation = (
            await ctx.session.get(Invitation, binding.source_invitation_id)
            if binding.source_invitation_id
            else None
        )
        view = to_binding_view(
            binding,
            provider=provider,
            contract=contract,
            warranty=None,
            invitation=invitation,
        )
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


def _revoking_party(actor: Actor) -> uuid.UUID | None:
    if isinstance(actor, OperatorActor):
        return None
    if isinstance(actor, IntegrationActor):
        return policy.require_binding_actor(actor).organization_id
    user = policy.require_customer_manager(actor) if _is_customer(actor) else None
    if user is not None:
        return user.organization_id
    return policy.require_binding_actor(actor).organization_id


def _is_customer(actor: Actor) -> bool:
    return isinstance(actor, UserActor) and actor.side == "customer"
