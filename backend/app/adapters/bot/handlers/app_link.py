from __future__ import annotations

import structlog

from app.adapters.bot import actions, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.core.errors import DomainError
from app.infra.config import get_settings
from app.infra.max.transport import MaxApiError
from app.infra.max.types import ButtonLink
from app.modules.identity import api as identity

log = structlog.get_logger("bot")


async def send_login_link(ctx: BotContext, target: str | None) -> None:
    try:
        issued = await identity.issue_login_link(str(ctx.max_user_id), target)
    except DomainError:
        await ctx.reply(texts.LOGIN_LINK_UNAVAILABLE)
        return
    minutes = max(1, get_settings().login_link_ttl_seconds // 60)
    try:
        await ctx.transport.send_message(
            user_id=ctx.max_user_id,
            text=texts.LOGIN_LINK_READY.format(minutes=minutes),
            attachments=[
                keyboards.rows([ButtonLink(text=texts.LOGIN_LINK_BUTTON, url=issued.url)])
            ],
        )
    except MaxApiError as exc:
        log.warning("bot_send_failed", status=exc.status, code=exc.code)


@actions.action(actions.OPEN_APP_ACTION)
async def open_app_from_notification(ctx: BotContext, claimed: ClaimedAction) -> None:
    async with ctx.unit() as session:
        await actions.release(session, claimed.id)
    target = claimed.params.get(actions.OPEN_APP_TARGET_PARAM)
    await send_login_link(ctx, target if isinstance(target, str) else None)
