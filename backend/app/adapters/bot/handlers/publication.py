from __future__ import annotations

import uuid
from typing import Any

from app.adapters.bot import actions, buttons, dialogs, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import cards
from app.adapters.bot.handlers.draft_common import (
    MARKETPLACE_SCENARIO,
    STEP_PUBLISH_DISTRICT,
    STEP_PUBLISH_PREVIEW,
    STEP_SENSITIVE_CONFIRM,
)
from app.core import ids
from app.db.enums import RequestRoute
from app.modules.catalog import api as catalog
from app.modules.files import api as files
from app.modules.requests import api as requests_api

ACTION_PUBLISH = "marketplace.publish"

PLAIN = "request_private"
SENSITIVE = "request_sensitive"


async def open_publication(ctx: BotContext, request_id: uuid.UUID, *, number: int) -> None:
    actor = await ctx.org_actor()
    if actor is None or not actor.is_manager:
        await ctx.reply(texts.ONLY_MANAGER_CAN_PUBLISH)
        return
    await dialogs.enter(
        ctx,
        MARKETPLACE_SCENARIO,
        STEP_PUBLISH_PREVIEW,
        {
            "route": RequestRoute.MARKETPLACE,
            "request_id": ids.encode("request", request_id),
            "request_number": number,
        },
    )


def _request_id(ctx: BotContext) -> uuid.UUID:
    return ids.decode("request", str(ctx.conversation.data["request_id"]))


def _selected(ctx: BotContext) -> list[str]:
    value = ctx.conversation.data.get("publish_attachment_ids")
    return list(value) if isinstance(value, list) else []


def _district(ctx: BotContext) -> str | None:
    value = ctx.conversation.data.get("publish_district_id")
    return value if isinstance(value, str) else None


def _card_input(ctx: BotContext) -> requests_api.PublicCardInput:
    district = _district(ctx)
    return requests_api.PublicCardInput(
        attachment_ids=tuple(ids.decode("attachment", a) for a in _selected(ctx)),
        district_id=ids.decode("district", district) if district else None,
        confirm_sensitive=bool(ctx.conversation.data.get("confirm_sensitive")),
    )


async def _city(city_id: str) -> catalog.CityView | None:
    return next((c for c in await catalog.list_cities() if c.id == city_id), None)


def _card_lines(
    card: requests_api.RequestPublicCardView, city: catalog.CityView | None
) -> list[str]:
    district = next(
        (d.name for d in (city.districts if city else []) if d.id == card.district_id), None
    )
    place = city.name if city else "—"
    if district:
        place = f"{place}, {district}"
    equipment = " ".join(p for p in (card.brand, card.model) if p) or "—"
    return [
        texts.PUBLIC_CARD_CATEGORY.format(category=card.equipment_category_name or "—"),
        texts.PUBLIC_CARD_EQUIPMENT.format(equipment=equipment),
        texts.PUBLIC_CARD_PLACE.format(place=place),
        texts.PUBLIC_CARD_URGENCY.format(
            urgency=texts.URGENCY_LABELS.get(card.urgency, card.urgency)
        ),
        texts.PUBLIC_CARD_DESCRIPTION.format(description=card.published_description or "—"),
    ]


