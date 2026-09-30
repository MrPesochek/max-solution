from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    loop_name: Mapped[str] = mapped_column(Text, primary_key=True)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processed: Mapped[int | None] = mapped_column(Integer)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
