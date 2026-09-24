from __future__ import annotations

import uuid

from app.adapters.bot import actions, dialogs, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import cards
from app.adapters.bot.handlers.request_actions import (
    ACTION_CANCEL_FORCE,
    ACTION_CANCEL_START,
    ACTION_CANCEL_WITHDRAW,
    manager_actor,
)
from app.modules.requests import api as requests_api

CANCEL_SCENARIO = "req_cancel"
STEP_CANCEL_TARGET = "target"
STEP_CANCEL_REASON = "reason"


@actions.action(ACTION_CANCEL_START)
async def _start_cancel(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        CANCEL_SCENARIO,
        request_id=str(claimed.object_id),
        expected_version=claimed.expected_version,
    )


async def _prompt_cancel_target(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(texts.CANCEL_TARGET_STOP, STEP_CANCEL_TARGET, "cancel_request")],
        [
            keyboards.dialog_button(
                texts.CANCEL_TARGET_CHANGE, STEP_CANCEL_TARGET, "change_provider"
            )
        ],
        keyboards.back_cancel_row(STEP_CANCEL_TARGET, with_back=False),
    ]
    await ctx.reply(texts.ASK_CANCEL_TARGET, [keyboards.rows(*rows)])


async def _handle_cancel_target(ctx: BotContext, value: str) -> str | None:
    if value not in {"cancel_request", "change_provider"}:
        return None
    ctx.conversation.data["target"] = value
    return STEP_CANCEL_REASON


async def _prompt_cancel_reason(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_CANCEL_REASON, [keyboards.rows(keyboards.back_cancel_row(STEP_CANCEL_REASON))]
    )


async def _handle_cancel_reason(ctx: BotContext, value: str) -> str | None:
    ctx.conversation.data["reason"] = value.strip()[:2000] or None
    return dialogs.FINISH


async def _finish_cancel(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id = uuid.UUID(str(data["request_id"]))
    target = str(data["target"])
    result = await requests_api.request_cancellation(
        actor,
        request_id,
        target=target,
        reason=data.get("reason"),
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(
            ctx, "requests.request_cancellation", {"target": target, "reason": data.get("reason")}
        ),
    )
    status = result.body.get("status")
    if status == "cancelled":
        await ctx.reply(texts.CANCEL_DONE)
        return
    if status == "action_required":
        await ctx.reply(texts.CHANGE_PROVIDER_DONE)
        await cards.show_actual(ctx, request_id)
        return
    await ctx.reply(texts.CANCEL_REQUESTED)


dialogs.register(
    dialogs.Scenario(
        name=CANCEL_SCENARIO,
        first=STEP_CANCEL_TARGET,
        steps=(
            dialogs.Step(
                STEP_CANCEL_TARGET, _prompt_cancel_target, _handle_cancel_target, allow_back=False
            ),
            dialogs.Step(STEP_CANCEL_REASON, _prompt_cancel_reason, _handle_cancel_reason),
        ),
        finish=_finish_cancel,
    )
)


@actions.action(ACTION_CANCEL_WITHDRAW)
async def _withdraw_cancellation(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await manager_actor(ctx)
    if actor is None:
        return
    await requests_api.withdraw_cancellation(
        actor,
        request_id,
        cancellation_id=claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.CANCEL_WITHDRAWN)


@actions.action(ACTION_CANCEL_FORCE)
async def _force_cancellation(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await manager_actor(ctx)
    if actor is None:
        return
    await requests_api.force_cancellation(
        actor,
        request_id,
        cancellation_id=claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.CANCEL_FORCED)
