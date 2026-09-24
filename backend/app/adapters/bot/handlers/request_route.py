from __future__ import annotations

from app.adapters.bot import actions, dialogs, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import cards, draft_steps, publication
from app.adapters.bot.handlers.request_actions import CardRule, CardState
from app.core import ids
from app.db.enums import RequestRoute
from app.modules.requests import api as requests_api

ACTION_PUBLICATION_OPEN = "publication.open"
ACTION_RETURN_START = "request.return_start"
ACTION_REVOKE_START = "assignment.revoke_start"
ACTION_RESEND_OWN = "request.resend_own"
ACTION_FOLLOWUP = "request.followup"

RETURN_SCENARIO = "req_return"
REVOKE_SCENARIO = "req_revoke"
STEP_COMMENT = "comment"


def _spec(label: str, action_type: str, state: CardState) -> list[ActionSpec]:
    return [
        ActionSpec(
            label,
            action_type,
            object_type="request",
            object_id=state.request_id,
            expected_version=state.view.version,
            params=state.params,
        )
    ]


def _revoke_row(state: CardState) -> list[ActionSpec]:
    assert state.view.assignment is not None
    return [
        ActionSpec(
            texts.BUTTON_REVOKE_ASSIGNMENT,
            ACTION_REVOKE_START,
            object_type="assignment",
            object_id=ids.decode("assignment", state.view.assignment.id),
            expected_version=state.view.version,
            params=state.params,
        )
    ]


def _search_label(state: CardState) -> str:
    return (
        texts.BUTTON_REPEAT_SEARCH
        if state.view.route == RequestRoute.MARKETPLACE
        else texts.BUTTON_EXTERNAL_SEARCH
    )


def _pending_own_service(state: CardState) -> bool:
    assignment = state.view.assignment
    return (
        state.view.status == "awaiting_provider"
        and assignment is not None
        and assignment.state == "pending"
    )


CARD_RULES: tuple[CardRule, ...] = (
    CardRule(
        lambda s: s.manager and s.view.status == "approval_required",
        lambda s: (
            _spec(texts.BUTTON_REVIEW_PUBLICATION, ACTION_PUBLICATION_OPEN, s)
            + _spec(texts.BUTTON_RETURN_TO_DRAFT, ACTION_RETURN_START, s)
        ),
    ),
    CardRule(lambda s: s.manager and _pending_own_service(s), _revoke_row),
    CardRule(
        lambda s: s.manager and s.view.status == "action_required",
        lambda s: _spec(_search_label(s), ACTION_PUBLICATION_OPEN, s),
    ),
    CardRule(
        lambda s: s.view.status == "action_required" and s.view.route == RequestRoute.OWN_SERVICE,
        lambda s: _spec(texts.BUTTON_RESEND_OWN, ACTION_RESEND_OWN, s),
    ),
    CardRule(
        lambda s: s.view.status in {"closed", "cancelled"},
        lambda s: _spec(texts.BUTTON_FOLLOWUP, ACTION_FOLLOWUP, s),
    ),
)


@actions.action(ACTION_PUBLICATION_OPEN)
async def _open_publication(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    view = await requests_api.get_request(actor, claimed.object_id)
    if not isinstance(view, requests_api.RequestCustomerView) or view.status not in {
        "draft",
        "approval_required",
        "action_required",
    }:
        await ctx.reply(texts.ACTION_OUTDATED)
        await cards.show_actual(ctx, claimed.object_id)
        return
    await publication.open_publication(ctx, claimed.object_id, number=view.request_number)


@actions.action(ACTION_RESEND_OWN)
async def _resend_own(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    result = await requests_api.submit_to_own_service(
        actor,
        claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.DRAFT_SUBMITTED_OWN.format(number=result.body["request_number"]))


@actions.action(ACTION_FOLLOWUP)
async def _followup(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    result = await requests_api.create_followup_request(
        actor, claimed.object_id, idem=claimed.idempotency
    )
    body = result.body
    await ctx.reply(texts.FOLLOWUP_CREATED.format(number=body["request_number"]))
    await draft_steps.resume_draft(
        ctx, ids.decode("request", body["id"]), str(body.get("route") or RequestRoute.OWN_SERVICE)
    )


@actions.action(ACTION_RETURN_START)
async def _return_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        RETURN_SCENARIO,
        request_id=ids.encode("request", claimed.object_id),
        expected_version=claimed.expected_version,
    )


@actions.action(ACTION_REVOKE_START)
async def _revoke_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        REVOKE_SCENARIO,
        request_id=ids.encode("request", request_id),
        assignment_id=ids.encode("assignment", claimed.object_id),
        expected_version=claimed.expected_version,
    )


def _comment_step(prompt_text: str, *, required: bool) -> dialogs.Step:
    async def prompt(ctx: BotContext) -> None:
        rows = [keyboards.back_cancel_row(STEP_COMMENT, with_back=False)]
        await ctx.reply(prompt_text, [keyboards.rows(*rows)])

    async def handle(ctx: BotContext, value: str) -> str | None:
        comment = value.strip()
        if required and not comment:
            await ctx.reply(prompt_text)
            return None
        ctx.conversation.data["comment"] = comment[:2000] or None
        return dialogs.FINISH

    return dialogs.Step(STEP_COMMENT, prompt, handle, allow_back=False)


async def _finish_return(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id = ids.decode("request", str(data["request_id"]))
    comment = str(data.get("comment") or "")
    await requests_api.return_to_draft(
        actor,
        request_id,
        comment=comment,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.return_to_draft", {"comment": comment}),
    )
    await ctx.reply(texts.RETURNED_TO_DRAFT)


async def _finish_revoke(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id = ids.decode("request", str(data["request_id"]))
    reason = data.get("comment")
    await requests_api.revoke_pending_assignment(
        actor,
        request_id,
        assignment_id=ids.decode("assignment", str(data["assignment_id"])),
        reason=reason,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.revoke_assignment", {"reason": reason}),
    )
    await ctx.reply(texts.ASSIGNMENT_REVOKED)
    await cards.show_actual(ctx, request_id)


dialogs.register(
    dialogs.Scenario(
        name=RETURN_SCENARIO,
        first=STEP_COMMENT,
        steps=(_comment_step(texts.ASK_RETURN_COMMENT, required=True),),
        finish=_finish_return,
    )
)
dialogs.register(
    dialogs.Scenario(
        name=REVOKE_SCENARIO,
        first=STEP_COMMENT,
        steps=(_comment_step(texts.ASK_REVOKE_REASON, required=False),),
        finish=_finish_revoke,
    )
)
