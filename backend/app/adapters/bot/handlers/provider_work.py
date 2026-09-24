from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.bot import actions, buttons, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.core import ids
from app.db.enums import AssignmentState
from app.infra.max.types import Button
from app.modules.requests import api as requests_api

ACTION_VISIT_START = "visit.start"
ACTION_QUOTE_START = "quote.start"
ACTION_START_WORK = "assignment.start_work"
ACTION_EN_ROUTE = "assignment.en_route"
ACTION_WARRANTY = "assignment.warranty"
ACTION_REPORT_START = "assignment.report_start"
ACTION_WITHDRAW_START = "assignment.withdraw_start"
ACTION_FIELD_WORKER_START = "assignment.field_worker_start"
ACTION_CANCEL_ACCEPT = "cancellation.provider_accept"
ACTION_CANCEL_DECLINE = "cancellation.provider_decline"
ACTION_MORE = "in_progress.more"

PAGE_SIZE = 10

ACTIVE_STATES = frozenset({"accepted", "scheduled", "in_progress"})
WORK_STATES = ACTIVE_STATES | {"cancellation_pending", "completion_reported"}

_WARRANTY_CHOICES = (
    ("warranty", texts.WARRANTY_YES),
    ("not_warranty", texts.WARRANTY_NO),
    ("undetermined", texts.WARRANTY_UNDETERMINED),
)


@menu.menu("in_progress")
async def show_in_progress(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    if actor is None or actor.side != "provider":
        await ctx.reply(texts.NOT_PROVIDER_SIDE)
        return
    await _send_page(ctx, cursor=None)


async def _send_page(ctx: BotContext, *, cursor: str | None) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    items, next_cursor = await requests_api.list_requests(
        actor, assignment_states=[AssignmentState.ACCEPTED], cursor=cursor, limit=PAGE_SIZE
    )
    shown = False
    for item in items:
        if item.status not in WORK_STATES or item.assignment_id is None:
            continue
        view = await requests_api.get_request(actor, ids.decode("request", item.id))
        if isinstance(view, requests_api.RequestProviderView):
            await send_work_card(ctx, view)
            shown = True
    if not shown and cursor is None:
        await ctx.reply(texts.IN_PROGRESS_EMPTY)
        return
    if next_cursor:
        more = await buttons.mint(
            ctx, ActionSpec(texts.BUTTON_MORE, ACTION_MORE, params={"cursor": next_cursor})
        )
        await ctx.reply(texts.BUTTON_MORE, [keyboards.rows([more])])


@actions.action(ACTION_MORE)
async def _more(ctx: BotContext, claimed: ClaimedAction) -> None:
    cursor = claimed.params.get("cursor")
    await _send_page(ctx, cursor=cursor if isinstance(cursor, str) else None)


@dataclass(frozen=True, slots=True)
class WorkState:
    view: requests_api.RequestProviderView

    def spec(self, label: str, action_type: str, **params: str) -> ActionSpec:
        return ActionSpec(
            label,
            action_type,
            object_type="assignment",
            object_id=ids.decode("assignment", self.view.assignment.id),
            expected_version=self.view.version,
            params={"request_id": self.view.id, **params},
        )


def _single(label: str, action_type: str) -> Callable[[WorkState], list[ActionSpec]]:
    return lambda s: [s.spec(label, action_type)]


def _warranty_row(state: WorkState) -> list[ActionSpec]:
    return [
        state.spec(label, ACTION_WARRANTY, decision=value) for value, label in _WARRANTY_CHOICES
    ]


def _cancellation_row(state: WorkState) -> list[ActionSpec]:
    cancellation = state.view.cancellation
    assert cancellation is not None
    params = {"request_id": state.view.id, "assignment_id": state.view.assignment.id}
    return [
        ActionSpec(
            label,
            action_type,
            object_type="cancellation",
            object_id=ids.decode("cancellation", cancellation.id),
            expected_version=state.view.version,
            params=params,
        )
        for label, action_type in (
            (texts.BUTTON_ACCEPT_CANCELLATION, ACTION_CANCEL_ACCEPT),
            (texts.BUTTON_DISPUTE_CANCELLATION, ACTION_CANCEL_DECLINE),
        )
    ]


@dataclass(frozen=True, slots=True)
class WorkRule:
    applies: Callable[[WorkState], bool]
    build: Callable[[WorkState], list[ActionSpec]]


_WORK_RULES: tuple[WorkRule, ...] = (
    WorkRule(
        lambda s: s.view.status in {"accepted", "scheduled"},
        _single(texts.BUTTON_PROPOSE_VISIT, ACTION_VISIT_START),
    ),
    WorkRule(
        lambda s: s.view.status in ACTIVE_STATES,
        _single(texts.BUTTON_REPAIR_QUOTE, ACTION_QUOTE_START),
    ),
    WorkRule(
        lambda s: s.view.status == "scheduled" and s.view.assignment.en_route_at is None,
        _single(texts.BUTTON_EN_ROUTE, ACTION_EN_ROUTE),
    ),
    WorkRule(
        lambda s: s.view.status == "scheduled",
        _single(texts.BUTTON_START_WORK, ACTION_START_WORK),
    ),
    WorkRule(
        lambda s: s.view.status == "in_progress",
        _single(texts.BUTTON_REPORT_DONE, ACTION_REPORT_START),
    ),
    WorkRule(lambda s: s.view.status in ACTIVE_STATES, _warranty_row),
    WorkRule(
        lambda s: s.view.status in ACTIVE_STATES,
        _single(texts.BUTTON_FIELD_WORKER, ACTION_FIELD_WORKER_START),
    ),
    WorkRule(
        lambda s: s.view.status in {"accepted", "scheduled"},
        _single(texts.BUTTON_WITHDRAW_ASSIGNMENT, ACTION_WITHDRAW_START),
    ),
    WorkRule(
        lambda s: s.view.cancellation is not None and s.view.cancellation.status == "pending",
        _cancellation_row,
    ),
)


def _card_lines(view: requests_api.RequestProviderView) -> list[str]:
    lines = [
        texts.WORK_CARD_HEADER.format(
            number=view.request_number, status=texts.STATUS_LABELS.get(view.status, view.status)
        ),
        texts.REVIEW_EQUIPMENT.format(
            title=" ".join(p for p in (view.equipment.brand, view.equipment.model) if p) or "—"
        ),
        texts.REVIEW_SYMPTOMS.format(symptoms=view.symptom_description or "—"),
    ]
    if view.contacts_disclosed and view.location.address:
        lines.append(texts.WORK_CARD_ADDRESS.format(address=view.location.address))
    if view.status == "scheduled" and view.assignment.en_route_at is not None:
        lines.append(texts.WORK_CARD_EN_ROUTE)
    if view.status == "completion_reported":
        lines.append(texts.WORK_CARD_COMPLETION_REPORTED)
    worker = view.assignment.field_worker
    if worker is not None and worker.display_name:
        lines.append(texts.WORK_CARD_FIELD_WORKER.format(name=worker.display_name))
    decision = view.assignment.warranty_decision
    if decision and decision != "not_stated":
        lines.append(
            texts.WORK_CARD_WARRANTY.format(decision=texts.WARRANTY_LABELS.get(decision, decision))
        )
    if view.cancellation is not None and view.cancellation.status == "pending":
        lines.append(
            texts.WORK_CARD_CANCEL_REQUESTED.format(reason=view.cancellation.reason or "—")
        )
    return lines


async def send_work_card(ctx: BotContext, view: requests_api.RequestProviderView) -> None:
    state = WorkState(view)
    rows: list[list[Button]] = await buttons.mint_rows(
        ctx, [rule.build(state) for rule in _WORK_RULES if rule.applies(state)]
    )
    rows.append([keyboards.open_app(texts.BUTTON_OPEN_IN_APP, "request", view.id)])
    await ctx.reply("\n".join(_card_lines(view)), [keyboards.rows(*rows)])


async def _target(ctx: BotContext, claimed: ClaimedAction) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Заявка и назначение из кнопки карточки."""
    if claimed.object_id is None or claimed.request_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return None
    return claimed.request_id, claimed.object_id


@actions.action(ACTION_START_WORK)
async def _start_work(ctx: BotContext, claimed: ClaimedAction) -> None:
    target = await _target(ctx, claimed)
    actor = await ctx.org_actor()
    if target is None or actor is None:
        return
    request_id, assignment_id = target
    await requests_api.start_work(
        actor,
        request_id,
        assignment_id=assignment_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.WORK_STARTED)


@actions.action(ACTION_EN_ROUTE)
async def _en_route(ctx: BotContext, claimed: ClaimedAction) -> None:
    target = await _target(ctx, claimed)
    actor = await ctx.org_actor()
    if target is None or actor is None:
        return
    request_id, assignment_id = target
    await requests_api.mark_en_route(
        actor,
        request_id,
        assignment_id=assignment_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.EN_ROUTE_MARKED)


@actions.action(ACTION_CANCEL_ACCEPT)
async def _cancel_accept(ctx: BotContext, claimed: ClaimedAction) -> None:
    request_id = claimed.request_id
    assignment_value = claimed.params.get("assignment_id")
    if claimed.object_id is None or request_id is None or not isinstance(assignment_value, str):
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    await requests_api.respond_cancellation(
        actor,
        request_id,
        assignment_id=ids.decode("assignment", assignment_value),
        cancellation_id=claimed.object_id,
        decision="accept",
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.CANCEL_DONE)
