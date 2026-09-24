from __future__ import annotations

from datetime import timedelta

import structlog

from app.adapters.bot import actions, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.core import ids
from app.core.actor import BareUserActor
from app.core.errors import DomainError
from app.infra.config import get_settings
from app.modules.identity import api as identity

log = structlog.get_logger("bot")

ACCEPT = "invitation.accept"

_STATE_TEXTS = {
    "expired": texts.INVITATION_EXPIRED,
    "used": texts.INVITATION_USED,
    "revoked": texts.INVITATION_REVOKED,
}


async def show_preview(ctx: BotContext, token: str) -> None:
    try:
        preview = await identity.preview_invitation_for_bot(token)
    except DomainError:
        log.info("bot_invitation_unknown")
        await ctx.reply(texts.INVITATION_UNKNOWN)
        await menu.send_menu(ctx)
        return

    if preview.state != "active" or preview.expires_at is None:
        await ctx.reply(_STATE_TEXTS.get(preview.state, texts.INVITATION_UNKNOWN))
        await menu.send_menu(ctx)
        return

    ttl = min(
        preview.expires_at - ctx.now,
        timedelta(seconds=get_settings().bot_action_ttl_seconds),
    )
    async with ctx.unit() as session:
        code = await actions.make_action(
            session,
            ctx.user_id,
            ACCEPT,
            ctx.now,
            conversation_id=ctx.conversation.id,
            object_type="invitation",
            object_id=ids.decode("invitation", preview.id),
            ttl=ttl,
        )
    role = texts.ROLE_TITLES.get(preview.role or "", preview.role or "")
    await ctx.reply(
        texts.INVITATION_PREVIEW.format(
            organization=preview.organization_name,
            role=texts.INVITATION_ROLE.format(role=role) if role else "",
        ),
        [keyboards.rows([keyboards.action_button(texts.INVITATION_ACCEPT, code)])],
    )


@actions.action(ACCEPT)
async def accept(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.INVITATION_UNKNOWN)
        return
    result = await identity.accept_invitation_by_id(
        BareUserActor(ctx.user_id), claimed.object_id, idem=claimed.idempotency
    )
    membership = result.body
    organization = membership["organization"]["name"]
    if membership["status"] != "active":
        await ctx.reply(texts.INVITATION_PENDING.format(organization=organization))
        return
    ctx.conversation.active_organization_id = ids.decode(
        "organization", membership["organization"]["id"]
    )
    ctx.conversation.active_membership_id = ids.decode("membership", membership["id"])
    await ctx.save()
    await menu.send_menu(ctx, greeting=texts.INVITATION_ACCEPTED.format(organization=organization))
