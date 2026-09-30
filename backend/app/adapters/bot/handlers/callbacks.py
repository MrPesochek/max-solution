from __future__ import annotations

import uuid

import structlog
from maxapi.types.updates.message_callback import MessageCallback

from app.adapters.bot import actions, dialogs, keyboards, menu, scenarios, texts
from app.adapters.bot.actions import RejectedAction
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import app_link, cards
from app.core import ids
from app.core.errors import DomainError

log = structlog.get_logger("bot")


async def on_callback(event: MessageCallback, ctx: BotContext) -> None:
    payload = keyboards.parse_payload(event.callback.payload)
    if payload is None:
        await _outdated(ctx)
        return
    if payload.kind == keyboards.ACTION:
        await _run_action(ctx, payload.value)
    elif payload.kind == keyboards.MENU:
        await ctx.ack()
        await _open_menu_item(ctx, payload.value)
    elif payload.kind == keyboards.DIALOG:
        await _feed_dialog(ctx, payload)
    elif payload.kind == keyboards.SELECT_ORG:
        await ctx.ack()
        await _select_organization(ctx, payload.value)
    elif payload.kind == keyboards.OPEN_APP:
        await ctx.ack()
        await app_link.send_login_link(ctx, payload.value or None)


async def _outdated(ctx: BotContext, request_id: uuid.UUID | None = None) -> None:
    await ctx.ack(texts.ACTION_OUTDATED)
    await cards.show_actual(ctx, request_id)


async def _run_action(ctx: BotContext, code: str) -> None:
    async with ctx.unit() as session:
        claimed = await actions.claim(session, code, ctx.user_id, ctx.now)
    if isinstance(claimed, RejectedAction):
        log.info("bot_action_rejected", reason=claimed.reason.value)
        await _outdated(ctx, claimed.request_id)
        return
    if claimed.membership_id is not None and not await _act_as(ctx, claimed.membership_id):
        async with ctx.unit() as session:
            await actions.release(session, claimed.id)
        await ctx.ack(texts.ROLE_UNAVAILABLE)
        await cards.show_actual(ctx, claimed.request_id)
        return
    handler = actions.handler_for(claimed.action_type)
    if handler is None:
        log.error("bot_action_no_handler", action_type=claimed.action_type)
        await _outdated(ctx, claimed.request_id)
        return
    await ctx.ack()
    try:
        await handler(ctx, claimed)
    except DomainError as exc:
        await ctx.reply(exc.message)
        await cards.show_actual(ctx, claimed.request_id)
    except Exception:
        async with ctx.unit() as session:
            await actions.release(session, claimed.id)
        await ctx.reply(texts.TRY_AGAIN)
        raise


async def _act_as(ctx: BotContext, membership_id: uuid.UUID) -> bool:
    public_id = ids.encode("membership", membership_id)
    target = next(
        (m for m in await ctx.memberships() if m.id == public_id and m.status == "active"),
        None,
    )
    if target is None:
        return False
    if ctx.conversation.active_membership_id != membership_id:
        await ctx.set_active(target)
        await ctx.save()
    return True


async def _open_menu_item(ctx: BotContext, key: str) -> None:
    if key == menu.NEW_CUSTOMER:
        await scenarios.start_registration(ctx, "customer")
        return
    if key == menu.NEW_PROVIDER:
        await scenarios.start_registration(ctx, "provider")
        return
    if key == menu.MAIN:
        await menu.send_menu(ctx)
        return
    if key == menu.SWITCH_ORG:
        await menu.send_organization_choice(ctx)
        return
    item = menu.find(key)
    if item is None:
        await ctx.reply(texts.UNKNOWN_INPUT)
        return
    handler = menu.handler_for(key)
    if handler is None:
        await ctx.reply(
            texts.SECTION_LATER,
            [keyboards.rows([keyboards.open_app(texts.OPEN_WEBAPP, item.screen)])],
        )
        return
    try:
        await handler(ctx)
    except DomainError as exc:
        await ctx.reply(exc.message)


async def _feed_dialog(ctx: BotContext, payload: keyboards.Payload) -> None:
    parts = payload.parts
    step, value = parts[0], ":".join(parts[1:])
    if ctx.conversation.step != step:
        await ctx.ack(texts.ACTION_OUTDATED)
        return
    await ctx.ack()
    await dialogs.feed(ctx, value)


async def _select_organization(ctx: BotContext, public_id: str) -> None:
    active = [m for m in await ctx.memberships() if m.status == "active"]
    matched = [m for m in active if m.id == public_id]
    if not matched:
        matched = [m for m in active if m.organization.id == public_id]
    if len(matched) != 1:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    target = matched[0]
    await ctx.set_active(target)
    await ctx.save()
    await menu.send_menu(ctx, greeting=texts.ORG_SWITCHED.format(name=target.organization.name))
