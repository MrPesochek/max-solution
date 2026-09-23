from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core import ids
from app.db.enums import ModerationStatus
from app.db.models import ModerationCase, Organization, Review, ReviewReply, ReviewVersion
from app.infra.config import get_settings

CONFIRMED_CUSTOMER_LABEL = "Подтверждённый бизнес-клиент"


class ReviewReplyView(BaseModel):
    id: str
    body: str
    created_at: datetime
    updated_at: datetime


class ReviewPublishedSnapshotView(BaseModel):
    """Версия, которая реально видна публично: может отставать от последней правки
    автора, если новая правка ещё не прошла модерацию (ТЗ 8.3.2)."""

    version: int
    rating: int
    text: str | None
    published_at: datetime


class MyReviewView(BaseModel):
    """Отзыв глазами его автора: последняя (возможно, ещё не промодерированная) правка."""

    id: str
    request_id: str
    assignment_id: str
    provider_organization_id: str
    rating: int
    text: str | None
    show_customer_name: bool
    moderation_status: str
    moderation_reason: str | None
    version: int
    suspected_fraud: bool
    reply: ReviewReplyView | None
    published: ReviewPublishedSnapshotView | None
    photo_attachment_ids: list[str]
    created_at: datetime
    updated_at: datetime


class ReviewEligibilityView(BaseModel):
    can_submit: bool
    mode: str | None
    reason_code: str | None
    reason_message: str | None
    allow_no_show_complaint: bool
    assignment_id: str | None = None


class RequestReviewStateView(BaseModel):
    review: MyReviewView | None
    eligibility: ReviewEligibilityView


class PublicReviewView(BaseModel):
    """Опубликованная версия отзыва — то, что видит рынок (ТЗ 8.3.2)."""

    id: str
    provider_organization_id: str
    rating: int
    text: str | None
    author_display_name: str
    reply: ReviewReplyView | None
    photo_attachment_ids: list[str]
    order_occurred_at: datetime
    published_at: datetime


class RatingSummaryView(BaseModel):
    average: float | None
    unique_customers: int
    published_reviews_count: int
    label: str | None


class ComplaintView(BaseModel):
    id: str
    subject_type: str
    status: str
    description: str | None
    decision_reason: str | None
    appeal_status: str | None
    created_at: datetime
    updated_at: datetime
    subject_id: str | None = None
    review_id: str | None = None
    reason_code: str | None = None


class ComplaintBriefView(BaseModel):
    id: str
    status: str


class ProviderReviewView(BaseModel):
    """Отзыв о своей компании глазами исполнителя: опубликованная версия, номер
    заявки и последнее оспаривание. Номер заявки в публичный отзыв не попадает."""

    id: str
    request_id: str
    request_number: int
    rating: int
    text: str | None
    author_display_name: str
    reply: ReviewReplyView | None
    photo_attachment_ids: list[str]
    order_occurred_at: datetime
    published_at: datetime
    complaint: ComplaintBriefView | None = None


class ProfileAppealView(BaseModel):
    """Последнее обжалование отказа/приостановки профиля (ТЗ 6.5.1).

    `status` — `pending` на рассмотрении, `resolved` — оператор принял решение;
    `decision` — решение по делу, `decision_reason` — его основание.
    """

    id: str
    status: str
    decision: str | None
    decision_reason: str | None
    created_at: datetime
    resolved_at: datetime | None


class ReviewOperatorView(BaseModel):
    id: str
    request_id: str
    customer_organization_id: str
    customer_organization_name: str
    provider_organization_id: str
    provider_organization_name: str
    rating: int
    text: str | None
    show_customer_name: bool
    moderation_status: str
    moderation_reason: str | None
    suspected_fraud: bool
    version: int
    has_reply: bool
    fraud_signals: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ModerationCaseOperatorView(BaseModel):
    id: str
    subject_type: str
    status: str
    filer_organization_id: str | None
    filer_organization_name: str | None
    review_id: str | None
    provider_profile_id: str | None
    attachment_id: str | None
    assignment_id: str | None
    evidence: dict[str, Any]
    decision_reason: str | None
    appeal_status: str | None
    created_at: datetime
    updated_at: datetime


def to_reply_view(reply: ReviewReply) -> ReviewReplyView:
    return ReviewReplyView(
        id=ids.encode("review_reply", reply.id),
        body=reply.body,
        created_at=reply.created_at,
        updated_at=reply.updated_at,
    )


def to_published_snapshot(version: ReviewVersion | None) -> ReviewPublishedSnapshotView | None:
    if version is None:
        return None
    return ReviewPublishedSnapshotView(
        version=version.version,
        rating=version.rating,
        text=version.text_body,
        published_at=version.created_at,
    )


