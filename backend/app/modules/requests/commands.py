import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select, update

from app.core import ids
from app.core.actor import PROVIDER_ROLES, IntegrationActor, UserActor
from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.core.locking import check_version
from app.core.pipeline import CommandContext, CommandResult, Handler
from app.core.unset import UNSET, UnsetType
from app.db.enums import (
    AssignmentState,
    IntegrationEventType,
    MembershipStatus,
    RepairQuoteStatus,
    RequestRoute,
    RequestStatus,
    Urgency,
    VisitProposalStatus,
    WarrantyDecision,
)
from app.db.models import (
    Assignment,
    District,
    ExternalReference,
    Membership,
    Message,
    RepairQuote,
    RepairRequest,
    ServiceBinding,
    VisitProposal,
)
from app.infra.config import get_settings
from app.modules.requests import policy, queries, recipients, search, support, views
from app.modules.requests.transitions import RequestCommand as C
from app.modules.requests.transitions import apply_transition


@dataclass(frozen=True, slots=True)
class VisitProposalInput:
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
class RepairQuoteItemInput:
    title: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class RepairQuoteInput:
    description_of_work: str
    amount_minor: int | None = None
    currency: str | None = None
    vat_mode: str | None = None
    zero_cost_reason: str | None = None
    valid_until: datetime | None = None
    items: tuple[RepairQuoteItemInput, ...] | None = None
    warranty_terms: str | None = None


MAX_QUOTE_ITEMS = 50


def quote_items(data: RepairQuoteInput) -> tuple[list[dict[str, Any]] | None, int | None]:
    """Позиции сметы и итоговая сумма: без суммы она считается по позициям,
    а переданная сумма обязана с ними совпасть."""
    if not data.items:
        return None, data.amount_minor
    if len(data.items) > MAX_QUOTE_ITEMS:
        raise ValidationFailed(f"В смете не больше {MAX_QUOTE_ITEMS} позиций", field="items")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(data.items):
        title = support.required_text(item.title, "Укажите название позиции", f"items.{index}")
        if item.amount_minor < 0:
            raise ValidationFailed(
                "Стоимость позиции не может быть отрицательной", field=f"items.{index}"
            )
        items.append({"title": title, "amount_minor": item.amount_minor})
    total = sum(item["amount_minor"] for item in items)
    if data.amount_minor is not None and data.amount_minor != total:
        raise ValidationFailed(
            "Сумма сметы не совпадает с суммой позиций",
            code="QUOTE_ITEMS_SUM_MISMATCH",
            field="amount_minor",
            items_total_minor=total,
        )
    return items, total


