from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.adapters.bot import actions, buttons, dialogs, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import cards
from app.core import ids
from app.core.actor import UserActor
from app.infra.max.types import Button
from app.modules.requests import api as requests_api
from app.modules.requests.views import RepairQuoteView

ACTION_VISIT_APPROVE = "visit_proposal.approve"
ACTION_VISIT_REJECT = "visit_proposal.reject"
ACTION_QUOTE_APPROVE = "repair_quote.approve"
ACTION_QUOTE_REJECT = "repair_quote.reject"
ACTION_COMPLETION_CONFIRM = "completion.confirm"
ACTION_COMPLETION_PROBLEM = "completion.problem"
ACTION_CANCEL_START = "cancellation.start"
ACTION_CANCEL_WITHDRAW = "cancellation.withdraw"
ACTION_CANCEL_FORCE = "cancellation.force"
ACTION_OFFERS_LIST = "offers.list"
ACTION_OFFER_PREVIEW = "offer.select_preview"
ACTION_OFFER_CONFIRM = "offer.select_confirm"

PROBLEM_SCENARIO = "req_problem"

STEP_PROBLEM_REASON = "reason"

_CANCELLABLE = frozenset(
    {
        "approval_required",
        "awaiting_provider",
        "searching",
        "awaiting_assignment_confirmation",
        "action_required",
        "accepted",
        "scheduled",
        "in_progress",
    }
)


@dataclass(frozen=True, slots=True)
class CardState:
    actor: UserActor
    view: requests_api.RequestCustomerView
    now: datetime

    @property
    def request_id(self) -> uuid.UUID:
        return ids.decode("request", self.view.id)

    @property
    def params(self) -> dict[str, str]:
        return {"request_id": self.view.id}

    @property
    def manager(self) -> bool:
        return self.actor.is_manager


def pending_visit(view: requests_api.RequestCustomerView) -> requests_api.VisitProposalView | None:
    return next((p for p in view.visit_proposals if p.status == "pending"), None)


def pending_quote(view: requests_api.RequestCustomerView) -> RepairQuoteView | None:
    return next((q for q in view.repair_quotes if q.status == "pending"), None)


def _terms_spec(
    state: CardState,
    label: str,
    action_type: str,
    object_type: str,
    public_id: str,
    version: int,
) -> ActionSpec:
    return ActionSpec(
        label,
        action_type,
        object_type=object_type,
        object_id=ids.decode(object_type, public_id),
        expected_version=state.view.version,
        proposal_version=version,
        params=state.params,
    )


def _visit_row(state: CardState) -> list[ActionSpec]:
    proposal = pending_visit(state.view)
    assert proposal is not None
    approve = texts.BUTTON_APPROVE_VISIT.format(version=proposal.version)
    return [
        _terms_spec(
            state, approve, ACTION_VISIT_APPROVE, "visit_proposal", proposal.id, proposal.version
        ),
        _terms_spec(
            state,
            texts.BUTTON_REJECT_VISIT,
            ACTION_VISIT_REJECT,
            "visit_proposal",
            proposal.id,
            proposal.version,
        ),
    ]


def _quote_row(state: CardState) -> list[ActionSpec]:
    quote = pending_quote(state.view)
    assert quote is not None
    approve = texts.BUTTON_APPROVE_QUOTE.format(version=quote.version)
    return [
        _terms_spec(state, approve, ACTION_QUOTE_APPROVE, "repair_quote", quote.id, quote.version),
        _terms_spec(
            state,
            texts.BUTTON_REJECT_QUOTE,
            ACTION_QUOTE_REJECT,
            "repair_quote",
            quote.id,
            quote.version,
        ),
    ]


def _request_button(label: str, action_type: str) -> Callable[[CardState], list[ActionSpec]]:
    def build(state: CardState) -> list[ActionSpec]:
        return [
            ActionSpec(
                label,
                action_type,
                object_type="request",
                object_id=state.request_id,
                expected_version=state.view.version,
            )
        ]

    return build


def _completion_row(state: CardState) -> list[ActionSpec]:
    return [
        *_request_button(texts.BUTTON_CONFIRM_DONE, ACTION_COMPLETION_CONFIRM)(state),
        *_request_button(texts.BUTTON_PROBLEM_REMAINS, ACTION_COMPLETION_PROBLEM)(state),
    ]


def _cancellation_button(label: str, action_type: str) -> Callable[[CardState], list[ActionSpec]]:
    def build(state: CardState) -> list[ActionSpec]:
        assert state.view.cancellation is not None
        return [
            ActionSpec(
                label,
                action_type,
                object_type="cancellation",
                object_id=ids.decode("cancellation", state.view.cancellation.id),
                expected_version=state.view.version,
                params=state.params,
            )
        ]

    return build


def _cancellation_status(state: CardState) -> str | None:
    return state.view.cancellation.status if state.view.cancellation is not None else None


def _force_allowed(state: CardState) -> bool:
    cancellation = state.view.cancellation
    if cancellation is None or cancellation.status not in {"pending", "disputed"}:
        return False
    deadline = cancellation.dispute_deadline_at
    return deadline is not None and deadline <= state.now


@dataclass(frozen=True, slots=True)
class CardRule:
    applies: Callable[[CardState], bool]
    build: Callable[[CardState], list[ActionSpec]]


