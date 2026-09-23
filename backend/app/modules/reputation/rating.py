import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ModerationStatus, VerificationStatus
from app.db.models import Organization, ProviderRatingAggregate, Review
from app.infra.config import get_settings

_QUANTUM = Decimal("0.1")


def _round_half_up(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


async def recalculate_rating(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> ProviderRatingAggregate:
    """Пересчитывает агрегат по подтверждённым допустимым отзывам.

    В расчёт идут опубликованные отзывы организаций-заказчиков с подтверждённым
    представителем, не помеченные
    подтверждённой накруткой; на пару «заказчик — исполнитель» берётся одна,
    последняя по дате заказа оценка.
    """
    rows = (
        await session.execute(
            select(Review.customer_org_id, Review.rating, Review.order_occurred_at, Review.id)
            .join(Organization, Organization.id == Review.customer_org_id)
            .where(
                Review.provider_org_id == provider_org_id,
                Review.moderation_status == ModerationStatus.PUBLISHED.value,
                Review.suspected_fraud.is_(False),
                Organization.representative_verification_status == VerificationStatus.VERIFIED,
            )
        )
    ).all()

    published_count = (
        await session.execute(
            select(Review.id).where(
                Review.provider_org_id == provider_org_id,
                Review.moderation_status == ModerationStatus.PUBLISHED.value,
            )
        )
    ).all()

    latest_by_org: dict[uuid.UUID, tuple[object, int, uuid.UUID]] = {}
    for customer_org_id, rating, order_occurred_at, review_id in rows:
        current = latest_by_org.get(customer_org_id)
        if current is None or (order_occurred_at, review_id) > (current[0], current[2]):
            latest_by_org[customer_org_id] = (order_occurred_at, rating, review_id)

    unique_orgs = len(latest_by_org)
    average: Decimal | None = None
    if unique_orgs >= get_settings().rating_min_unique_orgs:
        ratings = [item[1] for item in latest_by_org.values()]
        average = _round_half_up(Decimal(sum(ratings)) / Decimal(len(ratings)))

    aggregate = (
        await session.execute(
            select(ProviderRatingAggregate)
            .where(ProviderRatingAggregate.provider_org_id == provider_org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if aggregate is None:
        stmt = (
            pg_insert(ProviderRatingAggregate)
            .values(provider_org_id=provider_org_id)
            .on_conflict_do_nothing(index_elements=["provider_org_id"])
        )
        await session.execute(stmt)
        aggregate = (
            await session.execute(
                select(ProviderRatingAggregate)
                .where(ProviderRatingAggregate.provider_org_id == provider_org_id)
                .with_for_update()
            )
        ).scalar_one()

    aggregate.average_rating = average
    aggregate.unique_reviewer_orgs_count = unique_orgs
    aggregate.published_reviews_count = len(published_count)
    await session.flush()
    return aggregate


async def recalculate_for_customer(session: AsyncSession, customer_org_id: uuid.UUID) -> None:
    """Статус проверки заказчика меняет вклад всех его отзывов (ТЗ 8.3.3):
    пересчитываются рейтинги каждого исполнителя, о котором он писал."""
    provider_ids = (
        await session.execute(
            select(Review.provider_org_id)
            .where(Review.customer_org_id == customer_org_id)
            .distinct()
            .order_by(Review.provider_org_id)
        )
    ).scalars()
    for provider_org_id in list(provider_ids):
        await recalculate_rating(session, provider_org_id)