def to_my_review_view(
    review: Review,
    *,
    reply: ReviewReply | None,
    published_version: ReviewVersion | None,
    photo_attachment_ids: list[str],
) -> MyReviewView:
    return MyReviewView(
        id=ids.encode("review", review.id),
        request_id=ids.encode("request", review.request_id),
        assignment_id=ids.encode("assignment", review.assignment_id),
        provider_organization_id=ids.encode("organization", review.provider_org_id),
        rating=review.rating,
        text=review.text_body,
        show_customer_name=review.show_customer_name,
        moderation_status=review.moderation_status,
        moderation_reason=review.moderation_reason,
        version=review.current_version,
        suspected_fraud=review.suspected_fraud,
        reply=to_reply_view(reply) if reply is not None else None,
        published=to_published_snapshot(published_version),
        photo_attachment_ids=photo_attachment_ids,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def author_display_name(review: Review, customer_org: Organization) -> str:
    return customer_org.display_name if review.show_customer_name else CONFIRMED_CUSTOMER_LABEL


def to_public_review_view(
    review: Review,
    version: ReviewVersion,
    *,
    customer_org: Organization,
    reply: ReviewReply | None,
    photo_attachment_ids: list[str],
) -> PublicReviewView:
    return PublicReviewView(
        id=ids.encode("review", review.id),
        provider_organization_id=ids.encode("organization", review.provider_org_id),
        rating=version.rating,
        text=version.text_body,
        author_display_name=author_display_name(review, customer_org),
        reply=to_reply_view(reply) if reply is not None else None,
        photo_attachment_ids=photo_attachment_ids,
        order_occurred_at=review.order_occurred_at,
        published_at=version.created_at,
    )


def to_rating_summary(
    *,
    average: float | None,
    unique_customers: int,
    published_reviews_count: int,
) -> RatingSummaryView:
    settings = get_settings()
    label = (
        None
        if unique_customers >= settings.rating_min_unique_orgs
        else settings.rating_no_reviews_label
    )
    return RatingSummaryView(
        average=average if label is None else None,
        unique_customers=unique_customers,
        published_reviews_count=published_reviews_count,
        label=label,
    )


def to_complaint_view(case: ModerationCase) -> ComplaintView:
    return ComplaintView(
        id=ids.encode("moderation_case", case.id),
        subject_type=case.subject_type,
        status=case.status,
        description=(case.evidence or {}).get("description") if case.evidence else None,
        decision_reason=case.decision_reason,
        appeal_status=case.appeal_status,
        created_at=case.created_at,
        updated_at=case.updated_at,
        subject_id=_complaint_subject_id(case),
        review_id=ids.encode_opt("review", case.review_id),
        reason_code=(case.evidence or {}).get("reason_code") if case.evidence else None,
    )


def _complaint_subject_id(case: ModerationCase) -> str | None:
    if case.review_id is not None:
        return ids.encode("review", case.review_id)
    if case.attachment_id is not None:
        return ids.encode("attachment", case.attachment_id)
    if case.provider_profile_id is not None:
        return ids.encode("provider_profile", case.provider_profile_id)
    if case.assignment_id is not None:
        return ids.encode("assignment", case.assignment_id)
    return None


def to_profile_appeal_view(case: ModerationCase) -> ProfileAppealView:
    resolved = case.status != ModerationStatus.PENDING.value
    return ProfileAppealView(
        id=ids.encode("moderation_case", case.id),
        status=case.appeal_status or ("resolved" if resolved else "pending"),
        decision=case.status if resolved else None,
        decision_reason=case.decision_reason,
        created_at=case.created_at,
        resolved_at=case.appeal_resolved_at,
    )


def to_review_operator_view(
    review: Review,
    *,
    customer_org: Organization,
    provider_org: Organization,
    has_reply: bool,
    fraud_signals: dict[str, Any],
) -> ReviewOperatorView:
    return ReviewOperatorView(
        id=ids.encode("review", review.id),
        request_id=ids.encode("request", review.request_id),
        customer_organization_id=ids.encode("organization", review.customer_org_id),
        customer_organization_name=customer_org.display_name,
        provider_organization_id=ids.encode("organization", review.provider_org_id),
        provider_organization_name=provider_org.display_name,
        rating=review.rating,
        text=review.text_body,
        show_customer_name=review.show_customer_name,
        moderation_status=review.moderation_status,
        moderation_reason=review.moderation_reason,
        suspected_fraud=review.suspected_fraud,
        version=review.current_version,
        has_reply=has_reply,
        fraud_signals=fraud_signals,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def to_moderation_case_operator_view(
    case: ModerationCase, *, filer_org: Organization | None
) -> ModerationCaseOperatorView:
    return ModerationCaseOperatorView(
        id=ids.encode("moderation_case", case.id),
        subject_type=case.subject_type,
        status=case.status,
        filer_organization_id=ids.encode_opt("organization", case.filer_org_id),
        filer_organization_name=filer_org.display_name if filer_org is not None else None,
        review_id=ids.encode_opt("review", case.review_id),
        provider_profile_id=ids.encode_opt("provider_profile", case.provider_profile_id),
        attachment_id=ids.encode_opt("attachment", case.attachment_id),
        assignment_id=ids.encode_opt("assignment", case.assignment_id),
        evidence=case.evidence or {},
        decision_reason=case.decision_reason,
        appeal_status=case.appeal_status,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )
