from __future__ import annotations

import uuid

import structlog

from app.adapters.bot import actions, dialogs, keyboards, texts, updates
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers.draft_photos import one_chunk, photo_url
from app.core import ids
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.files.owners import request_owner
from app.modules.requests import api as requests_api

log = structlog.get_logger("bot")

ACTION_REPLY_START = "message.reply_start"
SCENARIO = "req_reply"
STEP_BODY = "body"


async def start_reply(
    ctx: BotContext,
    request_id: uuid.UUID,
    *,
    request_number: int,
    assignment_id: uuid.UUID | None = None,
    thread_provider_org_id: uuid.UUID | None = None,
) -> None:
    await dialogs.start(
        ctx,
        SCENARIO,
        request_id=str(request_id),
        request_number=request_number,
        assignment_id=str(assignment_id) if assignment_id else None,
        thread_provider_org_id=str(thread_provider_org_id) if thread_provider_org_id else None,
    )


@actions.action(ACTION_REPLY_START)
async def _reply_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    view = await requests_api.get_request(actor, claimed.object_id)
    assignment_id = claimed.params.get("assignment_id")
    thread_org = claimed.params.get("thread_provider_org_id")
    await start_reply(
        ctx,
        claimed.object_id,
        request_number=getattr(view, "request_number", 0),
        assignment_id=uuid.UUID(assignment_id) if isinstance(assignment_id, str) else None,
        thread_provider_org_id=uuid.UUID(thread_org) if isinstance(thread_org, str) else None,
    )


async def _prompt_body(ctx: BotContext) -> None:
    number = ctx.conversation.data.get("request_number", "")
    await ctx.reply(
        texts.ASK_REPLY.format(number=number),
        [keyboards.rows(keyboards.back_cancel_row(STEP_BODY, with_back=False))],
    )


async def _handle_body(ctx: BotContext, value: str) -> str | None:
    text = value.strip()
    url = photo_url(ctx.event)
    if not text and url is None:
        await ctx.reply(
            texts.ASK_REPLY.format(number=ctx.conversation.data.get("request_number", ""))
        )
        return None
    ctx.conversation.data["body"] = text or "Фото приложено"
    ctx.conversation.data["has_photo"] = url is not None
    return dialogs.FINISH


async def _finish(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id = uuid.UUID(str(data["request_id"]))
    assignment_id = uuid.UUID(str(data["assignment_id"])) if data.get("assignment_id") else None
    thread_org_id = (
        ids.decode("organization", str(data["thread_provider_org_id"]))
        if data.get("thread_provider_org_id")
        else None
    )
    if data.get("has_photo"):
        await _attach_photo(ctx, request_id)
    body = str(data["body"])[:4000]
    await requests_api.post_message(
        actor,
        request_id,
        body=body,
        assignment_id=assignment_id,
        thread_provider_org_id=thread_org_id,
        idem=dialogs.idempotency(ctx, "requests.post_message", {"body": body}),
    )
    await ctx.reply(texts.REPLY_SENT)


async def _attach_photo(ctx: BotContext, request_id: uuid.UUID) -> None:
    url = photo_url(ctx.event)
    if url is None:
        return
    actor = await ctx.org_actor()
    if actor is None:
        return
    try:
        data = await ctx.transport.download_attachment(
            url, max_bytes=get_settings().max_upload_bytes
        )
        await files.upload_attachment(
            actor,
            owner=request_owner(request_id),
            purpose="reply",
            filename_hint="reply.jpg",
            content_type_hint="image/jpeg",
            stream=one_chunk(data),
            idem=updates.event_idempotency(
                "files.upload_attachment",
                {"request_id": str(request_id), "purpose": "reply", "size": len(data)},
            ),
        )
    except Exception:
        log.warning("bot_reply_photo_failed")


dialogs.register(
    dialogs.Scenario(
        name=SCENARIO,
        first=STEP_BODY,
        steps=(dialogs.Step(STEP_BODY, _prompt_body, _handle_body, allow_back=False),),
        finish=_finish,
    )
)
