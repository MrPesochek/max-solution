import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, UserActor
from app.core.clock import utcnow
from app.core.errors import NotFound
from app.core.pipeline import CommandContext, CommandResult, run_command
from app.core.scope import AccessScope, scope_of
from app.db import session as db_session
from app.db.enums import (
    BindingStatus,
    InvitationKind,
    MembershipRole,
    VerificationDecision,
    VerificationStatus,
    WarrantyAuthorizationStatus,
)
from app.db.models import (
    Equipment,
    Invitation,
    Organization,
    ProviderProfile,
    ServiceBinding,
    ServiceContract,
    VerificationCase,
    WarrantyAuthorization,
)
from app.infra.crypto import hash_token
from app.modules.trust import policy
from app.modules.trust.views import (
    CHECK_CUSTOMER_REPRESENTATIVE,
    CHECK_REPRESENTATIVE,
    CHECK_REQUISITES,
    CHECK_WARRANTY_AUTHORIZATION,
    BindingInvitationPreviewView,
    BindingInvitationView,
    ProviderBindingView,
    ServiceBindingView,
    VerificationBadgeView,
    VerificationCaseOperatorView,
    VerificationCaseView,
    WarrantyAuthorizationView,
    badge,
    invitation_state,
    to_binding_invitation_preview,
    to_binding_invitation_view,
    to_binding_view,
    to_provider_binding_view,
    to_verification_case_operator_view,
    to_verification_case_view,
    to_warranty_view,
)

DEFAULT_LIMIT = 50


def _paginate[T](
    rows: list[T], limit: int, key: Callable[[T], uuid.UUID]
) -> tuple[list[T], uuid.UUID | None]:
    if len(rows) <= limit:
        return rows, None
    page = rows[:limit]
    return page, key(page[-1])


async def _latest_approved_cases(
    session: AsyncSession, organization_id: uuid.UUID
) -> dict[str, VerificationCase]:
    rows = list(
        (
            await session.execute(
                select(VerificationCase)
                .where(
                    VerificationCase.organization_id == organization_id,
                    VerificationCase.decision == VerificationDecision.APPROVED,
                )
                .order_by(VerificationCase.checked_at)
            )
        ).scalars()
    )
    return {case.check_kind: case for case in rows}


def _is_current(case: VerificationCase | None, now: datetime) -> bool:
    return case is None or case.expires_at is None or case.expires_at > now


def _confirmed_checks(
    org: Organization, latest: dict[str, VerificationCase], now: datetime
) -> set[str]:
    confirmed = set()
    if org.details_verification_status == VerificationStatus.VERIFIED and _is_current(
        latest.get(CHECK_REQUISITES), now
    ):
        confirmed.add(CHECK_REQUISITES)
    representative_cases = [
        case
        for case in (latest.get(CHECK_REPRESENTATIVE), latest.get(CHECK_CUSTOMER_REPRESENTATIVE))
        if case is not None
    ]
    if org.representative_verification_status == VerificationStatus.VERIFIED and (
        not representative_cases or any(_is_current(c, now) for c in representative_cases)
    ):
        confirmed.update((CHECK_REPRESENTATIVE, CHECK_CUSTOMER_REPRESENTATIVE))
    return confirmed


