import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog
from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute

from app.core import ids
from app.core.actor import Actor, SystemActor
from app.core.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.core.quarantine import Quarantine
from app.db import session as db_session
from app.db.enums import (
    AssignmentState,
    BindingStatus,
    IntegrationClientStatus,
    ProviderProfileStatus,
    VerificationDecision,
    VerificationStatus,
    WarrantyAuthorizationStatus,
    WebhookSubscriptionStatus,
)
from app.db.models import (
    Assignment,
    IntegrationClient,
    Invitation,
    Membership,
    Organization,
    ProviderProfile,
    RepairRequest,
    ServiceBinding,
    Session,
    VerificationCase,
    WarrantyAuthorization,
    WebhookSubscription,
)
from app.infra.config import get_settings
from app.modules.trust import notify, policy
from app.modules.trust.views import (
    CHECK_CUSTOMER_REPRESENTATIVE,
    CHECK_REPRESENTATIVE,
    CHECK_REQUISITES,
    to_verification_case_view,
)

log = structlog.get_logger(__name__)

SUBJECT_ORGANIZATION_DETAILS = "organization_details"
SUBJECT_REPRESENTATIVE = "representative"
SUBJECT_CUSTOMER_REPRESENTATIVE = "customer_representative"

_SUBJECT_BY_CHECK = {
    CHECK_REQUISITES: SUBJECT_ORGANIZATION_DETAILS,
    CHECK_REPRESENTATIVE: SUBJECT_REPRESENTATIVE,
    CHECK_CUSTOMER_REPRESENTATIVE: SUBJECT_CUSTOMER_REPRESENTATIVE,
}

_REPRESENTATIVE_CHECKS = (CHECK_REPRESENTATIVE, CHECK_CUSTOMER_REPRESENTATIVE)

_OPEN_DECISIONS = (VerificationDecision.PENDING, VerificationDecision.NEEDS_INFORMATION)
_DECISIONS = (
    VerificationDecision.APPROVED,
    VerificationDecision.NEEDS_INFORMATION,
    VerificationDecision.REJECTED,
)


@dataclass(slots=True)
class VerificationDecisionData:
    decision: str
    reason: str
    source: str | None = None
    expires_at: datetime | None = None
    is_demo: bool = False


@dataclass(slots=True)
class VerificationInformationData:
    note: str
    attachment_refs: list[str] = field(default_factory=list)


def resolve_is_demo(is_demo: bool) -> bool:
    """Вне прода любая проверка демонстрационная и помечается как таковая (A37)."""
    return is_demo or get_settings().app_env != "prod"


async def open_verification_cases(
    ctx: CommandContext,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID | None,
    check_kinds: tuple[str, ...],
) -> list[VerificationCase]:
    """Ставит организацию в очередь проверки; уже открытые дела не дублируются."""
    existing = {
        case.check_kind: case
        for case in (
            await ctx.session.execute(
                select(VerificationCase).where(
                    VerificationCase.organization_id == organization_id,
                    VerificationCase.decision.in_([d.value for d in _OPEN_DECISIONS]),
                )
            )
        ).scalars()
    }
    org = await ctx.session.get(Organization, organization_id)
    if org is None:
        raise NotFound()
    cases = []
    for kind in check_kinds:
        case = existing.get(kind)
        if case is None:
            case = VerificationCase(
                organization_id=organization_id,
                membership_id=membership_id if kind != CHECK_REQUISITES else None,
                subject_type=_SUBJECT_BY_CHECK[kind],
                check_kind=kind,
                decision=VerificationDecision.PENDING.value,
            )
            ctx.session.add(case)
        else:
            case.decision = VerificationDecision.PENDING.value
        cases.append(case)
        if kind == CHECK_REQUISITES:
            org.details_verification_status = VerificationStatus.PENDING.value
        else:
            org.representative_verification_status = VerificationStatus.PENDING.value
    await ctx.session.flush()
    return cases


