import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import Actor, IntegrationActor, UserActor
from app.core.errors import Forbidden, NotFound
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.core.scope import AccessScope, scope_of
from app.core.unset import UNSET, UnsetType
from app.db import session as db_session
from app.db.enums import AssignmentState, PublicCardStatus, RequestRoute, RequestStatus, Urgency
from app.db.models import Assignment, Message, Organization, RepairRequest, RequestPublicCard
from app.modules.files import api as files
from app.modules.providers import api as providers
from app.modules.reputation import api as reputation
from app.modules.requests import (
    cancellation,
    commands,
    completion,
    details,
    policy,
    queries,
    search,
    support,
    views,
)
from app.modules.requests.commands import RepairQuoteInput, RepairQuoteItemInput, VisitProposalInput
from app.modules.requests.search import OfferInput, PublicCardInput
from app.modules.requests.sweeper import expire_due, expire_request
from app.modules.requests.transitions import RequestCommand
from app.modules.requests.views import (
    MarketplaceCardView,
    MessagesReadView,
    MessageView,
    OfferView,
    PendingApprovalItemView,
    PendingApprovalObjectView,
    PendingApprovalRequestView,
    PendingDecisionView,
    PublicCardPreviewView,
    RequestCustomerView,
    RequestEventView,
    RequestFormerProviderView,
    RequestListItemView,
    RequestProviderView,
    RequestPublicCardView,
    VisitProposalView,
)

__all__ = [
    "MarketplaceCardView",
    "MessageView",
    "MessagesReadView",
    "OfferInput",
    "OfferView",
    "PendingApprovalItemView",
    "PendingApprovalObjectView",
    "PendingApprovalRequestView",
    "PendingDecisionView",
    "PublicCardInput",
    "PublicCardPreviewView",
    "RepairQuoteInput",
    "RepairQuoteItemInput",
    "RequestCommand",
    "RequestCustomerView",
    "RequestEventView",
    "RequestFormerProviderView",
    "RequestListItemView",
    "RequestProviderView",
    "RequestPublicCardView",
    "SupervisedAssignmentView",
    "VisitProposalInput",
    "VisitProposalView",
    "accept_assignment",
    "approve_repair_quote",
    "approve_visit_proposal",
    "cancel_draft",
    "confirm_completion",
    "create_draft",
    "create_followup_request",
    "create_repair_quote",
    "decline_assignment",
    "ensure_provider_not_suspended",
    "expire_due",
    "expire_request",
    "force_cancellation",
    "get_marketplace_card",
    "get_request",
    "list_dialog_messages",
    "list_marketplace_requests",
    "list_messages",
    "list_offers",
    "list_repair_quotes",
    "list_requests",
    "list_visit_proposals",
    "marketplace_card_visible",
    "pending_approvals",
    "post_dialog_message",
    "post_message",
    "preview_public_card",
    "propose_visit",
    "publish_search",
    "reject_completion",
    "reject_repair_quote",
    "reject_visit_proposal",
    "release_suspended_provider",
    "report_completion",
    "request_approval",
    "request_cancellation",
    "request_history",
    "respond_cancellation",
    "return_to_draft",
    "revoke_pending_assignment",
    "select_offer",
    "set_external_reference",
    "set_field_worker",
    "set_warranty_decision",
    "start_work",
    "submit_offer",
    "submit_to_own_service",
    "supervised_assignments",
    "update_draft",
    "update_request_details",
    "withdraw_assignment",
    "withdraw_cancellation",
    "withdraw_offer",
    "withdraw_offer_by_id",
]

ensure_provider_not_suspended = support.ensure_provider_not_suspended
release_suspended_provider = search.release_suspended_provider
supervised_assignments = search.supervised_assignments
SupervisedAssignmentView = search.SupervisedAssignmentView


async def create_draft(
    actor: Actor,
    *,
    equipment_id: uuid.UUID,
    route: str = RequestRoute.OWN_SERVICE,
    urgency: str = Urgency.NORMAL,
    symptom_description: str | None = None,
    error_code: str | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.create_draft(
            equipment_id=equipment_id,
            route=route,
            urgency=urgency,
            symptom_description=symptom_description,
            error_code=error_code,
        ),
        idempotency=idem,
    )


async def update_draft(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    equipment_id: uuid.UUID | UnsetType | None = UNSET,
    urgency: str | UnsetType | None = UNSET,
    symptom_description: str | UnsetType | None = UNSET,
    error_code: str | UnsetType | None = UNSET,
    photos_incomplete: bool | UnsetType | None = UNSET,
    photos_incomplete_reason: str | UnsetType | None = UNSET,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.update_draft(
            request_id,
            equipment_id=equipment_id,
            urgency=urgency,
            symptom_description=symptom_description,
            error_code=error_code,
            photos_incomplete=photos_incomplete,
            photos_incomplete_reason=photos_incomplete_reason,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def cancel_draft(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    reason: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.cancel_draft(request_id, reason=reason, expected_version=expected_version),
        idempotency=idem,
    )


async def request_approval(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.request_approval(request_id, comment=comment, expected_version=expected_version),
        idempotency=idem,
    )


async def return_to_draft(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    comment: str,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.return_to_draft(request_id, comment=comment, expected_version=expected_version),
        idempotency=idem,
    )


async def submit_to_own_service(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    photos_incomplete: bool = False,
    photos_incomplete_reason: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.submit_to_own_service(
            request_id,
            photos_incomplete=photos_incomplete,
            photos_incomplete_reason=photos_incomplete_reason,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def revoke_pending_assignment(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    reason: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        cancellation.revoke_pending_assignment(
            request_id,
            assignment_id=assignment_id,
            reason=reason,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def approve_visit_proposal(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    proposal_id: uuid.UUID,
    proposal_version: int,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        commands.respond_visit_proposal(
            request_id,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            approve=True,
            comment=comment,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def reject_visit_proposal(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    proposal_id: uuid.UUID,
    proposal_version: int,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        commands.respond_visit_proposal(
            request_id,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            approve=False,
            comment=comment,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def approve_repair_quote(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    quote_id: uuid.UUID,
    quote_version: int,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        commands.respond_repair_quote(
            request_id,
            quote_id=quote_id,
            quote_version=quote_version,
            approve=True,
            comment=comment,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def reject_repair_quote(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    quote_id: uuid.UUID,
    quote_version: int,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        commands.respond_repair_quote(
            request_id,
            quote_id=quote_id,
            quote_version=quote_version,
            approve=False,
            comment=comment,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def request_cancellation(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    target: str,
    reason: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        cancellation.request_cancellation(
            request_id, target=target, reason=reason, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def withdraw_cancellation(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    cancellation_id: uuid.UUID,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        cancellation.withdraw_cancellation(
            request_id, cancellation_id=cancellation_id, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def force_cancellation(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    cancellation_id: uuid.UUID,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        cancellation.force_cancellation(
            request_id, cancellation_id=cancellation_id, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def confirm_completion(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        completion.confirm_completion(request_id, expected_version=expected_version),
        idempotency=idem,
    )


async def reject_completion(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    reason: str,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        completion.reject_completion(request_id, reason=reason, expected_version=expected_version),
        idempotency=idem,
    )


async def update_request_details(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    symptom_description: str | UnsetType | None = UNSET,
    urgency: str | UnsetType | None = UNSET,
    district_id: uuid.UUID | UnsetType | None = UNSET,
    published_description: str | UnsetType | None = UNSET,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.update_request_details(
            request_id,
            symptom_description=symptom_description,
            urgency=urgency,
            district_id=district_id,
            published_description=published_description,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def accept_assignment(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        commands.accept_assignment(
            request_id, assignment_id=assignment_id, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def decline_assignment(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    reason: str,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        commands.decline_assignment(
            request_id,
            assignment_id=assignment_id,
            reason=reason,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def withdraw_assignment(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    reason: str,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.withdraw_assignment(
            request_id,
            assignment_id=assignment_id,
            reason=reason,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def propose_visit(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    data: VisitProposalInput,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.propose_visit(
            request_id,
            assignment_id=assignment_id,
            data=data,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def create_repair_quote(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    data: RepairQuoteInput,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.create_repair_quote(
            request_id,
            assignment_id=assignment_id,
            data=data,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def start_work(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.start_work(
            request_id, assignment_id=assignment_id, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def mark_en_route(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.mark_en_route(
            request_id, assignment_id=assignment_id, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def report_completion(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    outcome: str,
    summary: str,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        completion.report_completion(
            request_id,
            assignment_id=assignment_id,
            outcome=outcome,
            summary=summary,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def respond_cancellation(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    cancellation_id: uuid.UUID,
    decision: str,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        cancellation.respond_cancellation(
            request_id,
            assignment_id=assignment_id,
            cancellation_id=cancellation_id,
            decision=decision,
            comment=comment,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def set_warranty_decision(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    decision: str,
    comment: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.set_warranty_decision(
            request_id,
            assignment_id=assignment_id,
            decision=decision,
            comment=comment,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def set_field_worker(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    membership_id: uuid.UUID | None = None,
    display_name: str | None = None,
    contact_phone: str | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.set_field_worker(
            request_id,
            assignment_id=assignment_id,
            membership_id=membership_id,
            display_name=display_name,
            contact_phone=contact_phone,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def set_external_reference(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    external_id: str,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.set_external_reference(
            request_id, external_id=external_id, expected_version=expected_version
        ),
        idempotency=idem,
    )


async def publish_search(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    data: PublicCardInput | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        search.publish_search(
            request_id, data=data or PublicCardInput(), expected_version=expected_version
        ),
        idempotency=idem,
    )


async def submit_offer(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    data: OfferInput,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        search.submit_offer(request_id, data=data, expected_version=expected_version),
        idempotency=idem,
    )


async def withdraw_offer(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    offer_id: uuid.UUID,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        search.withdraw_offer(request_id, offer_id=offer_id, expected_version=expected_version),
        idempotency=idem,
    )


async def withdraw_offer_by_id(
    actor: Actor,
    offer_id: uuid.UUID,
    *,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        search.withdraw_offer_by_id(offer_id, expected_version=expected_version),
        idempotency=idem,
    )


async def select_offer(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    offer_id: uuid.UUID,
    offer_version: int | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    await expire_request(request_id)
    return await run_command(
        actor,
        search.select_offer(
            request_id,
            offer_id=offer_id,
            offer_version=offer_version,
            expected_version=expected_version,
        ),
        idempotency=idem,
    )


async def create_followup_request(
    actor: Actor,
    parent_request_id: uuid.UUID,
    *,
    urgency: str | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        search.followup_request(parent_request_id, urgency=urgency),
        idempotency=idem,
    )


async def post_message(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    body: str,
    assignment_id: uuid.UUID | None = None,
    thread_provider_org_id: uuid.UUID | None = None,
    expected_version: int | None = None,
    author_label: str | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor,
        commands.post_message(
            request_id,
            body=body,
            assignment_id=assignment_id,
            thread_provider_org_id=thread_provider_org_id,
            expected_version=expected_version,
            author_label=author_label,
        ),
        idempotency=idem,
    )


@asynccontextmanager
async def _read_session() -> AsyncIterator[AsyncSession]:
    async with db_session.get_sessionmaker()() as session:
        yield session


def _require_read_scope(actor: Actor) -> AccessScope:
    if isinstance(actor, IntegrationActor) and policy.REQUESTS_READ not in actor.scopes:
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=policy.REQUESTS_READ)
    return scope_of(actor)


async def get_request(
    actor: Actor, request_id: uuid.UUID
) -> RequestCustomerView | RequestProviderView | RequestFormerProviderView:
    scope = _require_read_scope(actor)
    async with _read_session() as session:
        if scope.side == "customer":
            row = await queries.customer_request(scope, session, request_id)
            if row is None:
                raise NotFound()
            pair = await queries.equipment_with_category(session, row.request.equipment_id)
            location = await queries.get_location(session, row.request.location_id)
            provider_display_name = None
            if row.assignment is not None:
                provider_org = await session.get(Organization, row.assignment.provider_org_id)
                provider_display_name = provider_org.display_name if provider_org else None
            attachments = await files.list_for_request_in(session, actor, row.request.id)
            return views.to_customer_view(
                row.request,
                equipment=pair[0] if pair else None,
                category=pair[1] if pair else None,
                location=location,
                assignment=row.assignment,
                field_worker_name=await support.assignment_worker_name(session, row.assignment),
                provider_display_name=provider_display_name,
                proposals=await queries.visit_proposals(session, row.request.id),
                quotes=await queries.repair_quotes(session, row.request.id),
                cancellation=await queries.last_cancellation(session, row.request.id),
                attachments=attachments,
                unread_messages_count=await support.unread_for(session, actor, row.request.id),
                approver_name=await support.approver_for(session, row.request),
                **await details.customer_card_extras(
                    session, row.request, row.assignment, attachments
                ),
            )

        request = await _provider_request(session, request_id)
        assignment = await queries.provider_assignment(session, request_id, scope.organization_id)
        found = policy.ensure_assignment_belongs(actor, request, assignment)
        if found.state not in policy.READABLE_ASSIGNMENT_STATES:
            return views.to_former_provider_view(request.id, found)
        attachments = await files.list_for_request_in(session, actor, request.id)
        disclose = policy.discloses_contacts(found)
        return views.to_provider_view(
            request,
            found,
            disclose=disclose,
            field_worker_name=await support.assignment_worker_name(session, found),
            proposals=await queries.visit_proposals(session, request.id, assignment_id=found.id),
            quotes=await queries.repair_quotes(session, request.id, assignment_id=found.id),
            cancellation=await queries.last_cancellation(
                session, request.id, assignment_id=found.id
            ),
            attachments=attachments,
            unread_messages_count=await support.unread_for(
                session, actor, request.id, channel=support.provider_channel(found)
            ),
            completion_report=await details.completion_report(session, request, found, attachments),
            customer_org_name=await details.disclosed_customer_name(
                session, request, disclose=disclose
            ),
        )


async def list_requests(
    actor: Actor,
    *,
    statuses: Sequence[str] | None = None,
    location_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    active: bool | None = None,
    assignment_states: Sequence[str] | None = None,
    updated_since: datetime | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> tuple[list[RequestListItemView], str | None]:
    scope = _require_read_scope(actor)
    async with _read_session() as session:
        if scope.side == "customer":
            page = await queries.customer_request_rows(
                scope,
                session,
                statuses=statuses,
                location_id=location_id,
                equipment_id=equipment_id,
                active=active,
                updated_since=updated_since,
                cursor=cursor,
                limit=limit,
            )
        else:
            page = await queries.provider_request_rows(
                scope,
                session,
                states=assignment_states,
                equipment_id=equipment_id,
                updated_since=updated_since,
                cursor=cursor,
                limit=limit,
            )
        decisions: dict[uuid.UUID, queries.PendingDecision] = {}
        if isinstance(actor, UserActor) and actor.is_manager:
            decisions = await queries.pending_decisions(
                session, [row.request for row in page.items]
            )
        customers: dict[uuid.UUID, str] = {}
        contracts: dict[uuid.UUID, str] = {}
        ratings: dict[uuid.UUID, int] = {}
        if scope.side == "provider":
            requests = [row.request for row in page.items]
            customers = await details.customer_names(
                session, {request.customer_org_id for request in requests}
            )
            contracts = await details.contract_numbers(session, scope.organization_id, requests)
        else:
            ratings = await queries.own_review_ratings(
                session, scope.organization_id, [row.request.id for row in page.items]
            )
        assignments = [row.assignment for row in page.items if row.assignment is not None]
        windows = await queries.approved_visit_windows(session, [a.id for a in assignments])
        worker_names = await queries.membership_names(
            session,
            {
                a.field_worker_membership_id
                for a in assignments
                if a.field_worker_membership_id is not None
            },
        )
        channels = [(row.request.id, _list_channel(scope.side, row)) for row in page.items]
        counters = await queries.message_counters(
            session,
            channels,
            membership_id=actor.membership_id if isinstance(actor, UserActor) else None,
        )
        items = []
        for row, (_, channel) in zip(page.items, channels, strict=True):
            decision = decisions.get(row.request.id)
            disclosed = scope.side == "customer" or (
                row.assignment is not None and policy.discloses_contacts(row.assignment)
            )
            counter = counters.get(
                (row.request.id, channel.assignment_id), queries.MessageCounters()
            )
            items.append(
                views.to_list_item(
                    row.request,
                    location_name=row.location_name if disclosed else None,
                    equipment_title=row.equipment_title,
                    assignment=row.assignment,
                    equipment_id=row.equipment_id,
                    equipment_category_name=row.equipment_category_name,
                    equipment_brand=row.equipment_brand,
                    equipment_model=row.equipment_model,
                    pending_decision=(
                        views.PendingDecisionView(
                            kind=cast(views.PendingDecisionKind, decision.kind),
                            amount_minor=decision.amount_minor,
                            currency=decision.currency,
                            respond_by=decision.respond_by,
                            offers_count=decision.offers_count,
                        )
                        if decision is not None
                        else None
                    ),
                    customer_org_name=(
                        customers.get(row.request.customer_org_id) if disclosed else None
                    ),
                    contract_number=contracts.get(row.request.id) if disclosed else None,
                    visit_proposal=(
                        windows.get(row.assignment.id) if row.assignment is not None else None
                    ),
                    timezone=row.timezone,
                    field_worker_name=_list_field_worker_name(
                        scope.side, row.assignment, worker_names
                    ),
                    unread_messages_count=(
                        counter.unread if isinstance(actor, UserActor) else None
                    ),
                    last_message_at=counter.last_message_at,
                    my_review_rating=ratings.get(row.request.id),
                )
            )
        return items, page.next_cursor


def _list_channel(side: str, row: queries.RequestRow) -> queries.MessageChannel:
    if side == "provider" and row.assignment is not None:
        return support.provider_channel(row.assignment)
    return queries.WHOLE_CHANNEL


def _list_field_worker_name(
    side: str, assignment: Assignment | None, names: dict[uuid.UUID, str]
) -> str | None:
    if assignment is None:
        return None
    if side == "customer" and assignment.state not in (
        AssignmentState.ACCEPTED,
        AssignmentState.COMPLETED,
    ):
        return None
    if assignment.field_worker_membership_id is not None:
        return names.get(assignment.field_worker_membership_id)
    return assignment.field_worker_display_name


async def request_history(
    actor: Actor, request_id: uuid.UUID, *, cursor: str | None = None, limit: int | None = None
) -> tuple[list[RequestEventView], str | None]:
    async with _read_session() as session:
        assignment = await _ensure_readable(actor, session, request_id)
        side = scope_of(actor).side
        visible = None
        disclosed = True
        if side != "customer":
            assert assignment is not None
            visible = await queries.provider_visible_events(session, request_id, assignment)
            disclosed = policy.discloses_contacts(assignment)
        page = await queries.event_page(
            session, request_id, cursor=cursor, limit=limit, visible=visible
        )
        names = await details.event_actor_names(
            session, page.items, side=side, other_side_disclosed=disclosed
        )
        return [
            views.to_event_view(e, side=side, actor_display_name=names.get(e.id))
            for e in page.items
        ], page.next_cursor


async def list_messages(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    cursor: str | None = None,
    limit: int | None = None,
    direction: queries.MessageDirection = "forward",
) -> tuple[list[MessageView], str | None]:
    scope = _require_read_scope(actor)
    async with _read_session() as session:
        channel = await _message_channel(session, scope, request_id)
        page = await queries.message_page(
            session,
            request_id,
            channel=channel,
            cursor=cursor,
            limit=limit,
            direction=direction,
        )
        return await _message_views(session, scope, request_id, page.items, channel), (
            page.next_cursor
        )


async def _message_views(
    session: AsyncSession,
    scope: AccessScope,
    request_id: uuid.UUID,
    messages: Sequence[Message],
    channel: queries.MessageChannel,
) -> list[MessageView]:
    return await support.message_views_for(
        session, scope.side, request_id, messages, assignment_id=channel.assignment_id
    )


async def _dialog_thread(
    session: AsyncSession, scope: AccessScope, request_id: uuid.UUID, offer_id: uuid.UUID | None
) -> uuid.UUID:
    if scope.side == "customer":
        if await queries.customer_request(scope, session, request_id) is None:
            raise NotFound()
        offer = await queries.get_offer(session, offer_id) if offer_id is not None else None
        if offer is None or offer.request_id != request_id:
            raise NotFound()
        return offer.provider_org_id
    await _message_channel(session, scope, request_id)
    return scope.organization_id


async def list_dialog_messages(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    offer_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    direction: queries.MessageDirection = "forward",
) -> tuple[list[MessageView], str | None]:
    scope = _require_read_scope(actor)
    async with _read_session() as session:
        thread_org_id = await _dialog_thread(session, scope, request_id, offer_id)
        page = await queries.message_page(
            session,
            request_id,
            channel=queries.MessageChannel(provider_org_id=thread_org_id),
            cursor=cursor,
            limit=limit,
            direction=direction,
        )
        return await support.message_views_for(session, scope.side, request_id, page.items), (
            page.next_cursor
        )


async def post_dialog_message(
    actor: Actor,
    request_id: uuid.UUID,
    *,
    body: str,
    offer_id: uuid.UUID | None = None,
    expected_version: int | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    scope = scope_of(actor)
    thread_org_id: uuid.UUID | None = None
    if scope.side == "customer":
        async with _read_session() as session:
            thread_org_id = await _dialog_thread(session, scope, request_id, offer_id)
    return await run_command(
        actor,
        commands.post_message(
            request_id,
            body=body,
            assignment_id=None,
            thread_provider_org_id=thread_org_id,
            expected_version=expected_version,
            dialog_only=True,
        ),
        idempotency=idem,
    )


async def _message_channel(
    session: AsyncSession, scope: AccessScope, request_id: uuid.UUID
) -> queries.MessageChannel:
    if scope.side == "customer":
        if await queries.customer_request(scope, session, request_id) is None:
            raise NotFound()
        return queries.WHOLE_CHANNEL
    provider_org_id = scope.organization_id
    request = await _provider_request(session, request_id)
    assignment = await queries.provider_assignment(session, request_id, provider_org_id)
    if assignment is not None and assignment.state in policy.READABLE_ASSIGNMENT_STATES:
        return support.provider_channel(assignment)
    card = await queries.get_public_card(session, request_id)
    allowed = card is not None and await search.provider_matches(
        session, provider_org_id, request, card
    )
    if not allowed and not await queries.offers(
        session, request_id, provider_org_id=provider_org_id
    ):
        raise NotFound()
    return queries.MessageChannel(provider_org_id=provider_org_id)


async def mark_messages_read(actor: Actor, request_id: uuid.UUID) -> CommandResult:
    if not isinstance(actor, UserActor):
        raise Forbidden("Отметка прочтения — для участника-пользователя")
    scope = scope_of(actor)

    async def handler(ctx: CommandContext) -> CommandResult:
        channel = await _message_channel(ctx.session, scope, request_id)
        last_id = await queries.last_visible_message_id(ctx.session, request_id, channel=channel)
        await queries.advance_message_read(
            ctx.session, request_id, actor.membership_id, last_id, ctx.now
        )
        unread = await queries.unread_messages_count(
            ctx.session,
            request_id,
            actor.membership_id,
            channel=channel,
        )
        view = views.MessagesReadView(
            request_id=ids.encode("request", request_id),
            last_read_message_id=ids.encode_opt("message", last_id),
            unread_messages_count=unread,
        )
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler)


async def list_visit_proposals(actor: Actor, request_id: uuid.UUID) -> list[dict[str, object]]:
    async with _read_session() as session:
        assignment = await _ensure_readable(actor, session, request_id)
        rows = await queries.visit_proposals(
            session, request_id, assignment_id=assignment.id if assignment else None
        )
        return [views.to_visit_proposal_view(row).model_dump(mode="json") for row in rows]


async def list_repair_quotes(actor: Actor, request_id: uuid.UUID) -> list[dict[str, object]]:
    async with _read_session() as session:
        assignment = await _ensure_readable(actor, session, request_id)
        rows = await queries.repair_quotes(
            session, request_id, assignment_id=assignment.id if assignment else None
        )
        return [views.to_repair_quote_view(row).model_dump(mode="json") for row in rows]


async def preview_public_card(
    actor: Actor, request_id: uuid.UUID, *, data: PublicCardInput | None = None
) -> PublicCardPreviewView:
    scope = _require_read_scope(actor)
    if scope.side != "customer":
        raise Forbidden("Предпросмотр публикации доступен стороне заказчика")
    async with _read_session() as session:
        row = await queries.customer_request(scope, session, request_id)
        if row is None:
            raise NotFound()
        return await search.build_preview(session, row.request, data or PublicCardInput())


async def list_marketplace_requests(
    actor: Actor, *, cursor: str | None = None, limit: int | None = None
) -> tuple[list[views.MarketplaceListItemView], str | None]:
    provider_org_id = _marketplace_reader(actor)
    size = queries.page_limit(limit)
    after = queries.decode_cursor("request", cursor)
    cards: list[views.RequestPublicCardView] = []
    last_id: uuid.UUID | None = None
    async with _read_session() as session:
        candidates = await queries.open_public_cards(session, after=after, limit=size * 5 + 1)
        stopped_early = False
        for request, card in candidates:
            if len(cards) >= size:
                stopped_early = True
                break
            last_id = request.id
            if not await search.provider_matches(session, provider_org_id, request, card):
                continue
            cards.append(
                views.to_public_card_view(
                    request,
                    card,
                    attachment_ids=await queries.published_attachment_ids(session, request.id),
                    **await queries.card_place_names(session, card),
                )
            )
        items = await _marketplace_items(session, cards, provider_org_id)
        has_more = stopped_early or len(candidates) > size * 5
    next_cursor = ids.encode("request", last_id) if has_more and last_id is not None else None
    return items, next_cursor


async def _marketplace_items(
    session: AsyncSession, cards: list[views.RequestPublicCardView], provider_org_id: uuid.UUID
) -> list[views.MarketplaceListItemView]:
    request_ids = [ids.decode("request", card.request_id) for card in cards]
    counts = await queries.active_offer_counts(session, request_ids)
    authors = await queries.last_thread_author_kinds(session, request_ids, provider_org_id)
    items = []
    for card, request_id in zip(cards, request_ids, strict=True):
        author = authors.get(request_id)
        items.append(
            views.MarketplaceListItemView(
                **card.model_dump(),
                offers_count=counts.get(request_id, 0),
                has_open_question=author in queries.PROVIDER_AUTHOR_KINDS,
                has_clarification=author == "customer_membership",
            )
        )
    return items


async def _open_marketplace_card(
    session: AsyncSession, provider_org_id: uuid.UUID, request_id: uuid.UUID
) -> tuple[RepairRequest, RequestPublicCard] | None:
    request = await session.get(RepairRequest, request_id)
    if request is None:
        return None
    card = await queries.get_public_card(session, request_id)
    if (
        card is None
        or card.status != PublicCardStatus.OPEN
        or request.status != RequestStatus.SEARCHING
        or not await search.provider_matches(session, provider_org_id, request, card)
    ):
        return None
    return request, card


async def marketplace_card_visible(
    session: AsyncSession, actor: Actor, request_id: uuid.UUID
) -> bool:
    try:
        provider_org_id = _marketplace_reader(actor)
    except Forbidden:
        return False
    return await _open_marketplace_card(session, provider_org_id, request_id) is not None


async def get_marketplace_card(actor: Actor, request_id: uuid.UUID) -> MarketplaceCardView:
    provider_org_id = _marketplace_reader(actor)
    async with _read_session() as session:
        found = await _open_marketplace_card(session, provider_org_id, request_id)
        if found is None:
            raise NotFound()
        request, card = found
        return MarketplaceCardView(
            card=views.to_public_card_view(
                request,
                card,
                attachment_ids=await queries.published_attachment_ids(session, request.id),
                **await queries.card_place_names(session, card),
            ),
            my_offers=[
                views.to_offer_view(offer)
                for offer in await queries.offers(
                    session, request_id, provider_org_id=provider_org_id
                )
            ],
        )


async def list_offers(actor: Actor, request_id: uuid.UUID) -> list[OfferView]:
    scope = _require_read_scope(actor)
    async with _read_session() as session:
        if scope.side == "customer":
            row = await queries.customer_request(scope, session, request_id)
            if row is None:
                raise NotFound()
            rows = await queries.offers(session, request_id)
            provider_org_ids = list({offer.provider_org_id for offer in rows})
            summaries = await providers.get_provider_summaries(session, provider_org_ids)
            ratings = await reputation.get_rating_summaries(session, provider_org_ids)
            return [
                views.to_offer_view(
                    offer, provider=_offer_provider_view(offer.provider_org_id, summaries, ratings)
                )
                for offer in rows
            ]
        request = await _provider_request(session, request_id)
        rows = await queries.offers(session, request_id, provider_org_id=scope.organization_id)
        if not rows:
            card = await queries.get_public_card(session, request_id)
            if card is None or not await search.provider_matches(
                session, scope.organization_id, request, card
            ):
                raise NotFound()
        return [views.to_offer_view(offer) for offer in rows]


def _offer_provider_view(
    provider_org_id: uuid.UUID,
    summaries: dict[uuid.UUID, providers.ProviderSummaryView],
    ratings: dict[uuid.UUID, reputation.RatingSummaryView],
) -> views.OfferProviderView | None:
    summary = summaries.get(provider_org_id)
    if summary is None:
        return None
    rating = ratings.get(provider_org_id)
    return views.OfferProviderView(
        id=summary.id,
        display_name=summary.display_name,
        verification_marks=summary.verification_marks,
        rating=rating.average if rating else None,
        rating_label=rating.label if rating else None,
        unique_reviewer_orgs_count=rating.unique_customers if rating else 0,
        reviews_count=rating.published_reviews_count if rating else 0,
    )


async def pending_approvals(actor: Actor) -> list[PendingApprovalItemView]:
    user = policy.require_customer(actor)
    scope = scope_of(user)
    async with _read_session() as session:
        rows = await queries.pending_approvals(scope, session, manager=user.is_manager)
        return [_to_pending_approval_view(row) for row in rows]


def _to_pending_approval_view(row: queries.PendingApprovalRow) -> PendingApprovalItemView:
    obj = None
    if row.object_id is not None and row.object_kind is not None:
        obj = PendingApprovalObjectView(
            id=ids.encode(row.object_kind, row.object_id), version=row.object_version
        )
    return PendingApprovalItemView(
        kind=cast(views.PendingApprovalKind, row.kind),
        request=PendingApprovalRequestView(
            id=ids.encode("request", row.request.id),
            request_number=row.request.request_number,
            status=row.request.status,
            version=row.request.version,
        ),
        object=obj,
        due_at=row.due_at,
        amount_minor=row.amount_minor,
        currency=row.currency,
        thread_provider_id=ids.encode_opt("organization", row.thread_provider_org_id),
    )


def _marketplace_reader(actor: Actor) -> uuid.UUID:
    if isinstance(actor, IntegrationActor) and policy.MARKETPLACE_READ not in actor.scopes:
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=policy.MARKETPLACE_READ)
    scope = scope_of(actor)
    if scope.side != "provider":
        raise Forbidden("Биржа доступна стороне исполнителя")
    return scope.organization_id


async def _provider_request(session: AsyncSession, request_id: uuid.UUID) -> RepairRequest:
    request = await session.get(RepairRequest, request_id)
    if request is None:
        raise NotFound()
    return request


async def _ensure_readable(
    actor: Actor, session: AsyncSession, request_id: uuid.UUID
) -> Assignment | None:
    scope = _require_read_scope(actor)
    if scope.side == "customer":
        row = await queries.customer_request(scope, session, request_id)
        if row is None:
            raise NotFound()
        return row.assignment
    request = await _provider_request(session, request_id)
    assignment = await queries.provider_assignment(session, request_id, scope.organization_id)
    return policy.ensure_provider_read(actor, request, assignment)
