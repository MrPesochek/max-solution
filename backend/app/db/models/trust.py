import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, Boolean, Date, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampsMixin


class VerificationCase(IdMixin, TimestampsMixin, Base):
    __tablename__ = "verification_cases"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    check_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    operator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    decision: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verification_cases.id")
    )


class WarrantyAuthorization(IdMixin, TimestampsMixin, Base):
    __tablename__ = "warranty_authorizations"

    guarantor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    guarantor_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    guarantor_name: Mapped[str | None] = mapped_column(Text)
    authorized_provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    equipment_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id")
    )
    brand_scope: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    territory_city_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cities.id")
    )
    source_verification_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verification_cases.id")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)


class ServiceContract(IdMixin, TimestampsMixin, Base):
    __tablename__ = "service_contracts"

    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    customer_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    contract_number: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id")
    )


class ServiceBinding(IdMixin, TimestampsMixin, Base):
    __tablename__ = "service_bindings"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment.id"), nullable=False
    )
    customer_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    provider_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    personal_contact_name: Mapped[str | None] = mapped_column(Text)
    personal_contact_phone: Mapped[str | None] = mapped_column(Text)
    claimed_contract_number: Mapped[str | None] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(Text)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_contracts.id")
    )
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    guarantor_kind: Mapped[str | None] = mapped_column(Text)
    guarantor_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    warranty_authorization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warranty_authorizations.id")
    )
    stated_guarantor_name: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    customer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id")
    )
    invitation_item_index: Mapped[int | None] = mapped_column(Integer)
    created_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id"), nullable=False
    )
