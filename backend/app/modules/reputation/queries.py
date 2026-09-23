import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import CUSTOMER_ROLES, PROVIDER_ROLES, Actor, IntegrationActor, UserActor
from app.core.clock import utcnow
from app.core.errors import Forbidden, NotFound
from app.db import session as db_session
from app.db.enums import ModerationStatus, ModerationSubjectType
from app.db.models import (
    Assignment,
    Attachment,
    Membership,
    ModerationCase,
    Organization,
    ProviderRatingAggregate,
    RepairRequest,
    RequestEvent,
    Review,
    ReviewReply,
    ReviewVersion,
)
from app.modules.reputation import fraud, policy
from app.modules.reputation.eligibility import (
    EVENT_ASSIGNMENT_CONFIRMED,
    EVENT_VISIT_AGREED,
    WORK_EVENTS,
    ReviewTarget,
    assess_review_eligibility,
    classify_assignment,
)
from app.modules.reputation.views import (
    ComplaintBriefView,
    ComplaintView,
    ModerationCaseOperatorView,
    ProfileAppealView,
    ProviderReviewView,
    PublicReviewView,
    RatingSummaryView,
    RequestReviewStateView,
    ReviewEligibilityView,
    ReviewOperatorView,
    author_display_name,
    to_complaint_view,
    to_moderation_case_operator_view,
    to_my_review_view,
    to_profile_appeal_view,
    to_public_review_view,
    to_rating_summary,
    to_reply_view,
    to_review_operator_view,
)

DEFAULT_LIMIT = 50


def _paginate[T](
    rows: list[T], limit: int, key: Callable[[T], uuid.UUID]
) -> tuple[list[T], uuid.UUID | None]:
    if len(rows) <= limit:
        return rows, None
    page = rows[:limit]
    return page, key(page[-1])


async def _assignment_marks(
    session: AsyncSession, request: RepairRequest
) -> list[tuple[Assignment, set[str]]]:
    """Назначения заявки (старые первыми) и этапы, пройденные при каждом из них.

    Одновременно активно не больше одного назначения (I1), поэтому событие журнала
    относится к последнему назначению, созданному до него. Порядок берётся по
    `uuidv7`-идентификаторам: и назначения, и события получают их от базы.
    """
    assignments = list(
        (
            await session.execute(
                select(Assignment)
                .where(Assignment.request_id == request.id)
                .order_by(Assignment.id)
            )
        ).scalars()
    )
    rows = (
        await session.execute(
            select(RequestEvent.id, RequestEvent.event_type, RequestEvent.payload)
            .where(
                RequestEvent.request_id == request.id,
                RequestEvent.event_type.in_((*WORK_EVENTS, EVENT_ASSIGNMENT_CONFIRMED)),
            )
            .order_by(RequestEvent.id)
        )
    ).all()
    events = []
    for event_id, event_type, payload in rows:
        if event_type == EVENT_ASSIGNMENT_CONFIRMED:
            if not (payload or {}).get("visit_agreed"):
                continue
            event_type = EVENT_VISIT_AGREED
        events.append((event_id, event_type))
    result = []
    for index, assignment in enumerate(assignments):
        upper = assignments[index + 1].id if index + 1 < len(assignments) else None
        marks = {
            event_type
            for event_id, event_type in events
            if event_id > assignment.id and (upper is None or event_id < upper)
        }
        result.append((assignment, marks))
    return result


async def review_targets(session: AsyncSession, request: RepairRequest) -> list[ReviewTarget]:
    """Назначения, о которых можно оставить отзыв, — новые первыми (ТЗ 8.3.1)."""
    targets = []
    for assignment, marks in await _assignment_marks(session, request):
        mode = classify_assignment(assignment.state, marks)
        if mode is not None:
            targets.append(
                ReviewTarget(
                    assignment_id=assignment.id,
                    provider_org_id=assignment.provider_org_id,
                    mode=mode,
                )
            )
    targets.reverse()
    return targets


async def pick_review_target(
    session: AsyncSession, request: RepairRequest, assignment_id: uuid.UUID | None = None
) -> ReviewTarget | None:
    """Без явного назначения — последнее реально работавшее. Явно указанное
    назначение должно само давать право на отзыв: отказавшийся или отозванный до
    начала работ исполнитель отзыва о ремонте не получает."""
    targets = await review_targets(session, request)
    if assignment_id is None:
        return targets[0] if targets else None
    return next((t for t in targets if t.assignment_id == assignment_id), None)


