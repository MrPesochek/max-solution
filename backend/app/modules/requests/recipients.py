import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import CUSTOMER_ROLES, PROVIDER_ROLES
from app.core.pipeline import CommandContext
from app.db.enums import IntegrationEventType, MembershipStatus
from app.db.models import Assignment, Membership, RepairRequest
from app.modules.requests import views
from app.modules.requests.policy import (
    CUSTOMER_MANAGER,
    PROVIDER_ADMIN,
    PROVIDER_DISPATCHER,
    discloses_contacts,
)

CHANGE_KINDS = frozenset(
    {
        "provider_declined",
        "visit_proposed",
        "visit_proposal_expired",
        "repair_quote_created",
        "repair_quote_expired",
        "en_route",
        "work_started",
        "completion_reported",
        "completion_rejected",
        "cancellation_disputed",
        "cancellation_withdrawn",
        "cancellation_forced",
        "warranty_decision",
        "field_worker",
        "external_reference",
    }
)
REASON_KINDS = frozenset(
    {
        "customer_revoked",
        "provider_withdrawn",
        "provider_declined",
        "expired",
        "provider_suspended",
        "cancellation",
    }
)


@dataclass(frozen=True, slots=True)
class Target:
    user_id: uuid.UUID
    membership_id: uuid.UUID


async def customer_targets(
    session: AsyncSession, request: RepairRequest, *, managers_only: bool = False
) -> list[Target]:
    stmt = select(Membership.id, Membership.user_id, Membership.role).where(
        Membership.organization_id == request.customer_org_id,
        Membership.status == MembershipStatus.ACTIVE,
        Membership.role.in_(CUSTOMER_ROLES),
    )
    targets: dict[uuid.UUID, Target] = {}
    for membership_id, user_id, role in (await session.execute(stmt)).all():
        is_author = membership_id == request.author_membership_id
        if role == CUSTOMER_MANAGER or (not managers_only and is_author):
            targets[membership_id] = Target(user_id, membership_id)
    return list(targets.values())


async def provider_org_targets(
    session: AsyncSession,
    provider_org_id: uuid.UUID,
    *,
    field_worker_membership_id: uuid.UUID | None = None,
) -> list[Target]:
    stmt = select(Membership.id, Membership.user_id, Membership.role).where(
        Membership.organization_id == provider_org_id,
        Membership.status == MembershipStatus.ACTIVE,
        Membership.role.in_(PROVIDER_ROLES),
    )
    targets: dict[uuid.UUID, Target] = {}
    for membership_id, user_id, role in (await session.execute(stmt)).all():
        if role in (PROVIDER_ADMIN, PROVIDER_DISPATCHER) or (
            membership_id == field_worker_membership_id
        ):
            targets[membership_id] = Target(user_id, membership_id)
    return list(targets.values())


async def provider_targets(session: AsyncSession, assignment: Assignment) -> list[Target]:
    return await provider_org_targets(
        session,
        assignment.provider_org_id,
        field_worker_membership_id=assignment.field_worker_membership_id,
    )


def notify_targets(
    ctx: CommandContext,
    targets: list[Target],
    *,
    request: RepairRequest,
    organization_id: uuid.UUID,
    notification_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    body = {"request_id": ids.encode("request", request.id), **(payload or {})}
    for target in targets:
        ctx.notify(
            target.user_id,
            notification_type,
            body,
            membership_id=target.membership_id,
            organization_id=organization_id,
            request_id=request.id,
        )


async def notify_customer(
    ctx: CommandContext,
    request: RepairRequest,
    notification_type: str,
    *,
    managers_only: bool = False,
    payload: dict[str, Any] | None = None,
) -> None:
    targets = await customer_targets(ctx.session, request, managers_only=managers_only)
    notify_targets(
        ctx,
        targets,
        request=request,
        organization_id=request.customer_org_id,
        notification_type=notification_type,
        payload=payload,
    )


async def notify_provider(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment,
    notification_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    targets = await provider_targets(ctx.session, assignment)
    notify_targets(
        ctx,
        targets,
        request=request,
        organization_id=assignment.provider_org_id,
        notification_type=notification_type,
        payload={"assignment_id": ids.encode("assignment", assignment.id), **(payload or {})},
    )


async def notify_provider_org(
    ctx: CommandContext,
    request: RepairRequest,
    provider_org_id: uuid.UUID,
    notification_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    targets = await provider_org_targets(ctx.session, provider_org_id)
    notify_targets(
        ctx,
        targets,
        request=request,
        organization_id=provider_org_id,
        notification_type=notification_type,
        payload=payload,
    )


def request_payload(
    request: RepairRequest,
    assignment: Assignment,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    view = views.to_provider_view(request, assignment, disclose=discloses_contacts(assignment))
    return {"request": view.model_dump(mode="json"), **(extra or {})}


def emit_provider_event(
    ctx: CommandContext,
    event_type: IntegrationEventType,
    request: RepairRequest,
    assignment: Assignment,
    *,
    change_kind: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if event_type == IntegrationEventType.REQUEST_CHANGED and change_kind is None:
        raise ValueError("request.changed требует change_kind")
    if change_kind is not None and change_kind not in CHANGE_KINDS:
        raise ValueError(f"неизвестный change_kind: {change_kind}")
    payload = request_payload(
        request, assignment, extra={"change_kind": change_kind, **(extra or {})}
    )
    if change_kind is None:
        payload.pop("change_kind", None)
    ctx.emit_integration_event(
        str(event_type),
        recipient_org_id=assignment.provider_org_id,
        resource_kind="request",
        resource_id=request.id,
        resource_version=request.version,
        payload=payload,
    )


def emit_assignment_revoked(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment,
    *,
    reason_kind: str,
) -> None:
    if reason_kind not in REASON_KINDS:
        raise ValueError(f"неизвестный reason_kind: {reason_kind}")
    view = views.to_former_provider_view(request.id, assignment)
    ctx.emit_integration_event(
        str(IntegrationEventType.ASSIGNMENT_REVOKED),
        recipient_org_id=assignment.provider_org_id,
        resource_kind="assignment",
        resource_id=assignment.id,
        resource_version=None,
        payload={"reason_kind": reason_kind, **view.model_dump(mode="json")},
    )