def _route_rules() -> tuple[CardRule, ...]:
    from app.adapters.bot.handlers import request_details, request_route

    return (*request_route.CARD_RULES, *request_details.CARD_RULES)


_CARD_RULES: tuple[CardRule, ...] = (
    CardRule(lambda s: s.manager and pending_visit(s.view) is not None, _visit_row),
    CardRule(lambda s: s.manager and pending_quote(s.view) is not None, _quote_row),
    CardRule(
        lambda s: s.manager and s.view.status == "completion_reported",
        _completion_row,
    ),
    CardRule(
        lambda s: s.view.status == "searching",
        _request_button(texts.BUTTON_OFFERS, ACTION_OFFERS_LIST),
    ),
    CardRule(
        lambda s: s.manager and _cancellation_status(s) == "pending",
        _cancellation_button(texts.CANCEL_WITHDRAW, ACTION_CANCEL_WITHDRAW),
    ),
    CardRule(
        lambda s: s.manager and _force_allowed(s),
        _cancellation_button(texts.CANCEL_FORCE, ACTION_CANCEL_FORCE),
    ),
    CardRule(
        lambda s: (
            s.manager
            and _cancellation_status(s) not in {"pending", "disputed"}
            and s.view.status in _CANCELLABLE
        ),
        _request_button(texts.BUTTON_CANCEL_REQUEST, ACTION_CANCEL_START),
    ),
)


async def card_buttons(
    ctx: BotContext, actor: UserActor, view: requests_api.RequestCustomerView
) -> list[list[Button]]:
    state = CardState(actor=actor, view=view, now=ctx.now)
    rules = (*_CARD_RULES, *_route_rules())
    return await buttons.mint_rows(
        ctx, [rule.build(state) for rule in rules if rule.applies(state)]
    )


async def manager_actor(ctx: BotContext) -> UserActor | None:
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return None
    if not actor.is_manager:
        await ctx.reply(texts.NOT_MANAGER_FOR_APPROVAL)
        return None
    return actor


@actions.action(ACTION_VISIT_APPROVE)
async def _visit_approve(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _respond_visit(ctx, claimed, approve=True)


@actions.action(ACTION_VISIT_REJECT)
async def _visit_reject(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _respond_visit(ctx, claimed, approve=False)


async def _respond_visit(ctx: BotContext, claimed: ClaimedAction, *, approve: bool) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None or claimed.proposal_version is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await manager_actor(ctx)
    if actor is None:
        return
    fn = requests_api.approve_visit_proposal if approve else requests_api.reject_visit_proposal
    await fn(
        actor,
        request_id,
        proposal_id=claimed.object_id,
        proposal_version=claimed.proposal_version,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.VISIT_PROPOSAL_APPROVED if approve else texts.VISIT_PROPOSAL_REJECTED)
    await cards.show_actual(ctx, request_id)


@actions.action(ACTION_QUOTE_APPROVE)
async def _quote_approve(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _respond_quote(ctx, claimed, approve=True)


@actions.action(ACTION_QUOTE_REJECT)
async def _quote_reject(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _respond_quote(ctx, claimed, approve=False)


async def _respond_quote(ctx: BotContext, claimed: ClaimedAction, *, approve: bool) -> None:
    request_id = claimed.request_id
    if claimed.object_id is None or request_id is None or claimed.proposal_version is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await manager_actor(ctx)
    if actor is None:
        return
    fn = requests_api.approve_repair_quote if approve else requests_api.reject_repair_quote
    await fn(
        actor,
        request_id,
        quote_id=claimed.object_id,
        quote_version=claimed.proposal_version,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.REPAIR_QUOTE_APPROVED if approve else texts.REPAIR_QUOTE_REJECTED)
    await cards.show_actual(ctx, request_id)


@actions.action(ACTION_COMPLETION_CONFIRM)
async def _confirm_completion(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await manager_actor(ctx)
    if actor is None:
        return
    await requests_api.confirm_completion(
        actor,
        claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await ctx.reply(texts.CONFIRM_DONE_TEXT)


@actions.action(ACTION_COMPLETION_PROBLEM)
async def _start_problem(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.start(
        ctx,
        PROBLEM_SCENARIO,
        request_id=str(claimed.object_id),
        expected_version=claimed.expected_version,
    )


async def _prompt_problem_reason(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_PROBLEM_REASON,
        [keyboards.rows(keyboards.back_cancel_row(STEP_PROBLEM_REASON, with_back=False))],
    )


async def _handle_problem_reason(ctx: BotContext, value: str) -> str | None:
    reason = value.strip()
    if not reason:
        await ctx.reply(texts.ASK_PROBLEM_REASON)
        return None
    ctx.conversation.data["reason"] = reason[:2000]
    return dialogs.FINISH


async def _finish_problem(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    request_id = uuid.UUID(str(data["request_id"]))
    await requests_api.reject_completion(
        actor,
        request_id,
        reason=str(data["reason"]),
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.reject_completion", {"reason": data["reason"]}),
    )
    await ctx.reply(texts.PROBLEM_REPORTED)


dialogs.register(
    dialogs.Scenario(
        name=PROBLEM_SCENARIO,
        first=STEP_PROBLEM_REASON,
        steps=(
            dialogs.Step(
                STEP_PROBLEM_REASON,
                _prompt_problem_reason,
                _handle_problem_reason,
                allow_back=False,
            ),
        ),
        finish=_finish_problem,
    )
)
