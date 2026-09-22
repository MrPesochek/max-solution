import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class IntegrationClient(IdMixin, TimestampsMixin, Base):
    __tablename__ = "integration_clients"

    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"), nullable=False)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalReference(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "external_references"

    integration_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_clients.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)


class WebhookSubscription(IdMixin, TimestampsMixin, Base):
    __tablename__ = "webhook_subscriptions"

    integration_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_clients.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    event_types: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"), nullable=False)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationEvent(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "integration_events"

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    feed_seq: Mapped[int | None] = mapped_column(BigInteger)
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_version: Mapped[int | None] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class IntegrationFeedCounter(Base):
    """Последний выданный `feed_seq` получателя. Не зависит от уборки событий:
    после удаления старых строк нумерация продолжается, а не начинается заново."""

    __tablename__ = "integration_feed_counters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), primary_key=True
    )
    last_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), nullable=False)


class WebhookDelivery(IdMixin, TimestampsMixin, Base):
    __tablename__ = "webhook_deliveries"

    integration_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_events.id"), nullable=False
    )
    webhook_subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhook_subscriptions.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, server_default=text("'queued'"), nullable=False)
    current_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("uuidv7()"), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
