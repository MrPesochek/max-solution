from __future__ import annotations

from app.adapters.bot import dialogs, keyboards, texts
from app.adapters.bot.context import BotContext
from app.core.errors import DomainError
from app.core.pipeline import Idempotency
from app.db.enums import LegalForm, ProviderKind
from app.infra.max.types import Button
from app.modules.catalog import api as catalog
from app.modules.identity import api as identity
from app.modules.providers import api as providers

SCENARIO = "provider_setup"

STEP_KIND = "kind"
STEP_LEGAL_FORM = "legal_form"
STEP_INN = "inn"
STEP_CATEGORIES = "categories"
STEP_CITY = "pcity"
STEP_DISTRICTS = "pdistricts"
STEP_CONFIRM = "confirm"

PAGE_SIZE = 8
DONE = "done"
WHOLE_CITY = "all"
SUBMIT = "submit"
DRAFT = "draft"

_KINDS = (
    (ProviderKind.COMPANY.value, texts.SETUP_KIND_COMPANY),
    (ProviderKind.INDEPENDENT_SPECIALIST.value, texts.SETUP_KIND_SPECIALIST),
)
_LEGAL_FORMS = (
    (LegalForm.OOO.value, texts.SETUP_FORM_OOO),
    (LegalForm.IP.value, texts.SETUP_FORM_IP),
    (LegalForm.SELF_EMPLOYED.value, texts.SETUP_FORM_SELF_EMPLOYED),
)


async def start(ctx: BotContext) -> None:
    await dialogs.start(ctx, SCENARIO, category_ids=[], district_ids=[])


def _choice_rows(step: str, choices: tuple[tuple[str, str], ...]) -> list[list[Button]]:
    return [[keyboards.dialog_button(label, step, value)] for value, label in choices]


async def _prompt_kind(ctx: BotContext) -> None:
    rows = _choice_rows(STEP_KIND, _KINDS)
    rows.append(keyboards.back_cancel_row(STEP_KIND, with_back=False))
    await ctx.reply(texts.SETUP_ASK_KIND, [keyboards.rows(*rows)])


async def _handle_kind(ctx: BotContext, value: str) -> str | None:
    if value not in {k for k, _ in _KINDS}:
        return None
    ctx.conversation.data["provider_kind"] = value
    return STEP_LEGAL_FORM


async def _prompt_legal_form(ctx: BotContext) -> None:
    rows = _choice_rows(STEP_LEGAL_FORM, _LEGAL_FORMS)
    rows.append(keyboards.back_cancel_row(STEP_LEGAL_FORM))
    await ctx.reply(texts.SETUP_ASK_LEGAL_FORM, [keyboards.rows(*rows)])


async def _handle_legal_form(ctx: BotContext, value: str) -> str | None:
    if value not in {f for f, _ in _LEGAL_FORMS}:
        return None
    ctx.conversation.data["legal_form"] = value
    return STEP_INN


async def _prompt_inn(ctx: BotContext) -> None:
    await ctx.reply(texts.SETUP_ASK_INN, [keyboards.rows(keyboards.back_cancel_row(STEP_INN))])


async def _handle_inn(ctx: BotContext, value: str) -> str | None:
    try:
        inn = identity.require_valid_inn(value)
    except DomainError as exc:
        await ctx.reply(exc.message)
        return None
    if inn is None:
        await ctx.reply(texts.SETUP_ASK_INN)
        return None
    ctx.conversation.data["inn"] = value.strip()
    return STEP_CATEGORIES


def _toggle(ctx: BotContext, key: str, value: str) -> None:
    selected = [str(v) for v in ctx.conversation.data.get(key) or []]
    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)
    ctx.conversation.data[key] = selected


def _mark(label: str, selected: bool) -> str:
    return f"✓ {label}" if selected else label


async def _prompt_categories(ctx: BotContext) -> None:
    categories = await catalog.list_equipment_categories()
    selected = set(ctx.conversation.data.get("category_ids") or [])
    page = int(ctx.conversation.data.get("category_page", 0))
    chunk, has_prev, has_next = keyboards.paginate(categories, page, PAGE_SIZE)
    rows = [
        [keyboards.dialog_button(_mark(c.name, c.id in selected)[:64], STEP_CATEGORIES, c.id)]
        for c in chunk
    ]
    rows.append(keyboards.nav_row(STEP_CATEGORIES, page, has_prev=has_prev, has_next=has_next))
    rows.append([keyboards.dialog_button(texts.SETUP_DONE, STEP_CATEGORIES, DONE)])
    rows.append(keyboards.back_cancel_row(STEP_CATEGORIES))
    await ctx.reply(texts.SETUP_ASK_CATEGORIES, [keyboards.rows(*rows)])


async def _handle_categories(ctx: BotContext, value: str) -> str | None:
    if value.startswith("page="):
        ctx.conversation.data["category_page"] = max(int(value[5:] or 0), 0)
        return dialogs.REPROMPT
    if value == DONE:
        if not ctx.conversation.data.get("category_ids"):
            await ctx.reply(texts.SETUP_CATEGORIES_REQUIRED)
            return None
        return STEP_CITY
    if value not in {c.id for c in await catalog.list_equipment_categories()}:
        return None
    _toggle(ctx, "category_ids", value)
    return dialogs.REPROMPT


async def _find_city(public_id: str) -> catalog.CityView | None:
    return next((c for c in await catalog.list_cities() if c.id == public_id), None)


async def _prompt_city(ctx: BotContext) -> None:
    cities = await catalog.list_cities()
    page = int(ctx.conversation.data.get("city_page", 0))
    chunk, has_prev, has_next = keyboards.paginate(cities, page, PAGE_SIZE)
    rows = [[keyboards.dialog_button(city.name, STEP_CITY, city.id)] for city in chunk]
    rows.append(keyboards.nav_row(STEP_CITY, page, has_prev=has_prev, has_next=has_next))
    rows.append(keyboards.back_cancel_row(STEP_CITY))
    await ctx.reply(texts.SETUP_ASK_CITY, [keyboards.rows(*rows)])


async def _handle_city(ctx: BotContext, value: str) -> str | None:
    if value.startswith("page="):
        ctx.conversation.data["city_page"] = max(int(value[5:] or 0), 0)
        return dialogs.REPROMPT
    city = await _find_city(value)
    if city is None:
        return None
    ctx.conversation.data["city_id"] = city.id
    ctx.conversation.data["district_ids"] = []
    return STEP_DISTRICTS if city.districts else STEP_CONFIRM


async def _prompt_districts(ctx: BotContext) -> None:
    city = await _find_city(str(ctx.conversation.data.get("city_id", "")))
    districts = city.districts if city else []
    selected = set(ctx.conversation.data.get("district_ids") or [])
    rows = [
        [keyboards.dialog_button(_mark(d.name, d.id in selected)[:64], STEP_DISTRICTS, d.id)]
        for d in districts[: PAGE_SIZE * 2]
    ]
    rows.append([keyboards.dialog_button(texts.SETUP_WHOLE_CITY, STEP_DISTRICTS, WHOLE_CITY)])
    if selected:
        rows.append([keyboards.dialog_button(texts.SETUP_DONE, STEP_DISTRICTS, DONE)])
    rows.append(keyboards.back_cancel_row(STEP_DISTRICTS))
    await ctx.reply(texts.SETUP_ASK_DISTRICTS, [keyboards.rows(*rows)])


async def _handle_districts(ctx: BotContext, value: str) -> str | None:
    if value == WHOLE_CITY:
        ctx.conversation.data["district_ids"] = []
        return STEP_CONFIRM
    if value == DONE:
        return STEP_CONFIRM
    city = await _find_city(str(ctx.conversation.data.get("city_id", "")))
    if city is None or value not in {d.id for d in city.districts}:
        return None
    _toggle(ctx, "district_ids", value)
    return dialogs.REPROMPT


async def _prompt_confirm(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(texts.SETUP_SUBMIT, STEP_CONFIRM, SUBMIT)],
        [keyboards.dialog_button(texts.SETUP_SAVE_DRAFT, STEP_CONFIRM, DRAFT)],
        keyboards.back_cancel_row(STEP_CONFIRM),
    ]
    await ctx.reply(texts.SETUP_ASK_CONFIRM, [keyboards.rows(*rows)])


async def _handle_confirm(ctx: BotContext, value: str) -> str | None:
    if value not in {SUBMIT, DRAFT}:
        return None
    ctx.conversation.data["submit"] = value == SUBMIT
    return dialogs.FINISH


def _suffixed(idem: Idempotency, suffix: str) -> Idempotency:
    return Idempotency(
        key=f"{idem.key}-{suffix}", operation=idem.operation, body_hash=idem.body_hash
    )


async def _finish(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    area = providers.ServiceAreaInput(
        city_id=str(data["city_id"]),
        district_ids=[str(d) for d in data.get("district_ids") or []],
    )
    update = providers.ProviderProfileUpdateData(
        provider_kind=str(data["provider_kind"]),
        legal_form=str(data["legal_form"]),
        inn=str(data["inn"]),
        category_ids=[str(c) for c in data.get("category_ids") or []],
        service_areas=[area],
    )
    body = {
        "provider_kind": update.provider_kind,
        "legal_form": update.legal_form,
        "inn": update.inn,
        "category_ids": update.category_ids,
        "service_area": [area.city_id, area.district_ids],
    }
    await providers.update_profile(
        actor,
        update,
        idem=_suffixed(dialogs.idempotency(ctx, "providers.update_profile", body), "update"),
    )
    if not data.get("submit"):
        await ctx.reply(texts.SETUP_SAVED_DRAFT)
        return
    await providers.submit_for_review(
        actor,
        idem=_suffixed(dialogs.idempotency(ctx, "providers.submit_for_review", {}), "submit"),
    )
    await ctx.reply(texts.SETUP_SUBMITTED)


dialogs.register(
    dialogs.Scenario(
        name=SCENARIO,
        first=STEP_KIND,
        steps=(
            dialogs.Step(STEP_KIND, _prompt_kind, _handle_kind, allow_back=False),
            dialogs.Step(STEP_LEGAL_FORM, _prompt_legal_form, _handle_legal_form),
            dialogs.Step(STEP_INN, _prompt_inn, _handle_inn),
            dialogs.Step(STEP_CATEGORIES, _prompt_categories, _handle_categories),
            dialogs.Step(STEP_CITY, _prompt_city, _handle_city),
            dialogs.Step(STEP_DISTRICTS, _prompt_districts, _handle_districts),
            dialogs.Step(STEP_CONFIRM, _prompt_confirm, _handle_confirm),
        ),
        finish=_finish,
    )
)