async def no_show_assignment(session: AsyncSession, request: RepairRequest) -> Assignment | None:
    """Назначение, при котором был согласован выезд, — адресат жалобы на неявку."""
    for assignment, marks in reversed(await _assignment_marks(session, request)):
        if EVENT_VISIT_AGREED in marks:
            return assignment
    return None


async def find_review(
    session: AsyncSession, assignment_id: uuid.UUID, customer_org_id: uuid.UUID
) -> Review | None:
    """Один отзыв организации на одно назначение (ТЗ 8.3.1, I18)."""
    return (
        await session.execute(
            select(Review).where(
                Review.assignment_id == assignment_id, Review.customer_org_id == customer_org_id
            )
        )
    ).scalar_one_or_none()


async def latest_published_version(
    session: AsyncSession, review_id: uuid.UUID
) -> ReviewVersion | None:
    return (
        await session.execute(
            select(ReviewVersion)
            .where(
                ReviewVersion.review_id == review_id,
                ReviewVersion.moderation_status == ModerationStatus.PUBLISHED.value,
            )
            .order_by(ReviewVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def review_reply(session: AsyncSession, review_id: uuid.UUID) -> ReviewReply | None:
    return (
        await session.execute(select(ReviewReply).where(ReviewReply.review_id == review_id))
    ).scalar_one_or_none()


async def photo_attachment_ids(
    session: AsyncSession, review_id: uuid.UUID, *, published_only: bool = False
) -> list[str]:
    """Копии фото отзыва делает модуль files (`attach_review_photos`); каждая копия
    проходит его собственную публикационную модерацию (`Attachment.moderation_case_id`)."""
    stmt = select(Attachment.id).where(Attachment.review_id == review_id)
    if published_only:
        stmt = stmt.join(ModerationCase, ModerationCase.id == Attachment.moderation_case_id).where(
            ModerationCase.status == ModerationStatus.PUBLISHED.value
        )
    rows = (await session.execute(stmt.order_by(Attachment.created_at))).scalars()
    return [ids.encode("attachment", row) for row in rows]


def ensure_customer_request(actor: Actor, request: RepairRequest | None) -> UserActor:
    """Заявка своей организации и — для сотрудника — своей точки, иначе `NotFound`."""
    if not isinstance(actor, UserActor) or actor.side != "customer":
        raise Forbidden()
    if request is None or request.customer_org_id != actor.organization_id:
        raise NotFound()
    if actor.location_ids is not None and request.location_id not in actor.location_ids:
        raise NotFound()
    return actor


async def get_review_state(
    actor: Actor, request_id: uuid.UUID, *, assignment_id: uuid.UUID | None = None
) -> RequestReviewStateView:
    if not isinstance(actor, UserActor) or actor.side != "customer":
        raise Forbidden()
    async with db_session.transaction() as session:
        request = await session.get(RepairRequest, request_id)
        ensure_customer_request(actor, request)
        assert request is not None
        target = await pick_review_target(session, request, assignment_id)
        review = (
            await find_review(session, target.assignment_id, actor.organization_id)
            if target is not None
            else None
        )
        if review is not None:
            eligibility = ReviewEligibilityView(
                can_submit=True,
                mode="edit",
                reason_code=None,
                reason_message=None,
                allow_no_show_complaint=False,
                assignment_id=ids.encode("assignment", review.assignment_id),
            )
            view = to_my_review_view(
                review,
                reply=await review_reply(session, review.id),
                published_version=await latest_published_version(session, review.id),
                photo_attachment_ids=await photo_attachment_ids(session, review.id),
            )
            return RequestReviewStateView(review=view, eligibility=eligibility)

        assessment = assess_review_eligibility(request, target)
        eligibility = ReviewEligibilityView(
            can_submit=assessment.allowed,
            mode=assessment.mode,
            reason_code=assessment.reason_code,
            reason_message=assessment.reason_message,
            allow_no_show_complaint=assessment.allow_no_show_complaint,
            assignment_id=ids.encode_opt("assignment", assessment.assignment_id),
        )
        return RequestReviewStateView(review=None, eligibility=eligibility)


@dataclass(frozen=True, slots=True)
class _ReviewPageRow:
    version: ReviewVersion
    customer_org: Organization
    reply: ReviewReply | None
    photo_attachment_ids: list[str]


async def _load_review_page(
    session: AsyncSession, reviews: Sequence[Review]
) -> dict[uuid.UUID, _ReviewPageRow]:
    """Всё для страницы отзывов — четырьмя запросами на страницу, а не на отзыв.

    Правила видимости те же, что у одиночных запросов: последняя опубликованная
    версия и только опубликованные фото."""
    review_ids = [review.id for review in reviews]
    if not review_ids:
        return {}
    versions = {
        row.review_id: row
        for row in (
            await session.execute(
                select(ReviewVersion)
                .where(
                    ReviewVersion.review_id.in_(review_ids),
                    ReviewVersion.moderation_status == ModerationStatus.PUBLISHED.value,
                )
                .order_by(ReviewVersion.review_id, ReviewVersion.version.desc())
                .distinct(ReviewVersion.review_id)
            )
        ).scalars()
    }
    org_ids = {review.customer_org_id for review in reviews}
    orgs = {
        org.id: org
        for org in (
            await session.execute(select(Organization).where(Organization.id.in_(org_ids)))
        ).scalars()
    }
    replies = {
        reply.review_id: reply
        for reply in (
            await session.execute(select(ReviewReply).where(ReviewReply.review_id.in_(review_ids)))
        ).scalars()
    }
    photos: dict[uuid.UUID, list[str]] = {}
    photo_rows = await session.execute(
        select(Attachment.review_id, Attachment.id)
        .join(ModerationCase, ModerationCase.id == Attachment.moderation_case_id)
        .where(
            Attachment.review_id.in_(review_ids),
            ModerationCase.status == ModerationStatus.PUBLISHED.value,
        )
        .order_by(Attachment.created_at)
    )
    for review_id, attachment_id in photo_rows.all():
        photos.setdefault(review_id, []).append(ids.encode("attachment", attachment_id))
    page: dict[uuid.UUID, _ReviewPageRow] = {}
    for review in reviews:
        version = versions.get(review.id)
        customer_org = orgs.get(review.customer_org_id)
        if version is None or customer_org is None:
            continue
        page[review.id] = _ReviewPageRow(
            version=version,
            customer_org=customer_org,
            reply=replies.get(review.id),
            photo_attachment_ids=photos.get(review.id, []),
        )
    return page


async def list_published_reviews(
    provider_org_id: uuid.UUID, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[PublicReviewView], uuid.UUID | None]:
    """Только отзывы, у которых есть опубликованная версия; более новая
    непромодерированная правка автора наружу не видна (ТЗ 8.3.2)."""
    has_published = (
        select(ReviewVersion.id)
        .where(
            ReviewVersion.review_id == Review.id,
            ReviewVersion.moderation_status == ModerationStatus.PUBLISHED.value,
        )
        .exists()
    )
    async with db_session.transaction() as session:
        stmt = (
            select(Review)
            .where(Review.provider_org_id == provider_org_id, has_published)
            .order_by(Review.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(Review.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda review: review.id)
        loaded = await _load_review_page(session, page)
        items = [
            to_public_review_view(
                review,
                found.version,
                customer_org=found.customer_org,
                reply=found.reply,
                photo_attachment_ids=found.photo_attachment_ids,
            )
            for review in page
            if (found := loaded.get(review.id)) is not None
        ]
        return items, next_cursor


async def list_my_reviews(
    actor: Actor, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[ProviderReviewView], uuid.UUID | None]:
    """`GET /reviews/mine`: опубликованные отзывы о своей компании для экрана
    «Ответ на отзыв и жалоба». Только сторона исполнителя, только своя организация."""
    if not isinstance(actor, UserActor) or actor.side != "provider":
        raise Forbidden("Отзывы о компании видит сторона исполнителя")
    has_published = (
        select(ReviewVersion.id)
        .where(
            ReviewVersion.review_id == Review.id,
            ReviewVersion.moderation_status == ModerationStatus.PUBLISHED.value,
        )
        .exists()
    )
    async with db_session.transaction() as session:
        stmt = (
            select(Review, RepairRequest.request_number)
            .join(RepairRequest, RepairRequest.id == Review.request_id)
            .where(Review.provider_org_id == actor.organization_id, has_published)
            .order_by(Review.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(Review.id < cursor)
        rows = list((await session.execute(stmt)).all())
        page, next_cursor = _paginate(rows, limit, lambda row: row[0].id)
        review_ids = [review.id for review, _ in page]
        complaints: dict[uuid.UUID, ModerationCase] = {}
        if review_ids:
            side_cases = (
                select(ModerationCase)
                .join(Membership, Membership.id == ModerationCase.filer_membership_id)
                .where(
                    ModerationCase.review_id.in_(review_ids),
                    ModerationCase.filer_org_id == actor.organization_id,
                    Membership.role.in_(PROVIDER_ROLES),
                )
                .order_by(ModerationCase.id.desc())
            )
            for case in (await session.execute(side_cases)).scalars():
                if case.review_id is not None:
                    complaints.setdefault(case.review_id, case)
        loaded = await _load_review_page(session, [review for review, _ in page])
        items = []
        for review, request_number in page:
            found = loaded.get(review.id)
            if found is None:
                continue
            version = found.version
            reply = found.reply
            found_case = complaints.get(review.id)
            items.append(
                ProviderReviewView(
                    id=ids.encode("review", review.id),
                    request_id=ids.encode("request", review.request_id),
                    request_number=request_number,
                    rating=version.rating,
                    text=version.text_body,
                    author_display_name=author_display_name(review, found.customer_org),
                    reply=to_reply_view(reply) if reply is not None else None,
                    photo_attachment_ids=found.photo_attachment_ids,
                    order_occurred_at=review.order_occurred_at,
                    published_at=version.created_at,
                    complaint=(
                        ComplaintBriefView(
                            id=ids.encode("moderation_case", found_case.id),
                            status=found_case.status,
                        )
                        if found_case is not None
                        else None
                    ),
                )
            )
        return items, next_cursor


async def list_reviews_for_provider(
    actor: IntegrationActor, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[PublicReviewView], uuid.UUID | None]:
    """`GET /reviews` интеграционного API: опубликованные отзывы своей компании."""
    policy.require_reviews_read(actor)
    return await list_published_reviews(actor.organization_id, cursor=cursor, limit=limit)


async def get_rating_summary(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> RatingSummaryView:
    aggregate = (
        await session.execute(
            select(ProviderRatingAggregate).where(
                ProviderRatingAggregate.provider_org_id == provider_org_id
            )
        )
    ).scalar_one_or_none()
    if aggregate is None:
        return to_rating_summary(average=None, unique_customers=0, published_reviews_count=0)
    return to_rating_summary(
        average=float(aggregate.average_rating) if aggregate.average_rating is not None else None,
        unique_customers=aggregate.unique_reviewer_orgs_count,
        published_reviews_count=aggregate.published_reviews_count,
    )


async def get_rating_summaries(
    session: AsyncSession, provider_org_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RatingSummaryView]:
    if not provider_org_ids:
        return {}
    rows = (
        await session.execute(
            select(ProviderRatingAggregate).where(
                ProviderRatingAggregate.provider_org_id.in_(provider_org_ids)
            )
        )
    ).scalars()
    result: dict[uuid.UUID, RatingSummaryView] = {}
    for aggregate in rows:
        result[aggregate.provider_org_id] = to_rating_summary(
            average=float(aggregate.average_rating)
            if aggregate.average_rating is not None
            else None,
            unique_customers=aggregate.unique_reviewer_orgs_count,
            published_reviews_count=aggregate.published_reviews_count,
        )
    for provider_org_id in provider_org_ids:
        result.setdefault(
            provider_org_id,
            to_rating_summary(average=None, unique_customers=0, published_reviews_count=0),
        )
    return result


async def list_my_complaints(
    actor: Actor, *, cursor: uuid.UUID | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[ComplaintView], uuid.UUID | None]:
    if not isinstance(actor, UserActor):
        raise Forbidden()
    async with db_session.transaction() as session:
        side_roles = CUSTOMER_ROLES if actor.side == "customer" else PROVIDER_ROLES
        stmt = (
            select(ModerationCase)
            .join(Membership, Membership.id == ModerationCase.filer_membership_id)
            .where(
                ModerationCase.filer_org_id == actor.organization_id,
                Membership.role.in_(side_roles),
            )
            .order_by(ModerationCase.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            stmt = stmt.where(ModerationCase.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda case: case.id)
        return [to_complaint_view(case) for case in page], next_cursor


async def list_review_queue(
    actor: Actor,
    *,
    status: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[ReviewOperatorView], uuid.UUID | None]:
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        stmt = select(Review).order_by(Review.id).limit(limit + 1)
        stmt = stmt.where(Review.moderation_status == status) if status else stmt
        if cursor is not None:
            stmt = stmt.where(Review.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda review: review.id)
        items = []
        for review in page:
            items.append(await _review_operator_view(session, review))
        return items, next_cursor


async def get_review_operator(actor: Actor, review_id: uuid.UUID) -> ReviewOperatorView:
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        review = await session.get(Review, review_id)
        if review is None:
            raise NotFound()
        return await _review_operator_view(session, review)


async def _review_operator_view(session: AsyncSession, review: Review) -> ReviewOperatorView:
    customer_org = await session.get(Organization, review.customer_org_id)
    provider_org = await session.get(Organization, review.provider_org_id)
    assert customer_org is not None and provider_org is not None
    reply = await review_reply(session, review.id)
    signals = await fraud.collect_fraud_signals(session, review, now=utcnow())
    return to_review_operator_view(
        review,
        customer_org=customer_org,
        provider_org=provider_org,
        has_reply=reply is not None,
        fraud_signals=signals,
    )


async def list_moderation_case_queue(
    actor: Actor,
    *,
    subject_type: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[ModerationCaseOperatorView], uuid.UUID | None]:
    """`kind` — вид дела из `evidence.kind`: `appeal` (обжалование) или вид жалобы."""
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        stmt = select(ModerationCase).order_by(ModerationCase.id).limit(limit + 1)
        if subject_type is not None:
            stmt = stmt.where(ModerationCase.subject_type == subject_type)
        if kind is not None:
            stmt = stmt.where(ModerationCase.evidence["kind"].astext == kind)
        if status is not None:
            stmt = stmt.where(ModerationCase.status == status)
        if cursor is not None:
            stmt = stmt.where(ModerationCase.id > cursor)
        rows = list((await session.execute(stmt)).scalars())
        page, next_cursor = _paginate(rows, limit, lambda case: case.id)
        items = []
        for case in page:
            filer_org = (
                await session.get(Organization, case.filer_org_id)
                if case.filer_org_id is not None
                else None
            )
            items.append(to_moderation_case_operator_view(case, filer_org=filer_org))
        return items, next_cursor


def _profile_appeals(provider_profile_id: uuid.UUID) -> Select[tuple[ModerationCase]]:
    return (
        select(ModerationCase)
        .where(
            ModerationCase.subject_type == ModerationSubjectType.PROVIDER_PROFILE.value,
            ModerationCase.provider_profile_id == provider_profile_id,
            ModerationCase.evidence["kind"].astext == "appeal",
        )
        .order_by(ModerationCase.id.desc())
    )


async def open_profile_appeal(
    session: AsyncSession, provider_profile_id: uuid.UUID
) -> ModerationCase | None:
    stmt = _profile_appeals(provider_profile_id).where(
        ModerationCase.status == ModerationStatus.PENDING.value
    )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def open_review_appeal(
    session: AsyncSession, review_id: uuid.UUID, filer_org_id: uuid.UUID
) -> ModerationCase | None:
    """Открытое обжалование отзыва от этой стороны — не больше одного."""
    stmt = select(ModerationCase).where(
        ModerationCase.subject_type == ModerationSubjectType.REVIEW.value,
        ModerationCase.review_id == review_id,
        ModerationCase.filer_org_id == filer_org_id,
        ModerationCase.status == ModerationStatus.PENDING.value,
        ModerationCase.evidence["kind"].astext == "appeal",
    )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def get_profile_appeal(
    session: AsyncSession, provider_profile_id: uuid.UUID
) -> ProfileAppealView | None:
    """Последнее обжалование профиля — для статуса в собственном профиле исполнителя."""
    case = (
        await session.execute(_profile_appeals(provider_profile_id).limit(1))
    ).scalar_one_or_none()
    return to_profile_appeal_view(case) if case is not None else None


async def get_moderation_case_operator(
    actor: Actor, case_id: uuid.UUID
) -> ModerationCaseOperatorView:
    policy.require_operator(actor)
    async with db_session.transaction() as session:
        case = await session.get(ModerationCase, case_id)
        if case is None:
            raise NotFound()
        filer_org = (
            await session.get(Organization, case.filer_org_id)
            if case.filer_org_id is not None
            else None
        )
        return to_moderation_case_operator_view(case, filer_org=filer_org)


__all__ = [
    "author_display_name",
    "ensure_customer_request",
    "find_review",
    "get_moderation_case_operator",
    "get_rating_summaries",
    "get_rating_summary",
    "get_review_operator",
    "get_review_state",
    "latest_published_version",
    "list_moderation_case_queue",
    "list_my_complaints",
    "list_published_reviews",
    "list_review_queue",
    "list_reviews_for_provider",
    "no_show_assignment",
    "photo_attachment_ids",
    "pick_review_target",
    "review_reply",
    "review_targets",
]
