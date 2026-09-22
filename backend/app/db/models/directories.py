import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampsMixin


class City(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "cities"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        Text, server_default=text("'Europe/Moscow'"), nullable=False
    )


class District(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "districts"

    city_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cities.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)


class EquipmentCategory(IdMixin, TimestampsMixin, Base):
    __tablename__ = "equipment_categories"

    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    photo_template: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
