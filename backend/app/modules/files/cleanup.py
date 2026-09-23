from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db_session
from app.db.enums import AttachmentState, ModerationStatus, ModerationSubjectType, VisibilityClass
from app.db.models import Attachment, AttachmentVariant, ModerationCase
from app.infra.config import get_settings
from app.modules.files import commands, queries
from app.modules.files.storage import get_storage

log = structlog.get_logger("files.cleanup")


async def run_once(now: datetime) -> int:
    settings = get_settings()
    removed = await _drop(
        select(Attachment).where(
            Attachment.processing_state == AttachmentState.REJECTED,
            Attachment.updated_at < now - timedelta(days=settings.rejected_files_retention_days),
        ),
        settings.cleanup_batch,
    )
    removed += await _drop(
        select(Attachment)
        .join(ModerationCase, ModerationCase.attachment_id == Attachment.id)
        .where(
            Attachment.visibility_class == VisibilityClass.PUBLIC_CARD,
            ModerationCase.subject_type == ModerationSubjectType.ATTACHMENT,
            ModerationCase.status == ModerationStatus.REMOVED,
            ModerationCase.updated_at
            < now - timedelta(days=settings.revoked_copies_retention_days),
        ),
        settings.cleanup_batch,
    )
    removed += await _drop_orphan_keys(
        now, settings.orphan_files_min_age_days, settings.cleanup_batch
    )
    if removed:
        log.info("files_cleanup_done", removed=removed)
    return removed


async def _drop(stmt: Select[tuple[Attachment]], batch: int) -> int:
    keys: list[str] = []
    dropped = 0
    async with db_session.transaction() as session:
        for row in (await session.execute(stmt.limit(batch))).scalars().all():
            keys.append(row.storage_key)
            keys.extend(
                variant.storage_key for variant in await queries.variants_of(session, row.id)
            )
            await commands.purge_row(session, row)
            dropped += 1
    if keys:
        await commands.drop_keys(keys)()
    return dropped


async def _drop_orphan_keys(now: datetime, min_age_days: int, batch: int) -> int:
    """Ключи хранилища без строки в attachments/attachment_variants.

    Возраст читается из даты, зашитой в сам ключ (`make_storage_key`: `.../YYYY/MM/DD/...`,
    вариант — тот же путь с суффиксом): свежие ключи никогда не совпадают с датой
    до `cutoff`, так что незавершённая загрузка не может попасть под уборку.
    """
    cutoff = (now - timedelta(days=min_age_days)).date()
    async with db_session.transaction() as session:
        live_keys = await _live_storage_keys(session)

    storage = get_storage()
    dropped = 0
    async for key in storage.iter_keys(""):
        if dropped >= batch:
            break
        if key in live_keys:
            continue
        key_date = _key_date(key)
        if key_date is None or key_date >= cutoff:
            continue
        await storage.delete(key)
        dropped += 1
    return dropped


async def _live_storage_keys(session: AsyncSession) -> set[str]:
    keys = set((await session.execute(select(Attachment.storage_key))).scalars().all())
    keys.update((await session.execute(select(AttachmentVariant.storage_key))).scalars().all())
    return keys


def _key_date(key: str) -> date | None:
    parts = key.split("/")
    if len(parts) < 4:
        return None
    try:
        return date(int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None
