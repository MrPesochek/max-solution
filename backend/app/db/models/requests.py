import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class RepairRequest(IdMixin, TimestampsMixin, Base):
    __tablename__ = "repair_requests"

    request_number: Mapped[int] = mapped_column(
        BigInteger, server_default=text("nextval('request_number_seq')"), nullable=False
    )
    customer_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id"), nullable=False
    )
    author_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
    route: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    urgency: Mapped[str] = mapped_column(Text, server_default=text("'normal'"), nullable=False)
    symptom_description: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    equipment_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    location_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    closure_kind: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    disputed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    search_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id")
    )
    photos_incomplete: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    photos_incomplete_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestPublicCard(IdMixin, TimestampsMixin, Base):
    __tablename__ = "request_public_cards"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    equipment_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cities.id"), nullable=False
    )
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("districts.id")
    )
    urgency: Mapped[str] = mapped_column(Text, nullable=False)
    published_description: Mapped[str | None] = mapped_column(Text)
    published_attachment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'::uuid[]"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Assignment(IdMixin, TimestampsMixin, Base):
    __tablename__ = "assignments"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    route: Mapped[str] = mapped_column(Text, nullable=False)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("offers.id"))
    state: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    field_worker_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    field_worker_display_name: Mapped[str | None] = mapped_column(Text)
    field_worker_contact_phone: Mapped[str | None] = mapped_column(Text)
    warranty_decision: Mapped[str] = mapped_column(
        Text, server_default=text("'not_stated'"), nullable=False
    )
    warranty_decision_comment: Mapped[str | None] = mapped_column(Text)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(Text)
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    en_route_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Offer(IdMixin, TimestampsMixin, Base):
    __tablename__ = "offers"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    visit_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visit_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visit_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    vat_mode: Mapped[str | None] = mapped_column(Text)
    zero_cost_reason: Mapped[str | None] = mapped_column(Text)
    scope_description: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    access_requirements: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, server_default=text("'active'"), nullable=False)
    superseded_by_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("offers.id")
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )


class VisitProposal(IdMixin, TimestampsMixin, Base):
    __tablename__ = "visit_proposals"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    visit_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visit_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visit_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    vat_mode: Mapped[str | None] = mapped_column(Text)
    zero_cost_reason: Mapped[str | None] = mapped_column(Text)
    scope_description: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    access_requirements: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    response_comment: Mapped[str | None] = mapped_column(Text)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )


class RepairQuote(IdMixin, TimestampsMixin, Base):
    __tablename__ = "repair_quotes"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    description_of_work: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    vat_mode: Mapped[str | None] = mapped_column(Text)
    zero_cost_reason: Mapped[str | None] = mapped_column(Text)
    warranty_terms: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    response_comment: Mapped[str | None] = mapped_column(Text)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )


class CancellationRequest(IdMixin, TimestampsMixin, Base):
    __tablename__ = "cancellation_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    target: Mapped[str] = mapped_column(Text, nullable=False)
    previous_status: Mapped[str] = mapped_column(Text, nullable=False)
    initiated_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    provider_response: Mapped[str | None] = mapped_column(Text)
    disputed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    dispute_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_kind: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    visibility_scope: Mapped[str] = mapped_column(
        Text, server_default=text("'all_participants'"), nullable=False
    )
    thread_provider_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assignments.id")
    )
    author_kind: Mapped[str] = mapped_column(Text, nullable=False)
    author_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    author_integration_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_clients.id")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_label: Mapped[str | None] = mapped_column(Text)


class MessageRead(IdMixin, Base):
    __tablename__ = "message_reads"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
    last_read_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id")
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequestEvent(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "request_events"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    actor_integration_client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
