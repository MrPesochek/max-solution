from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog
from maxapi.enums.attachment import AttachmentType
from maxapi.types.attachments.attachment import PhotoAttachmentPayload
from maxapi.types.attachments.image import Image
from maxapi.types.updates.message_created import MessageCreated

from app.adapters.bot import dialogs, keyboards, texts, updates
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers.draft_common import STEP_PHOTO_REASON, STEP_PHOTOS, STEP_REVIEW
from app.core import ids
from app.core.errors import DomainError
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.files.owners import request_owner

log = structlog.get_logger("bot")


def photo_url(event: Any) -> str | None:
    if not isinstance(event, MessageCreated):
        return None
    body = event.message.body
    if body is None:
        return None
    for attachment in body.attachments or []:
        if attachment.type != AttachmentType.IMAGE:
            continue
        image = (
            attachment
            if isinstance(attachment, Image)
            else Image.model_validate(attachment, from_attributes=True)
        )
        payload = image.payload
        if isinstance(payload, PhotoAttachmentPayload):
            return payload.url
        if isinstance(payload, dict) and payload.get("url"):
            return str(payload["url"])
    return None


async def one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _slot_prompt(slot: dict[str, Any]) -> str:
    required = bool(slot.get("required"))
    return texts.PHOTO_SLOT_PROMPT.format(
        label=slot.get("label", slot.get("code", "")),
        required=texts.PHOTO_SLOT_REQUIRED if required else texts.PHOTO_SLOT_OPTIONAL,
    )


def _current_slot(ctx: BotContext) -> dict[str, Any] | None:
    slots = ctx.conversation.data.get("photo_slots") or []
    index = int(ctx.conversation.data.get("photo_index", 0))
    return slots[index] if index < len(slots) else None


async def _prompt_photos(ctx: BotContext) -> None:
    from app.adapters.bot.handlers import draft_steps

    slot = _current_slot(ctx)
    if slot is None:
        await draft_steps.prompt_review(ctx)
        return
    rows: list[list[Any]] = []
    if not slot.get("required"):
        rows.append([keyboards.dialog_button(texts.BUTTON_SKIP, STEP_PHOTOS, "skip")])
    rows.append([keyboards.dialog_button(texts.BUTTON_CANT_PHOTO, STEP_PHOTOS, "cant")])
    rows.append(keyboards.back_cancel_row(STEP_PHOTOS, with_back=False))
    await ctx.reply(_slot_prompt(slot), [keyboards.rows(*rows)])


async def _handle_photos(ctx: BotContext, value: str) -> str | None:
    slot = _current_slot(ctx)
    if slot is None:
        return STEP_REVIEW
    required = bool(slot.get("required"))
    if value == "skip" and not required:
        return _next_photo(ctx)
    if value == "cant":
        return STEP_PHOTO_REASON
    if photo_url(ctx.event) is None:
        await ctx.reply(_slot_prompt(slot))
        return None

    if await _save_photo(ctx, slot):
        await ctx.reply(texts.PHOTO_SAVED.format(label=slot.get("label", "")))
    else:
        await ctx.reply(texts.PHOTO_FAILED.format(label=slot.get("label", "")))
        if required:
            _mark_incomplete(ctx, "не удалось загрузить обязательное фото")
    return _next_photo(ctx)


def _next_photo(ctx: BotContext) -> str:
    ctx.conversation.data["photo_index"] = int(ctx.conversation.data.get("photo_index", 0)) + 1
    return STEP_PHOTOS if _current_slot(ctx) is not None else STEP_REVIEW


async def _save_photo(ctx: BotContext, slot: dict[str, Any]) -> bool:
    url = photo_url(ctx.event)
    if url is None:
        return False
    try:
        data = await ctx.transport.download_attachment(
            url, max_bytes=get_settings().max_upload_bytes
        )
    except Exception:
        log.warning("bot_photo_download_failed")
        return False

    actor = await ctx.org_actor()
    if actor is None:
        return False
    request_id = ids.decode("request", str(ctx.conversation.data["request_id"]))
    try:
        await files.upload_attachment(
            actor,
            owner=request_owner(request_id),
            purpose=str(slot.get("code")),
            filename_hint=f"{slot.get('code')}.jpg",
            content_type_hint="image/jpeg",
            stream=one_chunk(data),
            idem=updates.event_idempotency(
                "files.upload_attachment",
                {"request_id": str(request_id), "purpose": slot.get("code"), "size": len(data)},
            ),
        )
    except DomainError:
        log.warning("bot_photo_upload_rejected")
        return False
    return True


def _mark_incomplete(ctx: BotContext, reason: str) -> None:
    ctx.conversation.data["photos_incomplete"] = True
    ctx.conversation.data["photos_incomplete_reason"] = reason


async def _prompt_photo_reason(ctx: BotContext) -> None:
    await ctx.reply(texts.ASK_PHOTO_REASON)


async def _handle_photo_reason(ctx: BotContext, value: str) -> str | None:
    reason = value.strip()
    if not reason:
        await ctx.reply(texts.ASK_PHOTO_REASON)
        return None
    slot = _current_slot(ctx)
    _mark_incomplete(ctx, reason)
    await ctx.reply(texts.PHOTO_SKIPPED_INCOMPLETE.format(label=(slot or {}).get("label", "")))
    return _next_photo(ctx)


STEPS: tuple[dialogs.Step, ...] = (
    dialogs.Step(STEP_PHOTOS, _prompt_photos, _handle_photos),
    dialogs.Step(STEP_PHOTO_REASON, _prompt_photo_reason, _handle_photo_reason),
)
