from __future__ import annotations

from app.adapters.bot import dialogs
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import draft_photos, draft_steps, publication
from app.adapters.bot.handlers.draft_common import (
    MARKETPLACE_SCENARIO,
    OWN_SERVICE_SCENARIO,
    STEP_LOCATION,
)

open_collection = draft_steps.open_collection


async def _finish_noop(ctx: BotContext) -> None:
    return None


def _build_scenario(name: str) -> dialogs.Scenario:
    return dialogs.Scenario(
        name=name,
        first=STEP_LOCATION,
        steps=(
            *draft_steps.STEPS,
            *draft_photos.STEPS,
            draft_steps.REVIEW_STEP,
            *publication.STEPS,
        ),
        finish=_finish_noop,
    )


dialogs.register(_build_scenario(OWN_SERVICE_SCENARIO))
dialogs.register(_build_scenario(MARKETPLACE_SCENARIO))