async def active_checks(
    session: AsyncSession, organization_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    if not organization_ids:
        return {}
    now = utcnow()
    orgs = (
        await session.execute(select(Organization).where(Organization.id.in_(organization_ids)))
    ).scalars()
    cases = (
        await session.execute(
            select(VerificationCase)
            .where(
                VerificationCase.organization_id.in_(organization_ids),
                VerificationCase.decision == VerificationDecision.APPROVED,
            )
            .order_by(VerificationCase.checked_at)
        )
    ).scalars()
    latest: dict[uuid.UUID, dict[str, VerificationCase]] = {}
    for case in cases:
        latest.setdefault(case.organization_id, {})[case.check_kind] = case
    return {org.id: _confirmed_checks(org, latest.get(org.id, {}), now) for org in orgs}


async def verification_badges(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[VerificationBadgeView]:
    org = await session.get(Organization, organization_id)
    if org is None:
        raise NotFound()
    latest = await _latest_approved_cases(session, organization_id)
    confirmed_checks = _confirmed_checks(org, latest, utcnow())
    result = []
    for kind in (CHECK_REQUISITES, CHECK_REPRESENTATIVE):
        confirmed = kind in confirmed_checks
        case = latest.get(kind)
        result.append(
            badge(
                kind,
                confirmed=confirmed,
                source=case.source if case else None,
                is_demo=case.is_demo if case else False,
                checked_at=case.checked_at if case else None,
                valid_until=case.expires_at if case else None,
            )
        )
    return result


async def warranty_badges(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> list[WarrantyAuthorizationView]:
    now = utcnow()
    rows = list(
        (
            await session.execute(
                select(WarrantyAuthorization, VerificationCase)
                .outerjoin(
                    VerificationCase,
                    VerificationCase.id == WarrantyAuthorization.source_verification_case_id,
                )
                .where(
                    WarrantyAuthorization.authorized_provider_org_id == provider_org_id,
                    WarrantyAuthorization.status == WarrantyAuthorizationStatus.ACTIVE,
                )
                .order_by(WarrantyAuthorization.id)
            )
        ).all()
    )
    return [
        to_warranty_view(
            row,
            source=case.source if case else None,
            is_demo=case.is_demo if case else False,
        )
        for row, case in rows
        if (row.valid_until is None or row.valid_until >= now.date()) and _is_current(case, now)
    ]


_VERIFICATION_ROLES = frozenset({"provider_admin", "customer_manager"})
_SIDE_CHECKS = {
    "provider": frozenset({CHECK_REQUISITES, CHECK_REPRESENTATIVE, CHECK_WARRANTY_AUTHORIZATION}),
    "customer": frozenset({CHECK_REQUISITES, CHECK_CUSTOMER_REPRESENTATIVE}),
}


async def list_verification_cases(actor: Actor | AccessScope) -> list[VerificationCaseView]:
    scope = actor if isinstance(actor, AccessScope) else scope_of(actor)
    full = isinstance(actor, UserActor) and actor.role in _VERIFICATION_ROLES
    async with db_session.transaction() as session:
        rows = list(
            (
                await session.execute(
                    select(VerificationCase)
                    .where(
                        VerificationCase.organization_id == scope.organization_id,
                        VerificationCase.check_kind.in_(tuple(_SIDE_CHECKS[scope.side])),
                    )
                    .order_by(VerificationCase.id)
                )
            ).scalars()
        )
        views = [to_verification_case_view(case) for case in rows]
        if full:
            return views
        return [
            view.model_copy(update={"evidence_note": None, "decision_reason": None, "source": None})
            for view in views
        ]


async def list_verification_queue(
    actor: Actor,
    *,
    decision: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
    organization_ids: tuple[uuid.UUID, ...] | None = None,
) -> tuple[list[VerificationCaseOperatorView], uuid.UUID | None]:
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        stmt = select(VerificationCase).order_by(VerificationCase.id).limit(limit + 1)
        if organization_ids is not None:
            stmt = stmt.where(VerificationCase.organization_id.in_(organization_ids))
        if decision is not None:
            stmt = stmt.where(VerificationCase.decision == decision)
        if cursor is not None:
            stmt = stmt.where(VerificationCase.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda case: case.id)
        return [await _operator_view(session, case) for case in page], next_cursor


async def get_verification_case(actor: Actor, case_id: uuid.UUID) -> VerificationCaseOperatorView:
    policy.require_operator(actor)

    async def handler(ctx: CommandContext) -> CommandResult:
        case = await ctx.session.get(VerificationCase, case_id)
        if case is None:
            raise NotFound()
        view = await _operator_view(ctx.session, case)
        ctx.audit(
            "verification_case.read",
            "verification_case",
            case.id,
            organization_id=case.organization_id,
        )
        return CommandResult(view.model_dump(mode="json"))

    result = await run_command(actor, handler)
    return VerificationCaseOperatorView.model_validate(result.body)


async def _operator_view(
    session: AsyncSession, case: VerificationCase
) -> VerificationCaseOperatorView:
    org = await session.get(Organization, case.organization_id)
    assert org is not None
    profile = (
        await session.execute(
            select(ProviderProfile).where(ProviderProfile.organization_id == org.id)
        )
    ).scalar_one_or_none()
    return to_verification_case_operator_view(case, org, profile.status if profile else None)


async def list_warranty_authorizations(
    actor: Actor,
    *,
    provider_org_id: uuid.UUID | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[WarrantyAuthorizationView], uuid.UUID | None]:
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        stmt = select(WarrantyAuthorization).order_by(WarrantyAuthorization.id).limit(limit + 1)
        if provider_org_id is not None:
            stmt = stmt.where(WarrantyAuthorization.authorized_provider_org_id == provider_org_id)
        if cursor is not None:
            stmt = stmt.where(WarrantyAuthorization.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda row: row.id)
        return [to_warranty_view(row) for row in page], next_cursor


async def _load_contracts(
    session: AsyncSession, bindings: list[ServiceBinding]
) -> dict[uuid.UUID, ServiceContract]:
    contract_ids = [b.contract_id for b in bindings if b.contract_id is not None]
    if not contract_ids:
        return {}
    return {
        row.id: row
        for row in (
            await session.execute(
                select(ServiceContract).where(ServiceContract.id.in_(contract_ids))
            )
        ).scalars()
    }


async def list_bindings(
    scope: AccessScope,
    *,
    equipment_id: uuid.UUID | None = None,
    status: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[ServiceBindingView | ProviderBindingView], uuid.UUID | None]:
    async with db_session.transaction() as session:
        stmt: Select[tuple[ServiceBinding]] = (
            select(ServiceBinding).order_by(ServiceBinding.id).limit(limit + 1)
        )
        if scope.side == "customer":
            stmt = stmt.where(ServiceBinding.customer_org_id == scope.organization_id)
            if scope.location_ids is not None:
                stmt = stmt.join(Equipment, Equipment.id == ServiceBinding.equipment_id).where(
                    Equipment.location_id.in_(scope.location_ids)
                )
        else:
            stmt = stmt.where(ServiceBinding.provider_org_id == scope.organization_id)
        if equipment_id is not None:
            stmt = stmt.where(ServiceBinding.equipment_id == equipment_id)
        if status is not None:
            stmt = stmt.where(ServiceBinding.status == status)
        if cursor is not None:
            stmt = stmt.where(ServiceBinding.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda b: b.id)
        views = [await _binding_view(session, scope, b) for b in page]
        return views, next_cursor


async def get_binding(
    scope: AccessScope, binding_id: uuid.UUID
) -> ServiceBindingView | ProviderBindingView:
    async with db_session.transaction() as session:
        binding = await _load_binding(session, scope, binding_id)
        return await _binding_view(session, scope, binding)


async def _load_binding(
    session: AsyncSession, scope: AccessScope, binding_id: uuid.UUID
) -> ServiceBinding:
    stmt = select(ServiceBinding).where(ServiceBinding.id == binding_id)
    if scope.side == "customer":
        stmt = stmt.where(ServiceBinding.customer_org_id == scope.organization_id)
    else:
        stmt = stmt.where(ServiceBinding.provider_org_id == scope.organization_id)
    binding = (await session.execute(stmt)).scalar_one_or_none()
    if binding is None:
        raise NotFound()
    if scope.side == "customer" and scope.location_ids is not None:
        equipment = await session.get(Equipment, binding.equipment_id)
        if equipment is None or equipment.location_id not in scope.location_ids:
            raise NotFound()
    return binding


async def _binding_view(
    session: AsyncSession, scope: AccessScope, binding: ServiceBinding
) -> ServiceBindingView | ProviderBindingView:
    contracts = await _load_contracts(session, [binding])
    contract = contracts.get(binding.contract_id) if binding.contract_id else None
    if scope.side == "customer":
        provider = (
            await session.get(Organization, binding.provider_org_id)
            if binding.provider_org_id
            else None
        )
        guarantor = (
            await session.get(Organization, binding.guarantor_org_id)
            if binding.guarantor_org_id
            else None
        )
        warranty = (
            await session.get(WarrantyAuthorization, binding.warranty_authorization_id)
            if binding.warranty_authorization_id
            else None
        )
        invitation = (
            await session.get(Invitation, binding.source_invitation_id)
            if binding.source_invitation_id
            else None
        )
        return to_binding_view(
            binding,
            provider=provider,
            contract=contract,
            warranty=warranty,
            guarantor=guarantor,
            invitation=invitation,
        )
    customer = await session.get(Organization, binding.customer_org_id)
    assert customer is not None
    equipment = await session.get(Equipment, binding.equipment_id)
    return to_provider_binding_view(
        binding,
        customer=customer,
        equipment=equipment,
        contract=contract,
    )


async def list_provider_equipment(
    scope: AccessScope, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[uuid.UUID], uuid.UUID | None]:
    async with db_session.transaction() as session:
        stmt = (
            select(ServiceBinding.equipment_id)
            .where(
                ServiceBinding.provider_org_id == scope.organization_id,
                ServiceBinding.status == BindingStatus.CONFIRMED,
            )
            .order_by(ServiceBinding.equipment_id)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(ServiceBinding.equipment_id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        return _paginate(rows, limit, lambda eid: eid)


async def list_binding_invitations(
    scope: AccessScope, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[BindingInvitationView], uuid.UUID | None]:
    now = utcnow()
    async with db_session.transaction() as session:
        stmt = (
            select(Invitation)
            .where(
                Invitation.organization_id == scope.organization_id,
                Invitation.kind == InvitationKind.SERVICE_BINDING,
            )
            .order_by(Invitation.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(Invitation.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda inv: inv.id)
        views = [to_binding_invitation_view(invitation, now) for invitation in page]
        return views, next_cursor


async def verified_customer_by_inn(session: AsyncSession, inn: str) -> Organization | None:
    return (
        await session.execute(
            select(Organization)
            .where(
                Organization.inn_normalized == inn,
                Organization.is_customer.is_(True),
                Organization.representative_verification_status == VerificationStatus.VERIFIED,
            )
            .order_by(Organization.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def intended_recipient(
    session: AsyncSession, invitation: Invitation, customer: Organization
) -> bool:
    if (
        invitation.target_organization_id is not None
        and invitation.target_organization_id != customer.id
    ):
        return False
    expected_inn = (invitation.binding_details or {}).get("customer_inn")
    if not isinstance(expected_inn, str) or expected_inn != customer.inn_normalized:
        return False
    if customer.representative_verification_status == VerificationStatus.VERIFIED:
        return True
    verified = await verified_customer_by_inn(session, expected_inn)
    return verified is None or verified.id == customer.id


async def preview_binding_invitation(
    token: str, actor: Actor | None = None
) -> BindingInvitationPreviewView:
    now = utcnow()
    async with db_session.transaction() as session:
        invitation = (
            await session.execute(
                select(Invitation).where(
                    Invitation.token_hash == hash_token(token),
                    Invitation.kind == InvitationKind.SERVICE_BINDING,
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFound()
        provider = await session.get(Organization, invitation.organization_id)
        assert provider is not None
        checks = await active_checks(session, [provider.id])
        disclose = False
        if (
            isinstance(actor, UserActor)
            and actor.role == MembershipRole.CUSTOMER_MANAGER
            and invitation_state(invitation, now) == "active"
        ):
            customer = await session.get(Organization, actor.organization_id)
            disclose = customer is not None and await intended_recipient(
                session, invitation, customer
            )
        return to_binding_invitation_preview(
            invitation,
            provider,
            now,
            provider_checks=checks.get(provider.id, set()),
            disclose=disclose,
        )


async def list_operator_bindings(
    actor: Actor,
    *,
    status: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[dict[str, Any]], uuid.UUID | None]:
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        stmt = select(ServiceBinding).order_by(ServiceBinding.id).limit(limit + 1)
        if status is not None:
            stmt = stmt.where(ServiceBinding.status == status)
        else:
            stmt = stmt.where(
                or_(
                    ServiceBinding.status == BindingStatus.PENDING,
                    ServiceBinding.status == BindingStatus.REJECTED,
                )
            )
        if cursor is not None:
            stmt = stmt.where(ServiceBinding.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda b: b.id)
        contracts = await _load_contracts(session, page)
        items = []
        for binding in page:
            customer = await session.get(Organization, binding.customer_org_id)
            provider = (
                await session.get(Organization, binding.provider_org_id)
                if binding.provider_org_id
                else None
            )
            contract = contracts.get(binding.contract_id) if binding.contract_id else None
            items.append(
                {
                    "id": binding.id,
                    "status": binding.status,
                    "basis": binding.basis,
                    "customer_org_id": binding.customer_org_id,
                    "customer_name": customer.display_name if customer else "",
                    "provider_org_id": binding.provider_org_id,
                    "provider_name": provider.display_name if provider else None,
                    "equipment_id": binding.equipment_id,
                    "contract_number": (
                        contract.contract_number if contract else binding.claimed_contract_number
                    ),
                    "status_reason": binding.status_reason,
                    "created_at": binding.created_at,
                }
            )
        return items, next_cursor
