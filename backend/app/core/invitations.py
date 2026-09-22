from datetime import datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.db.enums import InvitationKind, InvitationState
from app.db.models import Invitation


def invitation_invalid(reason: str | None = None) -> Conflict:
    if reason == "expired":
        return Conflict(
            "Срок действия приглашения истёк", code="INVITATION_INVALID", reason="expired"
        )
    return Conflict("Приглашение недействительно", code="INVITATION_INVALID")


async def explain_failed_claim(
    session: AsyncSession,
    match: ColumnElement[bool],
    kind: InvitationKind,
    now: datetime,
) -> Conflict:
    """Почему атомарное погашение не сработало. Срок оценивается по `now`,
    независимо от того, успел ли sweeper перевести строку в `expired`."""
    row = (await session.execute(select(Invitation).where(match))).scalar_one_or_none()
    if row is None or row.kind != kind:
        return invitation_invalid()
    if row.status == InvitationState.EXPIRED or (
        row.status == InvitationState.PENDING and row.expires_at <= now
    ):
        return invitation_invalid("expired")
    return invitation_invalid()
