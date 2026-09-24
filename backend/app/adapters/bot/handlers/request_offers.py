from __future__ import annotations

import uuid

from app.adapters.bot import actions, buttons, conditions, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import cards
from app.adapters.bot.handlers.request_actions import (
    ACTION_OFFER_CONFIRM,
    ACTION_OFFER_PREVIEW,
    ACTION_OFFERS_LIST,
)
from app.core import ids
from app.core.actor import UserActor
from app.infra.max.types import Button
from app.modules.requests import api as requests_api


def _offer_lines(offer: requests_api.OfferView, tz: str | None) -> list[str]:
    return conditions.offer_lines(
        provider_name=offer.provider.display_name if offer.provider else None,
        version=offer.version,
        window_start=offer.visit_window_start,
        window_end=offer.visit_window_end,
        amount_minor=offer.price.amount_minor,
        currency=offer.price.currency,
        zero_cost_reason=offer.price.zero_cost_reason,
        vat_mode=offer.price.vat_mode,
        scope=offer.scope_description,
        valid_until=offer.valid_until,
        tz=tz,
    )


def _offer_spec(
    label: str,
    action_type: str,
    offer: requests_api.OfferView,
    view: requests_api.RequestCustomerView,
) -> ActionSpec:
    return ActionSpec(
        label,
        action_type,
        object_type="offer",
        object_id=ids.decode("offer", offer.id),
        expected_version=view.version,
        proposal_version=offer.version,
        params={"request_id": view.id},
    )


@actions.action(ACTION_OFFERS_LIST)
async def _offers_list(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    view = await requests_api.get_request(actor, claimed.object_id)
    if not isinstance(view, requests_api.RequestCustomerView):
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    active = [
        o for o in await requests_api.list_offers(actor, claimed.object_id) if o.state == "active"
    ]
    if not active:
        await ctx.reply(texts.OFFERS_EMPTY)
        return
    for offer in active:
        lines = _offer_lines(offer, view.location.timezone)
        rows: list[list[Button]] = []
        if actor.is_manager:
            rows = await buttons.mint_rows(
                ctx, [[_offer_spec(texts.BUTTON_SELECT_OFFER, ACTION_OFFER_PREVIEW, offer, view)]]
            )
        else:
            lines.append(texts.ONLY_MANAGER_CAN_SELECT)
        await ctx.reply("\n".join(lines), [keyboards.rows(*rows)] if rows else None)


async def _current_offer(
    ctx: BotContext, actor: UserActor, claimed: ClaimedAction, request_id: uuid.UUID
) -> tuple[requests_api.OfferView, requests_api.RequestCustomerView] | None:
    """Оффер той же версии, что была на экране; иначе условия изменились."""
    view = await requests_api.get_request(actor, request_id)
    if not isinstance(view, requests_api.RequestCustomerView):
        return None
    offer_public_id = ids.encode("offer", claimed.object_id) if claimed.object_id else None
    offer = next(
        (o for o in await requests_api.list_offers(actor, request_id) if o.id == offer_public_id),
        None,
    )
    if offer is None or offer.state != "active" or offer.version != claimed.proposal_version:
        return None
    return offer, view


@actions.action(ACTION_OFFER_PREVIEW)
async def _offer_preview(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None or not actor.is_manager:
        await ctx.reply(texts.ONLY_MANAGER_CAN_SELECT)
        return
    found = await _current_offer(ctx, actor, claimed, request_id)
    if found is None:
        await ctx.reply(texts.TERMS_CHANGED)
        await cards.show_actual(ctx, request_id)
        return
    offer, view = found
    confirm = await buttons.mint(
        ctx, _offer_spec(texts.BUTTON_CONFIRM_OFFER, ACTION_OFFER_CONFIRM, offer, view)
    )
    lines = [texts.OFFER_CONFIRM_ASK, *_offer_lines(offer, view.location.timezone)]
    await ctx.reply("\n".join(lines), [keyboards.rows([confirm])])


@actions.action(ACTION_OFFER_CONFIRM)
async def _offer_confirm(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None or not actor.is_manager:
        await ctx.reply(texts.ONLY_MANAGER_CAN_SELECT)
        return
    if await _current_offer(ctx, actor, claimed, request_id) is None:
        await ctx.reply(texts.TERMS_CHANGED)
        await cards.show_actual(ctx, request_id)
        return
    await requests_api.select_offer(
        actor,
        request_id,
        offer_id=claimed.object_id,
        offer_version=claimed.proposal_version,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.OFFER_SELECTED)
