from __future__ import annotations

from typing import Any

from app.adapters.bot import actions, dialogs, keyboards, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import cards
from app.adapters.bot.handlers.request_actions import CardRule, CardState, manager_actor
from app.core import ids
from app.core.unset import UNSET
from app.db.enums import RequestRoute, Urgency
from app.modules.catalog import api as catalog
from app.modules.requests import api as requests_api

ACTION_DETAILS_START = "request.details_start"

DETAILS_SCENARIO = "req_details"

STEP_MENU = "details_menu"
STEP_DESCRIPTION = "details_description"
STEP_URGENCY = "details_urgency"
STEP_DISTRICT = "details_district"

_OWN_DISTRICT = ""

_URGENCY_BUTTONS = (
    (Urgency.CRITICAL, texts.URGENCY_CRITICAL),
    (Urgency.URGENT, texts.URGENCY_URGENT),
    (Urgency.NORMAL, texts.URGENCY_NORMAL),
)


def _start_row(state: CardState) -> list[ActionSpec]:
    return [
        ActionSpec(
            texts.BUTTON_CHANGE_TERMS,
            ACTION_DETAILS_START,
            object_type="request",
            object_id=state.request_id,
            expected_version=state.view.version,
            params=state.params,
        )
    ]


CARD_RULES: tuple[CardRule, ...] = (
    CardRule(lambda s: s.manager and s.view.status == "action_required", _start_row),
)


@actions.action(ACTION_DETAILS_START)
async def _details_start(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await manager_actor(ctx)
    if actor is None:
        return
    view = await requests_api.get_request(actor, claimed.object_id)
    if not isinstance(view, requests_api.RequestCustomerView) or view.status != "action_required":
        await ctx.reply(texts.ACTION_OUTDATED)
        await cards.show_actual(ctx, claimed.object_id)
        return
    await dialogs.start(
        ctx,
        DETAILS_SCENARIO,
        request_id=view.id,
        request_number=view.request_number,
        expected_version=claimed.expected_version,
        published=view.route == RequestRoute.MARKETPLACE,
        city_id=view.location.city_id,
        current_description=view.symptom_description,
        current_urgency=view.urgency,
        changes={},
    )


def _changes(ctx: BotContext) -> dict[str, Any]:
    value = ctx.conversation.data.get("changes")
    if not isinstance(value, dict):
        value = {}
        ctx.conversation.data["changes"] = value
    return value


async def _districts(ctx: BotContext) -> list[catalog.DistrictView]:
    city_id = ctx.conversation.data.get("city_id")
    city = next((c for c in await catalog.list_cities() if c.id == city_id), None)
    return list(city.districts) if city else []


async def _prompt_menu(ctx: BotContext) -> None:
    data = ctx.conversation.data
    changes = _changes(ctx)
    description = changes.get("symptom_description", data.get("current_description"))
    urgency = str(changes.get("urgency", data.get("current_urgency") or ""))
    lines = [
        texts.DETAILS_TITLE.format(number=data.get("request_number")),
        texts.REVIEW_SYMPTOMS.format(symptoms=description or "—"),
        texts.REVIEW_URGENCY.format(urgency=texts.URGENCY_LABELS.get(urgency, urgency)),
    ]
    districts = await _districts(ctx) if data.get("published") else []
    if "district_id" in changes:
        name = next((d.name for d in districts if d.id == changes["district_id"]), None)
        lines.append(texts.DETAILS_DISTRICT.format(district=name or texts.DISTRICT_AS_LOCATION))
    lines.append(texts.DETAILS_CHANGED if changes else texts.DETAILS_HINT)

    rows = [
        [keyboards.dialog_button(texts.BUTTON_DETAILS_DESCRIPTION, STEP_MENU, "description")],
        [keyboards.dialog_button(texts.BUTTON_DETAILS_URGENCY, STEP_MENU, "urgency")],
    ]
    if districts:
        rows.append([keyboards.dialog_button(texts.BUTTON_CHANGE_DISTRICT, STEP_MENU, "district")])
    if changes:
        rows.append([keyboards.dialog_button(texts.BUTTON_DETAILS_SAVE, STEP_MENU, "save")])
    rows.append(keyboards.back_cancel_row(STEP_MENU, with_back=False))
    await ctx.reply("\n".join(lines), [keyboards.rows(*rows)])


async def _handle_menu(ctx: BotContext, value: str) -> str | None:
    if value == "description":
        return STEP_DESCRIPTION
    if value == "urgency":
        return STEP_URGENCY
    if value == "district" and ctx.conversation.data.get("published"):
        return STEP_DISTRICT
    if value == "save" and _changes(ctx):
        return dialogs.FINISH
    return dialogs.REPROMPT


async def _prompt_description(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_DETAILS_DESCRIPTION,
        [keyboards.rows(keyboards.back_cancel_row(STEP_DESCRIPTION))],
    )


async def _handle_description(ctx: BotContext, value: str) -> str | None:
    description = value.strip()
    if not description:
        await ctx.reply(texts.ASK_SYMPTOMS_AGAIN)
        return None
    _changes(ctx)["symptom_description"] = description[:4000]
    return STEP_MENU


async def _prompt_urgency(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(title, STEP_URGENCY, value)] for value, title in _URGENCY_BUTTONS
    ]
    rows.append(keyboards.back_cancel_row(STEP_URGENCY))
    await ctx.reply(texts.ASK_URGENCY, [keyboards.rows(*rows)])


