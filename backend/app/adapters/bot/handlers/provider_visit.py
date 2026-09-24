from __future__ import annotations

import uuid
from typing import Any

from app.adapters.bot import actions, dialogs, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import visit_terms
from app.adapters.bot.handlers.provider_work import ACTION_QUOTE_START, ACTION_VISIT_START
from app.core import ids
from app.modules.requests import api as requests_api

VISIT_SCENARIO = "req_visit"
QUOTE_SCENARIO = "req_quote"

STEP_SCOPE = "scope"


async def _dialog_data(ctx: BotContext, claimed: ClaimedAction) -> dict[str, Any] | None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return None
    return {
        "request_id": ids.encode("request", request_id),
        "assignment_id": ids.encode("assignment", claimed.object_id),
        "expected_version": claimed.expected_version,
    }


def _target(data: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    return (
        ids.decode("request", str(data["request_id"])),
        ids.decode("assignment", str(data["assignment_id"])),
    )


@actions.action(ACTION_VISIT_START)
async def _start_visit(ctx: BotContext, claimed: ClaimedAction) -> None:
    data = await _dialog_data(ctx, claimed)
    actor = await ctx.org_actor()
    if data is None or actor is None:
        return
    view = await requests_api.get_request(actor, _target(data)[0])
    if isinstance(view, requests_api.RequestProviderView):
        data["timezone"] = view.location.timezone
    await dialogs.start(ctx, VISIT_SCENARIO, **data)


async def _prompt_visit_scope(ctx: BotContext) -> None:
    await ctx.reply(texts.ASK_OFFER_SCOPE, [keyboards.rows(keyboards.back_cancel_row(STEP_SCOPE))])


async def _handle_visit_scope(ctx: BotContext, value: str) -> str | None:
    text = value.strip()
    if not text:
        await ctx.reply(texts.ASK_OFFER_SCOPE)
        return None
    ctx.conversation.data["scope_description"] = text[:2000]
    return dialogs.FINISH


async def _finish_visit(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    start, end = visit_terms.visit_window(
        int(data["day_offset"]), str(data["slot"]), data.get("timezone")
    )
    request_id, assignment_id = _target(data)
    price = visit_terms.price_payload(data)
    payload = requests_api.VisitProposalInput(
        visit_window_start=start,
        visit_window_end=end,
        scope_description=str(data.get("scope_description") or ""),
        **price,
    )
    await requests_api.propose_visit(
        actor,
        request_id,
        assignment_id=assignment_id,
        data=payload,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(
            ctx,
            "requests.propose_visit",
            {**price, "window": [start, end], "scope": payload.scope_description},
        ),
    )
    await ctx.reply(texts.VISIT_PROPOSED)


dialogs.register(
    dialogs.Scenario(
        name=VISIT_SCENARIO,
        first=visit_terms.STEP_DAY,
        steps=(
            visit_terms.day_step(visit_terms.STEP_SLOT),
            visit_terms.slot_step(visit_terms.STEP_PRICE_MODE),
            visit_terms.price_mode_step(
                prompt_text=texts.OFFER_ASK_PRICE_MODE, after_price=STEP_SCOPE, allow_later=False
            ),
            visit_terms.price_sum_step(STEP_SCOPE),
            visit_terms.price_free_step(STEP_SCOPE),
            dialogs.Step(STEP_SCOPE, _prompt_visit_scope, _handle_visit_scope),
        ),
        finish=_finish_visit,
    )
)


@actions.action(ACTION_QUOTE_START)
async def _start_quote(ctx: BotContext, claimed: ClaimedAction) -> None:
    data = await _dialog_data(ctx, claimed)
    if data is None:
        return
    await dialogs.start(ctx, QUOTE_SCENARIO, **data)


async def _prompt_quote_scope(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_QUOTE_SCOPE,
        [keyboards.rows(keyboards.back_cancel_row(STEP_SCOPE, with_back=False))],
    )


async def _handle_quote_scope(ctx: BotContext, value: str) -> str | None:
    text = value.strip()
    if not text:
        await ctx.reply(texts.ASK_QUOTE_SCOPE)
        return None
    ctx.conversation.data["description_of_work"] = text[:2000]
    return visit_terms.STEP_PRICE_MODE


async def _finish_quote(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id, assignment_id = _target(data)
    price = visit_terms.price_payload(data)
    description = str(data.get("description_of_work") or "")
    await requests_api.create_repair_quote(
        actor,
        request_id,
        assignment_id=assignment_id,
        data=requests_api.RepairQuoteInput(description_of_work=description, **price),
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(
            ctx, "requests.create_repair_quote", {**price, "description": description}
        ),
    )
    await ctx.reply(texts.QUOTE_CREATED)


dialogs.register(
    dialogs.Scenario(
        name=QUOTE_SCENARIO,
        first=STEP_SCOPE,
        steps=(
            dialogs.Step(STEP_SCOPE, _prompt_quote_scope, _handle_quote_scope, allow_back=False),
            visit_terms.price_mode_step(
                prompt_text=texts.QUOTE_ASK_PRICE_MODE,
                after_price=dialogs.FINISH,
                allow_later=False,
            ),
            visit_terms.price_sum_step(dialogs.FINISH),
            visit_terms.price_free_step(dialogs.FINISH),
        ),
        finish=_finish_quote,
    )
)
