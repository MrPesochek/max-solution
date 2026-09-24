from __future__ import annotations

import uuid

from app.adapters.bot import actions, buttons, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import draft_common as common
from app.core import ids
from app.db.enums import RequestRoute
from app.infra.max.types import Button
from app.modules.catalog import api as catalog

ACTION_LOCATIONS = "equipment.locations"
ACTION_LOCATION = "equipment.location"
ACTION_CARD = "equipment.card"
ACTION_NEW_REQUEST = "equipment.new_request"

PAGE_SIZE = 8


@menu.menu("equipment")
async def show_equipment(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    if actor is None or actor.side != "customer":
        await ctx.reply(texts.NOT_CUSTOMER_SIDE)
        return
    await _send_locations(ctx, page=0)


def _nav(
    action_type: str,
    page: int,
    *,
    has_prev: bool,
    has_next: bool,
    location_id: uuid.UUID | None = None,
) -> list[ActionSpec]:
    object_type = "location" if location_id is not None else None
    row: list[ActionSpec] = []
    for shown, label, target in (
        (has_prev, texts.BUTTON_PREV, page - 1),
        (has_next, texts.BUTTON_MORE, page + 1),
    ):
        if shown:
            row.append(
                ActionSpec(
                    label,
                    action_type,
                    object_type=object_type,
                    object_id=location_id,
                    params={"page": target},
                )
            )
    return row


async def _send_locations(ctx: BotContext, *, page: int) -> None:
    scope = await ctx.scope()
    assert scope is not None
    items = await common.all_locations(scope)
    if not items:
        await ctx.reply(texts.NO_LOCATIONS, [keyboards.rows([_open_app()])])
        return
    chunk, has_prev, has_next = keyboards.paginate(items, page, PAGE_SIZE)
    specs = [
        [
            ActionSpec(
                loc.name[:64],
                ACTION_LOCATION,
                object_type="location",
                object_id=ids.decode("location", loc.id),
            )
        ]
        for loc in chunk
    ]
    specs.append(_nav(ACTION_LOCATIONS, page, has_prev=has_prev, has_next=has_next))
    rows = await buttons.mint_rows(ctx, specs)
    rows.append([keyboards.menu_button(texts.BUTTON_TO_MENU, menu.MAIN)])
    await ctx.reply(texts.EQUIPMENT_CHOOSE_LOCATION, [keyboards.rows(*rows)])


@actions.action(ACTION_LOCATIONS)
async def _locations(ctx: BotContext, claimed: ClaimedAction) -> None:
    await _send_locations(ctx, page=int(claimed.params.get("page", 0)))


@actions.action(ACTION_LOCATION)
async def _location(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await _send_equipment(ctx, claimed.object_id, page=int(claimed.params.get("page", 0)))


async def _send_equipment(ctx: BotContext, location_id: uuid.UUID, *, page: int) -> None:
    scope = await ctx.scope()
    assert scope is not None
    location = await catalog.get_location(scope, location_id)
    items = await common.all_equipment(scope, location_id)
    chunk, has_prev, has_next = keyboards.paginate(items, page, PAGE_SIZE)
    specs = [
        [
            ActionSpec(
                common.equipment_title(eq),
                ACTION_CARD,
                object_type="equipment",
                object_id=ids.decode("equipment", eq.id),
            )
        ]
        for eq in chunk
    ]
    location_public_id = ids.encode("location", location_id)
    specs.append(
        _nav(ACTION_LOCATION, page, has_prev=has_prev, has_next=has_next, location_id=location_id)
    )
    specs.append([ActionSpec(texts.BUTTON_BACK, ACTION_LOCATIONS, params={"page": 0})])
    rows = await buttons.mint_rows(ctx, specs)
    text = texts.EQUIPMENT_LIST_TITLE.format(location=location.name, address=location.address)
    if not items:
        text = f"{text}\n{texts.NO_EQUIPMENT}"
    rows.append([_open_app("equipment", location_public_id)])
    await ctx.reply(text, [keyboards.rows(*rows)])


@actions.action(ACTION_CARD)
async def _card(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    scope = await ctx.scope()
    assert scope is not None
    equipment = await catalog.get_equipment(scope, claimed.object_id)
    location_id = ids.decode("location", equipment.location_id)
    location = await catalog.get_location(scope, location_id)
    categories = await catalog.list_equipment_categories()
    category = next((c.name for c in categories if c.id == equipment.equipment_category_id), "—")
    service = await common.confirmed_service_name(scope, claimed.object_id)

    lines = [
        texts.EQUIPMENT_CARD.format(
            title=common.equipment_title(equipment),
            location=location.name,
            address=location.address,
            service=texts.BINDING_KNOWN_SERVICE.format(name=service)
            if service
            else texts.BINDING_UNKNOWN,
        ),
        texts.EQUIPMENT_CATEGORY.format(category=category),
        texts.EQUIPMENT_SERIAL.format(serial=equipment.serial_number or "—"),
    ]
    route = RequestRoute.OWN_SERVICE if service else RequestRoute.MARKETPLACE
    lines.append(texts.EQUIPMENT_NEW_REQUEST_OWN if service else texts.EQUIPMENT_NEW_REQUEST_SEARCH)
    rows: list[list[Button]] = await buttons.mint_rows(
        ctx,
        [
            [
                ActionSpec(
                    texts.BUTTON_NEW_REQUEST,
                    ACTION_NEW_REQUEST,
                    object_type="equipment",
                    object_id=claimed.object_id,
                    params={"route": route, "location_id": equipment.location_id},
                )
            ],
            [
                ActionSpec(
                    texts.BUTTON_BACK,
                    ACTION_LOCATION,
                    object_type="location",
                    object_id=location_id,
                    params={"page": 0},
                )
            ],
        ],
    )
    rows.append([_open_app("equipment", equipment.id)])
    await ctx.reply("\n".join(lines), [keyboards.rows(*rows)])


@actions.action(ACTION_NEW_REQUEST)
async def _new_request(ctx: BotContext, claimed: ClaimedAction) -> None:
    from app.adapters.bot.handlers import draft_steps

    location_id = claimed.params.get("location_id")
    if claimed.object_id is None or not isinstance(location_id, str):
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await draft_steps.start_with_equipment(
        ctx,
        route=str(claimed.params.get("route", RequestRoute.OWN_SERVICE)),
        location_id=location_id,
        equipment_id=ids.encode("equipment", claimed.object_id),
    )


def _open_app(screen: str = "equipment", object_id: str | None = None) -> Button:
    return keyboards.open_app(texts.BUTTON_OPEN_IN_APP, screen, object_id)
