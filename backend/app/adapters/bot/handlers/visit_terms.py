from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.bot import dialogs, formatting, keyboards, texts
from app.adapters.bot.context import BotContext
from app.core.clock import utcnow

STEP_DAY = "day"
STEP_SLOT = "slot"
STEP_PRICE_MODE = "price_mode"
STEP_PRICE_SUM = "price_sum"
STEP_PRICE_FREE = "price_free"

SLOTS = {
    "morning": (9, 13, texts.OFFER_SLOT_MORNING),
    "day": (13, 17, texts.OFFER_SLOT_DAY),
    "evening": (17, 21, texts.OFFER_SLOT_EVENING),
}

DAY_OFFSETS = (0, 1, 2)


def visit_window(day_offset: int, slot: str, tz_name: str | None) -> tuple[datetime, datetime]:
    start_hour, end_hour, _ = SLOTS[slot]
    return formatting.local_window_to_utc(day_offset, start_hour, end_hour, tz_name)


def open_slots(day_offset: int, tz_name: str | None) -> list[str]:
    """Слоты, которые ещё не закончились: прошедшее окно ядро не примет (ТЗ 8.1)."""
    now = utcnow()
    return [key for key in SLOTS if visit_window(day_offset, key, tz_name)[1] > now]


def open_day_offsets(tz_name: str | None) -> list[int]:
    return [offset for offset in DAY_OFFSETS if open_slots(offset, tz_name)]


def parse_rubles(text: str) -> int | None:
    """Сумма в рублях → минимальные единицы (копейки) без float (ТЗ 5.2)."""
    cleaned = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    whole, sep, frac = cleaned.partition(".")
    if not whole.isdigit() or (sep and not frac.isdigit()) or len(frac) > 2:
        return None
    frac = (frac + "00")[:2]
    return int(whole) * 100 + int(frac)


def day_step(next_step: str) -> dialogs.Step:
    async def prompt(ctx: BotContext) -> None:
        tz = ctx.conversation.data.get("timezone")
        rows = [
            [keyboards.dialog_button(formatting.local_day_label(offset, tz), STEP_DAY, str(offset))]
            for offset in open_day_offsets(tz)
        ]
        rows.append(keyboards.back_cancel_row(STEP_DAY, with_back=False))
        text = f"{texts.OFFER_ASK_DAY}\n{texts.LOCAL_TIME_HINT.format(tz=formatting.tz_label(tz))}"
        await ctx.reply(text, [keyboards.rows(*rows)])

    async def handle(ctx: BotContext, value: str) -> str | None:
        try:
            offset = int(value)
        except ValueError:
            return None
        if offset not in open_day_offsets(ctx.conversation.data.get("timezone")):
            return None
        ctx.conversation.data["day_offset"] = offset
        return next_step

    return dialogs.Step(STEP_DAY, prompt, handle, allow_back=False)


def slot_step(next_step: str) -> dialogs.Step:
    async def prompt(ctx: BotContext) -> None:
        data = ctx.conversation.data
        slots = open_slots(int(data["day_offset"]), data.get("timezone"))
        rows = [[keyboards.dialog_button(SLOTS[key][2], STEP_SLOT, key)] for key in slots]
        rows.append(keyboards.back_cancel_row(STEP_SLOT))
        await ctx.reply(texts.OFFER_ASK_SLOT, [keyboards.rows(*rows)])

    async def handle(ctx: BotContext, value: str) -> str | None:
        data = ctx.conversation.data
        if value not in open_slots(int(data["day_offset"]), data.get("timezone")):
            return None
        data["slot"] = value
        return next_step

    return dialogs.Step(STEP_SLOT, prompt, handle)


def price_mode_step(
    *, prompt_text: str, after_price: str, allow_later: bool, first: bool = False
) -> dialogs.Step:
    """«Назову сумму» / «Уточню после осмотра» / «Бесплатно (с основанием)»."""

    async def prompt(ctx: BotContext) -> None:
        rows = [[keyboards.dialog_button(texts.OFFER_PRICE_SUM, STEP_PRICE_MODE, "sum")]]
        if allow_later:
            rows.append(
                [keyboards.dialog_button(texts.OFFER_PRICE_LATER, STEP_PRICE_MODE, "later")]
            )
        rows.append([keyboards.dialog_button(texts.OFFER_PRICE_FREE, STEP_PRICE_MODE, "free")])
        rows.append(keyboards.back_cancel_row(STEP_PRICE_MODE, with_back=not first))
        await ctx.reply(prompt_text, [keyboards.rows(*rows)])

    async def handle(ctx: BotContext, value: str) -> str | None:
        data = ctx.conversation.data
        if value == "sum":
            return STEP_PRICE_SUM
        if value == "free":
            return STEP_PRICE_FREE
        if value == "later" and allow_later:
            data["amount_minor"] = None
            data["zero_cost_reason"] = None
            return after_price
        return None

    return dialogs.Step(STEP_PRICE_MODE, prompt, handle)


def price_sum_step(next_step: str) -> dialogs.Step:
    async def prompt(ctx: BotContext) -> None:
        await ctx.reply(
            texts.ASK_RUBLES, [keyboards.rows(keyboards.back_cancel_row(STEP_PRICE_SUM))]
        )

    async def handle(ctx: BotContext, value: str) -> str | None:
        minor = parse_rubles(value)
        if minor is None or minor == 0:
            await ctx.reply(texts.ASK_RUBLES_AGAIN)
            return None
        ctx.conversation.data["amount_minor"] = minor
        ctx.conversation.data["zero_cost_reason"] = None
        return next_step

    return dialogs.Step(STEP_PRICE_SUM, prompt, handle)


def price_free_step(next_step: str) -> dialogs.Step:
    async def prompt(ctx: BotContext) -> None:
        await ctx.reply(
            texts.ASK_FREE_REASON, [keyboards.rows(keyboards.back_cancel_row(STEP_PRICE_FREE))]
        )

    async def handle(ctx: BotContext, value: str) -> str | None:
        reason = value.strip()
        if not reason:
            await ctx.reply(texts.ASK_FREE_REASON)
            return None
        ctx.conversation.data["amount_minor"] = 0
        ctx.conversation.data["zero_cost_reason"] = reason[:500]
        return next_step

    return dialogs.Step(STEP_PRICE_FREE, prompt, handle)


def price_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Поля цены для `VisitProposalInput`/`RepairQuoteInput`/`OfferInput`."""
    amount = data.get("amount_minor")
    return {
        "amount_minor": amount,
        "currency": "RUB" if amount is not None else None,
        "zero_cost_reason": data.get("zero_cost_reason"),
    }