async def submit_verification_information(
    actor: Actor, data: VerificationInformationData, *, idem: Idempotency | None
) -> CommandResult:
    """Заявитель доносит минимально необходимые сведения текстом (ТЗ 6.5.2)."""
    admin = policy.require_provider_admin(actor)
    note = policy.require_text(data.note, "note", "Укажите сведения для проверки")

    async def handler(ctx: CommandContext) -> CommandResult:
        cases = list(
            (
                await ctx.session.execute(
                    select(VerificationCase)
                    .where(
                        VerificationCase.organization_id == admin.organization_id,
                        VerificationCase.decision.in_([d.value for d in _OPEN_DECISIONS]),
                    )
                    .order_by(VerificationCase.id)
                    .with_for_update()
                )
            ).scalars()
        )
        if not cases:
            raise InvalidTransition("Нет открытых проверок")
        block = _evidence_block(note, data.attachment_refs, ctx.now)
        for case in cases:
            case.evidence_note = f"{case.evidence_note}\n{block}" if case.evidence_note else block
            case.decision = VerificationDecision.PENDING.value
        profile = await _profile_of(ctx, admin.organization_id)
        if profile is not None and profile.status == ProviderProfileStatus.NEEDS_INFORMATION:
            profile.status = ProviderProfileStatus.PENDING_REVIEW.value
            profile.status_reason = None
        ctx.audit(
            "verification.information",
            "verification_case",
            cases[0].id,
            organization_id=admin.organization_id,
            cases=len(cases),
        )
        return CommandResult(
            {"items": [to_verification_case_view(c).model_dump(mode="json") for c in cases]}
        )

    return await run_command(actor, handler, idempotency=idem)


def _evidence_block(note: str, attachment_refs: list[str], now: datetime) -> str:
    lines = [f"[{now.isoformat()}] {note}"]
    lines += [f"вложение: {ref}" for ref in attachment_refs if ref.strip()]
    return "\n".join(lines)


