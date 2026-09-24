from __future__ import annotations

import uuid
from typing import Any

from app.adapters.bot import actions, dialogs, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers.provider_work import (
    ACTION_CANCEL_DECLINE,
    ACTION_FIELD_WORKER_START,
    ACTION_REPORT_START,
    ACTION_WARRANTY,
    ACTION_WITHDRAW_START,
)
from app.core import ids
from app.modules.identity import api as identity
from app.modules.requests import api as requests_api

REPORT_SCENARIO = "req_report"
WITHDRAW_SCENARIO = "req_withdraw"
FIELD_WORKER_SCENARIO = "req_field_worker"
WARRANTY_SCENARIO = "req_warranty"
DISPUTE_SCENARIO = "req_cancel_dispute"

STEP_OUTCOME = "outcome"
STEP_SUMMARY = "summary"
STEP_REASON = "reason"
STEP_WORKER = "worker"
STEP_WORKER_NAME = "worker_name"
STEP_WORKER_PHONE = "worker_phone"
STEP_COMMENT = "comment"

_WARRANTY_DECISIONS = frozenset({"warranty", "not_warranty", "undetermined"})

WORKER_PAGE_SIZE = 8


def _dialog_data(claimed: ClaimedAction) -> dict[str, Any] | None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None:
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


async def _start(ctx: BotContext, claimed: ClaimedAction, scenario: str) -> None:
    data = _dialog_data(claimed)
    if data is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(ctx, scenario, **data)


def _text_step(
    name: str, prompt_text: str, key: str, next_step: str, *, first: bool = False
) -> dialogs.Step:
    async def prompt(ctx: BotContext) -> None:
        rows = [keyboards.back_cancel_row(name, with_back=not first)]
        await ctx.reply(prompt_text, [keyboards.rows(*rows)])

    async def handle(ctx: BotContext, value: str) -> str | None:
        text = value.strip()
        if not text:
            await ctx.reply(prompt_text)
            return None
        ctx.conversation.data[key] = text[:2000]
        return next_step

    return dialogs.Step(name, prompt, handle, allow_back=not first)


@actions.action(ACTION_REPORT_START)
async def _report_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _start(ctx, claimed, REPORT_SCENARIO)


async def _prompt_outcome(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(texts.OUTCOME_BUTTON_RESOLVED, STEP_OUTCOME, "resolved")],
        [keyboards.dialog_button(texts.OUTCOME_BUTTON_NOT_RESOLVED, STEP_OUTCOME, "not_resolved")],
        keyboards.back_cancel_row(STEP_OUTCOME, with_back=False),
    ]
    await ctx.reply(texts.ASK_OUTCOME, [keyboards.rows(*rows)])


async def _handle_outcome(ctx: BotContext, value: str) -> str | None:
    if value not in {"resolved", "not_resolved"}:
        return None
    ctx.conversation.data["outcome"] = value
    return STEP_SUMMARY


async def _finish_report(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id, assignment_id = _target(data)
    outcome, summary = str(data["outcome"]), str(data["summary"])
    await requests_api.report_completion(
        actor,
        request_id,
        assignment_id=assignment_id,
        outcome=outcome,
        summary=summary,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(
            ctx, "requests.report_completion", {"outcome": outcome, "summary": summary}
        ),
    )
    await ctx.reply(texts.COMPLETION_SENT)


dialogs.register(
    dialogs.Scenario(
        name=REPORT_SCENARIO,
        first=STEP_OUTCOME,
        steps=(
            dialogs.Step(STEP_OUTCOME, _prompt_outcome, _handle_outcome, allow_back=False),
            _text_step(STEP_SUMMARY, texts.ASK_SUMMARY, "summary", dialogs.FINISH),
        ),
        finish=_finish_report,
    )
)


@actions.action(ACTION_WITHDRAW_START)
async def _withdraw_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _start(ctx, claimed, WITHDRAW_SCENARIO)


async def _finish_withdraw(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id, assignment_id = _target(data)
    reason = str(data["reason"])
    await requests_api.withdraw_assignment(
        actor,
        request_id,
        assignment_id=assignment_id,
        reason=reason,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.withdraw_assignment", {"reason": reason}),
    )
    await ctx.reply(texts.ASSIGNMENT_WITHDRAWN)


dialogs.register(
    dialogs.Scenario(
        name=WITHDRAW_SCENARIO,
        first=STEP_REASON,
        steps=(
            _text_step(
                STEP_REASON, texts.ASK_WITHDRAW_REASON, "reason", dialogs.FINISH, first=True
            ),
        ),
        finish=_finish_withdraw,
    )
)


@actions.action(ACTION_FIELD_WORKER_START)
async def _field_worker_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _start(ctx, claimed, FIELD_WORKER_SCENARIO)


async def _active_members(ctx: BotContext) -> list[identity.MemberView]:
    scope = await ctx.scope()
    if scope is None:
        return []
    members: list[identity.MemberView] = []
    cursor: uuid.UUID | None = None
    while True:
        page, cursor = await identity.list_members(scope, cursor=cursor, limit=100)
        members.extend(m for m in page if m.status == "active")
        if cursor is None:
            break
    return members


async def _prompt_worker(ctx: BotContext) -> None:
    members = await _active_members(ctx)
    page = int(ctx.conversation.data.get("worker_page", 0))
    chunk, has_prev, has_next = keyboards.paginate(members, page, WORKER_PAGE_SIZE)
    rows = [[keyboards.dialog_button(m.user.display_name[:64], STEP_WORKER, m.id)] for m in chunk]
    rows.append(keyboards.nav_row(STEP_WORKER, page, has_prev=has_prev, has_next=has_next))
    rows.append([keyboards.dialog_button(texts.BUTTON_WORKER_BY_NAME, STEP_WORKER, "name")])
    rows.append(keyboards.back_cancel_row(STEP_WORKER, with_back=False))
    await ctx.reply(texts.ASK_FIELD_WORKER, [keyboards.rows(*rows)])


async def _handle_worker(ctx: BotContext, value: str) -> str | None:
    if value.startswith("page="):
        ctx.conversation.data["worker_page"] = max(int(value[5:] or 0), 0)
        return STEP_WORKER
    if value == "name":
        return STEP_WORKER_NAME
    if not any(m.id == value for m in await _active_members(ctx)):
        await ctx.reply(texts.ASK_FIELD_WORKER)
        return None
    ctx.conversation.data["membership_id"] = value
    return dialogs.FINISH


async def _prompt_worker_phone(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(texts.BUTTON_NO_PHONE, STEP_WORKER_PHONE, "skip")],
        keyboards.back_cancel_row(STEP_WORKER_PHONE),
    ]
    await ctx.reply(texts.ASK_FIELD_WORKER_PHONE, [keyboards.rows(*rows)])


async def _handle_worker_phone(ctx: BotContext, value: str) -> str | None:
    phone = None if value == "skip" else value.strip()[:50] or None
    ctx.conversation.data["contact_phone"] = phone
    return dialogs.FINISH


async def _finish_field_worker(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id, assignment_id = _target(data)
    membership = data.get("membership_id")
    body = {
        "membership_id": membership,
        "display_name": data.get("display_name"),
        "contact_phone": data.get("contact_phone"),
    }
    await requests_api.set_field_worker(
        actor,
        request_id,
        assignment_id=assignment_id,
        membership_id=ids.decode("membership", membership) if isinstance(membership, str) else None,
        display_name=data.get("display_name"),
        contact_phone=data.get("contact_phone"),
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.set_field_worker", body),
    )
    await ctx.reply(texts.FIELD_WORKER_SET)


dialogs.register(
    dialogs.Scenario(
        name=FIELD_WORKER_SCENARIO,
        first=STEP_WORKER,
        steps=(
            dialogs.Step(STEP_WORKER, _prompt_worker, _handle_worker, allow_back=False),
            _text_step(
                STEP_WORKER_NAME, texts.ASK_FIELD_WORKER_NAME, "display_name", STEP_WORKER_PHONE
            ),
            dialogs.Step(STEP_WORKER_PHONE, _prompt_worker_phone, _handle_worker_phone),
        ),
        finish=_finish_field_worker,
    )
)


@actions.action(ACTION_WARRANTY)
async def _warranty_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    """Решение выбрано кнопкой карточки; пояснение обязательно (D8) — следующим шагом."""
    data = _dialog_data(claimed)
    decision = claimed.params.get("decision")
    if data is None or decision not in _WARRANTY_DECISIONS:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(ctx, WARRANTY_SCENARIO, decision=decision, **data)


async def _prompt_warranty_comment(ctx: BotContext) -> None:
    decision = str(ctx.conversation.data.get("decision"))
    label = texts.WARRANTY_LABELS.get(decision, decision)
    rows = [keyboards.back_cancel_row(STEP_COMMENT, with_back=False)]
    await ctx.reply(texts.ASK_WARRANTY_COMMENT.format(decision=label), [keyboards.rows(*rows)])


async def _handle_comment(ctx: BotContext, value: str) -> str | None:
    text = value.strip()
    if not text:
        await ctx.reply(texts.ASK_COMMENT_AGAIN)
        return None
    ctx.conversation.data["comment"] = text[:2000]
    return dialogs.FINISH


async def _finish_warranty(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id, assignment_id = _target(data)
    decision, comment = str(data["decision"]), str(data["comment"])
    await requests_api.set_warranty_decision(
        actor,
        request_id,
        assignment_id=assignment_id,
        decision=decision,
        comment=comment,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(
            ctx, "requests.set_warranty_decision", {"decision": decision, "comment": comment}
        ),
    )
    await ctx.reply(texts.WARRANTY_SAVED)


dialogs.register(
    dialogs.Scenario(
        name=WARRANTY_SCENARIO,
        first=STEP_COMMENT,
        steps=(
            dialogs.Step(STEP_COMMENT, _prompt_warranty_comment, _handle_comment, allow_back=False),
        ),
        finish=_finish_warranty,
    )
)


@actions.action(ACTION_CANCEL_DECLINE)
async def _dispute_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    """«Не согласен» из карточки или уведомления: причина нужна для ручного
    согласования (ТЗ S6), шаблонный текст её не заменяет."""
    request_id = claimed.request_id
    assignment_value = claimed.params.get("assignment_id")
    if claimed.object_id is None or request_id is None or not isinstance(assignment_value, str):
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        DISPUTE_SCENARIO,
        request_id=ids.encode("request", request_id),
        assignment_id=assignment_value,
        cancellation_id=ids.encode("cancellation", claimed.object_id),
        expected_version=claimed.expected_version,
    )


async def _prompt_dispute_reason(ctx: BotContext) -> None:
    rows = [keyboards.back_cancel_row(STEP_COMMENT, with_back=False)]
    await ctx.reply(texts.ASK_DISPUTE_REASON, [keyboards.rows(*rows)])


async def _finish_dispute(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id, assignment_id = _target(data)
    comment = str(data["comment"])
    await requests_api.respond_cancellation(
        actor,
        request_id,
        assignment_id=assignment_id,
        cancellation_id=ids.decode("cancellation", str(data["cancellation_id"])),
        decision="decline",
        comment=comment,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(
            ctx, "requests.respond_cancellation", {"decision": "decline", "comment": comment}
        ),
    )
    await ctx.reply(texts.CANCEL_DISPUTE_SENT)


dialogs.register(
    dialogs.Scenario(
        name=DISPUTE_SCENARIO,
        first=STEP_COMMENT,
        steps=(
            dialogs.Step(STEP_COMMENT, _prompt_dispute_reason, _handle_comment, allow_back=False),
        ),
        finish=_finish_dispute,
    )
)
