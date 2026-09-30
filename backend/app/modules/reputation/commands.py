import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, inspect, literal_column, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import (
    CUSTOMER_ROLES,
    PROVIDER_ROLES,
    Actor,
    IntegrationActor,
    UserActor,
    require_roles,
)
from app.core.errors import (
    Conflict,
    Forbidden,
    InvalidTransition,
    NotFound,
    RateLimited,
    ValidationFailed,
)
from app.core.locking import advisory_xact_lock, lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db.enums import (
    MembershipRole,
    MembershipStatus,
    ModerationStatus,
    ModerationSubjectType,
    ProviderProfileStatus,
)
from app.db.models import (
    Attachment,
    AuditEntry,
    Membership,
    ModerationCase,
    Organization,
    ProviderProfile,
    RepairRequest,
    Review,
    ReviewReply,
    ReviewVersion,
)
from app.infra.config import get_settings
from app.modules.files.api import attach_review_photos, get_attachment
from app.modules.reputation import fraud, policy, queries
from app.modules.reputation.eligibility import assess_review_eligibility
from app.modules.reputation.rating import recalculate_rating
from app.modules.reputation.views import to_complaint_view, to_my_review_view, to_reply_view


async def _ensure_provider_may_change(session: AsyncSession, actor: Actor) -> None:
    provider_side = isinstance(actor, UserActor) and actor.side == "provider"
    if not (provider_side or isinstance(actor, IntegrationActor)):
        return
    assert isinstance(actor, UserActor | IntegrationActor)
    provider_org_id = actor.organization_id
    from app.modules.requests import api as requests_api

    await requests_api.ensure_provider_not_suspended(session, provider_org_id)


async def _reload_if_expired(session: AsyncSession, review: Review) -> None:
    if inspect(review).expired_attributes:
        await session.refresh(review)


SELF_REVIEW_FORBIDDEN = "SELF_REVIEW_FORBIDDEN"
NO_SHOW_NOT_ALLOWED = "NO_SHOW_COMPLAINT_NOT_ALLOWED"
ALREADY_REPLIED = "ALREADY_REPLIED"
APPEAL_NOT_ALLOWED = "APPEAL_NOT_ALLOWED"
APPEAL_ALREADY_OPEN = "APPEAL_ALREADY_OPEN"
REVIEW_ALREADY_EXISTS = "REVIEW_ALREADY_EXISTS"
COMPLAINT_AUDIT_ACTION = "complaint.create"


@dataclass(slots=True)
class ReviewSubmitData:
    rating: int
    text: str | None = None
    show_customer_name: bool = False
    photo_attachment_ids: list[uuid.UUID] = field(default_factory=list)
    confirm_sensitive: bool = False


@dataclass(slots=True)
class ComplaintCreateData:
    subject_type: str
    target_id: str
    description: str | None = None


def _validate_submit_data(data: ReviewSubmitData) -> None:
    if data.rating not in (1, 2, 3, 4, 5):
        raise ValidationFailed("Оценка — целое число от 1 до 5", field="rating")
    settings = get_settings()
    if data.text is not None and len(data.text) > settings.review_text_max_length:
        raise ValidationFailed("Слишком длинный текст отзыва", field="text")
    if len(data.photo_attachment_ids) > settings.review_max_photos:
        raise ValidationFailed("Слишком много фотографий", field="photo_attachment_ids")