async def _profile_of(ctx: CommandContext, organization_id: uuid.UUID) -> ProviderProfile | None:
    return (
        await ctx.session.execute(
            select(ProviderProfile)
            .where(ProviderProfile.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def decide_verification_case(
    actor: Actor,
    case_public_id: str,
    data: VerificationDecisionData,
    *,
    idem: Idempotency | None,
    organization_ids: tuple[uuid.UUID, ...] | None = None,
) -> CommandResult:
    operator = policy.require_operator(actor)
    case_id = ids.decode("verification_case", case_public_id)
    reason = policy.require_reason(data.reason)
    if data.decision not in {d.value for d in _DECISIONS}:
        raise ValidationFailed("Неизвестное решение", field="decision")
    if data.decision == VerificationDecision.APPROVED and not (data.source or "").strip():
        raise ValidationFailed("Укажите источник проверки", field="source")

    async def handler(ctx: CommandContext) -> CommandResult:
        if data.expires_at is not None and data.expires_at <= ctx.now:
            raise ValidationFailed("Срок действия проверки уже истёк", field="expires_at")
        case = await lock_by_id(ctx.session, VerificationCase, case_id)
        if organization_ids is not None and case.organization_id not in organization_ids:
            raise NotFound()
        if case.decision not in _OPEN_DECISIONS:
            raise InvalidTransition("Дело уже закрыто")
        org = await lock_by_id(ctx.session, Organization, case.organization_id)

        case.decision = data.decision
        case.decision_reason = reason
        case.operator_user_id = operator.user_id
        case.checked_at = ctx.now
        case.expires_at = data.expires_at
        if data.decision == VerificationDecision.APPROVED:
            case.source = data.source
            case.is_demo = resolve_is_demo(data.is_demo)
            _apply_status(org, case.check_kind, VerificationStatus.VERIFIED, ctx.now)
        elif data.decision == VerificationDecision.REJECTED:
            _apply_status(org, case.check_kind, VerificationStatus.REJECTED, None)
        else:
            _apply_status(org, case.check_kind, VerificationStatus.PENDING, None)

        try:
            await ctx.session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "По этому ИНН уже есть подтверждённый исполнитель",
                code="INN_ALREADY_VERIFIED",
            ) from exc

        await _sync_profile(ctx, org, case, reason)
        if (
            case.check_kind == CHECK_CUSTOMER_REPRESENTATIVE
            and case.decision == VerificationDecision.APPROVED
        ):
            await _confirm_awaiting_bindings(ctx, org)
        if case.check_kind != CHECK_REQUISITES:
            await _recalculate_customer_ratings(ctx, org)

        ctx.audit(
            "verification.decide",
            "verification_case",
            case.id,
            organization_id=org.id,
            check_kind=case.check_kind,
            decision=case.decision,
            reason=reason,
            is_demo=case.is_demo,
        )
        await _notify_organization(ctx, org.id, "verification.decided", {"decision": case.decision})
        return CommandResult(to_verification_case_view(case).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


def _apply_status(
    org: Organization, check_kind: str, status: VerificationStatus, moment: datetime | None
) -> None:
    if check_kind == CHECK_REQUISITES:
        org.details_verification_status = status.value
        org.details_verified_at = moment
    else:
        org.representative_verification_status = status.value
        org.representative_verified_at = moment


async def _sync_profile(
    ctx: CommandContext, org: Organization, case: VerificationCase, reason: str
) -> None:
    from app.modules.providers import api as providers

    if case.check_kind == CHECK_CUSTOMER_REPRESENTATIVE:
        return
    await providers.apply_verification_result(
        ctx,
        org.id,
        decision=case.decision,
        reason=reason,
        details_verified=org.details_verification_status == VerificationStatus.VERIFIED,
        representative_verified=(
            org.representative_verification_status == VerificationStatus.VERIFIED
        ),
    )


async def _recalculate_customer_ratings(ctx: CommandContext, org: Organization) -> None:
    if not org.is_customer:
        return
    from app.modules.reputation import api as reputation

    await reputation.recalculate_for_customer(ctx.session, org.id)


async def _confirm_awaiting_bindings(ctx: CommandContext, org: Organization) -> None:
    """ТЗ 6.6.2 п.4: привязка по приглашению ждала проверки организации заказчика.

    Подтверждаются только привязки, чей заявленный при выпуске ИНН по-прежнему
    совпадает с ИНН проверенной организации."""
    customer_org_id = org.id
    if not org.inn_normalized:
        return
    bindings = list(
        (
            await ctx.session.execute(
                select(ServiceBinding)
                .join(Invitation, Invitation.id == ServiceBinding.source_invitation_id)
                .where(
                    Invitation.binding_details["customer_inn"].astext == org.inn_normalized,
                    ServiceBinding.customer_org_id == customer_org_id,
                    ServiceBinding.status == BindingStatus.PENDING,
                    ServiceBinding.source_invitation_id.is_not(None),
                    ServiceBinding.provider_confirmed_at.is_not(None),
                    ServiceBinding.customer_confirmed_at.is_not(None),
                )
                .with_for_update(of=ServiceBinding)
            )
        ).scalars()
    )
    for binding in bindings:
        binding.status = BindingStatus.CONFIRMED.value
        ctx.audit(
            "service_binding.confirm",
            "service_binding",
            binding.id,
            organization_id=customer_org_id,
            source="customer_verified",
        )


async def _notify_organization(
    ctx: CommandContext, organization_id: uuid.UUID, kind: str, payload: dict[str, str]
) -> None:
    memberships = await notify.active_memberships(
        ctx.session,
        organization_id,
        notify.PROVIDER_NOTIFY_ROLES + notify.CUSTOMER_NOTIFY_ROLES,
    )
    for membership in memberships:
        ctx.notify(
            membership.user_id,
            kind,
            payload,
            membership_id=membership.id,
            organization_id=organization_id,
        )


async def suspend_provider(
    actor: Actor, organization_public_id: str, reason: str, *, idem: Idempotency | None
) -> CommandResult:
    return await _change_provider_status(
        actor, organization_public_id, reason, target=ProviderProfileStatus.SUSPENDED, idem=idem
    )


async def reinstate_provider(
    actor: Actor, organization_public_id: str, reason: str, *, idem: Idempotency | None
) -> CommandResult:
    return await _change_provider_status(
        actor, organization_public_id, reason, target=ProviderProfileStatus.ACTIVE, idem=idem
    )


async def _change_provider_status(
    actor: Actor,
    organization_public_id: str,
    reason: str,
    *,
    target: ProviderProfileStatus,
    idem: Idempotency | None,
) -> CommandResult:
    policy.require_operator_or_system(actor)
    organization_id = ids.decode("organization", organization_public_id)
    checked_reason = policy.require_reason(reason)

    suspending = target == ProviderProfileStatus.SUSPENDED
    action = "provider_profile.suspend" if suspending else "provider_profile.reinstate"

    async def handler(ctx: CommandContext) -> CommandResult:
        from app.modules.providers import api as providers

        result = await providers.set_profile_status(
            ctx, organization_id, target.value, checked_reason
        )
        if suspending:
            await _notify_active_customers(ctx, organization_id)
            from app.modules.requests import api as requests_api

            await requests_api.release_suspended_provider(ctx, organization_id)
        ctx.audit(
            action,
            "provider_profile",
            None,
            organization_id=organization_id,
            reason=checked_reason,
        )
        return CommandResult(result)

    return await run_command(actor, handler, idempotency=idem)


async def _notify_active_customers(ctx: CommandContext, provider_org_id: uuid.UUID) -> None:
    """D28: заказчики с активными работами узнают о потере статуса исполнителем."""
    rows = list(
        (
            await ctx.session.execute(
                select(RepairRequest.id, RepairRequest.customer_org_id)
                .join(Assignment, Assignment.request_id == RepairRequest.id)
                .where(
                    Assignment.provider_org_id == provider_org_id,
                    Assignment.state.in_(
                        [AssignmentState.PENDING.value, AssignmentState.ACCEPTED.value]
                    ),
                )
            )
        ).all()
    )
    for request_id, customer_org_id in rows:
        for membership in await notify.customer_recipients(ctx.session, customer_org_id):
            ctx.notify(
                membership.user_id,
                "provider.suspended",
                {"request_id": ids.encode("request", request_id)},
                membership_id=membership.id,
                organization_id=customer_org_id,
                request_id=request_id,
            )


_REOPENABLE_CHECKS = (CHECK_REQUISITES, CHECK_REPRESENTATIVE)


async def reopen_verification(
    actor: Actor,
    organization_public_id: str,
    check_kind: str,
    reason: str,
    *,
    compromise: bool = False,
    idem: Idempotency | None,
) -> CommandResult:
    """ТЗ 6.5.3: смена реквизитов, владельца или представителя проверенного исполнителя.

    Оператор открывает повторную проверку тем же механизмом, что и истечение срока:
    дело снова в очереди, профиль уходит в `needs_information` — реквизиты
    становятся доступны для правки, новые заявки закрыты до решения. При
    компрометации (`compromise`) отзываются ключи интеграции и сессии сотрудников."""
    policy.require_operator_or_system(actor)
    organization_id = ids.decode("organization", organization_public_id)
    checked_reason = policy.require_reason(reason)
    if check_kind not in _REOPENABLE_CHECKS:
        raise ValidationFailed("Неизвестный вид проверки", field="check_kind")

    async def handler(ctx: CommandContext) -> CommandResult:
        from app.modules.providers import api as providers

        org = await lock_by_id(ctx.session, Organization, organization_id)
        profile = (
            await ctx.session.execute(
                select(ProviderProfile).where(ProviderProfile.organization_id == org.id)
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound()
        if profile.status != ProviderProfileStatus.ACTIVE:
            raise InvalidTransition(
                "Повторная проверка открывается для допущенного профиля",
                code="PROFILE_NOT_ACTIVE",
                status=profile.status,
            )
        cases = await open_verification_cases(ctx, org.id, None, (check_kind,))
        if check_kind == CHECK_REQUISITES:
            org.details_verified_at = None
        else:
            org.representative_verified_at = None
        await providers.apply_verification_expiry(ctx, org.id, reason=checked_reason)
        revoked = await _revoke_access(ctx, org.id) if compromise else {}
        ctx.audit(
            "provider_profile.reopen_verification",
            "organization",
            org.id,
            organization_id=org.id,
            check_kind=check_kind,
            reason=checked_reason,
            compromise=compromise,
            **revoked,
        )
        await _notify_organization(ctx, org.id, "verification.reopened", {"check_kind": check_kind})
        items = [to_verification_case_view(case).model_dump(mode="json") for case in cases]
        return CommandResult({"items": items})

    return await run_command(actor, handler, idempotency=idem)


async def _revoke_access(ctx: CommandContext, organization_id: uuid.UUID) -> dict[str, int]:
    """Компрометация: ключи CRM и подписки отключаются, сессии сотрудников закрываются."""
    clients = list(
        (
            await ctx.session.execute(
                update(IntegrationClient)
                .where(
                    IntegrationClient.provider_org_id == organization_id,
                    IntegrationClient.status == IntegrationClientStatus.ACTIVE.value,
                )
                .values(status=IntegrationClientStatus.REVOKED.value, revoked_at=ctx.now)
                .returning(IntegrationClient.id)
            )
        ).scalars()
    )
    if clients:
        await ctx.session.execute(
            update(WebhookSubscription)
            .where(
                WebhookSubscription.integration_client_id.in_(clients),
                WebhookSubscription.status == WebhookSubscriptionStatus.ACTIVE.value,
            )
            .values(status=WebhookSubscriptionStatus.DISABLED.value, disabled_at=ctx.now)
        )
    members = select(Membership.user_id).where(Membership.organization_id == organization_id)
    sessions = list(
        (
            await ctx.session.execute(
                update(Session)
                .where(Session.user_id.in_(members), Session.revoked_at.is_(None))
                .values(revoked_at=ctx.now)
                .returning(Session.id)
            )
        ).scalars()
    )
    return {"revoked_api_keys": len(clients), "revoked_sessions": len(sessions)}


EXPIRED_REASON = "Срок действия проверки истёк"
EXPIRY_BATCH = 100
_EXPIRY_CASES = "verification_case"
_EXPIRY_WARRANTY = "warranty_authorization"
_expiry_quarantine = Quarantine(base=timedelta(minutes=1), maximum=timedelta(hours=1))


async def expire_verifications(now: datetime) -> int:
    """Цикл worker: снимает истёкшие проверки (`verification_cases.expires_at`).

    Признак перестаёт отображаться как действующий сразу по истечении срока —
    это делают представления (`queries.active_checks`); здесь состояние
    доводится до базы: дело закрывается как `revoked`, организация снова в
    очереди проверки, профиль исполнителя без действующих реквизитов или
    представителя уходит в `needs_information` (ТЗ 6.5.1 п.6), рейтинг
    пересчитывается, гарантийные полномочия с этим источником истекают.
    """
    held_cases = _expiry_quarantine.held(_EXPIRY_CASES, now)
    held_warranty = _expiry_quarantine.held(_EXPIRY_WARRANTY, now)
    due_cases = await _due_ids(
        select(VerificationCase.id)
        .where(
            VerificationCase.decision == VerificationDecision.APPROVED,
            VerificationCase.expires_at <= now,
        )
        .order_by(VerificationCase.expires_at, VerificationCase.id),
        VerificationCase.id,
        held_cases,
    )
    due_warranty = await _due_ids(
        select(WarrantyAuthorization.id)
        .where(
            WarrantyAuthorization.status == WarrantyAuthorizationStatus.ACTIVE,
            WarrantyAuthorization.valid_until < now.date(),
        )
        .order_by(WarrantyAuthorization.valid_until, WarrantyAuthorization.id),
        WarrantyAuthorization.id,
        held_warranty,
    )
    total = 0
    for kind, item_ids, apply in (
        (_EXPIRY_CASES, due_cases, _expire_case_by_id),
        (_EXPIRY_WARRANTY, due_warranty, _expire_warranty_by_id),
    ):
        for item_id in item_ids:
            try:
                done = await apply(item_id)
            except Exception:
                log.exception("verification_expiry_failed", kind=kind, item_id=str(item_id))
                _expiry_quarantine.hold(kind, item_id, now)
                continue
            _expiry_quarantine.release(kind, item_id)
            total += done
    return total


async def _due_ids(
    stmt: Select[tuple[uuid.UUID]],
    column: InstrumentedAttribute[uuid.UUID],
    held: set[uuid.UUID],
) -> list[uuid.UUID]:
    if held:
        stmt = stmt.where(column.not_in(tuple(held)))
    async with db_session.transaction() as session:
        return list((await session.execute(stmt.limit(EXPIRY_BATCH))).scalars())


async def _expire_case_by_id(case_id: uuid.UUID) -> int:
    async def handler(ctx: CommandContext) -> CommandResult:
        case = (
            await ctx.session.execute(
                select(VerificationCase)
                .where(
                    VerificationCase.id == case_id,
                    VerificationCase.decision == VerificationDecision.APPROVED,
                    VerificationCase.expires_at <= ctx.now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if case is None:
            return CommandResult({"expired": 0})
        await _expire_case(ctx, case)
        return CommandResult({"expired": 1})

    result = await run_command(SystemActor("verification_expiry"), handler)
    return int(result.body["expired"])


async def _expire_warranty_by_id(row_id: uuid.UUID) -> int:
    async def handler(ctx: CommandContext) -> CommandResult:
        row = (
            await ctx.session.execute(
                select(WarrantyAuthorization)
                .where(
                    WarrantyAuthorization.id == row_id,
                    WarrantyAuthorization.status == WarrantyAuthorizationStatus.ACTIVE,
                    WarrantyAuthorization.valid_until < ctx.now.date(),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return CommandResult({"expired": 0})
        _expire_warranty(ctx, row)
        return CommandResult({"expired": 1})

    result = await run_command(SystemActor("verification_expiry"), handler)
    return int(result.body["expired"])


def reset_expiry_quarantine() -> None:
    _expiry_quarantine.clear()


async def _expire_case(ctx: CommandContext, case: VerificationCase) -> None:
    case.decision = VerificationDecision.REVOKED.value
    case.decision_reason = EXPIRED_REASON
    ctx.audit(
        "verification.expire",
        "verification_case",
        case.id,
        organization_id=case.organization_id,
        check_kind=case.check_kind,
    )
    await _expire_warranty_authorizations(ctx, case)
    if case.check_kind not in _SUBJECT_BY_CHECK:
        return
    kinds = (
        _REPRESENTATIVE_CHECKS if case.check_kind in _REPRESENTATIVE_CHECKS else (case.check_kind,)
    )
    still_valid = (
        await ctx.session.execute(
            select(VerificationCase.id).where(
                VerificationCase.organization_id == case.organization_id,
                VerificationCase.check_kind.in_(kinds),
                VerificationCase.decision == VerificationDecision.APPROVED,
                VerificationCase.id != case.id,
                (VerificationCase.expires_at.is_(None)) | (VerificationCase.expires_at > ctx.now),
            )
        )
    ).first()
    if still_valid is not None:
        return
    org = await lock_by_id(ctx.session, Organization, case.organization_id)
    current = (
        org.details_verification_status
        if case.check_kind == CHECK_REQUISITES
        else org.representative_verification_status
    )
    if current != VerificationStatus.VERIFIED:
        return
    reopened = await open_verification_cases(ctx, org.id, case.membership_id, (case.check_kind,))
    for new_case in reopened:
        new_case.supersedes_case_id = case.id
    if case.check_kind == CHECK_REQUISITES:
        org.details_verified_at = None
    else:
        org.representative_verified_at = None
    if case.check_kind != CHECK_CUSTOMER_REPRESENTATIVE:
        from app.modules.providers import api as providers

        await providers.apply_verification_expiry(ctx, org.id, reason=EXPIRED_REASON)
    if case.check_kind != CHECK_REQUISITES:
        await _recalculate_customer_ratings(ctx, org)
    await _notify_organization(ctx, org.id, "verification.expired", {"check_kind": case.check_kind})


async def _expire_warranty_authorizations(ctx: CommandContext, case: VerificationCase) -> None:
    rows = (
        await ctx.session.execute(
            select(WarrantyAuthorization)
            .where(
                WarrantyAuthorization.source_verification_case_id == case.id,
                WarrantyAuthorization.status == WarrantyAuthorizationStatus.ACTIVE,
            )
            .with_for_update()
        )
    ).scalars()
    for row in rows:
        _expire_warranty(ctx, row)


def _expire_warranty(ctx: CommandContext, row: WarrantyAuthorization) -> None:
    row.status = WarrantyAuthorizationStatus.EXPIRED.value
    ctx.audit(
        "warranty_authorization.expire",
        "warranty_authorization",
        row.id,
        organization_id=row.authorized_provider_org_id,
    )