async def _prompt_publish_preview(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    request_id = _request_id(ctx)
    selected = _selected(ctx)
    preview = await requests_api.preview_public_card(actor, request_id, data=_card_input(ctx))
    city = await _city(preview.public_card.city_id)

    lines = [
        texts.PUBLISH_PREVIEW_TITLE.format(number=preview.public_card.request_number),
        *_card_lines(preview.public_card, city),
        texts.PUBLISH_PREVIEW_MATCHED.format(count=preview.matched_providers),
    ]
    if preview.withheld_fields:
        lines.append(texts.PUBLISH_PREVIEW_HIDDEN.format(fields=", ".join(preview.withheld_fields)))
    if preview.existing_binding is not None and preview.existing_binding.provider_name:
        lines.append(
            texts.PUBLISH_PREVIEW_BINDING.format(name=preview.existing_binding.provider_name)
        )

    attachments = await files.list_for_request(actor, request_id)
    plain = [a for a in attachments if a.visibility_class == PLAIN]
    sensitive = [a for a in attachments if a.visibility_class == SENSITIVE]
    chosen = [a.slot or a.id for a in attachments if a.id in selected]
    lines.append("")
    lines.append(
        texts.PUBLISH_PHOTOS_CHOSEN.format(photos=", ".join(chosen))
        if chosen
        else texts.PUBLISH_PHOTOS_NONE
    )

    rows: list[list[Any]] = []
    if plain or sensitive:
        quick = [keyboards.dialog_button(texts.BUTTON_PHOTOS_NONE, STEP_PUBLISH_PREVIEW, "none")]
        if plain:
            quick.append(
                keyboards.dialog_button(texts.BUTTON_PHOTOS_PLAIN, STEP_PUBLISH_PREVIEW, "plain")
            )
        rows.append(quick)
    if plain:
        lines.append(texts.PUBLISH_PHOTOS_TITLE)
        for attachment in plain:
            template = (
                texts.PUBLISH_PHOTO_ON if attachment.id in selected else texts.PUBLISH_PHOTO_OFF
            )
            rows.append(
                [
                    keyboards.dialog_button(
                        template.format(label=attachment.slot or attachment.id),
                        STEP_PUBLISH_PREVIEW,
                        f"toggle:{attachment.id}",
                    )
                ]
            )
    if sensitive:
        lines.append(texts.PUBLISH_SENSITIVE_TITLE)
        for attachment in sensitive:
            template = (
                texts.PUBLISH_SENSITIVE_ON
                if attachment.id in selected
                else texts.PUBLISH_SENSITIVE_OFF
            )
            rows.append(
                [
                    keyboards.dialog_button(
                        template.format(label=attachment.slot or attachment.id),
                        STEP_PUBLISH_PREVIEW,
                        f"sensitive:{attachment.id}",
                    )
                ]
            )
        lines.append(texts.PUBLISH_SENSITIVE_NOTE)
    if city is not None and city.districts:
        rows.append(
            [
                keyboards.dialog_button(
                    texts.BUTTON_CHANGE_DISTRICT, STEP_PUBLISH_PREVIEW, "district"
                )
            ]
        )

    fresh = await requests_api.get_request(actor, request_id)
    assert isinstance(fresh, requests_api.RequestCustomerView)
    publish = await buttons.mint(
        ctx,
        ActionSpec(
            texts.BUTTON_PUBLISH,
            ACTION_PUBLISH,
            object_type="request",
            object_id=request_id,
            expected_version=fresh.version,
            params={
                "attachment_ids": selected,
                "district_id": _district(ctx),
                "confirm_sensitive": bool(ctx.conversation.data.get("confirm_sensitive")),
            },
        ),
    )
    rows.append([publish])
    rows.append(keyboards.back_cancel_row(STEP_PUBLISH_PREVIEW))
    await ctx.reply("\n".join(lines), [keyboards.rows(*rows)])


async def _handle_publish_preview(ctx: BotContext, value: str) -> str | None:
    data = ctx.conversation.data
    if value == "none":
        data["publish_attachment_ids"] = []
        data["confirm_sensitive"] = False
        return STEP_PUBLISH_PREVIEW
    if value == "plain":
        actor = await ctx.org_actor()
        assert actor is not None
        attachments = await files.list_for_request(actor, _request_id(ctx))
        data["publish_attachment_ids"] = [a.id for a in attachments if a.visibility_class == PLAIN]
        data["confirm_sensitive"] = False
        return STEP_PUBLISH_PREVIEW
    if value == "district":
        return STEP_PUBLISH_DISTRICT
    if value.startswith("toggle:"):
        attachment_id = value.split(":", 1)[1]
        selected = _selected(ctx)
        if attachment_id in selected:
            selected.remove(attachment_id)
        else:
            selected.append(attachment_id)
        data["publish_attachment_ids"] = selected
        return STEP_PUBLISH_PREVIEW
    if value.startswith("sensitive:"):
        attachment_id = value.split(":", 1)[1]
        selected = _selected(ctx)
        if attachment_id in selected:
            selected.remove(attachment_id)
            data["publish_attachment_ids"] = selected
            return STEP_PUBLISH_PREVIEW
        data["pending_sensitive_id"] = attachment_id
        return STEP_SENSITIVE_CONFIRM
    await _prompt_publish_preview(ctx)
    return None


async def _prompt_district(ctx: BotContext) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    preview = await requests_api.preview_public_card(actor, _request_id(ctx), data=_card_input(ctx))
    city = await _city(preview.public_card.city_id)
    rows = [
        [keyboards.dialog_button(d.name, STEP_PUBLISH_DISTRICT, d.id)]
        for d in (city.districts if city else [])[:20]
    ]
    rows.append([keyboards.dialog_button(texts.DISTRICT_AS_LOCATION, STEP_PUBLISH_DISTRICT, "own")])
    rows.append(keyboards.back_cancel_row(STEP_PUBLISH_DISTRICT))
    await ctx.reply(texts.ASK_PUBLISH_DISTRICT, [keyboards.rows(*rows)])


async def _handle_district(ctx: BotContext, value: str) -> str | None:
    ctx.conversation.data["publish_district_id"] = None if value == "own" else value
    return STEP_PUBLISH_PREVIEW


async def _prompt_sensitive_confirm(ctx: BotContext) -> None:
    rows = [
        [keyboards.dialog_button(texts.BUTTON_CONFIRM_SENSITIVE, STEP_SENSITIVE_CONFIRM, "yes")],
        [keyboards.dialog_button(texts.BUTTON_KEEP_SENSITIVE_HIDDEN, STEP_SENSITIVE_CONFIRM, "no")],
    ]
    await ctx.reply(texts.PUBLISH_SENSITIVE_CONFIRM_ASK, [keyboards.rows(*rows)])


async def _handle_sensitive_confirm(ctx: BotContext, value: str) -> str | None:
    attachment_id = ctx.conversation.data.pop("pending_sensitive_id", None)
    if value == "yes" and isinstance(attachment_id, str):
        selected = _selected(ctx)
        selected.append(attachment_id)
        ctx.conversation.data["publish_attachment_ids"] = selected
        ctx.conversation.data["confirm_sensitive"] = True
    return STEP_PUBLISH_PREVIEW


@actions.action(ACTION_PUBLISH)
async def _publish(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None or not actor.is_manager:
        await ctx.reply(texts.ONLY_MANAGER_CAN_PUBLISH)
        return
    district = claimed.params.get("district_id")
    data = requests_api.PublicCardInput(
        attachment_ids=tuple(
            ids.decode("attachment", a) for a in claimed.params.get("attachment_ids") or []
        ),
        district_id=ids.decode("district", district) if isinstance(district, str) else None,
        confirm_sensitive=bool(claimed.params.get("confirm_sensitive")),
    )
    result = await requests_api.publish_search(
        actor,
        claimed.object_id,
        data=data,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await dialogs.cancel(ctx, notify=False)
    search = result.body.get("search") or {}
    if search.get("published"):
        await ctx.reply(texts.PUBLISH_DONE.format(count=search.get("matched_providers", 0)))
        await menu.send_menu(ctx)
        return
    await ctx.reply(texts.PUBLISH_NO_PROVIDERS)
    await cards.show_actual(ctx, claimed.object_id)


STEPS: tuple[dialogs.Step, ...] = (
    dialogs.Step(STEP_PUBLISH_PREVIEW, _prompt_publish_preview, _handle_publish_preview),
    dialogs.Step(STEP_PUBLISH_DISTRICT, _prompt_district, _handle_district),
    dialogs.Step(
        STEP_SENSITIVE_CONFIRM,
        _prompt_sensitive_confirm,
        _handle_sensitive_confirm,
        allow_back=False,
    ),
)
