from __future__ import annotations

import copy
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

from app.adapters.bot import conversations, texts
from app.core.clock import utcnow
from app.core.errors import DomainError
from app.core.pipeline import Idempotency, hash_body
from app.db import session as db_session
from app.infra.config import get_settings

if TYPE_CHECKING:
    from app.adapters.bot.context import BotContext

log = structlog.get_logger("bot")

FINISH = "__finish__"
REPROMPT = "__reprompt__"

BACK = "back"
CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    prompt: Callable[[BotContext], Awaitable[None]]
    handle: Callable[[BotContext, str], Awaitable[str | None]]
    allow_back: bool = True


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    first: str
    steps: tuple[Step, ...]
    finish: Callable[[BotContext], Awaitable[None]]

    def step(self, name: str | None) -> Step | None:
        return next((s for s in self.steps if s.name == name), None)


_SCENARIOS: dict[str, Scenario] = {}


def register(scenario: Scenario) -> Scenario:
    _SCENARIOS[scenario.name] = scenario
    return scenario


def get(name: str | None) -> Scenario | None:
    return _SCENARIOS.get(name) if name else None


def step_key(scenario: str, step: str) -> str:
    return f"{scenario}:{step}"


async def start(ctx: BotContext, scenario_name: str, **initial: object) -> None:
    scenario = _SCENARIOS[scenario_name]
    await enter(ctx, scenario_name, scenario.first, dict(initial))


async def enter(
    ctx: BotContext,
    scenario_name: str,
    step_name: str,
    data: dict[str, Any],
    *,
    prompt: bool = True,
) -> None:
    """Открывает диалог сразу на нужном шаге (продолжение черновика, вход из карточки)."""
    scenario = _SCENARIOS[scenario_name]
    step = scenario.step(step_name)
    assert step is not None
    ctx.conversation.reset_dialog()
    ctx.conversation.context = {
        conversations.DATA_KEY: data,
        conversations.HISTORY_KEY: [],
        conversations.RUN_KEY: uuid.uuid4().hex,
    }
    ctx.conversation.current_step = step_key(scenario_name, step_name)
    await ctx.save()
    if prompt:
        await step.prompt(ctx)


def idempotency(ctx: BotContext, operation: str, body: dict[str, Any]) -> Idempotency:
    """Ключ итоговой команды: диалог + проход + шаг, на котором нажали «Отправить»."""
    state = ctx.conversation
    step = state.finishing or state.current_step or ""
    return Idempotency(
        key=f"bot-dialog-{state.id.hex}-{state.run}-{step}",
        operation=f"bot:{operation}",
        body_hash=hash_body(body),
    )


async def cancel(ctx: BotContext, *, notify: bool = True) -> bool:
    """Закрывает текущий диалог. False — закрывать было нечего."""
    if ctx.conversation.current_step is None:
        if notify:
            await ctx.reply(texts.NOTHING_TO_CANCEL)
        return False
    ctx.conversation.reset_dialog()
    await ctx.save()
    if notify:
        await ctx.reply(texts.CANCELLED)
    return True


def is_expired(ctx: BotContext) -> bool:
    updated_at = ctx.conversation.updated_at
    if ctx.conversation.current_step is None or updated_at is None:
        return False
    ttl = timedelta(seconds=get_settings().bot_dialog_ttl_seconds)
    return utcnow() - updated_at > ttl


async def feed(ctx: BotContext, value: str) -> bool:
    """Передаёт ответ пользователя текущему шагу. False — активного диалога нет."""
    scenario = get(ctx.conversation.scenario)
    step = scenario.step(ctx.conversation.step) if scenario else None
    if scenario is None or step is None:
        if ctx.conversation.current_step is not None:
            ctx.conversation.reset_dialog()
            await ctx.save()
        return False

    if is_expired(ctx):
        ctx.conversation.reset_dialog()
        await ctx.save()
        await ctx.reply(texts.DIALOG_EXPIRED)
        return True

    if value == CANCEL:
        await cancel(ctx)
        return True
    if value == BACK:
        await _back(ctx, scenario, step)
        return True

    next_name = await step.handle(ctx, value)
    if next_name is None:
        await ctx.save()
        return True
    if next_name == FINISH:
        await _finish(ctx, scenario)
        return True
    if next_name == REPROMPT or next_name == step.name:
        await ctx.save()
        await step.prompt(ctx)
        return True
    await _go(ctx, scenario, step, next_name)
    return True


async def _go(ctx: BotContext, scenario: Scenario, current: Step, next_name: str) -> None:
    target = scenario.step(next_name)
    if target is None:
        log.error("bot_unknown_step", scenario=scenario.name, step=next_name)
        await cancel(ctx)
        return
    ctx.conversation.history.append(current.name)
    ctx.conversation.current_step = step_key(scenario.name, target.name)
    await ctx.save()
    await target.prompt(ctx)


async def _back(ctx: BotContext, scenario: Scenario, current: Step) -> None:
    history = ctx.conversation.history
    if not current.allow_back or not history:
        await cancel(ctx)
        return
    previous = scenario.step(history.pop())
    if previous is None:
        await cancel(ctx)
        return
    ctx.conversation.current_step = step_key(scenario.name, previous.name)
    await ctx.save()
    await previous.prompt(ctx)


async def _finish(ctx: BotContext, scenario: Scenario) -> None:
    state = ctx.conversation
    step = state.current_step
    snapshot = copy.deepcopy(state.context)
    async with db_session.transaction() as session:
        closed = await conversations.close_if_current(session, state.id, step, state.run)
    if not closed:
        state.reset_dialog()
        await ctx.reply(texts.ACTION_OUTDATED)
        return

    state.current_step = None
    state.finishing = step
    try:
        await scenario.finish(ctx)
    except DomainError as exc:
        await ctx.reply(exc.message)
    except Exception:
        state.current_step = step
        state.context = snapshot
        state.finishing = None
        await ctx.save()
        await ctx.reply(texts.TRY_AGAIN)
        raise
    state.finishing = None
    if state.current_step is None:
        state.reset_dialog()
    await ctx.save()
