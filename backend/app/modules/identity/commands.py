import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import structlog
from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core import ids
from app.core.actor import CUSTOMER_ROLES, PROVIDER_ROLES, Actor, Side, UserActor
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import (
    INVITATION_SECRET_FIELDS,
    CommandContext,
    CommandResult,
    Idempotency,
    run_command,
)
from app.core.unset import UNSET, UnsetType
from app.db.enums import (
    InvitationKind,
    InvitationState,
    MembershipRole,
    MembershipStatus,
    ProviderKind,
    ProviderProfileStatus,
    VerificationStatus,
)
from app.db.models import (
    AuditEntry,
    City,
    District,
    Invitation,
    Location,
    Membership,
    MembershipLocation,
    Organization,
    ProviderProfile,
    User,
)
from app.infra.config import get_settings
from app.infra.crypto import generate_token, hash_token, token_prefix
from app.infra.max.deeplinks import bot_start_link, build_start_param, webapp_start_link
from app.modules.identity import policy
from app.modules.identity.inn import require_valid_inn
from app.modules.identity.views import (
    to_invitation_issued_view,
    to_invitation_view,
    to_membership_view,
    to_organization_view,
)

log = structlog.get_logger(__name__)

INVITATION_START_KIND = "inv"


@dataclass(slots=True)
class FirstLocationData:
    name: str
    city_id: uuid.UUID
    address: str
    district_id: uuid.UUID | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


@dataclass(slots=True)
class OrganizationCreateData:
    name: str
    kind: str
    contact_phone: str
    contact_name: str | None = None
    representative_position: str | None = None
    contact_email: str | None = None
    legal_form: str | None = None
    inn: str | None = None
    provider_kind: str = ProviderKind.COMPANY.value
    first_location: FirstLocationData | None = None


@dataclass(slots=True)
class OrganizationUpdateData:
    """`UNSET` — поле не передано (не меняется); `None` — явная очистка nullable-поля."""

    name: str | UnsetType | None = UNSET
    contact_name: str | UnsetType | None = UNSET
    representative_position: str | UnsetType | None = UNSET
    contact_phone: str | UnsetType | None = UNSET
    contact_email: str | UnsetType | None = UNSET
    legal_form: str | UnsetType | None = UNSET
    inn: str | UnsetType | None = UNSET


@dataclass(slots=True)
class ParticipationData:
    kind: str
    provider_kind: str = ProviderKind.COMPANY.value
    first_location: FirstLocationData | None = None


@dataclass(slots=True)
class InvitationCreateData:
    role: str
    location_ids: list[uuid.UUID] = field(default_factory=list)
    recipient_max_user_id: str | None = None
    recipient_name: str | None = None


async def create_organization(
    actor: Actor, data: OrganizationCreateData, *, idem: Idempotency | None
) -> CommandResult:
    user_id = policy.user_id_of(actor)
    kind = policy.check_organization_kind(data.kind)
    is_customer, is_provider = kind == "customer", kind == "provider"
    role = policy.founder_role(kind)
    inn_normalized = require_valid_inn(data.inn)
    name = data.name.strip()
    if not name:
        raise ValidationFailed("Укажите название организации", field="name")
    if not data.contact_phone.strip():
        raise ValidationFailed("Укажите контактный телефон", field="contact_phone")
    if is_provider and data.provider_kind not in {k.value for k in ProviderKind}:
        raise ValidationFailed("Неизвестный тип исполнителя", field="provider_kind")

    async def handler(ctx: CommandContext) -> CommandResult:
        org = Organization(
            is_customer=is_customer,
            is_provider=is_provider,
            legal_name=name,
            display_name=name,
            legal_form=data.legal_form,
            inn_raw=data.inn,
            inn_normalized=inn_normalized,
            contact_name=data.contact_name,
            representative_position=(data.representative_position or "").strip() or None,
            contact_phone=data.contact_phone.strip(),
            contact_email=data.contact_email,
            details_verification_status=VerificationStatus.UNVERIFIED.value,
            representative_verification_status=VerificationStatus.UNVERIFIED.value,
        )
        ctx.session.add(org)
        await ctx.session.flush()

        membership = Membership(
            user_id=user_id,
            organization_id=org.id,
            role=role.value,
            status=MembershipStatus.ACTIVE.value,
        )
        ctx.session.add(membership)
        await ctx.session.flush()

        if is_provider:
            ctx.session.add(
                ProviderProfile(
                    organization_id=org.id,
                    provider_kind=data.provider_kind,
                    status=ProviderProfileStatus.DRAFT.value,
                    accepting_new_requests=False,
                    can_provide_documents=False,
                )
            )
        if is_customer and data.first_location is not None:
            await _insert_location(ctx, org.id, data.first_location)

        ctx.audit("organization.create", "organization", org.id, organization_id=org.id)
        view = {
            "organization": to_organization_view(org).model_dump(mode="json"),
            "membership": to_membership_view(membership, org, []).model_dump(mode="json"),
        }
        return CommandResult(view, status=201)

    return await run_command(actor, handler, idempotency=idem)


