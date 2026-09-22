import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class ProviderProfile(IdMixin, TimestampsMixin, Base):
    __tablename__ = "provider_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text)
    accepting_new_requests: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    visit_terms: Mapped[str | None] = mapped_column(Text)
    visit_price_from_minor: Mapped[int | None] = mapped_column(BigInteger)
    can_provide_documents: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)


class ProviderCategory(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "provider_categories"

    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    equipment_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )


class ProviderServiceArea(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "provider_service_areas"

    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cities.id"), nullable=False
    )
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("districts.id")
    )


class ProviderBrandRestriction(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "provider_brand_restrictions"

    provider_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    equipment_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    brand: Mapped[str] = mapped_column(Text, nullable=False)
