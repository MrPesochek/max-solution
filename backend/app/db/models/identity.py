import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class User(IdMixin, TimestampsMixin, Base):
    __tablename__ = "users"

    max_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    bot_available: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    bot_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organization(IdMixin, TimestampsMixin, Base):
    __tablename__ = "organizations"

    is_customer: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_provider: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_form: Mapped[str | None] = mapped_column(Text)
    inn_raw: Mapped[str | None] = mapped_column(Text)
    inn_normalized: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    representative_position: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    details_verification_status: Mapped[str] = mapped_column(
        Text, server_default=text("'unverified'"), nullable=False
    )
    details_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    representative_verification_status: Mapped[str] = mapped_column(
        Text, server_default=text("'unverified'"), nullable=False
    )
    representative_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(IdMixin, TimestampsMixin, Base):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    invited_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="SET NULL")
    )


class MembershipLocation(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "membership_locations"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False
    )


class PlatformRole(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "platform_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    active_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    active_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    init_data_key: Mapped[bytes | None] = mapped_column(LargeBinary)


class UsedInitData(Base):
    """Ключ уже предъявленного initData: строка блокируется на время выдачи сессии (D-S2)."""

    __tablename__ = "used_init_data"

    digest: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoginLink(IdMixin, CreatedAtMixin, Base):
    """Одноразовый вход в Web App по ссылке из бота (D-S3): в БД только хеш токена."""

    __tablename__ = "login_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    target: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "invitations"

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    target_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    role: Mapped[str | None] = mapped_column(Text)
    location_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
    binding_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    equipment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'"), nullable=False
    )
    service_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_contracts.id")
    )
    recipient_max_user_id: Mapped[str | None] = mapped_column(Text)
    recipient_name: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    decline_reason: Mapped[str | None] = mapped_column(Text)
