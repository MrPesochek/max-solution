import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.core.actor import UserActor
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pipeline import CommandContext
from app.db.enums import (
    AttachmentOwnerKind,
    AttachmentState,
    AttachmentVariantKind,
    ModerationStatus,
    VisibilityClass,
)
from app.db.models import Attachment, RepairRequest, Review
from app.infra.config import get_settings
from app.infra.storage.base import make_storage_key
from app.modules.files import commands, processing, queries
from app.modules.files.queries import EVIDENCE_KIND

COPY_PUBLIC_CARD = "public_card"
COPY_REVIEW = "review"


async def publish_to_public_card(
    ctx: CommandContext,
    request: RepairRequest,
    attachment_ids: Sequence[uuid.UUID],
    *,
    confirm_sensitive: bool = False,
) -> list[uuid.UUID]:
    """Создаёт публичные копии выбранных фото заявки и возвращает их идентификаторы."""
    await revoke_public_card_copies(ctx, request.id)
    if not attachment_ids:
        return []

    sources = await _load_sources(ctx, request.id, attachment_ids)
    sensitive = _require_sensitive_confirmed(sources, confirm_sensitive)

    copies: list[uuid.UUID] = []
    for source in sources:
        copy = await _copy_row(
            ctx,
            source,
            visibility_class=VisibilityClass.PUBLIC_CARD,
            owner_kind=AttachmentOwnerKind.REQUEST,
            request_id=request.id,
            review_id=None,
            status=ModerationStatus.PUBLISHED,
            kind=COPY_PUBLIC_CARD,
            prefix="public",
        )
        copies.append(copy.id)
    ctx.audit(
        "attachment.publish",
        "request",
        request.id,
        organization_id=request.customer_org_id,
        published=len(copies),
        sensitive=len(sensitive),
    )
    ctx.after_commit(processing.materialize_later(copies))
    return copies


async def revoke_public_card_copies(ctx: CommandContext, request_id: uuid.UUID) -> int:
    """Снятие карточки с публикации: копии помечаются отозванными и больше не отдаются."""
    stmt = select(Attachment).where(
        Attachment.request_id == request_id,
        Attachment.visibility_class == VisibilityClass.PUBLIC_CARD,
    )
    return await _revoke(ctx, list((await ctx.session.execute(stmt)).scalars().all()))


async def _revoke(ctx: CommandContext, copies: Sequence[Attachment]) -> int:
    revoked = 0
    for copy in copies:
        case = await queries.publication_case(ctx.session, copy.id)
        if case is None or case.status == ModerationStatus.REMOVED:
            continue
        case.status = ModerationStatus.REMOVED
        case.decision_reason = "unpublished"
        copy.publication_state = ModerationStatus.REMOVED
        revoked += 1
    return revoked


async def attach_review_photos(
    ctx: CommandContext,
    review_id: uuid.UUID,
    attachment_ids: Sequence[uuid.UUID],
    *,
    confirm_sensitive: bool = False,
) -> list[uuid.UUID]:
    """ТЗ 8.3.2: заказчик выбирает фото для отзыва; галерея заявки не переносится целиком.

    Вызывается из команды отзыва в её транзакции: копии публикуются только
    после модерации, повторная отправка отзыва заменяет прежний набор.
    """
    review = await ctx.session.get(Review, review_id)
    if review is None:
        raise NotFound()
    actor = ctx.actor
    if not isinstance(actor, UserActor) or not actor.is_manager:
        raise NotFound()
    if review.customer_org_id != actor.organization_id:
        raise NotFound()
    limit = get_settings().review_max_photos
    if len(attachment_ids) > limit:
        raise ValidationFailed(
            f"К отзыву можно приложить не больше {limit} фото",
            code="REVIEW_PHOTO_LIMIT_REACHED",
            limit=limit,
        )
    await _revoke(ctx, await queries.review_photos(ctx.session, review.id))
    if not attachment_ids:
        return []

    sources = await _load_sources(ctx, review.request_id, attachment_ids)
    _require_sensitive_confirmed(sources, confirm_sensitive)
    copies: list[uuid.UUID] = []
    for source in sources:
        copy = await _copy_row(
            ctx,
            source,
            visibility_class=VisibilityClass.REVIEW_PUBLIC,
            owner_kind=AttachmentOwnerKind.REVIEW,
            request_id=None,
            review_id=review.id,
            status=ModerationStatus.PENDING,
            kind=COPY_REVIEW,
            prefix="reviews",
        )
        copies.append(copy.id)
    ctx.audit("attachment.review_photos", "review", review.id, attached=len(copies))
    ctx.after_commit(processing.materialize_later(copies))
    return copies


def _require_sensitive_confirmed(
    sources: Sequence[Attachment], confirmed: bool
) -> list[Attachment]:
    sensitive = [
        row for row in sources if row.visibility_class == VisibilityClass.REQUEST_SENSITIVE
    ]
    if sensitive and not confirmed:
        raise ValidationFailed(
            "Фото шильдика и документов публикуются только с явным подтверждением",
            code="SENSITIVE_PHOTO_NOT_CONFIRMED",
            attachment_count=len(sensitive),
        )
    return sensitive


async def _load_sources(
    ctx: CommandContext, request_id: uuid.UUID | None, attachment_ids: Sequence[uuid.UUID]
) -> list[Attachment]:
    if not attachment_ids:
        return []
    stmt = select(Attachment).where(Attachment.id.in_(tuple(attachment_ids)))
    if request_id is not None:
        stmt = stmt.where(Attachment.request_id == request_id)
    found = {row.id: row for row in (await ctx.session.execute(stmt)).scalars().all()}
    rows: list[Attachment] = []
    for attachment_id in attachment_ids:
        row = found.get(attachment_id)
        if row is None or row.visibility_class == VisibilityClass.PUBLIC_CARD:
            raise NotFound()
        if row.processing_state != AttachmentState.READY:
            raise Conflict(
                "Фото ещё не прошло проверку",
                code="ATTACHMENT_NOT_READY",
                processing_state=row.processing_state,
            )
        rows.append(row)
    return rows


async def _copy_row(
    ctx: CommandContext,
    source: Attachment,
    *,
    visibility_class: str,
    owner_kind: str,
    request_id: uuid.UUID | None,
    review_id: uuid.UUID | None,
    status: str,
    kind: str,
    prefix: str,
) -> Attachment:
    safe = await queries.variant_of(ctx.session, source.id, AttachmentVariantKind.SAFE_COPY)
    if safe is None:
        raise Conflict("Безопасная копия ещё не готова", code="ATTACHMENT_NOT_READY")
    copy = Attachment(
        owner_kind=owner_kind,
        request_id=request_id,
        review_id=review_id,
        uploaded_by_user_id=source.uploaded_by_user_id,
        uploaded_by_membership_id=source.uploaded_by_membership_id,
        purpose=kind,
        slot=source.slot,
        source_attachment_id=source.id,
        visibility_class=visibility_class,
        mime_type=safe.mime_type,
        byte_size=safe.byte_size,
        pixel_width=safe.pixel_width,
        pixel_height=safe.pixel_height,
        storage_key=make_storage_key(prefix),
        processing_state=AttachmentState.QUARANTINED,
        content_hash=source.content_hash,
    )
    ctx.session.add(copy)
    await ctx.session.flush()
    await commands.open_moderation_case(ctx, copy, status=status, evidence={EVIDENCE_KIND: kind})
    return copy
