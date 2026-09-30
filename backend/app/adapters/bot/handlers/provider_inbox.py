from __future__ import annotations

import uuid

from app.adapters.bot import actions, dialogs, formatting, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.core import ids
from app.core.actor import Actor
from app.modules.requests import api as requests_api

ACTION_ACCEPT = "assignment.accept"
ACTION_DECLINE_START = "assignment.decline_start"
ACTION_MORE = "inbox.more"

DECLINE_SCENARIO = "req_decline"
STEP_REASON = "reason"

PAGE_SIZE = 10


@menu.menu("inbox")
async def show_inbox(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    if actor is None or actor.side != "provider":
        await ctx.reply(texts.NOT_PROVIDER_SIDE)
        return
    await _send_page(ctx, cursor=None)


async def _send_page(ctx: BotContext, *, cursor: str | None) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    items, next_cursor = await requests_api.list_requests(
        actor, assignment_states=["pending"], cursor=cursor, limit=PAGE_SIZE
    )
    if not items and cursor is None:
        await ctx.reply(texts.INBOX_EMPTY)
        return
    for item in items:
        assignment_id = ids.decode("assignment", item.assignment_id) if item.assignment_id else None
        if assignment_id is None:
            continue
        text = texts.INBOX_ITEM.format(
            number=item.request_number,
            title=item.equipment_title or "оборудование",
            urgency=texts.URGENCY_LABELS.get(item.urgency, item.urgency),
        )
        if item.status == "awaiting_assignment_confirmation":
            deadline = await _confirm_deadline(actor, ids.decode("request", item.id))
            if deadline:
                text = f"{text}\n{deadline}"
        async with ctx.unit() as session:
            accept_code = await actions.make_action(
                session,
                ctx.user_id,
                ACTION_ACCEPT,
                ctx.now,
                object_type="assignment",
                object_id=assignment_id,
                expected_version=item.version,
                params={"request_id": item.id},
            )
            decline_code = await actions.make_action(
                session,
                ctx.user_id,
                ACTION_DECLINE_START,
                ctx.now,
                object_type="assignment",
                object_id=assignment_id,
                expected_version=item.version,
                params={"request_id": item.id},
            )
        await ctx.reply(
            text,
            [
                keyboards.rows(
                    [
                        keyboards.action_button(texts.BUTTON_ACCEPT, accept_code),
                        keyboards.action_button(texts.BUTTON_DECLINE, decline_code),
                    ],
                    [keyboards.open_app(texts.BUTTON_OPEN_IN_APP, "request", item.id)],
                )
            ],
        )
    if next_cursor:
        async with ctx.unit() as session:
            code = await actions.make_action(
                session, ctx.user_id, ACTION_MORE, ctx.now, params={"cursor": next_cursor}
            )
        await ctx.reply(
            texts.BUTTON_MORE, [keyboards.rows([keyboards.action_button(texts.BUTTON_MORE, code)])]
        )


@actions.action(ACTION_MORE)
async def _more(ctx: BotContext, claimed: ClaimedAction) -> None:
    cursor = claimed.params.get("cursor")
    await _send_page(ctx, cursor=cursor if isinstance(cursor, str) else None)


async def _confirm_deadline(actor: Actor, request_id: uuid.UUID) -> str | None:
    view = await requests_api.get_request(actor, request_id)
    if not isinstance(view, requests_api.RequestProviderView) or view.assignment.expires_at is None:
        return None
    deadline = formatting.format_local_moment(view.assignment.expires_at, view.location.timezone)
    return texts.INBOX_CONFIRM_DEADLINE.format(deadline=deadline)


@actions.action(ACTION_ACCEPT)
async def _accept(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = _request_id(claimed)
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    await requests_api.accept_assignment(
        actor,
        request_id,
        assignment_id=claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.ASSIGNMENT_ACCEPTED)


@actions.action(ACTION_DECLINE_START)
async def _decline_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = _request_id(claimed)
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        DECLINE_SCENARIO,
        request_id=str(request_id),
        assignment_id=str(claimed.object_id),
        expected_version=claimed.expected_version,
    )


async def _prompt_reason(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_DECLINE_REASON,
        [keyboards.rows(keyboards.back_cancel_row(STEP_REASON, with_back=False))],
    )


async def _handle_reason(ctx: BotContext, value: str) -> str | None:
    reason = value.strip()
    if not reason:
        await ctx.reply(texts.ASK_DECLINE_REASON)
        return None
    ctx.conversation.data["reason"] = reason[:2000]
    return dialogs.FINISH


async def _finish(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    reason = str(data["reason"])
    await requests_api.decline_assignment(
        actor,
        uuid.UUID(str(data["request_id"])),
        assignment_id=uuid.UUID(str(data["assignment_id"])),
        reason=reason,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.decline_assignment", {"reason": reason}),
    )
    await ctx.reply(texts.ASSIGNMENT_DECLINED)


dialogs.register(
    dialogs.Scenario(
        name=DECLINE_SCENARIO,
        first=STEP_REASON,
        steps=(dialogs.Step(STEP_REASON, _prompt_reason, _handle_reason, allow_back=False),),
        finish=_finish,
    )
)


def _request_id(claimed: ClaimedAction) -> uuid.UUID | None:
    value = claimed.params.get("request_id")
    if not isinstance(value, str):
        return None
    try:
        return ids.decode("request", value)
    except Exception:
        return None
