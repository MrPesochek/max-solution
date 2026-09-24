from __future__ import annotations

import uuid

from app.adapters.bot import dialogs, keyboards, menu, texts
from app.adapters.bot.context import BotContext
from app.core import ids
from app.core.actor import BareUserActor
from app.core.errors import DomainError
from app.core.pipeline import Idempotency, hash_body
from app.modules.catalog import api as catalog
from app.modules.identity import api as identity

ORG_REGISTRATION = "org_reg"
CITY_PAGE_SIZE = 8
FIRST_LOCATION_NAME = "Основная точка"

STEP_NAME = "name"
STEP_PHONE = "phone"
STEP_CITY = "city"
STEP_DISTRICT = "district"
STEP_ADDRESS = "address"


async def start_registration(ctx: BotContext, kind: str) -> None:
    await dialogs.start(ctx, ORG_REGISTRATION, kind=kind, run=uuid.uuid4().hex)


async def _prompt_name(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_ORG_NAME,
        [keyboards.rows(keyboards.back_cancel_row(STEP_NAME, with_back=False))],
    )


async def _handle_name(ctx: BotContext, value: str) -> str | None:
    name = value.strip()
    if not name:
        await ctx.reply(texts.ASK_ORG_NAME_AGAIN)
        return None
    ctx.conversation.data["name"] = name[:200]
    return STEP_PHONE


async def _prompt_phone(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_PHONE,
        [
            keyboards.rows(
                [keyboards.contact_button()],
                keyboards.back_cancel_row(STEP_PHONE),
            )
        ],
    )


async def _handle_phone(ctx: BotContext, value: str) -> str | None:
    phone = value.strip()
    if len(phone) < 5:
        await ctx.reply(texts.ASK_PHONE_AGAIN)
        return None
    ctx.conversation.data["phone"] = phone[:50]
    if ctx.conversation.data.get("kind") != "customer":
        return dialogs.FINISH
    return STEP_CITY


async def _prompt_city(ctx: BotContext) -> None:
    cities = await catalog.list_cities()
    if not cities:
        await ctx.reply(texts.NO_CITIES)
        return
    page = int(ctx.conversation.data.get("city_page", 0))
    chunk, has_prev, has_next = keyboards.paginate(cities, page, CITY_PAGE_SIZE)
    rows = [[keyboards.dialog_button(city.name, STEP_CITY, city.id)] for city in chunk]
    rows.append(keyboards.nav_row(STEP_CITY, page, has_prev=has_prev, has_next=has_next))
    rows.append(keyboards.back_cancel_row(STEP_CITY))
    await ctx.reply(texts.ASK_CITY, [keyboards.rows(*rows)])


async def _handle_city(ctx: BotContext, value: str) -> str | None:
    if value.startswith("page="):
        ctx.conversation.data["city_page"] = max(int(value[5:] or 0), 0)
        return dialogs.REPROMPT
    city = await _find_city(value)
    if city is None:
        await ctx.reply(texts.ASK_CITY)
        return None
    ctx.conversation.data["city_id"] = city.id
    if not city.districts:
        return STEP_ADDRESS
    return STEP_DISTRICT


async def _prompt_district(ctx: BotContext) -> None:
    city = await _find_city(str(ctx.conversation.data.get("city_id", "")))
    districts = city.districts if city else []
    rows = [
        [keyboards.dialog_button(d.name, STEP_DISTRICT, d.id)]
        for d in districts[: CITY_PAGE_SIZE * 2]
    ]
    rows.append([keyboards.dialog_button(texts.NO_DISTRICT, STEP_DISTRICT, "none")])
    rows.append(keyboards.back_cancel_row(STEP_DISTRICT))
    await ctx.reply(texts.ASK_DISTRICT, [keyboards.rows(*rows)])


async def _handle_district(ctx: BotContext, value: str) -> str | None:
    ctx.conversation.data["district_id"] = None if value == "none" else value
    return STEP_ADDRESS


async def _prompt_address(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_ADDRESS,
        [keyboards.rows(keyboards.back_cancel_row(STEP_ADDRESS))],
    )


async def _handle_address(ctx: BotContext, value: str) -> str | None:
    address = value.strip()
    if not address:
        await ctx.reply(texts.ASK_ADDRESS_AGAIN)
        return None
    ctx.conversation.data["address"] = address[:300]
    return dialogs.FINISH


async def _find_city(public_id: str) -> catalog.CityView | None:
    cities = await catalog.list_cities()
    return next((c for c in cities if c.id == public_id), None)


async def _create_organization(ctx: BotContext) -> None:
    data = ctx.conversation.data
    kind = str(data.get("kind", "customer"))
    first_location = None
    if kind == "customer" and data.get("city_id"):
        district_id = data.get("district_id")
        first_location = identity.FirstLocationData(
            name=FIRST_LOCATION_NAME,
            city_id=ids.decode("city", str(data["city_id"])),
            address=str(data.get("address", "")),
            district_id=ids.decode("district", str(district_id)) if district_id else None,
        )
    payload = identity.OrganizationCreateData(
        name=str(data.get("name", "")),
        kind=kind,
        contact_phone=str(data.get("phone", "")),
        contact_name=ctx.display_name,
        first_location=first_location,
    )
    idem = Idempotency(
        key=f"bot-org-{data.get('run', uuid.uuid4().hex)}",
        operation="bot:organization.create",
        body_hash=hash_body({"kind": kind, "name": payload.name}),
    )
    try:
        result = await identity.create_organization(BareUserActor(ctx.user_id), payload, idem=idem)
    except DomainError as exc:
        await ctx.reply(exc.message)
        return

    organization = result.body["organization"]
    membership = result.body["membership"]
    ctx.conversation.active_organization_id = ids.decode("organization", organization["id"])
    ctx.conversation.active_membership_id = ids.decode("membership", membership["id"])
    if kind == "customer":
        await ctx.reply(texts.ORG_CREATED_CUSTOMER.format(name=organization["name"]))
        await menu.send_menu(ctx)
        return
    from app.adapters.bot.handlers import provider_setup

    await ctx.reply(texts.ORG_CREATED_PROVIDER.format(name=organization["name"]))
    await provider_setup.start(ctx)


dialogs.register(
    dialogs.Scenario(
        name=ORG_REGISTRATION,
        first=STEP_NAME,
        steps=(
            dialogs.Step(STEP_NAME, _prompt_name, _handle_name, allow_back=False),
            dialogs.Step(STEP_PHONE, _prompt_phone, _handle_phone),
            dialogs.Step(STEP_CITY, _prompt_city, _handle_city),
            dialogs.Step(STEP_DISTRICT, _prompt_district, _handle_district),
            dialogs.Step(STEP_ADDRESS, _prompt_address, _handle_address),
        ),
        finish=_create_organization,
    )
)
