import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import Actor, OperatorActor, UserActor
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.pipeline import CommandContext, CommandResult, Handler
from app.db import session as db_session
from app.db.enums import (
    AssignmentState,
    IntegrationEventType,
    OfferStatus,
    ProviderProfileStatus,
    PublicCardStatus,
    RequestRoute,
    RequestStatus,
    Urgency,
    VisitProposalStatus,
)
from app.db.models import (
    Assignment,
    Offer,
    Organization,
    ProviderProfile,
    RepairRequest,
    RequestPublicCard,
    ServiceBinding,
    VisitProposal,
)
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.requests import matching, policy, queries, recipients, support, views
from app.modules.requests.transitions import RequestCommand as C
from app.modules.requests.transitions import allowed_from, apply_transition


@dataclass(frozen=True, slots=True)
class OfferInput:
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


@dataclass(frozen=True, slots=True)
class PublicCardInput:
    published_description: str | None = None
    district_id: uuid.UUID | None = None
    attachment_ids: tuple[uuid.UUID, ...] = ()
    confirm_sensitive: bool = False


async def matching_providers(
    session: AsyncSession, request: RepairRequest, card: RequestPublicCard
) -> list[uuid.UUID]:
    found = await matching.find_matching_providers(
        session,
        category_id=card.equipment_category_id,
        city_id=card.city_id,
        district_id=card.district_id,
        brand=request.equipment_snapshot.get("brand"),
    )
    return [org_id for org_id in found if org_id != request.customer_org_id]


async def provider_matches(
    session: AsyncSession,
    provider_org_id: uuid.UUID,
    request: RepairRequest,
    card: RequestPublicCard,
) -> bool:
    return provider_org_id in set(await matching_providers(session, request, card))


@dataclass(frozen=True, slots=True)
class CardOrigin:
    category_id: uuid.UUID
    city_id: uuid.UUID
    district_id: uuid.UUID | None


async def card_origin(session: AsyncSession, request: RepairRequest) -> CardOrigin:
    equipment = request.equipment_snapshot
    location = request.location_snapshot
    if not (equipment and location):
        pair = await queries.equipment_with_category(session, request.equipment_id)
        current = await queries.get_location(session, request.location_id)
        if pair is None or current is None:
            raise NotFound()
        equipment = views.equipment_snapshot(pair[0], pair[1])
        location = views.location_snapshot(current)
    district = location.get("district_id")
    return CardOrigin(
        category_id=ids.decode("category", equipment["category_id"]),
        city_id=ids.decode("city", location["city_id"]),
        district_id=ids.decode("district", district) if district else None,
    )


async def build_card_row(
    session: AsyncSession,
    request: RepairRequest,
    data: PublicCardInput,
    *,
    persist: bool,
    now: datetime | None = None,
) -> RequestPublicCard:
    origin = await card_origin(session, request)
    existing = await queries.get_public_card(session, request.id)
    district_id = (
        data.district_id or (existing.district_id if existing else None) or origin.district_id
    )
    description = (
        data.published_description
        or (existing.published_description if existing else None)
        or request.symptom_description
    )
    if existing is None or not persist:
        card = RequestPublicCard(
            request_id=request.id,
            equipment_category_id=origin.category_id,
            city_id=origin.city_id,
            district_id=district_id,
            urgency=request.urgency,
            published_description=description,
            status=PublicCardStatus.OPEN,
        )
        if persist:
            session.add(card)
            await session.flush()
        return card
    existing.equipment_category_id = origin.category_id
    existing.city_id = origin.city_id
    existing.district_id = district_id
    existing.urgency = request.urgency
    existing.published_description = description
    existing.status = PublicCardStatus.OPEN
    existing.closed_at = None
    if now is not None:
        existing.published_at = now
    return existing


async def build_preview(
    session: AsyncSession, request: RepairRequest, data: PublicCardInput
) -> views.PublicCardPreviewView:
    card = await build_card_row(session, request, data, persist=False)
    card.published_at = request.created_at
    providers = await matching_providers(session, request, card)
    binding = await _existing_binding(session, request)
    return views.PublicCardPreviewView(
        public_card=views.to_public_card_view(
            request,
            card,
            attachment_ids=_encode_attachments(data.attachment_ids),
            **await queries.card_place_names(session, card),
        ),
        withheld_fields=list(views.WITHHELD_FROM_PUBLIC_CARD),
        matched_providers=len(providers),
        existing_binding=binding,
    )