async def _handle_urgency(ctx: BotContext, value: str) -> str | None:
    if value not in {v for v, _ in _URGENCY_BUTTONS}:
        await ctx.reply(texts.ASK_URGENCY)
        return None
    _changes(ctx)["urgency"] = value
    return STEP_MENU


async def _prompt_district(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(d.name, STEP_DISTRICT, d.id)] for d in (await _districts(ctx))[:20]
    ]
    rows.append([keyboards.dialog_button(texts.DISTRICT_AS_LOCATION, STEP_DISTRICT, "own")])
    rows.append(keyboards.back_cancel_row(STEP_DISTRICT))
    await ctx.reply(texts.ASK_PUBLISH_DISTRICT, [keyboards.rows(*rows)])


async def _handle_district(ctx: BotContext, value: str) -> str | None:
    if value != "own" and value not in {d.id for d in await _districts(ctx)}:
        return dialogs.REPROMPT
    _changes(ctx)["district_id"] = _OWN_DISTRICT if value == "own" else value
    return STEP_MENU


async def _finish_details(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        return
    changes = dict(_changes(ctx))
    request_id = ids.decode("request", str(data["request_id"]))
    description = changes.get("symptom_description", UNSET)
    district = changes.get("district_id", UNSET)
    await requests_api.update_request_details(
        actor,
        request_id,
        symptom_description=description,
        urgency=changes.get("urgency", UNSET),
        district_id=(
            (ids.decode("district", district) if district else None)
            if isinstance(district, str)
            else UNSET
        ),
        published_description=description if data.get("published") else UNSET,
        expected_version=data.get("expected_version"),
        idem=dialogs.idempotency(ctx, "requests.update_details", changes),
    )
    await ctx.reply(texts.DETAILS_SAVED)
    await cards.show_actual(ctx, request_id)


dialogs.register(
    dialogs.Scenario(
        name=DETAILS_SCENARIO,
        first=STEP_MENU,
        steps=(
            dialogs.Step(STEP_MENU, _prompt_menu, _handle_menu, allow_back=False),
            dialogs.Step(STEP_DESCRIPTION, _prompt_description, _handle_description),
            dialogs.Step(STEP_URGENCY, _prompt_urgency, _handle_urgency),
            dialogs.Step(STEP_DISTRICT, _prompt_district, _handle_district),
        ),
        finish=_finish_details,
    )
)
