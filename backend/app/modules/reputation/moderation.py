import uuid

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.errors import InvalidTransition, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db.enums import ModerationStatus
from app.db.models import ModerationCase, Organization, Review, ReviewVersion
from app.modules.reputation import fraud, notify, policy
from app.modules.reputation.queries import review_reply
from app.modules.reputation.rating import recalculate_rating
from app.modules.reputation.views import (
    ReviewOperatorView,
    to_complaint_view,
    to_review_operator_view,
)

_REVIEW_DECISIONS = frozenset(
    {
        ModerationStatus.PUBLISHED.value,
        ModerationStatus.REJECTED.value,
        ModerationStatus.REMOVED.value,
    }
)
_CASE_DECISIONS = frozenset(
    {
        ModerationStatus.PUBLISHED.value,
        ModerationStatus.REJECTED.value,
        ModerationStatus.REMOVED.value,
    }
)
_REASON_REQUIRED_FOR = frozenset({ModerationStatus.REJECTED.value, ModerationStatus.REMOVED.value})


async def _reload_if_expired(session: AsyncSession, row: Review | ModerationCase) -> None:
    if inspect(row).expired_attributes:
        await session.refresh(row)


async def decide_review(
    actor: Actor,
    review_id: uuid.UUID,
    decision: str,
    reason: str | None,
    *,
    idem: Idempotency | None,
) -> CommandResult:
    policy.require_operator(actor)
    if decision not in _REVIEW_DECISIONS:
        raise ValidationFailed("Неизвестное решение", field="decision")
    checked_reason = (
        policy.require_reason(reason)
        if decision in _REASON_REQUIRED_FOR
        else (reason or "").strip() or None
    )

    async def handler(ctx: CommandContext) -> CommandResult:
        review = await lock_by_id(ctx.session, Review, review_id)
        if decision == ModerationStatus.REMOVED.value:
            if review.moderation_status != ModerationStatus.PUBLISHED.value:
                raise InvalidTransition("Удалить можно только опубликованный отзыв")
        elif decision == ModerationStatus.PUBLISHED.value:
            if review.moderation_status == ModerationStatus.PUBLISHED.value:
                raise InvalidTransition("Решение уже принято по текущей версии отзыва")
        elif review.moderation_status != ModerationStatus.PENDING.value:
            raise InvalidTransition("Решение уже принято по текущей версии отзыва")

        review.moderation_status = decision
        review.moderation_reason = checked_reason
        version = (
            await ctx.session.execute(
                select(ReviewVersion)
                .where(
                    ReviewVersion.review_id == review.id,
                    ReviewVersion.version == review.current_version,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is not None:
            version.moderation_status = decision

        await recalculate_rating(ctx.session, review.provider_org_id)
        ctx.audit(
            "review.moderate",
            "review",
            review.id,
            organization_id=review.provider_org_id,
            decision=decision,
            reason=checked_reason,
        )
        if decision == ModerationStatus.PUBLISHED.value:
            await notify.notify_provider(ctx, review.provider_org_id, "review.published", review.id)
        await _reload_if_expired(ctx.session, review)
        view = await _operator_view(ctx, review)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def mark_suspected_fraud(
    actor: Actor,
    review_id: uuid.UUID,
    suspected: bool,
    reason: str | None,
    *,
    idem: Idempotency | None,
) -> CommandResult:
    policy.require_operator(actor)
    checked_reason = policy.require_reason(reason)

    async def handler(ctx: CommandContext) -> CommandResult:
        review = await lock_by_id(ctx.session, Review, review_id)
        review.suspected_fraud = suspected
        await recalculate_rating(ctx.session, review.provider_org_id)
        ctx.audit(
            "review.fraud_flag",
            "review",
            review.id,
            organization_id=review.provider_org_id,
            suspected=suspected,
            reason=checked_reason,
        )
        await _reload_if_expired(ctx.session, review)
        view = await _operator_view(ctx, review)
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def decide_moderation_case(
    actor: Actor, case_id: uuid.UUID, decision: str, reason: str | None, *, idem: Idempotency | None
) -> CommandResult:
    operator = policy.require_operator(actor)
    if decision not in _CASE_DECISIONS:
        raise ValidationFailed("Неизвестное решение", field="decision")
    checked_reason = (
        policy.require_reason(reason)
        if decision in _REASON_REQUIRED_FOR
        else (reason or "").strip() or None
    )

    async def handler(ctx: CommandContext) -> CommandResult:
        case = await lock_by_id(ctx.session, ModerationCase, case_id)
        if case.status != ModerationStatus.PENDING.value:
            raise InvalidTransition("Дело уже закрыто")
        case.status = decision
        case.decision_reason = checked_reason
        case.operator_user_id = operator.user_id
        if case.appeal_status is not None:
            case.appeal_status = "resolved"
            case.appeal_resolved_at = ctx.now
        await ctx.session.flush()
        ctx.audit(
            "moderation_case.decide",
            "moderation_case",
            case.id,
            organization_id=case.filer_org_id,
            subject_type=case.subject_type,
            decision=decision,
            reason=checked_reason,
        )
        await _reload_if_expired(ctx.session, case)
        return CommandResult(to_complaint_view(case).model_dump(mode="json"), status=200)

    return await run_command(actor, handler, idempotency=idem)


async def _operator_view(ctx: CommandContext, review: Review) -> ReviewOperatorView:
    customer_org = await ctx.session.get(Organization, review.customer_org_id)
    provider_org = await ctx.session.get(Organization, review.provider_org_id)
    assert customer_org is not None and provider_org is not None
    signals = await fraud.collect_fraud_signals(ctx.session, review, now=ctx.now)
    has_reply = (await review_reply(ctx.session, review.id)) is not None
    return to_review_operator_view(
        review,
        customer_org=customer_org,
        provider_org=provider_org,
        has_reply=has_reply,
        fraud_signals=signals,
    )


__all__ = [
    "decide_moderation_case",
    "decide_review",
    "mark_suspected_fraud",
]
