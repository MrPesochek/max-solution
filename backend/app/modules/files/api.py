import uuid
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import Actor
from app.core.errors import NotFound, ValidationFailed
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.db import session as db_session
from app.db.enums import VisibilityClass
from app.db.models import Attachment, RepairRequest
from app.infra.config import get_settings
from app.modules.files import (
    cleanup,
    commands,
    moderation,
    policy,
    processing,
    publication,
    queries,
    upload,
)
from app.modules.files.errors import FileTooLarge, UnsupportedMediaType
from app.modules.files.owners import (
    AttachmentOwner,
    OwnerKind,
    equipment_owner,
    message_owner,
    provider_profile_owner,
    request_owner,
    review_owner,
    verification_owner,
)
from app.modules.files.storage import get_storage, set_storage
from app.modules.files.upload import AVATAR_PURPOSE, PORTFOLIO_PURPOSE
from app.modules.files.views import (
    AttachmentContent,
    AttachmentView,
    GalleryItemView,
    server_filename,
    to_attachment_view,
)

__all__ = [
    "AVATAR_PURPOSE",
    "PORTFOLIO_PURPOSE",
    "AttachmentContent",
    "AttachmentOwner",
    "AttachmentView",
    "FileTooLarge",
    "GalleryItemView",
    "OwnerKind",
    "UnsupportedMediaType",
    "approve_attachment",
    "attach_review_photos",
    "cleanup_files",
    "delete_attachment",
    "equipment_owner",
    "get_attachment",
    "list_for_equipment",
    "list_for_request",
    "list_for_request_in",
    "list_moderation_queue",
    "list_portfolio",
    "message_owner",
    "open_attachment",
    "process_images",
    "provider_profile_owner",
    "public_gallery",
    "public_gallery_items",
    "publish_to_public_card",
    "reject_attachment",
    "request_owner",
    "review_owner",
    "revoke_public_card_copies",
    "set_portfolio_caption",
    "set_storage",
    "submit_portfolio_image",
    "upload_attachment",
    "verification_owner",
]


@asynccontextmanager
async def _read_session() -> AsyncIterator[AsyncSession]:
    async with db_session.get_sessionmaker()() as session:
        yield session


async def upload_attachment(
    actor: Actor,
    *,
    owner: AttachmentOwner,
    purpose: str | None = None,
    filename_hint: str | None = None,
    content_type_hint: str | None = None,
    stream: AsyncIterable[bytes],
    idem: Idempotency | None = None,
) -> CommandResult:
    async with _read_session() as session:
        plan = await upload.prepare(session, actor, owner, purpose)

    blob = await upload.store_incoming(
        stream, prefix=plan.prefix, max_bytes=get_settings().max_upload_bytes
    )
    try:
        result = await run_command(
            actor, commands.register_attachment(plan, blob), idempotency=idem
        )
    except BaseException:
        await get_storage().delete(blob.storage_key)
        raise
    if result.replayed:
        await get_storage().delete(blob.storage_key)
    return result


async def submit_portfolio_image(
    actor: Actor,
    *,
    purpose: str = PORTFOLIO_PURPOSE,
    filename_hint: str | None = None,
    content_type_hint: str | None = None,
    stream: AsyncIterable[bytes],
    idem: Idempotency | None = None,
) -> CommandResult:
    return await upload_attachment(
        actor,
        owner=provider_profile_owner(),
        purpose=AVATAR_PURPOSE if purpose == AVATAR_PURPOSE else PORTFOLIO_PURPOSE,
        filename_hint=filename_hint,
        content_type_hint=content_type_hint,
        stream=stream,
        idem=idem,
    )


async def delete_attachment(
    actor: Actor, attachment_id: uuid.UUID, *, idem: Idempotency | None = None
) -> CommandResult:
    return await run_command(actor, commands.delete_attachment(attachment_id), idempotency=idem)


async def attach_review_photos(
    ctx: CommandContext,
    review_id: uuid.UUID,
    attachment_ids: Sequence[uuid.UUID],
    *,
    confirm_sensitive: bool = False,
) -> list[uuid.UUID]:
    return await publication.attach_review_photos(
        ctx, review_id, attachment_ids, confirm_sensitive=confirm_sensitive
    )


async def publish_to_public_card(
    ctx: CommandContext,
    request: RepairRequest,
    attachment_ids: Sequence[uuid.UUID],
    *,
    confirm_sensitive: bool = False,
) -> list[uuid.UUID]:
    return await publication.publish_to_public_card(
        ctx, request, attachment_ids, confirm_sensitive=confirm_sensitive
    )


async def revoke_public_card_copies(ctx: CommandContext, request_id: uuid.UUID) -> int:
    return await publication.revoke_public_card_copies(ctx, request_id)


async def get_attachment(actor: Actor, attachment_id: uuid.UUID) -> AttachmentView:
    async with _read_session() as session:
        attachment = await queries.get_attachment(session, attachment_id)
        _, visible = await _visibility(session, attachment, actor)
        if not visible:
            raise NotFound()
        return to_attachment_view(attachment)


async def list_for_request(actor: Actor, request_id: uuid.UUID) -> list[AttachmentView]:
    async with _read_session() as session:
        return await list_for_request_in(session, actor, request_id)


