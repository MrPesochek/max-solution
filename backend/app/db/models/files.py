import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class Attachment(IdMixin, TimestampsMixin, Base):
    __tablename__ = "attachments"

    owner_kind: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repair_requests.id")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id")
    )
    provider_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_profiles.id")
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id")
    )
    verification_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verification_cases.id")
    )
    moderation_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("moderation_cases.id")
    )
    uploaded_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    uploaded_by_integration_client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id")
    )
    slot: Mapped[str | None] = mapped_column(Text)
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id")
    )
    publication_state: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    visibility_class: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pixel_width: Mapped[int | None] = mapped_column(Integer)
    pixel_height: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    processing_state: Mapped[str] = mapped_column(
        Text, server_default=text("'quarantined'"), nullable=False
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[bytes | None] = mapped_column(LargeBinary)


class AttachmentVariant(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "attachment_variants"

    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id"), nullable=False
    )
    variant_kind: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pixel_width: Mapped[int | None] = mapped_column(Integer)
    pixel_height: Mapped[int | None] = mapped_column(Integer)
    exif_stripped: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
