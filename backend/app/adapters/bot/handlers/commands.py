from __future__ import annotations

import structlog
from maxapi.enums.attachment import AttachmentType
from maxapi.types.attachments.attachment import ContactAttachmentPayload
from maxapi.types.attachments.contact import Contact
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.bot_stopped import BotStopped
from maxapi.types.updates.message_created import MessageCreated

from app.adapters.bot import dialogs, menu, texts
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import invitation
from app.infra.max.deeplinks import DeeplinkError, parse_start_param

log = structlog.get_logger("bot")

INVITATION_START_KIND = "inv"


async def on_bot_started(event: BotStarted, ctx: BotContext) -> None:
    await _start(ctx, event.payload)


async def on_bot_stopped(event: BotStopped, ctx: BotContext) -> None:
    ctx.conversation.reset_dialog()
    await ctx.save()


async def cmd_start(event: MessageCreated, ctx: BotContext, args: list[str] | None = None) -> None:
    await _start(ctx, args[0] if args else None)


async def cmd_help(event: MessageCreated, ctx: BotContext) -> None:
    await ctx.reply(texts.HELP)


async def cmd_cancel(event: MessageCreated, ctx: BotContext) -> None:
    await dialogs.cancel(ctx)


async def cmd_menu(event: MessageCreated, ctx: BotContext) -> None:
    await menu.send_menu(ctx)


async def on_message(event: MessageCreated, ctx: BotContext) -> None:
    value = _input_value(event)
    if value is None:
        return
    if await dialogs.feed(ctx, value):
        return
    await ctx.reply(texts.UNKNOWN_INPUT)


async def _start(ctx: BotContext, payload: str | None) -> None:
    if payload:
        try:
            kind, value = parse_start_param(payload)
        except DeeplinkError:
            kind, value = "", ""
        if kind == INVITATION_START_KIND and value:
            await invitation.show_preview(ctx, value)
            return
        log.info("bot_start_unknown_payload", kind=kind or "invalid")
    await dialogs.cancel(ctx, notify=False)
    await menu.send_menu(ctx)


def _input_value(event: MessageCreated) -> str | None:
    body = event.message.body
    if body is None:
        return None
    has_image = False
    for attachment in body.attachments or []:
        if attachment.type == AttachmentType.IMAGE:
            has_image = True
            continue
        if attachment.type != AttachmentType.CONTACT:
            continue
        contact = (
            attachment
            if isinstance(attachment, Contact)
            else Contact.model_validate(attachment, from_attributes=True)
        )
        payload = contact.payload
        if isinstance(payload, ContactAttachmentPayload) and payload.vcf.phone:
            return payload.vcf.phone
    text = (body.text or "").strip()
    if text:
        return text
    return "" if has_image else None
