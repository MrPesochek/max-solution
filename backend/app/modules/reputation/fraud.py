import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pipeline import CommandContext
from app.db.enums import MembershipStatus, ModerationStatus, ModerationSubjectType
from app.db.models import Membership, ModerationCase, Organization, RepairRequest, Review
from app.infra.config import get_settings

AUTO_SIGNALS_KIND = "auto_signals"

_WHITESPACE = re.compile(r"\s+")


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE.sub(" ", value.strip().casefold())
    return cleaned or None


async def _order_spike(session: AsyncSession, review: Review, now: datetime) -> dict[str, Any]:
    settings = get_settings()
    since = now - timedelta(hours=settings.fraud_order_spike_window_hours)
    count = (
        await session.execute(
            select(Review.id).where(
                Review.customer_org_id == review.customer_org_id,
                Review.provider_org_id == review.provider_org_id,
                Review.id != review.id,
                Review.created_at >= since,
            )
        )
    ).scalars()
    total = len(list(count)) + 1
    return {
        "triggered": total >= settings.fraud_order_spike_count,
        "count": total,
        "window_hours": settings.fraud_order_spike_window_hours,
    }


async def _duplicate_text(session: AsyncSession, review: Review) -> dict[str, Any]:
    normalized = _normalize_text(review.text_body)
    if normalized is None:
        return {"triggered": False, "matched_review_ids": []}
    candidates = (
        await session.execute(
            select(Review.id, Review.text_body).where(
                Review.provider_org_id == review.provider_org_id,
                Review.id != review.id,
                Review.text_body.is_not(None),
            )
        )
    ).all()
    matched = [row.id for row in candidates if _normalize_text(row.text_body) == normalized]
    return {
        "triggered": bool(matched),
        "matched_review_ids": [str(review_id) for review_id in matched],
    }


async def _fast_completion(session: AsyncSession, review: Review) -> dict[str, Any]:
    settings = get_settings()
    request = await session.get(RepairRequest, review.request_id)
    minutes: float | None = None
    if request is not None and request.accepted_at is not None and request.completion_reported_at:
        minutes = (request.completion_reported_at - request.accepted_at).total_seconds() / 60
    return {
        "triggered": minutes is not None and minutes < settings.fraud_fast_completion_minutes,
        "minutes": minutes,
    }


async def _shared_members(session: AsyncSession, review: Review) -> dict[str, Any]:
    customer_users = select(Membership.user_id).where(
        Membership.organization_id == review.customer_org_id,
        Membership.status == MembershipStatus.ACTIVE,
    )
    rows = (
        await session.execute(
            select(Membership.user_id)
            .where(
                Membership.organization_id == review.provider_org_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.user_id.in_(customer_users),
            )
            .distinct()
        )
    ).scalars()
    shared = list(rows)
    return {"triggered": bool(shared), "user_ids": [str(user_id) for user_id in shared]}


async def _new_organizations(
    session: AsyncSession, review: Review, now: datetime
) -> dict[str, Any]:
    settings = get_settings()
    threshold = timedelta(days=settings.fraud_new_org_days)
    customer_org = await session.get(Organization, review.customer_org_id)
    provider_org = await session.get(Organization, review.provider_org_id)
    customer_is_new = customer_org is not None and (now - customer_org.created_at) <= threshold
    provider_is_new = provider_org is not None and (now - provider_org.created_at) <= threshold
    return {
        "triggered": customer_is_new or provider_is_new,
        "customer_is_new": customer_is_new,
        "provider_is_new": provider_is_new,
    }


async def collect_fraud_signals(
    session: AsyncSession, review: Review, *, now: datetime
) -> dict[str, Any]:
    """Пять признаков ТЗ 8.3.4. Каждый по отдельности не является доказательством."""
    return {
        "order_spike": await _order_spike(session, review, now),
        "duplicate_text": await _duplicate_text(session, review),
        "fast_completion": await _fast_completion(session, review),
        "shared_members": await _shared_members(session, review),
        "new_organizations": await _new_organizations(session, review, now),
    }


async def sync_signals(ctx: CommandContext, review: Review) -> dict[str, Any]:
    """Пересчитывает сигналы и, если хоть один сработал, заводит/обновляет дело
    для оператора. Ничего в самом отзыве не меняет и не скрывает его (ТЗ 8.3.4)."""
    signals = await collect_fraud_signals(ctx.session, review, now=ctx.now)
    if not any(item.get("triggered") for item in signals.values()):
        return signals
    existing = (
        await ctx.session.execute(
            select(ModerationCase)
            .where(
                ModerationCase.review_id == review.id,
                ModerationCase.status == ModerationStatus.PENDING.value,
                ModerationCase.evidence["kind"].astext == AUTO_SIGNALS_KIND,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    evidence = {"kind": AUTO_SIGNALS_KIND, "signals": signals}
    if existing is not None:
        existing.evidence = evidence
    else:
        ctx.session.add(
            ModerationCase(
                subject_type=ModerationSubjectType.REVIEW.value,
                review_id=review.id,
                status=ModerationStatus.PENDING.value,
                evidence=evidence,
            )
        )
    await ctx.session.flush()
    return signals
