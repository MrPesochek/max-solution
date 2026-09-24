from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.bot import actions, keyboards
from app.infra.max.types import Button

if TYPE_CHECKING:
    from app.adapters.bot.context import BotContext


@dataclass(frozen=True, slots=True)
class ActionSpec:
    label: str
    action_type: str
    object_type: str | None = None
    object_id: uuid.UUID | None = None
    expected_version: int | None = None
    proposal_version: int | None = None
    params: dict[str, Any] = field(default_factory=dict)


async def mint_rows(ctx: BotContext, rows: list[list[ActionSpec]]) -> list[list[Button]]:
    result: list[list[Button]] = []
    if not any(rows):
        return result
    async with ctx.unit() as session:
        for row in rows:
            buttons: list[Button] = []
            for spec in row:
                code = await actions.make_action(
                    session,
                    ctx.user_id,
                    spec.action_type,
                    ctx.now,
                    conversation_id=ctx.conversation.id,
                    object_type=spec.object_type,
                    object_id=spec.object_id,
                    expected_version=spec.expected_version,
                    proposal_version=spec.proposal_version,
                    params=spec.params,
                    membership_id=ctx.conversation.active_membership_id,
                )
                buttons.append(keyboards.action_button(spec.label, code))
            if buttons:
                result.append(buttons)
    return result


async def mint(ctx: BotContext, spec: ActionSpec) -> Button:
    rows = await mint_rows(ctx, [[spec]])
    return rows[0][0]
