from __future__ import annotations

import uuid

from app.adapters.bot import actions, dialogs, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import visit_terms
from app.core import ids
from app.infra.max.types import Button
from app.modules.requests import api as requests_api

ACTION_RESPOND = "offer.start"
ACTION_WITHDRAW = "offer.withdraw"
ACTION_MORE = "marketplace.more"
ACTION_QUESTION = "marketplace.question"

PAGE_SIZE = 10

SCENARIO = "req_offer"
STEP_SCOPE = "scope"
QUESTION_SCENARIO = "req_market_question"
STEP_QUESTION = "question"
QUESTION_MAX_LENGTH = 4000


@menu.menu("available")
async def show_available(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    if actor is None or actor.side != "provider":
        await ctx.reply(texts.NOT_PROVIDER_SIDE)
        return
    await _send_page(ctx, cursor=None)


async def _send_page(ctx: BotContext, *, cursor: str | None) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    items, next_cursor = await requests_api.list_marketplace_requests(
        actor, cursor=cursor, limit=PAGE_SIZE
    )
    if not items and cursor is None:
        await ctx.reply(texts.MARKETPLACE_EMPTY)
        return
    for card in items:
        await _send_card(ctx, card)
    if next_cursor:
        async with ctx.unit() as session:
            code = await actions.make_action(
                session,
                ctx.user_id,
                ACTION_MORE,
                ctx.now,
                params={"cursor": next_cursor},
            )
        await ctx.reply(
            texts.BUTTON_MORE, [keyboards.rows([keyboards.action_button(texts.BUTTON_MORE, code)])]
        )


@actions.action(ACTION_MORE)
async def _more(ctx: BotContext, claimed: ClaimedAction) -> None:
    cursor = claimed.params.get("cursor")
    await _send_page(ctx, cursor=cursor if isinstance(cursor, str) else None)


def card_lines(card: requests_api.RequestPublicCardView) -> list[str]:
    lines = [
        texts.MARKETPLACE_ITEM.format(
            number=card.request_number,
            category=card.equipment_category_name or "оборудование",
            urgency=texts.URGENCY_LABELS.get(card.urgency, card.urgency),
        )
    ]
    title = " ".join(part for part in (card.brand, card.model) if part)
    if title:
        lines.append(texts.MARKETPLACE_EQUIPMENT.format(title=title))
    place = ", ".join(part for part in (card.city_name, card.district_name) if part)
    if place:
        lines.append(texts.MARKETPLACE_PLACE.format(place=place))
    if card.published_description:
        lines.append(texts.MARKETPLACE_DESCRIPTION.format(text=card.published_description))
    if card.published_attachment_ids:
        lines.append(texts.MARKETPLACE_PHOTOS.format(count=len(card.published_attachment_ids)))
    return lines


async def _send_card(ctx: BotContext, card: requests_api.RequestPublicCardView) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    text = "\n".join(card_lines(card))
    rows: list[list[Button]] = []
    marketplace_card = await requests_api.get_marketplace_card(
        actor, ids.decode("request", card.request_id)
    )
    active_offer = next((o for o in marketplace_card.my_offers if o.state == "active"), None)
    async with ctx.unit() as session:
        if active_offer is not None:
            withdraw_code = await actions.make_action(
                session,
                ctx.user_id,
                ACTION_WITHDRAW,
                ctx.now,
                object_type="offer",
                object_id=ids.decode("offer", active_offer.id),
            )
            rows.append([keyboards.action_button(texts.BUTTON_WITHDRAW_OFFER, withdraw_code)])
        else:
            respond_code = await actions.make_action(
                session,
                ctx.user_id,
                ACTION_RESPOND,
                ctx.now,
                object_type="request",
                object_id=ids.decode("request", card.request_id),
            )
            rows.append([keyboards.action_button(texts.BUTTON_RESPOND, respond_code)])
        question_code = await actions.make_action(
            session,
            ctx.user_id,
            ACTION_QUESTION,
            ctx.now,
            object_type="request",
            object_id=ids.decode("request", card.request_id),
            params={"request_number": card.request_number},
        )
        rows.append([keyboards.action_button(texts.BUTTON_ASK_QUESTION, question_code)])
    rows.append([keyboards.open_app(texts.BUTTON_OPEN_IN_APP, "request", card.request_id)])
    await ctx.reply(text, [keyboards.rows(*rows)])


@actions.action(ACTION_RESPOND)
async def _start_offer(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    card = await requests_api.get_marketplace_card(actor, claimed.object_id)
    await dialogs.start(
        ctx, SCENARIO, request_id=str(claimed.object_id), timezone=card.card.city_timezone
    )


async def _prompt_scope(ctx: BotContext) -> None:
    await ctx.reply(texts.ASK_OFFER_SCOPE, [keyboards.rows(keyboards.back_cancel_row(STEP_SCOPE))])


async def _handle_scope(ctx: BotContext, value: str) -> str | None:
    scope_text = value.strip()
    if not scope_text:
        await ctx.reply(texts.ASK_OFFER_SCOPE)
        return None
    ctx.conversation.data["scope_description"] = scope_text[:2000]
    return dialogs.FINISH


async def _finish(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    start, end = visit_terms.visit_window(
        int(data["day_offset"]), str(data["slot"]), data.get("timezone")
    )
    request_id = uuid.UUID(str(data["request_id"]))
    price = visit_terms.price_payload(data)
    offer_input = requests_api.OfferInput(
        visit_window_start=start,
        visit_window_end=end,
        scope_description=str(data.get("scope_description") or ""),
        **price,
    )
    await requests_api.submit_offer(
        actor,
        request_id,
        data=offer_input,
        expected_version=None,
        idem=dialogs.idempotency(
            ctx,
            "requests.submit_offer",
            {**price, "window": [start, end], "scope": offer_input.scope_description},
        ),
    )
    await ctx.reply(texts.OFFER_SUBMITTED)


dialogs.register(
    dialogs.Scenario(
        name=SCENARIO,
        first=visit_terms.STEP_DAY,
        steps=(
            visit_terms.day_step(visit_terms.STEP_SLOT),
            visit_terms.slot_step(visit_terms.STEP_PRICE_MODE),
            visit_terms.price_mode_step(
                prompt_text=texts.OFFER_ASK_PRICE_MODE, after_price=STEP_SCOPE, allow_later=True
            ),
            visit_terms.price_sum_step(STEP_SCOPE),
            visit_terms.price_free_step(STEP_SCOPE),
            dialogs.Step(STEP_SCOPE, _prompt_scope, _handle_scope),
        ),
        finish=_finish,
    )
)


@actions.action(ACTION_WITHDRAW)
async def _withdraw(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    await requests_api.withdraw_offer_by_id(
        actor,
        claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.OFFER_WITHDRAWN)


@actions.action(ACTION_QUESTION)
async def _question_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        QUESTION_SCENARIO,
        request_id=str(claimed.object_id),
        request_number=claimed.params.get("request_number"),
    )


async def _prompt_question(ctx: BotContext) -> None:
    number = ctx.conversation.data.get("request_number") or ""
    await ctx.reply(
        texts.ASK_MARKET_QUESTION.format(number=number),
        [keyboards.rows(keyboards.back_cancel_row(STEP_QUESTION, with_back=False))],
    )


async def _handle_question(ctx: BotContext, value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    ctx.conversation.data["body"] = text[:QUESTION_MAX_LENGTH]
    return dialogs.FINISH


async def _finish_question(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    body = str(data["body"])
    await requests_api.post_dialog_message(
        actor,
        uuid.UUID(str(data["request_id"])),
        body=body,
        idem=dialogs.idempotency(ctx, "requests.post_dialog_message", {"body": body}),
    )
    await ctx.reply(texts.MARKET_QUESTION_SENT)


dialogs.register(
    dialogs.Scenario(
        name=QUESTION_SCENARIO,
        first=STEP_QUESTION,
        steps=(dialogs.Step(STEP_QUESTION, _prompt_question, _handle_question, allow_back=False),),
        finish=_finish_question,
    )
)
