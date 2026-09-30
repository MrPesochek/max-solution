import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db_session
from app.db.enums import AttachmentState, AttachmentVariantKind, VisibilityClass
from app.db.models import Attachment, AttachmentVariant
from app.infra.config import get_settings
from app.infra.images.processor import ImageRejected, ProcessedImage
from app.infra.images.runner import process_image_isolated
from app.infra.storage.base import FileStorage
from app.modules.files import queries
from app.modules.files.storage import get_storage
from app.modules.files.views import MIME_BY_FORMAT

log = structlog.get_logger("files.images")

SAFE_SUFFIX = ".safe"
THUMB_SUFFIX = ".thumb"


@dataclass(frozen=True, slots=True)
class Job:
    attachment_id: uuid.UUID
    storage_key: str
    visibility_class: str
    attempts: int
    source_id: uuid.UUID | None


async def run_once(now: datetime) -> int:
    jobs = await lease(now)
    for job in jobs:
        try:
            if job.source_id is not None:
                await _materialize(job.attachment_id)
            else:
                await _process(job)
        except Exception:
            log.exception("image_job_failed", attachment_id=str(job.attachment_id))
    return len(jobs)


async def lease(now: datetime) -> list[Job]:
    settings = get_settings()
    lease_span = timedelta(seconds=settings.image_processing_lease_seconds)
    jobs: list[Job] = []
    async with db_session.transaction() as session:
        stmt = (
            select(Attachment)
            .where(
                Attachment.processing_state == AttachmentState.QUARANTINED,
                or_(Attachment.lease_until.is_(None), Attachment.lease_until <= now),
            )
            .order_by(Attachment.id)
            .limit(settings.image_processing_batch)
            .with_for_update(skip_locked=True)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        for row in rows:
            attempts = row.attempt_count + 1
            if attempts > settings.image_processing_max_attempts:
                row.processing_state = AttachmentState.REJECTED
                row.rejected_reason = "processing_failed"
                row.lease_until = None
                continue
            row.attempt_count = attempts
            row.lease_until = now + lease_span
            jobs.append(
                Job(
                    attachment_id=row.id,
                    storage_key=row.storage_key,
                    visibility_class=row.visibility_class,
                    attempts=attempts,
                    source_id=row.source_attachment_id,
                )
            )
    return jobs


async def _process(job: Job) -> None:
    storage = get_storage()
    settings = get_settings()
    try:
        data = await _read(storage, job.storage_key)
    except FileNotFoundError:
        await _reject(job.attachment_id, "missing_file")
        return

    try:
        processed = await process_image_isolated(
            data,
            max_pixels=settings.max_image_pixels,
            max_bytes=settings.max_upload_bytes,
            timeout=settings.image_processing_timeout_seconds,
            memory_limit_bytes=settings.image_processing_memory_bytes,
        )
    except ImageRejected as exc:
        await _reject(job.attachment_id, exc.code)
        return

    safe_key = job.storage_key + SAFE_SUFFIX
    thumb_key = job.storage_key + THUMB_SUFFIX
    await storage.put(safe_key, processed.data)
    await storage.put(thumb_key, processed.thumbnail)

    keep_original = (
        settings.keep_originals or job.visibility_class == VisibilityClass.VERIFICATION_EVIDENCE
    )
    await _finish(job, processed, safe_key=safe_key, thumb_key=thumb_key, keep=keep_original)
    if not keep_original:
        await storage.delete(job.storage_key)


async def _finish(
    job: Job,
    processed: ProcessedImage,
    *,
    safe_key: str,
    thumb_key: str,
    keep: bool,
) -> None:
    mime = MIME_BY_FORMAT[str(processed.format)]
    async with db_session.transaction() as session:
        row = await session.get(Attachment, job.attachment_id, with_for_update=True)
        if row is None or row.processing_state != AttachmentState.QUARANTINED:
            return
        original = (row.storage_key, row.mime_type, row.byte_size, None, None)
        row.processing_state = AttachmentState.READY
        row.rejected_reason = None
        row.lease_until = None
        row.mime_type = mime
        row.pixel_width = processed.width
        row.pixel_height = processed.height
        row.content_hash = bytes.fromhex(processed.sha256_original)
        await _replace_variants(
            session,
            row,
            {
                AttachmentVariantKind.SAFE_COPY: (
                    safe_key,
                    mime,
                    len(processed.data),
                    processed.width,
                    processed.height,
                ),
                AttachmentVariantKind.PREVIEW: (
                    thumb_key,
                    mime,
                    len(processed.thumbnail),
                    None,
                    None,
                ),
                **({AttachmentVariantKind.ORIGINAL: original} if keep else {}),
            },
        )


async def _replace_variants(
    session: AsyncSession,
    row: Attachment,
    variants: dict[str, tuple[str, str, int, int | None, int | None]],
) -> None:
    existing = {
        variant.variant_kind: variant for variant in await queries.variants_of(session, row.id)
    }
    for kind, (key, mime, size, width, height) in variants.items():
        variant = existing.get(kind)
        if variant is None:
            variant = AttachmentVariant(attachment_id=row.id, variant_kind=kind)
            session.add(variant)
        variant.storage_key = key
        variant.mime_type = mime
        variant.byte_size = size
        variant.pixel_width = width
        variant.pixel_height = height
        variant.exif_stripped = kind != AttachmentVariantKind.ORIGINAL
    await session.flush()


async def _reject(attachment_id: uuid.UUID, reason: str) -> None:
    async with db_session.transaction() as session:
        row = await session.get(Attachment, attachment_id, with_for_update=True)
        if row is None or row.processing_state != AttachmentState.QUARANTINED:
            return
        row.processing_state = AttachmentState.REJECTED
        row.rejected_reason = reason
        row.lease_until = None
    log.info("image_rejected", attachment_id=str(attachment_id), reason=reason)


def materialize_later(copy_ids: list[uuid.UUID]) -> Callable[[], Awaitable[None]]:

    async def run() -> None:
        for copy_id in copy_ids:
            await _materialize(copy_id)

    return run


async def _materialize(attachment_id: uuid.UUID) -> None:
    storage = get_storage()
    async with db_session.get_sessionmaker()() as session:
        copy = await session.get(Attachment, attachment_id)
        if copy is None or copy.processing_state != AttachmentState.QUARANTINED:
            return
        source_id = copy.source_attachment_id
        if source_id is None:
            return
        safe = await queries.variant_of(session, source_id, AttachmentVariantKind.SAFE_COPY)
        preview = await queries.variant_of(session, source_id, AttachmentVariantKind.PREVIEW)
        copy_key = copy.storage_key
        if safe is None:
            return
        safe_source, preview_source = safe.storage_key, preview.storage_key if preview else None
        safe_meta = (safe.mime_type, safe.byte_size, safe.pixel_width, safe.pixel_height)
        preview_meta = (
            (preview.mime_type, preview.byte_size, preview.pixel_width, preview.pixel_height)
            if preview is not None
            else None
        )

    thumb_key = copy_key + THUMB_SUFFIX
    await storage.put(copy_key, await _read(storage, safe_source))
    if preview_source is not None:
        await storage.put(thumb_key, await _read(storage, preview_source))

    async with db_session.transaction() as session:
        row = await session.get(Attachment, attachment_id, with_for_update=True)
        if row is None or row.processing_state != AttachmentState.QUARANTINED:
            return
        row.processing_state = AttachmentState.READY
        row.rejected_reason = None
        row.lease_until = None
        row.mime_type = safe_meta[0]
        row.byte_size = safe_meta[1]
        row.pixel_width = safe_meta[2]
        row.pixel_height = safe_meta[3]
        variants: dict[str, tuple[str, str, int, int | None, int | None]] = {
            AttachmentVariantKind.SAFE_COPY: (
                copy_key,
                safe_meta[0],
                safe_meta[1],
                safe_meta[2],
                safe_meta[3],
            )
        }
        if preview_meta is not None:
            variants[AttachmentVariantKind.PREVIEW] = (
                thumb_key,
                preview_meta[0],
                preview_meta[1],
                preview_meta[2],
                preview_meta[3],
            )
        await _replace_variants(session, row, variants)
    log.info("attachment_copy_ready", attachment_id=str(attachment_id))


async def _read(storage: FileStorage, key: str) -> bytes:
    chunks = [chunk async for chunk in storage.open(key)]
    return b"".join(chunks)