async def list_for_request_in(
    session: AsyncSession, actor: Actor, request_id: uuid.UUID
) -> list[AttachmentView]:
    context = await queries.request_access_context(session, request_id, actor)
    items: list[AttachmentView] = []
    for attachment in await queries.request_attachments(session, request_id):
        _, visible = await _visibility(session, attachment, actor, request_context=context)
        if visible:
            items.append(to_attachment_view(attachment))
    return items


async def list_for_equipment(actor: Actor, equipment_id: uuid.UUID) -> list[AttachmentView]:
    async with _read_session() as session:
        items: list[AttachmentView] = []
        for attachment in await queries.equipment_attachments(session, equipment_id):
            _, visible = await _visibility(session, attachment, actor)
            if visible:
                items.append(to_attachment_view(attachment))
        return items


async def list_portfolio(
    actor: Actor, *, provider_profile_id: uuid.UUID | None = None
) -> list[AttachmentView]:
    async with _read_session() as session:
        profile_id = provider_profile_id
        if profile_id is None:
            plan = await upload.prepare(session, actor, provider_profile_owner(), PORTFOLIO_PURPOSE)
            profile_id = plan.provider_profile_id
        if profile_id is None:
            raise NotFound()
        items: list[AttachmentView] = []
        for attachment in await queries.portfolio_images(session, profile_id):
            _, visible = await _visibility(session, attachment, actor)
            if visible:
                items.append(to_attachment_view(attachment))
        return items


async def set_portfolio_caption(
    actor: Actor, attachment_id: uuid.UUID, caption: str | None, *, idem: Idempotency | None = None
) -> CommandResult:
    return await run_command(
        actor, commands.set_portfolio_caption(attachment_id, caption), idempotency=idem
    )


async def public_gallery_items(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> list[GalleryItemView]:
    return [
        GalleryItemView(id=ids.encode("attachment", value), caption=caption)
        for value, caption in await queries.published_portfolio_items(session, provider_org_id)
    ]


async def public_gallery(session: AsyncSession, provider_org_id: uuid.UUID) -> list[str]:
    return [
        ids.encode("attachment", value)
        for value in await queries.published_portfolio_ids(session, provider_org_id)
    ]


async def open_attachment(
    actor: Actor, attachment_id: uuid.UUID, variant: str = queries.VARIANT_SAFE
) -> AttachmentContent:
    kind = queries.VARIANT_KINDS.get(variant)
    if kind is None:
        raise ValidationFailed("Доступны варианты safe и thumb", field="variant")

    async with _read_session() as session:
        attachment = await queries.get_attachment(session, attachment_id)
        access = await queries.load_access(session, attachment, actor)
        if not policy.is_ready(access):
            raise NotFound()
        if not policy.can_read(
            actor,
            access,
            marketplace_visible=await _marketplace_visible(session, actor, attachment),
        ):
            raise NotFound()
        row = await queries.variant_of(session, attachment.id, kind)
        if row is None:
            raise NotFound()
        key, mime, size = row.storage_key, row.mime_type, row.byte_size

    storage = get_storage()
    if not await storage.exists(key):
        raise NotFound()
    return AttachmentContent(
        attachment_id=attachment_id,
        filename=server_filename(attachment_id, mime, variant=variant),
        mime_type=mime,
        byte_size=size,
        stream=storage.open(key),
    )


async def _visibility(
    session: AsyncSession,
    attachment: Attachment,
    actor: Actor,
    *,
    request_context: queries.RequestAccessContext | None = None,
) -> tuple[policy.AttachmentAccess, bool]:
    access = await queries.load_access(session, attachment, actor, request_context=request_context)
    if not policy.is_ready(access):
        return access, policy.is_uploader(actor, access)
    visible = policy.can_read(
        actor, access, marketplace_visible=await _marketplace_visible(session, actor, attachment)
    )
    return access, visible or policy.is_uploader(actor, access)


async def _marketplace_visible(session: AsyncSession, actor: Actor, attachment: Attachment) -> bool:
    if attachment.visibility_class != VisibilityClass.PUBLIC_CARD or attachment.request_id is None:
        return False
    from app.modules.requests import api as requests_api

    return await requests_api.marketplace_card_visible(session, actor, attachment.request_id)


async def approve_attachment(
    actor: Actor,
    attachment_id: uuid.UUID,
    *,
    reason: str | None = None,
    idem: Idempotency | None = None,
) -> CommandResult:
    return await run_command(
        actor, moderation.decide(attachment_id, approve=True, reason=reason), idempotency=idem
    )


async def reject_attachment(
    actor: Actor, attachment_id: uuid.UUID, *, reason: str, idem: Idempotency | None = None
) -> CommandResult:
    return await run_command(
        actor, moderation.decide(attachment_id, approve=False, reason=reason), idempotency=idem
    )


async def list_moderation_queue(
    actor: Actor,
    *,
    status: str = "pending",
    cursor: uuid.UUID | None = None,
    limit: int = 50,
) -> tuple[list[AttachmentView], uuid.UUID | None]:
    moderation.require_operator(actor)
    async with _read_session() as session:
        rows, next_cursor = await queries.moderation_queue(
            session, status=status, after=cursor, limit=limit
        )
        return [to_attachment_view(attachment) for attachment, _ in rows], next_cursor


async def process_images(now: datetime) -> int:
    return await processing.run_once(now)


async def cleanup_files(now: datetime) -> int:
    return await cleanup.run_once(now)