def create_draft(
    *,
    equipment_id: uuid.UUID,
    route: str,
    urgency: str,
    symptom_description: str | None,
    error_code: str | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        policy.ensure_command_allowed(ctx.actor, C.CREATE_DRAFT)
        user = policy.require_customer(ctx.actor)
        support.one_of(route, {str(r) for r in RequestRoute}, "route")
        support.one_of(urgency, {str(u) for u in Urgency}, "urgency")

        pair = await queries.equipment_with_category(ctx.session, equipment_id)
        if pair is None or pair[0].customer_org_id != user.organization_id:
            raise NotFound()
        equipment = pair[0]
        policy.ensure_location_allowed(user, equipment.location_id)

        request = RepairRequest(
            customer_org_id=user.organization_id,
            location_id=equipment.location_id,
            equipment_id=equipment.id,
            author_membership_id=user.membership_id,
            route=route,
            status=RequestStatus.DRAFT,
            version=1,
            urgency=urgency,
            symptom_description=symptom_description,
            error_code=error_code,
            equipment_snapshot={},
            location_snapshot={},
        )
        ctx.session.add(request)
        await ctx.session.flush()

        apply_transition(ctx, request, C.CREATE_DRAFT, RequestStatus.DRAFT)
        support.audit(ctx, C.CREATE_DRAFT, request)
        return await support.customer_result(ctx, request, status=201)

    return handler


def update_draft(
    request_id: uuid.UUID,
    *,
    equipment_id: uuid.UUID | UnsetType | None,
    urgency: str | UnsetType | None,
    symptom_description: str | UnsetType | None,
    error_code: str | UnsetType | None,
    expected_version: int | None,
    photos_incomplete: bool | UnsetType | None = UNSET,
    photos_incomplete_reason: str | UnsetType | None = UNSET,
) -> Handler:
    if equipment_id is None:
        raise ValidationFailed("Оборудование обязательно", field="equipment_id")
    if urgency is None:
        raise ValidationFailed("Срочность обязательна", field="urgency")
    if photos_incomplete is None:
        raise ValidationFailed("Укажите, полные ли фото", field="photos_incomplete")

    async def handler(ctx: CommandContext) -> CommandResult:
        request, user = await support.customer_command(
            ctx, request_id, C.UPDATE_DRAFT, expected_version
        )
        policy.ensure_own_draft(user, request)

        if isinstance(equipment_id, uuid.UUID) and equipment_id != request.equipment_id:
            pair = await queries.equipment_with_category(ctx.session, equipment_id)
            if pair is None or pair[0].customer_org_id != request.customer_org_id:
                raise NotFound()
            policy.ensure_location_allowed(user, pair[0].location_id)
            request.equipment_id = pair[0].id
            request.location_id = pair[0].location_id
        if isinstance(urgency, str):
            request.urgency = support.one_of(urgency, {str(u) for u in Urgency}, "urgency")
        if not isinstance(symptom_description, UnsetType):
            request.symptom_description = symptom_description
        if not isinstance(error_code, UnsetType):
            request.error_code = error_code
        if isinstance(photos_incomplete, bool):
            request.photos_incomplete = photos_incomplete
        if not isinstance(photos_incomplete_reason, UnsetType):
            request.photos_incomplete_reason = (photos_incomplete_reason or "").strip() or None
        if not request.photos_incomplete:
            request.photos_incomplete_reason = None
        elif not request.photos_incomplete_reason:
            raise ValidationFailed(
                "Добавьте обязательные фото или укажите причину их отсутствия",
                field="photos_incomplete_reason",
            )

        apply_transition(ctx, request, C.UPDATE_DRAFT, None)
        support.audit(ctx, C.UPDATE_DRAFT, request)
        return await support.customer_result(ctx, request)

    return handler


def cancel_draft(
    request_id: uuid.UUID, *, reason: str | None, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, user = await support.customer_command(
            ctx, request_id, C.CANCEL_REQUEST, expected_version
        )
        if request.status not in (RequestStatus.DRAFT, RequestStatus.APPROVAL_REQUIRED):
            raise Conflict(
                "Заявка уже отправлена: используйте запрос отмены",
                code="INVALID_TRANSITION",
                status=request.status,
            )
        policy.ensure_own_draft(user, request)
        request.cancellation_reason = reason
        apply_transition(ctx, request, C.CANCEL_REQUEST, RequestStatus.CANCELLED, reason=reason)
        support.audit(ctx, C.CANCEL_REQUEST, request)
        return await support.customer_result(ctx, request)

    return handler


def request_approval(
    request_id: uuid.UUID, *, comment: str | None, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.SUBMIT_FOR_APPROVAL, expected_version
        )
        if request.route != RequestRoute.MARKETPLACE:
            raise Conflict(
                "Согласование руководителя нужно для внешней заявки",
                code="INVALID_ROUTE",
                route=request.route,
            )
        apply_transition(
            ctx, request, C.SUBMIT_FOR_APPROVAL, RequestStatus.APPROVAL_REQUIRED, comment=comment
        )
        await recipients.notify_customer(
            ctx, request, "request.approval_required", managers_only=True
        )
        support.audit(ctx, C.SUBMIT_FOR_APPROVAL, request)
        return await support.customer_result(ctx, request)

    return handler


def return_to_draft(
    request_id: uuid.UUID, *, comment: str, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        text = support.required_text(comment, "Укажите, что исправить", "comment")
        request, _ = await support.customer_command(
            ctx, request_id, C.RETURN_TO_DRAFT, expected_version
        )
        apply_transition(ctx, request, C.RETURN_TO_DRAFT, RequestStatus.DRAFT, comment=text)
        await recipients.notify_customer(ctx, request, "request.returned_to_draft")
        support.audit(ctx, C.RETURN_TO_DRAFT, request)
        return await support.customer_result(ctx, request)

    return handler


def submit_to_own_service(
    request_id: uuid.UUID,
    *,
    photos_incomplete: bool,
    photos_incomplete_reason: str | None,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        reason: str | None = None
        if photos_incomplete:
            reason = support.required_text(
                photos_incomplete_reason,
                "Укажите причину отсутствия фото",
                "photos_incomplete_reason",
            )
        request, _ = await support.customer_command(
            ctx, request_id, C.SUBMIT_TO_OWN_SERVICE, expected_version
        )
        if await queries.active_assignment(ctx.session, request.id) is not None:
            raise Conflict(
                "По заявке уже есть активное назначение", code="ASSIGNMENT_ALREADY_ACTIVE"
            )

        binding = await _confirmed_binding(ctx, request)
        provider_org_id = binding.provider_org_id
        assert provider_org_id is not None
        await support.ensure_provider_active(ctx.session, provider_org_id)

        await support.fix_snapshots(ctx, request)
        request.route = RequestRoute.OWN_SERVICE
        request.photos_incomplete = photos_incomplete
        request.photos_incomplete_reason = reason

        assignment = Assignment(
            request_id=request.id,
            provider_org_id=provider_org_id,
            route=RequestRoute.OWN_SERVICE,
            state=AssignmentState.PENDING,
            warranty_decision=WarrantyDecision.NOT_STATED,
        )
        ctx.session.add(assignment)
        await ctx.session.flush()

        apply_transition(
            ctx,
            request,
            C.SUBMIT_TO_OWN_SERVICE,
            RequestStatus.AWAITING_PROVIDER,
            assignment_id=ids.encode("assignment", assignment.id),
            service_binding_id=ids.encode("service_binding", binding.id),
            photos_incomplete=photos_incomplete,
            photos_incomplete_reason=reason,
        )

        recipients.emit_provider_event(
            ctx, IntegrationEventType.REQUEST_ASSIGNED, request, assignment
        )
        await recipients.notify_provider(ctx, request, assignment, "request.assigned")
        await recipients.notify_customer(ctx, request, "request.submitted")
        support.audit(ctx, C.SUBMIT_TO_OWN_SERVICE, request, provider_org_id=str(provider_org_id))
        return await support.customer_result(ctx, request, assignment=assignment)

    return handler


async def _confirmed_binding(ctx: CommandContext, request: RepairRequest) -> ServiceBinding:
    stmt = (
        select(ServiceBinding)
        .where(
            ServiceBinding.equipment_id == request.equipment_id,
            ServiceBinding.customer_org_id == request.customer_org_id,
            ServiceBinding.status == "confirmed",
            ServiceBinding.provider_org_id.is_not(None),
            ServiceBinding.provider_org_id != request.customer_org_id,
        )
        .order_by(ServiceBinding.id.desc())
        .limit(1)
    )
    binding = (await ctx.session.execute(stmt)).scalar_one_or_none()
    if binding is None:
        raise Conflict(
            "Для оборудования нет подтверждённой привязки своего сервиса",
            code="SERVICE_BINDING_REQUIRED",
        )
    return binding


def update_request_details(
    request_id: uuid.UUID,
    *,
    symptom_description: str | UnsetType | None,
    urgency: str | UnsetType | None,
    district_id: uuid.UUID | UnsetType | None,
    published_description: str | UnsetType | None,
    expected_version: int | None,
) -> Handler:
    """T56: руководитель уточняет условия заявки, которой нужно решение (S5).

    Снимок оборудования и точки отправленной заявки не переписывается (ТЗ 10.1):
    меняются описание, срочность и публичные поля будущей карточки, каждая
    правка остаётся в журнале событием `RequestDetailsUpdated`.
    """
    if urgency is None:
        raise ValidationFailed("Срочность обязательна", field="urgency")

    async def handler(ctx: CommandContext) -> CommandResult:
        request, _ = await support.customer_command(
            ctx, request_id, C.UPDATE_REQUEST_DETAILS, expected_version
        )
        changes: dict[str, object] = {}
        if isinstance(urgency, str) and urgency != request.urgency:
            request.urgency = support.one_of(urgency, {str(u) for u in Urgency}, "urgency")
            changes["urgency"] = urgency
        if (
            not isinstance(symptom_description, UnsetType)
            and symptom_description != request.symptom_description
        ):
            request.symptom_description = symptom_description
            changes["symptom_description"] = symptom_description

        public = not isinstance(district_id, UnsetType) or not isinstance(
            published_description, UnsetType
        )
        card = await queries.get_public_card(ctx.session, request.id) if public else None
        if public and card is None:
            raise ValidationFailed(
                "Публичные поля задаются при публикации поиска", field="district_id"
            )
        if card is not None:
            if not isinstance(district_id, UnsetType) and district_id != card.district_id:
                if district_id is not None:
                    await _ensure_district_in_city(ctx, district_id, card.city_id)
                card.district_id = district_id
                changes["district_id"] = ids.encode_opt("district", district_id)
            if (
                not isinstance(published_description, UnsetType)
                and published_description != card.published_description
            ):
                card.published_description = published_description
                changes["published_description"] = published_description
            card.urgency = request.urgency

        if not changes:
            raise ValidationFailed("Нет изменений", field="details")
        apply_transition(
            ctx,
            request,
            C.UPDATE_REQUEST_DETAILS,
            None,
            changed_fields=sorted(changes),
            changes=changes,
        )
        support.audit(ctx, C.UPDATE_REQUEST_DETAILS, request, changed_fields=sorted(changes))
        return await support.customer_result(ctx, request)

    return handler


async def _ensure_district_in_city(
    ctx: CommandContext, district_id: uuid.UUID, city_id: uuid.UUID
) -> None:
    district = await ctx.session.get(District, district_id)
    if district is None or district.city_id != city_id:
        raise ValidationFailed("Район не относится к городу точки", field="district_id")


def respond_visit_proposal(
    request_id: uuid.UUID,
    *,
    proposal_id: uuid.UUID,
    proposal_version: int,
    approve: bool,
    comment: str | None,
    expected_version: int | None,
) -> Handler:
    command = C.APPROVE_VISIT_PROPOSAL if approve else C.REJECT_VISIT_PROPOSAL

    async def handler(ctx: CommandContext) -> CommandResult:
        request, user = await support.customer_command(ctx, request_id, command, expected_version)
        proposal = await queries.get_visit_proposal(ctx.session, proposal_id)
        if proposal is None or proposal.request_id != request.id:
            raise NotFound()
        _ensure_current_proposal(proposal, proposal_version)
        support.ensure_proposal_not_due(proposal, ctx.now)

        if approve and proposal.visit_amount_minor is None:
            raise Conflict("Стоимость выезда не указана — согласовать нельзя", code="PRICE_UNKNOWN")
        if approve:
            problem = support.visit_window_problem(
                ctx.now, proposal.visit_window_start, proposal.visit_window_end
            )
            if problem == "VISIT_WINDOW_REQUIRED":
                raise Conflict("Окно выезда не указано — согласовать нельзя", code=problem)
            if problem is not None:
                raise Conflict("Окно выезда уже прошло — согласовать нельзя", code=problem)

        proposal.status = VisitProposalStatus.APPROVED if approve else VisitProposalStatus.REJECTED
        proposal.responded_at = ctx.now
        proposal.responded_by_membership_id = user.membership_id
        proposal.response_comment = comment

        to_status = (
            RequestStatus.SCHEDULED
            if approve and request.status == RequestStatus.ACCEPTED
            else None
        )
        apply_transition(
            ctx,
            request,
            command,
            to_status,
            visit_proposal_id=ids.encode("visit_proposal", proposal.id),
            proposal_version=proposal.version,
        )

        assignment = await queries.get_assignment(ctx.session, proposal.assignment_id)
        assert assignment is not None
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.VISIT_PROPOSAL_RESPONDED,
            request,
            assignment,
            extra={
                "visit_proposal": views.to_visit_proposal_view(proposal).model_dump(mode="json")
            },
        )
        await recipients.notify_provider(
            ctx,
            request,
            assignment,
            "visit_proposal.approved" if approve else "visit_proposal.rejected",
            payload={"visit_proposal_id": ids.encode("visit_proposal", proposal.id)},
        )
        support.audit(ctx, command, request, visit_proposal_version=proposal.version)
        return await support.customer_result(
            ctx, request, assignment=assignment, proposals=(proposal,)
        )

    return handler


def _ensure_current_proposal(proposal: VisitProposal, version: int) -> None:
    """A13/I23: старая кнопка не одобряет новую версию условий."""
    if proposal.version != version:
        raise Conflict(
            "Условия изменились, откройте актуальную версию",
            code="PROPOSAL_NOT_CURRENT",
            proposal_version=proposal.version,
        )
    if proposal.status == VisitProposalStatus.EXPIRED:
        raise Conflict("Срок предложения истёк", code="PROPOSAL_EXPIRED")
    if proposal.status == VisitProposalStatus.SUPERSEDED:
        raise Conflict(
            "Есть более новая версия условий",
            code="PROPOSAL_NOT_CURRENT",
            proposal_version=proposal.version,
        )
    if proposal.status != VisitProposalStatus.PENDING:
        raise Conflict("Ответ по этой версии уже дан", code="PROPOSAL_NOT_PENDING")


def _ensure_current_quote(quote: RepairQuote, version: int) -> None:
    if quote.version != version:
        raise Conflict(
            "Смета изменилась, откройте актуальную версию",
            code="QUOTE_NOT_CURRENT",
            quote_version=quote.version,
        )
    if quote.status == RepairQuoteStatus.EXPIRED:
        raise Conflict("Срок сметы истёк", code="QUOTE_EXPIRED")
    if quote.status == RepairQuoteStatus.SUPERSEDED:
        raise Conflict(
            "Есть более новая версия сметы", code="QUOTE_NOT_CURRENT", quote_version=quote.version
        )
    if quote.status != RepairQuoteStatus.PENDING:
        raise Conflict("Ответ по этой версии уже дан", code="QUOTE_NOT_PENDING")


def respond_repair_quote(
    request_id: uuid.UUID,
    *,
    quote_id: uuid.UUID,
    quote_version: int,
    approve: bool,
    comment: str | None,
    expected_version: int | None,
) -> Handler:
    command = C.APPROVE_REPAIR_QUOTE if approve else C.REJECT_REPAIR_QUOTE

    async def handler(ctx: CommandContext) -> CommandResult:
        request, user = await support.customer_command(ctx, request_id, command, expected_version)
        quote = await queries.get_repair_quote(ctx.session, quote_id)
        if quote is None or quote.request_id != request.id:
            raise NotFound()
        _ensure_current_quote(quote, quote_version)
        support.ensure_quote_not_due(quote, ctx.now)

        quote.status = RepairQuoteStatus.APPROVED if approve else RepairQuoteStatus.REJECTED
        quote.responded_at = ctx.now
        quote.responded_by_membership_id = user.membership_id
        quote.response_comment = comment

        apply_transition(
            ctx,
            request,
            command,
            None,
            repair_quote_id=ids.encode("repair_quote", quote.id),
            quote_version=quote.version,
        )

        assignment = await queries.get_assignment(ctx.session, quote.assignment_id)
        assert assignment is not None
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REPAIR_QUOTE_RESPONDED,
            request,
            assignment,
            extra={"repair_quote": views.to_repair_quote_view(quote).model_dump(mode="json")},
        )
        await recipients.notify_provider(
            ctx,
            request,
            assignment,
            "repair_quote.approved" if approve else "repair_quote.rejected",
            payload={"repair_quote_id": ids.encode("repair_quote", quote.id)},
        )
        support.audit(ctx, command, request, repair_quote_version=quote.version)
        return await support.customer_result(ctx, request, assignment=assignment, quotes=(quote,))

    return handler


def accept_assignment(
    request_id: uuid.UUID, *, assignment_id: uuid.UUID, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.ACCEPT_REQUEST, expected_version
        )
        if assignment.state != AssignmentState.PENDING:
            raise Conflict(
                "Назначение уже не ожидает ответа",
                code="ASSIGNMENT_NOT_ACTIVE",
                assignment_state=assignment.state,
            )
        if request.status == RequestStatus.AWAITING_ASSIGNMENT_CONFIRMATION:
            policy.ensure_command_allowed(ctx.actor, C.CONFIRM_ASSIGNMENT)
            return await search.confirm_assignment(ctx, request, assignment)

        await support.ensure_provider_active(ctx.session, assignment.provider_org_id)
        assignment.state = AssignmentState.ACCEPTED
        assignment.responded_at = ctx.now
        apply_transition(
            ctx,
            request,
            C.ACCEPT_REQUEST,
            RequestStatus.ACCEPTED,
            assignment_id=ids.encode("assignment", assignment.id),
        )
        await recipients.notify_customer(ctx, request, "request.accepted")
        support.audit(ctx, C.ACCEPT_REQUEST, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


def decline_assignment(
    request_id: uuid.UUID, *, assignment_id: uuid.UUID, reason: str, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        text = support.required_text(reason, "Укажите причину отказа", "reason")
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.DECLINE_REQUEST, expected_version
        )
        if assignment.state != AssignmentState.PENDING:
            raise Conflict(
                "Назначение уже не ожидает ответа",
                code="ASSIGNMENT_NOT_ACTIVE",
                assignment_state=assignment.state,
            )
        if request.status == RequestStatus.AWAITING_ASSIGNMENT_CONFIRMATION:
            policy.ensure_command_allowed(ctx.actor, C.DECLINE_ASSIGNMENT)
            return await search.decline_reservation(ctx, request, assignment, text)

        assignment.state = AssignmentState.DECLINED
        assignment.decline_reason = text
        assignment.responded_at = ctx.now

        apply_transition(
            ctx,
            request,
            C.DECLINE_REQUEST,
            RequestStatus.ACTION_REQUIRED,
            assignment_id=ids.encode("assignment", assignment.id),
            reason=text,
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="provider_declined",
            extra={"reason": text},
        )
        await recipients.notify_customer(
            ctx, request, "request.declined", managers_only=True, payload={"reason": text}
        )
        support.audit(ctx, C.DECLINE_REQUEST, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


def withdraw_assignment(
    request_id: uuid.UUID, *, assignment_id: uuid.UUID, reason: str, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        text = support.required_text(reason, "Укажите причину отказа от работы", "reason")
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.WITHDRAW_ASSIGNMENT, expected_version
        )
        if assignment.state != AssignmentState.ACCEPTED:
            raise Conflict(
                "Назначение не принято",
                code="ASSIGNMENT_NOT_ACTIVE",
                assignment_state=assignment.state,
            )
        assignment.state = AssignmentState.WITHDRAWN
        assignment.withdrawal_reason = text
        assignment.responded_at = ctx.now
        await support.supersede_children(ctx, request)

        apply_transition(
            ctx,
            request,
            C.WITHDRAW_ASSIGNMENT,
            RequestStatus.ACTION_REQUIRED,
            assignment_id=ids.encode("assignment", assignment.id),
            reason=text,
        )
        recipients.emit_assignment_revoked(
            ctx, request, assignment, reason_kind="provider_withdrawn"
        )
        await recipients.notify_customer(
            ctx, request, "assignment.withdrawn", managers_only=True, payload={"reason": text}
        )
        support.audit(ctx, C.WITHDRAW_ASSIGNMENT, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


def propose_visit(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    data: VisitProposalInput,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.PROPOSE_VISIT, expected_version
        )
        window_start, window_end = support.visit_window(
            ctx.now, data.visit_window_start, data.visit_window_end, required=True
        )
        price, valid_until = support.priced_terms(
            ctx.now, data, default_seconds=get_settings().visit_proposal_default_ttl_seconds
        )
        version = await queries.next_proposal_version(ctx.session, request.id, assignment.id)
        await ctx.session.execute(
            update(VisitProposal)
            .where(
                VisitProposal.request_id == request.id,
                VisitProposal.status.in_(support.SUPERSEDABLE),
            )
            .values(status=VisitProposalStatus.SUPERSEDED)
        )

        proposal = VisitProposal(
            request_id=request.id,
            assignment_id=assignment.id,
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
            status=VisitProposalStatus.PENDING,
            created_by_membership_id=policy.acting_membership_id(ctx.actor),
        )
        ctx.session.add(proposal)
        await support.flush_unique(ctx)

        to_status = RequestStatus.ACCEPTED if request.status == RequestStatus.SCHEDULED else None
        en_route_reset = _reset_en_route(assignment) if to_status is not None else False
        apply_transition(
            ctx,
            request,
            C.PROPOSE_VISIT,
            to_status,
            visit_proposal_id=ids.encode("visit_proposal", proposal.id),
            proposal_version=version,
            en_route_reset=en_route_reset or None,
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="visit_proposed",
            extra={
                "visit_proposal": views.to_visit_proposal_view(proposal).model_dump(mode="json")
            },
        )
        await recipients.notify_customer(
            ctx,
            request,
            "visit_proposal.created",
            managers_only=True,
            payload={
                "visit_proposal_id": ids.encode("visit_proposal", proposal.id),
                "proposal_version": version,
            },
        )
        support.audit(ctx, C.PROPOSE_VISIT, request, proposal_version=version)
        return await support.provider_result(ctx, request, assignment, proposals=(proposal,))

    return handler


def create_repair_quote(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    data: RepairQuoteInput,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        description = support.required_text(
            data.description_of_work, "Опишите состав работ", "description_of_work"
        )
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.CREATE_REPAIR_QUOTE, expected_version
        )
        items, amount_minor = quote_items(data)
        if amount_minor is None:
            raise ValidationFailed("Укажите стоимость ремонта", field="amount_minor")
        price, valid_until = support.priced_terms(
            ctx.now,
            replace(data, amount_minor=amount_minor),
            default_seconds=get_settings().repair_quote_default_ttl_seconds,
        )
        version = await queries.next_quote_version(ctx.session, request.id, assignment.id)
        await ctx.session.execute(
            update(RepairQuote)
            .where(
                RepairQuote.request_id == request.id,
                RepairQuote.status == RepairQuoteStatus.PENDING,
            )
            .values(status=RepairQuoteStatus.SUPERSEDED)
        )

        quote = RepairQuote(
            request_id=request.id,
            assignment_id=assignment.id,
            version=version,
            description_of_work=description,
            items=items,
            amount_minor=price.amount_minor,
            currency=price.currency,
            vat_mode=price.vat_mode,
            zero_cost_reason=price.zero_cost_reason,
            valid_until=valid_until,
            status=RepairQuoteStatus.PENDING,
            created_by_membership_id=policy.acting_membership_id(ctx.actor),
            warranty_terms=_warranty_terms(data.warranty_terms),
        )
        ctx.session.add(quote)
        await support.flush_unique(ctx)

        apply_transition(
            ctx,
            request,
            C.CREATE_REPAIR_QUOTE,
            None,
            repair_quote_id=ids.encode("repair_quote", quote.id),
            quote_version=version,
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="repair_quote_created",
            extra={"repair_quote": views.to_repair_quote_view(quote).model_dump(mode="json")},
        )
        await recipients.notify_customer(
            ctx,
            request,
            "repair_quote.created",
            managers_only=True,
            payload={
                "repair_quote_id": ids.encode("repair_quote", quote.id),
                "quote_version": version,
            },
        )
        support.audit(ctx, C.CREATE_REPAIR_QUOTE, request, quote_version=version)
        return await support.provider_result(ctx, request, assignment, quotes=(quote,))

    return handler


MAX_WARRANTY_TERMS = 1000


def _warranty_terms(value: str | None) -> str | None:
    text = (value or "").strip() or None
    if text is not None and len(text) > MAX_WARRANTY_TERMS:
        raise ValidationFailed(
            f"Условия гарантии — не длиннее {MAX_WARRANTY_TERMS} символов",
            field="warranty_terms",
        )
    return text


def start_work(
    request_id: uuid.UUID, *, assignment_id: uuid.UUID, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.START_WORK, expected_version
        )
        approved = [
            p
            for p in await queries.visit_proposals(
                ctx.session, request.id, assignment_id=assignment.id
            )
            if p.status == VisitProposalStatus.APPROVED
        ]
        if not approved:
            raise Conflict("Нет согласованных условий выезда", code="VISIT_NOT_AGREED")

        apply_transition(ctx, request, C.START_WORK, RequestStatus.IN_PROGRESS)
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="work_started",
        )
        await recipients.notify_customer(ctx, request, "work.started")
        support.audit(ctx, C.START_WORK, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


def _reset_en_route(assignment: Assignment) -> bool:
    """Снимает отметку выезда; `True`, если она была."""
    if assignment.en_route_at is None:
        return False
    assignment.en_route_at = None
    return True


def mark_en_route(
    request_id: uuid.UUID, *, assignment_id: uuid.UUID, expected_version: int | None
) -> Handler:
    """Мастер выехал: только отметка времени, статус заявки не меняется (ТЗ 5.3)."""

    async def handler(ctx: CommandContext) -> CommandResult:
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.MARK_EN_ROUTE, expected_version
        )
        if assignment.state != AssignmentState.ACCEPTED:
            raise InvalidTransition(status=request.status, command=str(C.MARK_EN_ROUTE))
        if assignment.en_route_at is not None:
            raise Conflict("Выезд уже отмечен", code="ALREADY_EN_ROUTE")
        assignment.en_route_at = ctx.now

        apply_transition(ctx, request, C.MARK_EN_ROUTE, None, assignment_id=assignment.id)
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="en_route",
        )
        await recipients.notify_customer(
            ctx,
            request,
            "field_worker.en_route",
            payload={"en_route_at": assignment.en_route_at.isoformat()},
        )
        support.audit(ctx, C.MARK_EN_ROUTE, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


def set_warranty_decision(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    decision: str,
    comment: str | None,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        support.one_of(decision, {str(d) for d in WarrantyDecision}, "decision")
        text = comment
        if decision != WarrantyDecision.NOT_STATED:
            text = support.required_text(comment, "Поясните решение по гарантии", "comment")
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.SUBMIT_WARRANTY_DECISION, expected_version
        )
        assignment.warranty_decision = decision
        assignment.warranty_decision_comment = text

        apply_transition(ctx, request, C.SUBMIT_WARRANTY_DECISION, None, warranty_decision=decision)
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="warranty_decision",
        )
        await recipients.notify_customer(ctx, request, "warranty_decision.stated")
        support.audit(ctx, C.SUBMIT_WARRANTY_DECISION, request, decision=decision)
        return await support.provider_result(ctx, request, assignment)

    return handler


def set_field_worker(
    request_id: uuid.UUID,
    *,
    assignment_id: uuid.UUID,
    membership_id: uuid.UUID | None,
    display_name: str | None,
    contact_phone: str | None,
    expected_version: int | None,
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        if membership_id is None and not (display_name or "").strip():
            raise ValidationFailed("Укажите сотрудника или имя мастера", field="field_worker")
        request, assignment = await support.provider_command(
            ctx, request_id, assignment_id, C.ASSIGN_FIELD_WORKER, expected_version
        )
        previous_worker = (
            assignment.field_worker_membership_id,
            assignment.field_worker_display_name,
        )
        if membership_id is not None:
            stmt = select(Membership).where(
                Membership.id == membership_id,
                Membership.organization_id == assignment.provider_org_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.role.in_(PROVIDER_ROLES),
            )
            if (await ctx.session.execute(stmt)).scalar_one_or_none() is None:
                raise NotFound()
            assignment.field_worker_membership_id = membership_id
            assignment.field_worker_display_name = None
            assignment.field_worker_contact_phone = contact_phone
        else:
            assignment.field_worker_membership_id = None
            assignment.field_worker_display_name = (display_name or "").strip()
            assignment.field_worker_contact_phone = contact_phone

        worker_changed = previous_worker != (
            assignment.field_worker_membership_id,
            assignment.field_worker_display_name,
        )
        en_route_reset = _reset_en_route(assignment) if worker_changed else False
        apply_transition(
            ctx, request, C.ASSIGN_FIELD_WORKER, None, en_route_reset=en_route_reset or None
        )
        recipients.emit_provider_event(
            ctx,
            IntegrationEventType.REQUEST_CHANGED,
            request,
            assignment,
            change_kind="field_worker",
        )
        await recipients.notify_customer(ctx, request, "field_worker.assigned")
        await recipients.notify_provider(ctx, request, assignment, "field_worker.assigned")
        support.audit(ctx, C.ASSIGN_FIELD_WORKER, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


def set_external_reference(
    request_id: uuid.UUID, *, external_id: str, expected_version: int | None
) -> Handler:
    async def handler(ctx: CommandContext) -> CommandResult:
        value = support.required_text(external_id, "Укажите идентификатор в CRM", "external_id")
        policy.ensure_command_allowed(ctx.actor, C.LINK_EXTERNAL_REFERENCE)
        if not isinstance(ctx.actor, IntegrationActor):
            raise Forbidden()
        request = await support.locked_request(ctx, request_id)
        assignment = policy.ensure_provider_read(
            ctx.actor,
            request,
            await queries.provider_assignment(ctx.session, request.id, ctx.actor.organization_id),
        )
        check_version(request.version, expected_version)

        client_id = ctx.actor.integration_client_id
        existing = (
            (
                await ctx.session.execute(
                    select(ExternalReference).where(
                        ExternalReference.integration_client_id == client_id,
                        (ExternalReference.external_id == value)
                        | (ExternalReference.request_id == request.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in existing:
            if row.request_id == request.id and row.external_id == value:
                return await support.provider_result(ctx, request, assignment)
            raise Conflict("Идентификатор CRM уже используется", code="EXTERNAL_REFERENCE_CONFLICT")

        ctx.session.add(
            ExternalReference(
                integration_client_id=client_id,
                provider_org_id=ctx.actor.organization_id,
                request_id=request.id,
                external_id=value,
            )
        )
        apply_transition(ctx, request, C.LINK_EXTERNAL_REFERENCE, None, external_id=value)
        support.audit(ctx, C.LINK_EXTERNAL_REFERENCE, request)
        return await support.provider_result(ctx, request, assignment)

    return handler


MAX_AUTHOR_LABEL = 100


def _crm_author_label(ctx: CommandContext, label: str | None) -> str | None:
    """Подпись автора задаёт только CRM; это строка без проверки личности."""
    if label is None:
        return None
    if not isinstance(ctx.actor, IntegrationActor):
        raise ValidationFailed("Подпись автора передаёт только CRM", field="author_label")
    value = "".join(ch for ch in label if ch.isprintable()).strip()
    if not value:
        return None
    if len(value) > MAX_AUTHOR_LABEL:
        raise ValidationFailed(
            f"Подпись автора — не длиннее {MAX_AUTHOR_LABEL} символов", field="author_label"
        )
    return value


def is_customer_actor(ctx: CommandContext) -> bool:
    return isinstance(ctx.actor, UserActor) and ctx.actor.side == "customer"


def post_message(
    request_id: uuid.UUID,
    *,
    body: str,
    assignment_id: uuid.UUID | None,
    thread_provider_org_id: uuid.UUID | None,
    expected_version: int | None,
    dialog_only: bool = False,
    author_label: str | None = None,
) -> Handler:
    """`dialog_only` — только приватный тред до выбора: после назначения такой
    ответ не должен молча уйти в общий канал."""

    async def handler(ctx: CommandContext) -> CommandResult:
        text = support.required_text(body, "Сообщение не может быть пустым", "body")
        request = await support.locked_request(ctx, request_id)
        if dialog_only and request.status != RequestStatus.SEARCHING:
            if is_customer_actor(ctx):
                policy.ensure_customer_request(ctx.actor, request)
            elif not await queries.offers(
                ctx.session, request.id, provider_org_id=policy.provider_org_id(ctx.actor)
            ):
                raise NotFound()
            raise InvalidTransition(
                "Диалог по отклику закрыт: исполнитель уже выбран или поиск завершён",
                code="OFFER_DIALOG_CLOSED",
            )
        is_customer = isinstance(ctx.actor, UserActor) and ctx.actor.side == "customer"
        thread_org_id: uuid.UUID | None = None
        assignment: Assignment | None = None

        if request.status == RequestStatus.SEARCHING:
            policy.ensure_command_allowed(ctx.actor, C.POST_OFFER_DIALOG_MESSAGE)
            thread_org_id = await search.resolve_dialog_thread(ctx, request, thread_provider_org_id)
            if not is_customer:
                await support.ensure_provider_not_suspended(ctx.session, thread_org_id)
        else:
            policy.ensure_command_allowed(ctx.actor, C.POST_MESSAGE)
            if is_customer:
                policy.ensure_customer_request(ctx.actor, request)
                assignment = await queries.active_assignment(ctx.session, request.id)
            else:
                if assignment_id is None:
                    raise ValidationFailed("Нужен идентификатор назначения", field="assignment_id")
                assignment = policy.ensure_assignment_belongs(
                    ctx.actor, request, await queries.get_assignment(ctx.session, assignment_id)
                )
                policy.ensure_assignment_active(assignment)
                if assignment.state != AssignmentState.ACCEPTED:
                    await support.ensure_provider_not_suspended(
                        ctx.session, assignment.provider_org_id
                    )
        check_version(request.version, expected_version)

        message = Message(
            request_id=request.id,
            visibility_scope=(
                "pre_assignment_thread" if thread_org_id is not None else "all_participants"
            ),
            thread_provider_org_id=thread_org_id,
            assignment_id=assignment.id if assignment is not None else None,
            author_kind=(
                "integration_client"
                if isinstance(ctx.actor, IntegrationActor)
                else ("customer_membership" if is_customer else "provider_membership")
            ),
            author_membership_id=policy.acting_membership_id(ctx.actor),
            author_integration_client_id=(
                ctx.actor.integration_client_id if isinstance(ctx.actor, IntegrationActor) else None
            ),
            body=text,
            author_label=_crm_author_label(ctx, author_label),
        )
        ctx.session.add(message)
        await ctx.session.flush()

        command = C.POST_OFFER_DIALOG_MESSAGE if thread_org_id is not None else C.POST_MESSAGE
        apply_transition(ctx, request, command, None, message_id=ids.encode("message", message.id))
        payload = {"message": views.to_message_view(message).model_dump(mode="json")}
        if thread_org_id is not None:
            if is_customer:
                ctx.emit_integration_event(
                    str(IntegrationEventType.MESSAGE_CREATED),
                    recipient_org_id=thread_org_id,
                    resource_kind="request",
                    resource_id=request.id,
                    resource_version=request.version,
                    payload=payload,
                )
                await recipients.notify_provider_org(ctx, request, thread_org_id, "message.created")
            else:
                await recipients.notify_customer(
                    ctx,
                    request,
                    "message.created",
                    payload={"thread_provider_org_id": ids.encode("organization", thread_org_id)},
                )
        elif assignment is not None:
            if is_customer:
                recipients.emit_provider_event(
                    ctx,
                    IntegrationEventType.MESSAGE_CREATED,
                    request,
                    assignment,
                    extra=payload,
                )
                await recipients.notify_provider(ctx, request, assignment, "message.created")
            else:
                await recipients.notify_customer(ctx, request, "message.created")
        support.audit(ctx, command, request)

        side: Literal["customer", "provider"] = "customer" if is_customer else "provider"
        [view] = await support.message_views_for(
            ctx.session,
            side,
            request.id,
            [message],
            assignment_id=assignment.id if assignment is not None else None,
        )
        return CommandResult(view.model_dump(mode="json"), status=201)

    return handler
