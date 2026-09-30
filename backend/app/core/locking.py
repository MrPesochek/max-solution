import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, VersionConflict


async def lock_by_id[T](session: AsyncSession, model: type[T], row_id: uuid.UUID) -> T:
    stmt = select(model).where(model.id == row_id).with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFound()
    return row


def check_version(current: int, expected: int | None) -> None:
    if expected is not None and expected != current:
        raise VersionConflict(current)


async def advisory_xact_lock(session: AsyncSession, *keys: str) -> None:
    for key in sorted(set(keys)):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
