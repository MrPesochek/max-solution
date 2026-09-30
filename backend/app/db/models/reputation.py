import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class Review(IdMixin, TimestampsMixin, Base):
    __tablename__ = "reviews"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    customer_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    author_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text_body: Mapped[str | None] = mapped_column(Text)
    show_customer_name: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    moderation_status: Mapped[str] = mapped_column(
        Text, server_default=text("'pending'"), nullable=False
    )
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    suspected_fraud: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    current_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    order_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewVersion(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "review_versions"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text_body: Mapped[str | None] = mapped_column(Text)
    moderation_status: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )


class ReviewReply(IdMixin, TimestampsMixin, Base):
    __tablename__ = "review_replies"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    author_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class ModerationCase(IdMixin, TimestampsMixin, Base):
    __tablename__ = "moderation_cases"

    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_profiles.id")
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id")
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id")
    )
    service_binding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_bindings.id")
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id")
    )
    filer_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    filer_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    operator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    appeal_status: Mapped[str | None] = mapped_column(Text)
    appeal_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderRatingAggregate(IdMixin, Base):
    __tablename__ = "provider_rating_aggregates"

    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    average_rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    unique_reviewer_orgs_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    published_reviews_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