async def _insert_location(
    ctx: CommandContext, organization_id: uuid.UUID, data: FirstLocationData
) -> Location:
    city = await ctx.session.get(City, data.city_id)
    if city is None:
        raise ValidationFailed("Неизвестный город", field="city_id")
    if data.district_id is not None:
        district = await ctx.session.get(District, data.district_id)
        if district is None or district.city_id != city.id:
            raise ValidationFailed("Район не принадлежит городу", field="district_id")
    location = Location(
        customer_org_id=organization_id,
        name=data.name,
        city_id=city.id,
        district_id=data.district_id,
        address=data.address,
        timezone=data.timezone or city.timezone,
        contact_name=data.contact_name,
        contact_phone=data.contact_phone,
    )
    ctx.session.add(location)
    await ctx.session.flush()
    return location


async def add_participation(
    actor: Actor,
    organization_id: uuid.UUID,
    data: ParticipationData,
    *,
    idem: Idempotency | None,
) -> CommandResult:
    """Второй тип участия той же организации (ТЗ 3).

    Руководитель получает отдельное членство новой стороны: контексты и полномочия
    заказчика и исполнителя не смешиваются. Профиль исполнителя начинается с
    черновика и проходит проверку как обычно.
    """
    manager = policy.require_org_manager(actor)
    kind = policy.check_organization_kind(data.kind)
    if kind == "provider" and data.provider_kind not in {k.value for k in ProviderKind}:
        raise ValidationFailed("Неизвестный тип исполнителя", field="provider_kind")

    async def handler(ctx: CommandContext) -> CommandResult:
        if organization_id != manager.organization_id:
            raise NotFound()
        org = await lock_by_id(ctx.session, Organization, organization_id)
        policy.check_can_add_participation(org, kind)
        if kind == "provider":
            org.is_provider = True
            try:
                await ctx.session.flush()
            except IntegrityError as exc:
                raise Conflict(
                    "По этому ИНН уже есть подтверждённый исполнитель",
                    code="INN_ALREADY_VERIFIED",
                ) from exc
            profile_exists = await ctx.session.scalar(
                select(ProviderProfile.id).where(ProviderProfile.organization_id == org.id)
            )
            if profile_exists is None:
                ctx.session.add(
                    ProviderProfile(
                        organization_id=org.id,
                        provider_kind=data.provider_kind,
                        status=ProviderProfileStatus.DRAFT.value,
                        accepting_new_requests=False,
                        can_provide_documents=False,
                    )
                )
        else:
            org.is_customer = True
            if data.first_location is not None:
                await _insert_location(ctx, org.id, data.first_location)

        membership = await _founder_membership(ctx, manager.user_id, org.id, kind)
        ctx.audit(
            "organization.add_participation",
            "organization",
            org.id,
            organization_id=org.id,
            kind=kind,
        )
        location_ids = await _membership_location_ids(ctx, membership.id)
        view = {
            "organization": to_organization_view(org).model_dump(mode="json"),
            "membership": to_membership_view(membership, org, location_ids).model_dump(mode="json"),
        }
        return CommandResult(view, status=201)

    return await run_command(actor, handler, idempotency=idem)