async def _check_self_review(
    session: AsyncSession,
    *,
    customer_org_id: uuid.UUID,
    provider_org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    if customer_org_id == provider_org_id:
        raise Forbidden(
            "Нельзя оставить отзыв о собственной организации", code=SELF_REVIEW_FORBIDDEN
        )
    is_provider_member = (
        await session.execute(
            select(Membership.id).where(
                Membership.user_id == user_id,
                Membership.organization_id == provider_org_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).first()
    if is_provider_member is not None:
        raise Forbidden(
            "Автор отзыва состоит в организации исполнителя", code=SELF_REVIEW_FORBIDDEN
        )
    customer_org = await session.get(Organization, customer_org_id)
    provider_org = await session.get(Organization, provider_org_id)
    assert customer_org is not None and provider_org is not None
    if (
        customer_org.inn_normalized
        and provider_org.inn_normalized
        and customer_org.inn_normalized == provider_org.inn_normalized
    ):
        raise Forbidden(
            "Заказчик и исполнитель — одно и то же юридическое лицо", code=SELF_REVIEW_FORBIDDEN
        )


async def _representative_membership(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> uuid.UUID | None:
    row = (
        await session.execute(
            select(Membership.id, Membership.role)
            .where(
                Membership.organization_id == provider_org_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.role.in_(["provider_admin", "provider_dispatcher"]),
            )
            .order_by(Membership.role, Membership.id)
            .limit(1)
        )
    ).first()
    return row.id if row is not None else None


async def _publish_review_photos(
    ctx: CommandContext,
    review: Review,
    photo_ids: list[uuid.UUID],
    *,
    confirm_sensitive: bool = False,
) -> None:
    if not photo_ids and review.current_version == 1:
        return
    await attach_review_photos(ctx, review.id, photo_ids, confirm_sensitive=confirm_sensitive)


async def submit_review(
    actor: Actor,
    request_id: uuid.UUID,
    data: ReviewSubmitData,
    *,
    idem: Idempotency | None,
    assignment_id: uuid.UUID | None = None,
) -> CommandResult:
    manager = policy.require_customer_manager(actor)
    _validate_submit_data(data)
    photo_ids = data.photo_attachment_ids

    async def handler(ctx: CommandContext) -> CommandResult:
        request = await lock_by_id(ctx.session, RepairRequest, request_id)
        queries.ensure_customer_request(manager, request)
        target = await queries.pick_review_target(ctx.session, request, assignment_id)
        if target is None and assignment_id is not None:
            raise NotFound()

        existing = (
            await queries.find_review(ctx.session, target.assignment_id, manager.organization_id)
            if target is not None
            else None
        )
        if existing is not None:
            return await _edit_review(ctx, manager, existing, data, photo_ids)

        assessment = assess_review_eligibility(request, target)
        if not assessment.allowed or target is None:
            raise InvalidTransition(
                assessment.reason_message or "Отзыв недоступен",
                code=assessment.reason_code or "REVIEW_NOT_ALLOWED",
            )
        await _check_self_review(
            ctx.session,
            customer_org_id=manager.organization_id,
            provider_org_id=target.provider_org_id,
            user_id=manager.user_id,
        )

        review = Review(
            assignment_id=target.assignment_id,
            request_id=request.id,
            customer_org_id=manager.organization_id,
            provider_org_id=target.provider_org_id,
            author_membership_id=manager.membership_id,
            rating=data.rating,
            text_body=data.text,
            show_customer_name=data.show_customer_name,
            moderation_status=ModerationStatus.PENDING.value,
            current_version=1,
            order_occurred_at=request.submitted_at or request.created_at,
        )
        ctx.session.add(review)
        try:
            await ctx.session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "Отзыв по этому назначению уже создан", code=REVIEW_ALREADY_EXISTS
            ) from exc
        ctx.session.add(
            ReviewVersion(
                review_id=review.id,
                version=1,
                rating=review.rating,
                text_body=review.text_body,
                moderation_status=ModerationStatus.PENDING.value,
                edited_by_membership_id=manager.membership_id,
            )
        )
        await ctx.session.flush()
        await _publish_review_photos(
            ctx, review, photo_ids, confirm_sensitive=data.confirm_sensitive
        )
        if assessment.mode == "needs_admission":
            ctx.session.add(
                ModerationCase(
                    subject_type=ModerationSubjectType.REVIEW.value,
                    review_id=review.id,
                    assignment_id=target.assignment_id,
                    status=ModerationStatus.PENDING.value,
                    evidence={
                        "kind": "admission_required",
                        "note": (
                            "Исполнитель не отметил завершение работ; "
                            "допуск отзыва решает оператор по истории взаимодействия"
                        ),
                    },
                )
            )
        await fraud.sync_signals(ctx, review)
        ctx.audit(
            "review.create",
            "review",
            review.id,
            organization_id=manager.organization_id,
            provider_org_id=str(target.provider_org_id),
            assignment_id=str(target.assignment_id),
        )
        view = to_my_review_view(
            review,
            reply=None,
            published_version=None,
            photo_attachment_ids=await queries.photo_attachment_ids(ctx.session, review.id),
        )
        return CommandResult(view.model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


async def _edit_review(
    ctx: CommandContext,
    manager: UserActor,
    existing: Review,
    data: ReviewSubmitData,
    photo_ids: list[uuid.UUID],
) -> CommandResult:
    review = await lock_by_id(ctx.session, Review, existing.id)
    review.rating = data.rating
    review.text_body = data.text
    review.show_customer_name = data.show_customer_name
    review.moderation_status = ModerationStatus.PENDING.value
    review.moderation_reason = None
    review.current_version += 1
    ctx.session.add(
        ReviewVersion(
            review_id=review.id,
            version=review.current_version,
            rating=review.rating,
            text_body=review.text_body,
            moderation_status=ModerationStatus.PENDING.value,
            edited_by_membership_id=manager.membership_id,
        )
    )
    await ctx.session.flush()
    await _publish_review_photos(ctx, review, photo_ids, confirm_sensitive=data.confirm_sensitive)
    await fraud.sync_signals(ctx, review)
    await recalculate_rating(ctx.session, review.provider_org_id)
    ctx.audit("review.edit", "review", review.id, organization_id=manager.organization_id)
    await _reload_if_expired(ctx.session, review)
    view = to_my_review_view(
        review,
        reply=await queries.review_reply(ctx.session, review.id),
        published_version=await queries.latest_published_version(ctx.session, review.id),
        photo_attachment_ids=await queries.photo_attachment_ids(ctx.session, review.id),
    )
    return CommandResult(view.model_dump(mode="json"))


async def reply_to_review(
    actor: Actor, review_id: uuid.UUID, body: str, *, idem: Idempotency | None
) -> CommandResult:
    if isinstance(actor, UserActor):
        admin = policy.require_provider_side(actor)
        provider_org_id = admin.organization_id
        author_membership_id: uuid.UUID | None = admin.membership_id
    else:
        if not isinstance(actor, IntegrationActor):
            raise Forbidden()
        policy.require_reviews_write(actor)
        provider_org_id = actor.organization_id
        author_membership_id = None
    text = policy.require_text(body, "body", "Введите текст ответа")
    settings = get_settings()
    if len(text) > settings.review_reply_max_length:
        raise ValidationFailed("Слишком длинный ответ", field="body")

    async def handler(ctx: CommandContext) -> CommandResult:
        review = await ctx.session.get(Review, review_id)
        if review is None or review.provider_org_id != provider_org_id:
            raise NotFound()
        await _ensure_provider_may_change(ctx.session, actor)
        existing = await queries.review_reply(ctx.session, review.id)
        if existing is not None:
            raise InvalidTransition("На отзыв уже дан ответ", code=ALREADY_REPLIED)
        membership_id = author_membership_id
        if membership_id is None:
            membership_id = await _representative_membership(ctx.session, provider_org_id)
        if membership_id is None:
            raise InvalidTransition(
                "В компании нет действующего сотрудника для подписи ответа",
                code="NO_PROVIDER_MEMBERSHIP",
            )
        reply = ReviewReply(
            review_id=review.id,
            provider_org_id=provider_org_id,
            author_membership_id=membership_id,
            body=text,
        )
        ctx.session.add(reply)
        await ctx.session.flush()
        ctx.audit("review.reply", "review", review.id, organization_id=provider_org_id)
        return CommandResult(to_reply_view(reply).model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


APPEAL_REASON_CODES = frozenset(
    {"not_our_work", "abuse_or_personal_data", "customer_not_involved", "other"}
)


async def appeal_review(
    actor: Actor,
    review_id: uuid.UUID,
    reason: str,
    *,
    idem: Idempotency | None,
    reason_code: str | None = None,
) -> CommandResult:
    if not isinstance(actor, UserActor):
        raise Forbidden()
    filer_membership_id = actor.membership_id
    filer_org_id = actor.organization_id
    as_author = actor.side == "customer"
    checked_reason = policy.require_text(reason, "reason", "Опишите причину обжалования")
    if reason_code is not None and reason_code not in APPEAL_REASON_CODES:
        raise ValidationFailed("Неизвестная причина", field="reason_code")

    async def handler(ctx: CommandContext) -> CommandResult:
        review = await ctx.session.get(Review, review_id)
        own_org = None
        if review is not None:
            own_org = review.customer_org_id if as_author else review.provider_org_id
        if review is None or filer_org_id != own_org:
            raise NotFound()
        if as_author and review.moderation_status not in (
            ModerationStatus.REJECTED.value,
            ModerationStatus.REMOVED.value,
        ):
            raise InvalidTransition(
                "Обжаловать можно только отклонённый или удалённый отзыв", code=APPEAL_NOT_ALLOWED
            )
        if not as_author and review.moderation_status != (ModerationStatus.PUBLISHED.value):
            raise InvalidTransition(
                "Оспорить можно только опубликованный отзыв", code=APPEAL_NOT_ALLOWED
            )
        await _ensure_provider_may_change(ctx.session, actor)
        await advisory_xact_lock(ctx.session, f"review.appeal:{review.id}:{filer_org_id}")
        if await queries.open_review_appeal(ctx.session, review.id, filer_org_id) is not None:
            raise Conflict("Обжалование уже на рассмотрении", code=APPEAL_ALREADY_OPEN)
        await _check_appeal_rate(ctx, actor)
        case = ModerationCase(
            subject_type=ModerationSubjectType.REVIEW.value,
            review_id=review.id,
            filer_org_id=filer_org_id,
            filer_membership_id=filer_membership_id,
            status=ModerationStatus.PENDING.value,
            appeal_status="pending",
            evidence={
                "kind": "appeal",
                "reason": checked_reason,
                "reason_code": reason_code,
                "review_moderation_status_at_filing": review.moderation_status,
            },
        )
        try:
            async with ctx.session.begin_nested():
                ctx.session.add(case)
                await ctx.session.flush()
        except IntegrityError as exc:
            if "ux_moderation_cases_open_review_appeal" not in str(exc.orig):
                raise
            raise Conflict("Обжалование уже на рассмотрении", code=APPEAL_ALREADY_OPEN) from exc
        ctx.audit(
            "review.appeal",
            "moderation_case",
            case.id,
            organization_id=filer_org_id,
            review_id=str(review.id),
        )
        return CommandResult(to_complaint_view(case).model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


async def withdraw_complaint(
    actor: Actor, case_id: uuid.UUID, *, idem: Idempotency | None
) -> CommandResult:
    if not isinstance(actor, UserActor):
        raise Forbidden()
    side_roles = CUSTOMER_ROLES if actor.side == "customer" else PROVIDER_ROLES

    async def handler(ctx: CommandContext) -> CommandResult:
        case = await lock_by_id(ctx.session, ModerationCase, case_id)
        if case.filer_org_id != actor.organization_id:
            raise NotFound()
        filer = (
            await ctx.session.get(Membership, case.filer_membership_id)
            if case.filer_membership_id is not None
            else None
        )
        if filer is None or filer.role not in side_roles:
            raise NotFound()
        if case.filer_membership_id != actor.membership_id and actor.role not in _SIDE_HEADS:
            raise Forbidden("Отозвать жалобу может её автор или руководитель", code="NOT_FILER")
        await _ensure_provider_may_change(ctx.session, actor)
        if case.status != ModerationStatus.PENDING.value:
            raise InvalidTransition("По жалобе уже есть решение", code="COMPLAINT_CLOSED")
        case.status = ModerationStatus.WITHDRAWN.value
        if case.appeal_status is not None:
            case.appeal_status = "resolved"
            case.appeal_resolved_at = ctx.now
        await ctx.session.flush()
        ctx.audit(
            "complaint.withdraw",
            "moderation_case",
            case.id,
            organization_id=actor.organization_id,
            subject_type=case.subject_type,
        )
        await ctx.session.refresh(case)
        return CommandResult(to_complaint_view(case).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


_SIDE_HEADS = frozenset(
    {MembershipRole.CUSTOMER_MANAGER.value, MembershipRole.PROVIDER_ADMIN.value}
)

PROFILE_APPEAL_ALREADY_OPEN = "PROFILE_APPEAL_ALREADY_OPEN"
_APPEALABLE_PROFILE_STATUSES = (
    ProviderProfileStatus.SUSPENDED.value,
    ProviderProfileStatus.REJECTED.value,
)


async def appeal_provider_profile(
    actor: Actor, text: str, *, idem: Idempotency | None
) -> CommandResult:
    admin = require_roles(actor, MembershipRole.PROVIDER_ADMIN)
    checked_text = policy.require_text(text, "text", "Опишите основания обжалования")

    async def handler(ctx: CommandContext) -> CommandResult:
        profile = (
            await ctx.session.execute(
                select(ProviderProfile)
                .where(ProviderProfile.organization_id == admin.organization_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound()
        if profile.status not in _APPEALABLE_PROFILE_STATUSES:
            raise InvalidTransition(
                "Обжаловать можно только отказ или приостановку профиля",
                code=APPEAL_NOT_ALLOWED,
            )
        if await queries.open_profile_appeal(ctx.session, profile.id) is not None:
            raise Conflict("Обжалование уже на рассмотрении", code=PROFILE_APPEAL_ALREADY_OPEN)
        case = ModerationCase(
            subject_type=ModerationSubjectType.PROVIDER_PROFILE.value,
            provider_profile_id=profile.id,
            filer_org_id=admin.organization_id,
            filer_membership_id=admin.membership_id,
            status=ModerationStatus.PENDING.value,
            appeal_status="pending",
            evidence={
                "kind": "appeal",
                "description": checked_text,
                "profile_status_at_filing": profile.status,
                "status_reason_at_filing": profile.status_reason,
            },
        )
        ctx.session.add(case)
        await ctx.session.flush()
        ctx.audit(
            "provider_profile.appeal",
            "moderation_case",
            case.id,
            organization_id=admin.organization_id,
            profile_status=profile.status,
        )
        return CommandResult(to_complaint_view(case).model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


_COMPLAINT_SUBJECTS = frozenset({"provider_profile", "review", "attachment", "no_show"})


async def create_complaint(
    actor: Actor, data: ComplaintCreateData, *, idem: Idempotency | None
) -> CommandResult:
    if not isinstance(actor, UserActor):
        raise Forbidden()
    if data.subject_type not in _COMPLAINT_SUBJECTS:
        raise ValidationFailed("Неизвестный тип жалобы", field="subject_type")
    if data.subject_type == "no_show":
        policy.require_customer_manager(actor)
    settings = get_settings()
    description = policy.require_text(data.description, "description", "Опишите жалобу")
    if len(description) > settings.complaint_description_max_length:
        raise ValidationFailed("Слишком длинное описание", field="description")
    attachment_id: uuid.UUID | None = None
    if data.subject_type == "attachment":
        attachment_id = ids.decode("attachment", data.target_id)
        await get_attachment(actor, attachment_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        await _ensure_provider_may_change(ctx.session, actor)
        await _check_complaint_rate(ctx, actor)
        case = ModerationCase(
            subject_type=data.subject_type,
            filer_org_id=actor.organization_id,
            filer_membership_id=actor.membership_id,
            status=ModerationStatus.PENDING.value,
            evidence={"description": description},
        )
        if data.subject_type == "provider_profile":
            provider_org_id = ids.decode("organization", data.target_id)
            profile = (
                await ctx.session.execute(
                    select(ProviderProfile).where(
                        ProviderProfile.organization_id == provider_org_id
                    )
                )
            ).scalar_one_or_none()
            if profile is None or (
                profile.status != ProviderProfileStatus.ACTIVE
                and not (actor.side == "provider" and provider_org_id == actor.organization_id)
            ):
                raise NotFound()
            case.provider_profile_id = profile.id
        elif data.subject_type == "review":
            review_id = ids.decode("review", data.target_id)
            review = await ctx.session.get(Review, review_id)
            if review is None or not await _review_visible(ctx.session, review, actor):
                raise NotFound()
            case.review_id = review.id
        elif data.subject_type == "attachment":
            assert attachment_id is not None
            attachment = await ctx.session.get(Attachment, attachment_id)
            if attachment is None:
                raise NotFound()
            case.attachment_id = attachment.id
        else:
            request_id = ids.decode("request", data.target_id)
            request = await ctx.session.get(RepairRequest, request_id)
            queries.ensure_customer_request(actor, request)
            assert request is not None
            if request.scheduled_at is None:
                raise InvalidTransition(
                    "Жалоба на неявку доступна только после согласованного выезда",
                    code=NO_SHOW_NOT_ALLOWED,
                )
            assignment = await queries.no_show_assignment(ctx.session, request)
            case.assignment_id = assignment.id if assignment is not None else None

        ctx.session.add(case)
        await ctx.session.flush()
        ctx.audit(
            COMPLAINT_AUDIT_ACTION,
            "moderation_case",
            case.id,
            organization_id=actor.organization_id,
            subject_type=data.subject_type,
        )
        return CommandResult(to_complaint_view(case).model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


async def _review_visible(session: AsyncSession, review: Review, actor: UserActor) -> bool:
    own_org = review.customer_org_id if actor.side == "customer" else review.provider_org_id
    if actor.organization_id == own_org:
        return True
    return await queries.latest_published_version(session, review.id) is not None


async def _check_complaint_rate(ctx: CommandContext, actor: UserActor) -> None:
    await advisory_xact_lock(ctx.session, f"{COMPLAINT_AUDIT_ACTION}:{actor.user_id}")
    settings = get_settings()
    cutoff = ctx.now - timedelta(seconds=settings.complaint_window_seconds)
    filed = await ctx.session.scalar(
        select(func.count())
        .select_from(AuditEntry)
        .where(
            AuditEntry.action == literal_column(f"'{COMPLAINT_AUDIT_ACTION}'"),
            AuditEntry.actor_user_id == actor.user_id,
            AuditEntry.occurred_at > cutoff,
        )
    )
    if (filed or 0) >= settings.complaint_limit:
        raise RateLimited("Слишком много жалоб, попробуйте позже")


async def _check_appeal_rate(ctx: CommandContext, actor: UserActor) -> None:
    settings = get_settings()
    cutoff = ctx.now - timedelta(seconds=settings.complaint_window_seconds)
    filed = await ctx.session.scalar(
        select(func.count())
        .select_from(ModerationCase)
        .where(
            ModerationCase.subject_type == ModerationSubjectType.REVIEW.value,
            ModerationCase.evidence["kind"].astext == "appeal",
            ModerationCase.filer_membership_id == actor.membership_id,
            ModerationCase.created_at > cutoff,
        )
    )
    if (filed or 0) >= settings.complaint_limit:
        raise RateLimited("Слишком много обжалований, попробуйте позже")


__all__ = [
    "ComplaintCreateData",
    "ReviewSubmitData",
    "appeal_provider_profile",
    "appeal_review",
    "create_complaint",
    "reply_to_review",
    "submit_review",
]