async def _existing_binding(
    session: AsyncSession, request: RepairRequest
) -> views.ExistingBindingView | None:
    stmt = (
        select(ServiceBinding, Organization)
        .join(Organization, Organization.id == ServiceBinding.provider_org_id, isouter=True)
        .where(
            ServiceBinding.equipment_id == request.equipment_id,
            ServiceBinding.customer_org_id == request.customer_org_id,
            ServiceBinding.status.in_(("pending", "confirmed")),
        )
        .order_by(ServiceBinding.id.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    binding, organization = row[0], row[1]
    return views.ExistingBindingView(
        service_binding_id=ids.encode("service_binding", binding.id),
        provider_organization_id=ids.encode_opt("organization", binding.provider_org_id),
        provider_name=organization.display_name if organization is not None else None,
        status=binding.status,
    )


def _encode_attachments(values: Sequence[uuid.UUID]) -> list[str]:
    return [ids.encode("attachment", value) for value in values]


def publish_search(
    request_id: uuid.UUID, *, data: PublicCardInput, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.PUBLISH_SEARCH, expected_version
        )
        if await queries.active_assignment(ctx.session, request.id) is not None:
            raise Conflict(
                "По заявке уже есть активное назначение", code="ASSIGNMENT_ALREADY_ACTIVE"
            )
        await support.fix_snapshots(ctx, request)

        card = await build_card_row(ctx.session, request, data, persist=True, now=ctx.now)
        providers = await matching_providers(ctx.session, request, card)

        if not providers:
            await files.revoke_public_card_copies(ctx, request.id)
            card.published_attachment_ids = []
            card.status = PublicCardStatus.CLOSED
            card.closed_at = ctx.now
            request.search_expires_at = None
            apply_transition(
                ctx, request, C.PUBLISH_SEARCH, RequestStatus.ACTION_REQUIRED, matched_providers=0
            )
            await recipients.notify_customer(
                ctx, request, "search.no_providers", managers_only=True
            )
            support.audit(ctx, C.PUBLISH_SEARCH, request, matched_providers=0)
            return await support.customer_result(
                ctx,
                request,
                search=views.SearchStateView(published=False, matched_providers=0),
            )

        copies = await files.publish_to_public_card(
            ctx, request, data.attachment_ids, confirm_sensitive=data.confirm_sensitive
        )
        card.published_attachment_ids = list(copies)
        attachment_ids = _encode_attachments(copies)

        request.route = RequestRoute.MARKETPLACE
        request.search_expires_at = ctx.now + timedelta(
            seconds=get_settings().search_window_seconds
        )
        apply_transition(
            ctx,
            request,
            C.PUBLISH_SEARCH,
            RequestStatus.SEARCHING,
            matched_providers=len(providers),
            attachment_ids=attachment_ids,
        )

        card_view = views.to_public_card_view(
            request,
            card,
            attachment_ids=attachment_ids,
            **await queries.card_place_names(ctx.session, card),
        )
        payload = {"public_card": card_view.model_dump(mode="json")}
        for provider_org_id in providers:
            ctx.emit_integration_event(
                str(IntegrationEventType.MARKETPLACE_REQUEST_AVAILABLE),
                recipient_org_id=provider_org_id,
                resource_kind="request",
                resource_id=request.id,
                resource_version=request.version,
                payload=payload,
            )
            await recipients.notify_provider_org(
                ctx, request, provider_org_id, "marketplace.request.available"
            )
        support.audit(ctx, C.PUBLISH_SEARCH, request, matched_providers=len(providers))
        return await support.customer_result(
            ctx,
            request,
            search=views.SearchStateView(
                published=True,
                matched_providers=len(providers),
                search_expires_at=request.search_expires_at,
                public_card=card_view,
            ),
        )

    return handler


def submit_offer(
    request_id: uuid.UUID, *, data: OfferInput, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        policy.ensure_command_allowed(ctx.actor, C.SUBMIT_OFFER)
        provider_org_id = policy.provider_org_id(ctx.actor)
        request = await support.locked_request(ctx, request_id)
        card = await _open_card(ctx.session, request)
        if not await provider_matches(ctx.session, provider_org_id, request, card):
            raise NotFound()
        await support.ensure_provider_active(ctx.session, provider_org_id)
        support.check_request_version(request, expected_version)

        window_start, window_end = support.visit_window(
            ctx.now, data.visit_window_start, data.visit_window_end, required=False
        )
        settings = get_settings()
        price, valid_until = support.priced_terms(
            ctx.now,
            data,
            default_seconds=settings.offer_default_ttl_seconds,
            max_seconds=settings.offer_max_ttl_seconds,
        )
        version = await queries.next_offer_version(ctx.session, request.id, provider_org_id)
        previous = await queries.offers(
            ctx.session,
            request.id,
            provider_org_id=provider_org_id,
            states=(OfferStatus.ACTIVE,),
        )
        for row in previous:
            row.state = OfferStatus.CLOSED
        await ctx.session.flush()

        offer = Offer(
            request_id=request.id,
            provider_org_id=provider_org_id,
            version=version,
            visit_window_start=window_start,
            visit_window_end=window_end,
            visit_amount_minor=price.amount_minor,
            currency=price.currency,
            vat_mode=price.vat_mode,
            zero_cost_reason=price.zero_cost_reason,
            scope_description=support.terms_text(data.scope_description, "scope_description"),
            comment=support.terms_text(data.comment, "comment"),
            access_requirements=support.terms_text(data.access_requirements, "access_requirements"),
            valid_until=valid_until,
            state=OfferStatus.ACTIVE,
            created_by_membership_id=policy.acting_membership_id(ctx.actor),
        )
        ctx.session.add(offer)
        await support.flush_unique(ctx)
        for row in previous:
            row.superseded_by_offer_id = offer.id

        apply_transition(
            ctx,
            request,
            C.SUBMIT_OFFER,
            None,
            offer_id=ids.encode("offer", offer.id),
            offer_version=version,
        )
        await recipients.notify_customer(
            ctx,
            request,
            "offer.submitted",
            managers_only=True,
            payload={"offer_id": ids.encode("offer", offer.id), "offer_version": version},
        )
        support.audit(ctx, C.SUBMIT_OFFER, request, offer_version=version)
        return CommandResult(views.to_offer_view(offer).model_dump(mode="json"), status=201)

    return handler


def withdraw_offer(
    request_id: uuid.UUID, *, offer_id: uuid.UUID, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        policy.ensure_command_allowed(ctx.actor, C.WITHDRAW_OFFER)
        provider_org_id = policy.provider_org_id(ctx.actor)
        request = await support.locked_request(ctx, request_id)
        offer = await queries.get_offer(ctx.session, offer_id)
        if offer is None or offer.request_id != request.id:
            raise NotFound()
        if offer.provider_org_id != provider_org_id:
            raise NotFound()
        return await _withdraw_offer(ctx, request, offer, expected_version)

    return handler


def withdraw_offer_by_id(offer_id: uuid.UUID, *, expected_version: int | None) -> Handler:

    async def handler(ctx: CommandContext) -> CommandResult:
        policy.ensure_command_allowed(ctx.actor, C.WITHDRAW_OFFER)
        provider_org_id = policy.provider_org_id(ctx.actor)
        offer = await queries.get_offer(ctx.session, offer_id)
        if offer is None or offer.provider_org_id != provider_org_id:
            raise NotFound()
        request = await support.locked_request(ctx, offer.request_id)
        return await _withdraw_offer(ctx, request, offer, expected_version)

    return handler


async def _withdraw_offer(
    ctx: CommandContext, request: RepairRequest, offer: Offer, expected_version: int | None
) -> CommandResult:
    support.check_request_version(request, expected_version)
    if offer.state != OfferStatus.ACTIVE:
        raise Conflict("Предложение уже неактивно", code="OFFER_NOT_ACTIVE", state=offer.state)

    offer.state = OfferStatus.WITHDRAWN
    apply_transition(ctx, request, C.WITHDRAW_OFFER, None, offer_id=ids.encode("offer", offer.id))
    await recipients.notify_customer(
        ctx,
        request,
        "offer.withdrawn",
        managers_only=True,
        payload={"offer_id": ids.encode("offer", offer.id)},
    )
    support.audit(ctx, C.WITHDRAW_OFFER, request)
    return CommandResult(views.to_offer_view(offer).model_dump(mode="json"))


def select_offer(
    request_id: uuid.UUID,
    *,
    offer_id: uuid.UUID,
    offer_version: int | None,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.SELECT_OFFER, expected_version
        )
        offer = await queries.get_offer(ctx.session, offer_id)
        if offer is None or offer.request_id != request.id:
            raise NotFound()
        _ensure_selectable(offer, ctx.now, offer_version)
        if await queries.active_assignment(ctx.session, request.id) is not None:
            raise Conflict(
                "По заявке уже есть активное назначение", code="ASSIGNMENT_ALREADY_ACTIVE"
            )
        await support.ensure_provider_active(ctx.session, offer.provider_org_id)

        offer.state = OfferStatus.SELECTED
        assignment = Assignment(
            request_id=request.id,
            provider_org_id=offer.provider_org_id,
            route=RequestRoute.MARKETPLACE,
            offer_id=offer.id,
            state=AssignmentState.PENDING,
            expires_at=ctx.now + timedelta(seconds=_confirm_seconds(request.urgency)),
        )
        ctx.session.add(assignment)
        try:
            await ctx.session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "По заявке уже есть активное назначение", code="ASSIGNMENT_ALREADY_ACTIVE"
            ) from exc

        apply_transition(
            ctx,
            request,
            C.SELECT_OFFER,
            RequestStatus.AWAITING_ASSIGNMENT_CONFIRMATION,
            offer_id=ids.encode("offer", offer.id),
            assignment_id=ids.encode("assignment", assignment.id),
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.OFFER_SELECTED,
            request,
            assignment,
            extra={"offer": views.to_offer_view(offer).model_dump(mode="json")},
        )
        await recipients.notify_provider(ctx, request, assignment, "offer.selected")
        support.audit(ctx, C.SELECT_OFFER, request)
        return await support.customer_result(ctx, request, assignment=assignment)

    return handler


def _ensure_selectable(offer: Offer, now: datetime, version: int | None) -> None:
    if version is not None and offer.version != version:
        raise Conflict(
            "Условия предложения изменились, откройте актуальную версию",
            code="OFFER_NOT_CURRENT",
            offer_version=offer.version,
        )
    if offer.state == OfferStatus.EXPIRED or (
        offer.state == OfferStatus.ACTIVE and offer.valid_until <= now
    ):
        raise Conflict("Срок предложения истёк", code="OFFER_EXPIRED")
    if offer.superseded_by_offer_id is not None:
        raise Conflict("Исполнитель обновил предложение", code="OFFER_NOT_CURRENT")
    if offer.state != OfferStatus.ACTIVE:
        raise Conflict("Предложение недоступно для выбора", code="OFFER_NOT_ACTIVE")


def _confirm_seconds(urgency: str) -> int:
    settings = get_settings()
    if urgency == Urgency.CRITICAL:
        return settings.assignment_confirm_critical_seconds
    return settings.assignment_confirm_seconds


async def confirm_assignment(
    ctx: CommandContext, request: RepairRequest, assignment: Assignment
) -> CommandResult:
    if assignment.expires_at is not None and assignment.expires_at <= ctx.now:
        raise Conflict("Срок подтверждения назначения истёк", code="ASSIGNMENT_EXPIRED")
    await support.ensure_provider_active(ctx.session, assignment.provider_org_id)

    offer = (
        await queries.get_offer(ctx.session, assignment.offer_id)
        if assignment.offer_id is not None
        else None
    )
    assignment.state = AssignmentState.ACCEPTED
    assignment.responded_at = ctx.now

    agreed = offer is not None and _offer_is_complete(offer, ctx.now)
    proposal: VisitProposal | None = None
    if agreed and offer is not None:
        proposal = VisitProposal(
            request_id=request.id,
            assignment_id=assignment.id,
            version=1,
            visit_window_start=offer.visit_window_start,
            visit_window_end=offer.visit_window_end,
            visit_amount_minor=offer.visit_amount_minor,
            currency=offer.currency,
            vat_mode=offer.vat_mode,
            zero_cost_reason=offer.zero_cost_reason,
            scope_description=offer.scope_description,
            comment=offer.comment,
            access_requirements=offer.access_requirements,
            valid_until=offer.valid_until,
            status=VisitProposalStatus.APPROVED,
            responded_at=ctx.now,
            created_by_membership_id=offer.created_by_membership_id,
        )
        ctx.session.add(proposal)
        await ctx.session.flush()

    to_status = RequestStatus.SCHEDULED if agreed else RequestStatus.ACCEPTED
    apply_transition(
        ctx,
        request,
        C.CONFIRM_ASSIGNMENT,
        to_status,
        assignment_id=ids.encode("assignment", assignment.id),
        visit_agreed=agreed,
    )
    if offer is not None:
        offer.state = OfferStatus.CLOSED
    await close_search(
        ctx, request, reason="assignment_confirmed", keep_offer_id=assignment.offer_id
    )

    recipients.emit_provider_event(ctx, IntegrationEventType.REQUEST_ASSIGNED, request, assignment)
    await recipients.notify_customer(ctx, request, "request.accepted")
    await recipients.notify_provider(ctx, request, assignment, "assignment.confirmed")
    support.audit(ctx, C.CONFIRM_ASSIGNMENT, request, visit_agreed=agreed)
    return await support.provider_result(
        ctx, request, assignment, proposals=(proposal,) if proposal is not None else ()
    )


def _offer_is_complete(offer: Offer, now: datetime) -> bool:
    return (
        support.visit_window_problem(now, offer.visit_window_start, offer.visit_window_end) is None
        and offer.visit_amount_minor is not None
        and bool((offer.scope_description or "").strip())
    )


async def decline_reservation(
    ctx: CommandContext, request: RepairRequest, assignment: Assignment, reason: str
) -> CommandResult:
    assignment.state = AssignmentState.DECLINED
    assignment.decline_reason = reason
    assignment.responded_at = ctx.now
    await _release(ctx, request, assignment, command=C.DECLINE_ASSIGNMENT, reason=reason)
    recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="provider_declined")
    await recipients.notify_customer(
        ctx, request, "assignment.declined", managers_only=True, payload={"reason": reason}
    )
    support.audit(ctx, C.DECLINE_ASSIGNMENT, request)
    return await support.provider_result(ctx, request, assignment)


async def release_reservation(
    ctx: CommandContext, request: RepairRequest, assignment: Assignment, *, expired: bool
) -> None:
    assignment.state = AssignmentState.EXPIRED if expired else AssignmentState.DECLINED
    assignment.responded_at = ctx.now
    await _release(ctx, request, assignment, command=C.EXPIRE_ASSIGNMENT_CONFIRMATION)
    recipients.emit_assignment_revoked(ctx, request, assignment, reason_kind="expired")
    await recipients.notify_provider(ctx, request, assignment, "assignment.expired")
    await recipients.notify_customer(ctx, request, "assignment.expired", managers_only=True)


async def _release(
    ctx: CommandContext,
    request: RepairRequest,
    assignment: Assignment,
    *,
    command: C,
    reason: str | None = None,
) -> None:
    if assignment.offer_id is not None:
        offer = await queries.get_offer(ctx.session, assignment.offer_id)
        if offer is not None and offer.state == OfferStatus.SELECTED:
            offer.state = OfferStatus.CLOSED
    if await _search_can_continue(ctx, request):
        apply_transition(
            ctx,
            request,
            command,
            RequestStatus.SEARCHING,
            assignment_id=ids.encode("assignment", assignment.id),
            reason=reason,
        )
        return
    await close_search(ctx, request, reason="search_exhausted")
    apply_transition(
        ctx,
        request,
        command,
        RequestStatus.ACTION_REQUIRED,
        assignment_id=ids.encode("assignment", assignment.id),
        reason=reason,
    )


async def release_suspended_provider(ctx: CommandContext, provider_org_id: uuid.UUID) -> int:
    changed = 0
    offers = (
        await ctx.session.execute(
            select(Offer).where(
                Offer.provider_org_id == provider_org_id, Offer.state == OfferStatus.ACTIVE
            )
        )
    ).scalars()
    for offer in list(offers):
        request = await support.locked_request(ctx, offer.request_id)
        if offer.state != OfferStatus.ACTIVE:
            continue
        offer.state = OfferStatus.WITHDRAWN
        changed += 1
        if request.status in allowed_from(C.WITHDRAW_OFFER, None):
            apply_transition(
                ctx, request, C.WITHDRAW_OFFER, None, offer_id=ids.encode("offer", offer.id)
            )
            await recipients.notify_customer(
                ctx,
                request,
                "offer.withdrawn",
                managers_only=True,
                payload={"offer_id": ids.encode("offer", offer.id)},
            )
        await recipients.notify_provider_org(
            ctx, request, provider_org_id, "marketplace.request.closed"
        )

    pending = (
        await ctx.session.execute(
            select(Assignment).where(
                Assignment.provider_org_id == provider_org_id,
                Assignment.state == AssignmentState.PENDING,
            )
        )
    ).scalars()
    for assignment in list(pending):
        request = await support.locked_request(ctx, assignment.request_id)
        if assignment.state != AssignmentState.PENDING:
            continue
        assignment.state = AssignmentState.REVOKED
        assignment.revoke_reason = "provider_suspended"
        assignment.responded_at = ctx.now
        if request.status == RequestStatus.AWAITING_ASSIGNMENT_CONFIRMATION:
            await _release(
                ctx,
                request,
                assignment,
                command=C.EXPIRE_ASSIGNMENT_CONFIRMATION,
                reason="provider_suspended",
            )
        elif request.status == RequestStatus.AWAITING_PROVIDER:
            apply_transition(
                ctx,
                request,
                C.REVOKE_ASSIGNMENT,
                RequestStatus.ACTION_REQUIRED,
                assignment_id=ids.encode("assignment", assignment.id),
                reason="provider_suspended",
            )
        recipients.emit_assignment_revoked(
            ctx, request, assignment, reason_kind="provider_suspended"
        )
        await recipients.notify_provider(ctx, request, assignment, "assignment.revoked")
        changed += 1
    return changed


class SupervisedAssignmentView(BaseModel):
    request_id: str
    request_number: int
    status: str
    assignment_id: str
    provider_organization_id: str
    provider_status: str
    accepted_at: datetime | None = None


async def supervised_assignments(actor: Actor) -> list[SupervisedAssignmentView]:
    if not isinstance(actor, OperatorActor):
        raise Forbidden("Доступно оператору платформы")
    async with db_session.transaction() as session:
        rows = (
            await session.execute(
                select(Assignment, RepairRequest, ProviderProfile.status)
                .join(RepairRequest, RepairRequest.id == Assignment.request_id)
                .join(
                    ProviderProfile,
                    ProviderProfile.organization_id == Assignment.provider_org_id,
                )
                .where(
                    Assignment.state == AssignmentState.ACCEPTED,
                    ProviderProfile.status.in_(
                        (ProviderProfileStatus.SUSPENDED, ProviderProfileStatus.REJECTED)
                    ),
                )
                .order_by(RepairRequest.request_number)
            )
        ).all()
    return [
        SupervisedAssignmentView(
            request_id=ids.encode("request", request.id),
            request_number=request.request_number,
            status=request.status,
            assignment_id=ids.encode("assignment", assignment.id),
            provider_organization_id=ids.encode("organization", assignment.provider_org_id),
            provider_status=provider_status,
            accepted_at=assignment.responded_at,
        )
        for assignment, request, provider_status in rows
    ]


async def _search_can_continue(ctx: CommandContext, request: RepairRequest) -> bool:
    live = [
        offer
        for offer in await queries.active_offers(ctx.session, request.id)
        if offer.valid_until > ctx.now
    ]
    if live:
        return True
    return request.search_expires_at is not None and request.search_expires_at > ctx.now


async def close_search(
    ctx: CommandContext,
    request: RepairRequest,
    *,
    reason: str,
    keep_offer_id: uuid.UUID | None = None,
) -> None:
    card = await queries.get_public_card(ctx.session, request.id)
    if card is not None and card.status == PublicCardStatus.OPEN:
        await files.revoke_public_card_copies(ctx, request.id)
        card.status = PublicCardStatus.CLOSED
        card.closed_at = ctx.now
    request.search_expires_at = None

    losers = [
        offer
        for offer in await queries.offers(
            ctx.session, request.id, states=(OfferStatus.ACTIVE, OfferStatus.SELECTED)
        )
        if offer.id != keep_offer_id
    ]
    if not losers:
        return
    await ctx.session.execute(
        update(Offer)
        .where(
            Offer.request_id == request.id,
            Offer.id.in_([offer.id for offer in losers]),
        )
        .values(state=OfferStatus.CLOSED)
    )
    payload = {
        "request_id": ids.encode("request", request.id),
        "request_number": request.request_number,
        "reason": reason,
    }
    for offer in losers:
        ctx.emit_integration_event(
            str(IntegrationEventType.MARKETPLACE_REQUEST_CLOSED),
            recipient_org_id=offer.provider_org_id,
            resource_kind="request",
            resource_id=request.id,
            resource_version=request.version,
            payload=payload,
        )
        await recipients.notify_provider_org(
            ctx, request, offer.provider_org_id, "marketplace.request.closed"
        )


async def resolve_dialog_thread(
    ctx: CommandContext, request: RepairRequest, thread_provider_org_id: uuid.UUID | None
) -> uuid.UUID:
    card = await _open_card(ctx.session, request)
    if isinstance(ctx.actor, UserActor) and ctx.actor.side == "customer":
        policy.ensure_customer_request(ctx.actor, request)
        if thread_provider_org_id is None:
            raise ValidationFailed("Укажите, кому адресован ответ", field="thread_provider_org_id")
        if not await _has_dialog(ctx, request, thread_provider_org_id, card):
            raise NotFound()
        return thread_provider_org_id

    provider_org_id = policy.provider_org_id(ctx.actor)
    if not await provider_matches(ctx.session, provider_org_id, request, card):
        raise NotFound()
    return provider_org_id


async def _has_dialog(
    ctx: CommandContext,
    request: RepairRequest,
    provider_org_id: uuid.UUID,
    card: RequestPublicCard,
) -> bool:
    if await queries.offers(ctx.session, request.id, provider_org_id=provider_org_id):
        return True
    return await provider_matches(ctx.session, provider_org_id, request, card)


async def _open_card(session: AsyncSession, request: RepairRequest) -> RequestPublicCard:
    card = await queries.get_public_card(session, request.id)
    if (
        card is None
        or card.status != PublicCardStatus.OPEN
        or request.status != RequestStatus.SEARCHING
    ):
        raise NotFound()
    return card


def followup_request(parent_request_id: uuid.UUID, *, urgency: str | None) -> Handler:

    async def handler(ctx: CommandContext) -> CommandResult:
        policy.ensure_command_allowed(ctx.actor, C.CREATE_LINKED_REQUEST)
        parent = await support.locked_request(ctx, parent_request_id)
        user = policy.ensure_customer_request(ctx.actor, parent)
        if parent.status not in (RequestStatus.CLOSED, RequestStatus.CANCELLED):
            raise Conflict(
                "Связанную заявку можно создать только по завершённой",
                code="INVALID_TRANSITION",
                status=parent.status,
            )
        if urgency is not None:
            support.one_of(urgency, {str(value) for value in Urgency}, "urgency")

        request = RepairRequest(
            customer_org_id=parent.customer_org_id,
            location_id=parent.location_id,
            equipment_id=parent.equipment_id,
            author_membership_id=user.membership_id,
            route=parent.route,
            status=RequestStatus.DRAFT,
            version=1,
            urgency=urgency or parent.urgency,
            parent_request_id=parent.id,
            equipment_snapshot={},
            location_snapshot={},
        )
        ctx.session.add(request)
        await ctx.session.flush()
        apply_transition(
            ctx,
            request,
            C.CREATE_LINKED_REQUEST,
            RequestStatus.DRAFT,
            parent_request_id=ids.encode("request", parent.id),
        )
        support.audit(ctx, C.CREATE_LINKED_REQUEST, request)
        return await support.customer_result(ctx, request, status=201)

    return handler