async def _founder_membership(
    ctx: CommandContext, user_id: uuid.UUID, organization_id: uuid.UUID, side: Side
) -> Membership:
    role = policy.founder_role(side)
    existing = await _side_membership(ctx, user_id, organization_id, side)
    if existing is None:
        membership = Membership(
            user_id=user_id,
            organization_id=organization_id,
            role=role.value,
            status=MembershipStatus.ACTIVE.value,
        )
        ctx.session.add(membership)
        await ctx.session.flush()
        return membership
    existing.role = role.value
    existing.status = MembershipStatus.ACTIVE.value
    await ctx.session.execute(
        delete(MembershipLocation).where(MembershipLocation.membership_id == existing.id)
    )
    return existing


async def _side_membership(
    ctx: CommandContext, user_id: uuid.UUID, organization_id: uuid.UUID, side: Side
) -> Membership | None:
    roles = CUSTOMER_ROLES if side == "customer" else PROVIDER_ROLES
    return (
        await ctx.session.execute(
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id,
                Membership.role.in_(roles),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


async def update_organization(
    actor: Actor,
    data: OrganizationUpdateData,
    *,
    idem: Idempotency | None,
    organization_id: uuid.UUID | None = None,
) -> CommandResult:
    """Профиль организации. Смена отображаемого имени не трогает репутацию — она
    привязана к организации, а не к названию (ТЗ 6.5.3)."""
    manager = policy.require_org_manager(actor)
    if data.name is None:
        raise ValidationFailed("Укажите название организации", field="name")
    inn_normalized = require_valid_inn(data.inn) if isinstance(data.inn, str) else None

    async def handler(ctx: CommandContext) -> CommandResult:
        if organization_id is not None and organization_id != manager.organization_id:
            raise NotFound()
        org = await lock_by_id(ctx.session, Organization, manager.organization_id)
        inn_changed = not isinstance(data.inn, UnsetType) and inn_normalized != org.inn_normalized
        legal_form_changed = (
            not isinstance(data.legal_form, UnsetType) and data.legal_form != org.legal_form
        )
        policy.check_requisites_change(
            org, inn_changed=inn_changed, legal_form_changed=legal_form_changed
        )
        if isinstance(data.name, str):
            name = data.name.strip()
            if not name:
                raise ValidationFailed("Укажите название организации", field="name")
            org.display_name = name
        if not isinstance(data.contact_name, UnsetType):
            org.contact_name = data.contact_name
        if not isinstance(data.representative_position, UnsetType):
            org.representative_position = data.representative_position
        if not isinstance(data.contact_phone, UnsetType):
            org.contact_phone = data.contact_phone
        if not isinstance(data.contact_email, UnsetType):
            org.contact_email = data.contact_email
        if not isinstance(data.legal_form, UnsetType):
            org.legal_form = data.legal_form
        if not isinstance(data.inn, UnsetType):
            org.inn_raw = data.inn
            org.inn_normalized = inn_normalized
        reverify = (inn_changed or legal_form_changed) and (
            org.details_verification_status == VerificationStatus.VERIFIED
        )
        if reverify:
            await _require_reverification(ctx, org)
        ctx.audit(
            "organization.update",
            "organization",
            org.id,
            organization_id=org.id,
            requisites_changed=inn_changed or legal_form_changed,
            reverification=reverify,
        )
        return CommandResult(to_organization_view(org).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def _require_reverification(ctx: CommandContext, org: Organization) -> None:
    """ТЗ 6.5.3: смена реквизитов требует повторной проверки — прежний признак снят."""
    from app.modules.providers import api as providers

    org.details_verification_status = VerificationStatus.UNVERIFIED.value
    org.details_verified_at = None
    if org.is_provider:
        await providers.apply_verification_expiry(
            ctx, org.id, reason="Изменены реквизиты организации, требуется повторная проверка"
        )


async def _membership_of_org(
    ctx: CommandContext, actor: UserActor, membership_id: uuid.UUID
) -> Membership:
    membership = await lock_by_id(ctx.session, Membership, membership_id)
    if (
        membership.organization_id != actor.organization_id
        or policy.role_side(membership.role) != actor.side
    ):
        raise NotFound()
    return membership


async def approve_membership(
    actor: Actor, membership_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_org_manager(actor)
    membership_id = ids.decode("membership", membership_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        membership = await _membership_of_org(ctx, manager, membership_id)
        if membership.status != MembershipStatus.PENDING:
            raise Conflict("Участник уже подтверждён или отозван")
        membership.status = MembershipStatus.ACTIVE.value
        org = await ctx.session.get(Organization, membership.organization_id)
        assert org is not None
        ctx.notify(
            membership.user_id,
            "membership.approved",
            {"membership_id": ids.encode("membership", membership.id)},
            membership_id=membership.id,
            organization_id=membership.organization_id,
        )
        ctx.audit(
            "membership.approve",
            "membership",
            membership.id,
            organization_id=membership.organization_id,
        )
        location_ids = await _membership_location_ids(ctx, membership.id)
        view = to_membership_view(membership, org, location_ids)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def revoke_membership(
    actor: Actor, membership_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_org_manager(actor)
    membership_id = ids.decode("membership", membership_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        membership = await _membership_of_org(ctx, manager, membership_id)
        if membership.status == MembershipStatus.REVOKED:
            raise Conflict("Участник уже отозван")
        if membership.role == manager.role:
            remaining = await ctx.session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.organization_id == manager.organization_id,
                    Membership.role == manager.role,
                    Membership.status == MembershipStatus.ACTIVE,
                    Membership.id != membership.id,
                )
            )
            if not remaining:
                raise Conflict(
                    "Нельзя отозвать последнего руководителя организации",
                    code="LAST_MANAGER",
                )
        if membership.id == manager.membership_id:
            raise Conflict("Нельзя исключить самого себя", code="SELF_REVOKE")
        membership.status = MembershipStatus.REVOKED.value
        await ctx.session.execute(
            delete(MembershipLocation).where(MembershipLocation.membership_id == membership.id)
        )
        ctx.audit(
            "membership.revoke",
            "membership",
            membership.id,
            organization_id=membership.organization_id,
        )
        org = await ctx.session.get(Organization, membership.organization_id)
        assert org is not None
        return CommandResult(to_membership_view(membership, org, []).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def set_membership_locations(
    actor: Actor,
    membership_public_id: str,
    location_public_ids: list[str],
    *,
    idem: Idempotency | None,
) -> CommandResult:
    manager = policy.require_customer_manager(actor)
    membership_id = ids.decode("membership", membership_public_id)
    location_ids = [ids.decode("location", pid) for pid in location_public_ids]

    async def handler(ctx: CommandContext) -> CommandResult:
        membership = await _membership_of_org(ctx, manager, membership_id)
        if membership.status == MembershipStatus.REVOKED:
            raise Conflict("Участник отозван")
        policy.check_locations_role(MembershipRole(membership.role), location_ids)
        await _check_locations_belong(ctx, manager.organization_id, location_ids)
        await ctx.session.execute(
            delete(MembershipLocation).where(MembershipLocation.membership_id == membership.id)
        )
        for location_id in dict.fromkeys(location_ids):
            ctx.session.add(
                MembershipLocation(membership_id=membership.id, location_id=location_id)
            )
        ctx.audit(
            "membership.set_locations",
            "membership",
            membership.id,
            organization_id=membership.organization_id,
            count=len(set(location_ids)),
        )
        org = await ctx.session.get(Organization, membership.organization_id)
        assert org is not None
        return CommandResult(
            to_membership_view(membership, org, list(dict.fromkeys(location_ids))).model_dump(
                mode="json"
            )
        )

    return await run_command(actor, handler, idempotency=idem)


async def _check_locations_belong(
    ctx: CommandContext, organization_id: uuid.UUID, location_ids: list[uuid.UUID]
) -> None:
    if not location_ids:
        return
    found = set(
        (
            await ctx.session.execute(
                select(Location.id).where(
                    Location.id.in_(location_ids),
                    Location.customer_org_id == organization_id,
                )
            )
        ).scalars()
    )
    if found != set(location_ids):
        raise NotFound()


async def _membership_location_ids(
    ctx: CommandContext, membership_id: uuid.UUID
) -> list[uuid.UUID]:
    return list(
        (
            await ctx.session.execute(
                select(MembershipLocation.location_id).where(
                    MembershipLocation.membership_id == membership_id
                )
            )
        ).scalars()
    )


MAX_RECIPIENT_ID = 64
MAX_RECIPIENT_NAME = 200


def _recipient_max_user_id(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_RECIPIENT_ID or any(ch.isspace() for ch in cleaned):
        raise ValidationFailed("Некорректный ID пользователя MAX", field="recipient_max_user_id")
    return cleaned


def _recipient_name(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        return None
    if len(cleaned) > MAX_RECIPIENT_NAME:
        raise ValidationFailed(f"Не длиннее {MAX_RECIPIENT_NAME} символов", field="recipient_name")
    return cleaned


async def create_invitation(
    actor: Actor, data: InvitationCreateData, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_org_manager(actor)
    role = policy.check_invite_role(manager, data.role)
    policy.check_locations_role(role, data.location_ids)
    recipient_max_user_id = _recipient_max_user_id(data.recipient_max_user_id)
    recipient_name = _recipient_name(data.recipient_name)
    settings = get_settings()
    token = generate_token()

    async def handler(ctx: CommandContext) -> CommandResult:
        await _check_locations_belong(ctx, manager.organization_id, data.location_ids)
        invitation = Invitation(
            kind=InvitationKind.MEMBERSHIP.value,
            organization_id=manager.organization_id,
            created_by_membership_id=manager.membership_id,
            role=role.value,
            location_ids=list(dict.fromkeys(data.location_ids)),
            equipment_ids=[],
            token_hash=hash_token(token),
            token_prefix=token_prefix(token),
            recipient_max_user_id=recipient_max_user_id,
            recipient_name=recipient_name,
            status=InvitationState.PENDING.value,
            expires_at=ctx.now + timedelta(seconds=settings.staff_invitation_ttl_seconds),
            created_at=ctx.now,
        )
        ctx.session.add(invitation)
        await ctx.session.flush()
        ctx.audit(
            "invitation.create",
            "invitation",
            invitation.id,
            organization_id=manager.organization_id,
            role=role.value,
            named=recipient_max_user_id is not None,
        )
        webapp_link, bot_link = _invitation_links(token)
        view = to_invitation_issued_view(
            invitation, ctx.now, token=token, webapp_link=webapp_link, bot_link=bot_link
        )
        return CommandResult(
            view.model_dump(mode="json"), status=201, secret_fields=INVITATION_SECRET_FIELDS
        )

    return await run_command(actor, handler, idempotency=idem)


def _invitation_links(token: str) -> tuple[str | None, str | None]:
    bot_username = get_settings().max_bot_username
    if not bot_username:
        return None, None
    payload = build_start_param(INVITATION_START_KIND, token)
    return webapp_start_link(bot_username, payload), bot_start_link(bot_username, payload)


async def revoke_invitation(
    actor: Actor, invitation_public_id: str, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_org_manager(actor)
    invitation_id = ids.decode("invitation", invitation_public_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        invitation = await lock_by_id(ctx.session, Invitation, invitation_id)
        if (
            invitation.organization_id != manager.organization_id
            or invitation.kind != InvitationKind.MEMBERSHIP
            or policy.role_side(invitation.role or MembershipRole.CUSTOMER_EMPLOYEE) != manager.side
        ):
            raise NotFound()
        if invitation.status != InvitationState.PENDING:
            raise Conflict("Приглашение недействительно", code="INVITATION_INVALID")
        invitation.status = InvitationState.REVOKED.value
        invitation.revoked_at = ctx.now
        invitation.revoked_by_membership_id = manager.membership_id
        ctx.audit(
            "invitation.revoke",
            "invitation",
            invitation.id,
            organization_id=manager.organization_id,
        )
        return CommandResult(to_invitation_view(invitation, ctx.now).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


def _invitation_invalid(reason: str | None = None) -> Conflict:
    """Единая ошибка: причина наружу не раскрывается, кроме истечения срока (A32).

    Чужое именное приглашение отвечает так же, как отозванное или использованное:
    по ответу не понять, кому оно выдано."""
    if reason == "expired":
        return Conflict(
            "Срок действия приглашения истёк", code="INVITATION_INVALID", reason="expired"
        )
    return Conflict("Приглашение недействительно", code="INVITATION_INVALID")


class _ForeignRecipient(Exception):
    """Именное приглашение предъявил не адресат: транзакция приёма откатывается,
    приглашение не расходуется, о попытке узнаёт приглашающий."""

    def __init__(self, invitation_id: uuid.UUID) -> None:
        super().__init__(invitation_id)
        self.invitation_id = invitation_id


async def accept_invitation(actor: Actor, token: str, *, idem: Idempotency | None) -> CommandResult:
    return await _accept_invitation(actor, Invitation.token_hash == hash_token(token), idem=idem)


async def accept_invitation_by_id(
    actor: Actor, invitation_id: uuid.UUID, *, idem: Idempotency | None
) -> CommandResult:
    """Приём приглашения, уже предъявленного токеном (бот: предпросмотр → кнопка «Принять»).

    Токен проверен при предпросмотре и повторно нигде не хранится; право нажать
    кнопку подтверждает одноразовая строка `bot_actions`, привязанная к адресату.
    Правила погашения и все ошибки — те же, что при приёме по токену.
    """
    return await _accept_invitation(actor, Invitation.id == invitation_id, idem=idem)


async def _accept_invitation(
    actor: Actor, match: ColumnElement[bool], *, idem: Idempotency | None
) -> CommandResult:
    """ТЗ 6.5.4, 6.7: именное приглашение принимает только адресат, и доступ открывается
    сразу; приглашение без адресата даёт членство `pending` до решения руководителя."""
    user_id = policy.user_id_of(actor)

    async def handler(ctx: CommandContext) -> CommandResult:
        user = await ctx.session.get(User, user_id)
        if user is None:
            raise _invitation_invalid()
        claimed_id = (
            await ctx.session.execute(
                update(Invitation)
                .where(
                    match,
                    Invitation.kind == InvitationKind.MEMBERSHIP,
                    Invitation.status == InvitationState.PENDING,
                    Invitation.expires_at > ctx.now,
                    or_(
                        Invitation.recipient_max_user_id.is_(None),
                        Invitation.recipient_max_user_id == user.max_user_id,
                    ),
                )
                .values(
                    status=InvitationState.ACCEPTED.value,
                    accepted_at=ctx.now,
                    accepted_by_user_id=user_id,
                )
                .returning(Invitation.id)
            )
        ).scalar_one_or_none()
        if claimed_id is None:
            raise await _explain_failed_claim(ctx, match)
        claimed = (
            await ctx.session.execute(
                select(Invitation)
                .where(Invitation.id == claimed_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

        org = await ctx.session.get(Organization, claimed.organization_id)
        assert org is not None
        role = MembershipRole(claimed.role) if claimed.role else MembershipRole.CUSTOMER_EMPLOYEE
        status = policy.membership_status_on_accept(named=claimed.recipient_max_user_id is not None)

        membership = await _side_membership(
            ctx, user_id, claimed.organization_id, policy.role_side(role.value)
        )
        if membership is None:
            membership = Membership(
                user_id=user_id,
                organization_id=claimed.organization_id,
                role=role.value,
                status=status,
                invited_by_membership_id=claimed.created_by_membership_id,
                invitation_id=claimed.id,
            )
            ctx.session.add(membership)
            await ctx.session.flush()
        elif membership.status == MembershipStatus.REVOKED:
            membership.role = role.value
            membership.status = status
            membership.invited_by_membership_id = claimed.created_by_membership_id
            membership.invitation_id = claimed.id
        else:
            raise Conflict("Вы уже участник этой организации в этой роли", code="ALREADY_MEMBER")

        await ctx.session.execute(
            delete(MembershipLocation).where(MembershipLocation.membership_id == membership.id)
        )
        location_ids = await _existing_locations(ctx, org.id, list(claimed.location_ids))
        for location_id in location_ids:
            ctx.session.add(
                MembershipLocation(membership_id=membership.id, location_id=location_id)
            )

        if status == MembershipStatus.PENDING:
            for approver_membership_id, approver_user_id in await _side_approvers(
                ctx, org.id, policy.role_side(role.value)
            ):
                ctx.notify(
                    approver_user_id,
                    "membership.pending_approval",
                    {"membership_id": ids.encode("membership", membership.id)},
                    membership_id=approver_membership_id,
                    organization_id=org.id,
                )

        ctx.audit(
            "invitation.accept",
            "invitation",
            claimed.id,
            organization_id=org.id,
            role=role.value,
            membership_status=status,
        )
        return CommandResult(
            to_membership_view(membership, org, location_ids).model_dump(mode="json"), status=201
        )

    try:
        return await run_command(actor, handler, idempotency=idem)
    except _ForeignRecipient as exc:
        await _report_foreign_attempt(actor, user_id, exc.invitation_id)
        raise _invitation_invalid() from None


async def _explain_failed_claim(ctx: CommandContext, match: ColumnElement[bool]) -> Exception:
    row = (await ctx.session.execute(select(Invitation).where(match))).scalar_one_or_none()
    if row is None:
        return _invitation_invalid()
    if row.kind != InvitationKind.MEMBERSHIP:
        return _invitation_invalid()
    if row.status == InvitationState.EXPIRED or (
        row.status == InvitationState.PENDING and row.expires_at <= ctx.now
    ):
        return _invitation_invalid("expired")
    if row.status == InvitationState.PENDING and row.recipient_max_user_id is not None:
        return _ForeignRecipient(row.id)
    return _invitation_invalid()


async def _side_approvers(
    ctx: CommandContext, organization_id: uuid.UUID, side: Side
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Действующие руководители стороны: (membership_id, user_id)."""
    rows = await ctx.session.execute(
        select(Membership.id, Membership.user_id).where(
            Membership.organization_id == organization_id,
            Membership.role == _ACCESS_APPROVERS[side],
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    return [(membership_id, user_id) for membership_id, user_id in rows.all()]


async def _report_foreign_attempt(
    actor: Actor, user_id: uuid.UUID, invitation_id: uuid.UUID
) -> None:
    """Попытка принять чужое именное приглашение: запись в журнал и, один раз на
    пользователя, уведомление приглашающему (или руководителям стороны, если его уже нет).

    Отдельная транзакция: транзакция приёма откатилась вместе с ключом идемпотентности."""

    async def handler(ctx: CommandContext) -> CommandResult:
        invitation = await ctx.session.get(Invitation, invitation_id)
        assert invitation is not None
        already_reported = await ctx.session.scalar(
            select(AuditEntry.id)
            .where(
                AuditEntry.action == "invitation.accept_foreign",
                AuditEntry.object_id == invitation.id,
                AuditEntry.actor_user_id == user_id,
            )
            .limit(1)
        )
        ctx.audit(
            "invitation.accept_foreign",
            "invitation",
            invitation.id,
            organization_id=invitation.organization_id,
        )
        if already_reported is None:
            payload = {
                "invitation_id": ids.encode("invitation", invitation.id),
                "user_id": ids.encode("user", user_id),
            }
            for recipient_membership_id, recipient_user_id in await _invitation_watchers(
                ctx, invitation
            ):
                ctx.notify(
                    recipient_user_id,
                    "invitation.foreign_attempt",
                    payload,
                    membership_id=recipient_membership_id,
                    organization_id=invitation.organization_id,
                )
        return CommandResult({})

    try:
        await run_command(actor, handler)
    except Exception:
        log.exception("invitation_foreign_attempt_report_failed")


async def _invitation_watchers(
    ctx: CommandContext, invitation: Invitation
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    side = policy.role_side(invitation.role or MembershipRole.CUSTOMER_EMPLOYEE)
    if invitation.created_by_membership_id is not None:
        inviter = await ctx.session.get(Membership, invitation.created_by_membership_id)
        if inviter is not None and inviter.status == MembershipStatus.ACTIVE:
            return [(inviter.id, inviter.user_id)]
    return await _side_approvers(ctx, invitation.organization_id, side)


async def _existing_locations(
    ctx: CommandContext, organization_id: uuid.UUID, location_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    if not location_ids:
        return []
    found = set(
        (
            await ctx.session.execute(
                select(Location.id).where(
                    Location.id.in_(location_ids),
                    Location.customer_org_id == organization_id,
                )
            )
        ).scalars()
    )
    return [lid for lid in dict.fromkeys(location_ids) if lid in found]


MAX_ACCESS_NOTE = 500
_ACCESS_APPROVERS: dict[str, str] = {
    "customer": MembershipRole.CUSTOMER_MANAGER.value,
    "provider": MembershipRole.PROVIDER_ADMIN.value,
}


@dataclass(frozen=True, slots=True)
class AccessRequestData:
    location_id: str | None = None
    note: str | None = None


async def request_access(
    actor: Actor, data: AccessRequestData, *, idem: Idempotency | None
) -> CommandResult:
    """«Запросить доступ» с экрана «Нет доступа»: уведомление руководителям своей стороны.

    Ответ одинаков при любой точке: чужая или несуществующая точка в уведомление не
    попадает, и по ответу нельзя понять, есть ли она. Заявку запрос не принимает."""
    if not isinstance(actor, UserActor):
        raise NotFound()
    note = (data.note or "").strip() or None
    if note is not None and len(note) > MAX_ACCESS_NOTE:
        raise ValidationFailed(f"Не длиннее {MAX_ACCESS_NOTE} символов", field="note")
    location_id: uuid.UUID | None = None
    if data.location_id:
        try:
            location_id = ids.decode("location", data.location_id)
        except ValueError:
            location_id = None

    async def handler(ctx: CommandContext) -> CommandResult:
        location_public_id: str | None = None
        if location_id is not None and actor.side == "customer":
            location = await ctx.session.get(Location, location_id)
            if location is not None and location.customer_org_id == actor.organization_id:
                location_public_id = ids.encode("location", location.id)
        approvers = (
            await ctx.session.execute(
                select(Membership.id, Membership.user_id).where(
                    Membership.organization_id == actor.organization_id,
                    Membership.role == _ACCESS_APPROVERS[actor.side],
                    Membership.status == MembershipStatus.ACTIVE,
                    Membership.id != actor.membership_id,
                )
            )
        ).all()
        payload = {
            "membership_id": ids.encode("membership", actor.membership_id),
            "location_id": location_public_id,
            "note": note,
        }
        for membership_id, user_id in approvers:
            ctx.notify(
                user_id,
                "membership.access_requested",
                payload,
                membership_id=membership_id,
                organization_id=actor.organization_id,
            )
        ctx.audit(
            "membership.access_request",
            "membership",
            actor.membership_id,
            organization_id=actor.organization_id,
            location_id=location_public_id,
            has_note=note is not None,
        )
        return CommandResult({"status": "sent"}, status=202)

    return await run_command(actor, handler, idempotency=idem)
