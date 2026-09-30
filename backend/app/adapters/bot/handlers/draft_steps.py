from __future__ import annotations

import uuid
from contextlib import suppress

from app.adapters.bot import actions, buttons, dialogs, keyboards, menu, texts
from app.adapters.bot.actions import ClaimedAction
from app.adapters.bot.buttons import ActionSpec
from app.adapters.bot.context import BotContext
from app.adapters.bot.handlers import draft_common as common
from app.adapters.bot.handlers.draft_common import (
    STEP_EQUIPMENT,
    STEP_ERROR_CODE,
    STEP_LOCATION,
    STEP_PHOTOS,
    STEP_PUBLISH_PREVIEW,
    STEP_REVIEW,
    STEP_SYMPTOMS,
    STEP_URGENCY,
)
from app.core import ids
from app.core.actor import UserActor
from app.core.errors import DomainError
from app.core.pipeline import Idempotency, hash_body
from app.db.enums import RequestRoute, Urgency
from app.infra.max.types import Button
from app.modules.catalog import api as catalog
from app.modules.requests import api as requests_api

ACTION_SUBMIT_OWN = "own_service.submit"
ACTION_SUBMIT_APPROVAL = "marketplace.request_approval"
ACTION_RESUME = "draft.resume"
ACTION_RESTART = "draft.restart"


async def open_collection(ctx: BotContext, *, route: str) -> None:
    from app.adapters.bot.handlers import publication

    actor = await ctx.org_actor()
    if actor is None or actor.side != "customer":
        await ctx.reply(texts.NOT_CUSTOMER_SIDE)
        return
    if route == RequestRoute.MARKETPLACE and actor.is_manager:
        pending = await _find_awaiting_approval(actor)
        if pending is not None:
            await publication.open_publication(
                ctx, ids.decode("request", pending.id), number=pending.request_number
            )
            return
    draft = await _find_open_draft(actor, route)
    if draft is not None:
        await _offer_resume(ctx, draft, route)
        return
    await start_fresh(ctx, route)


async def _find_awaiting_approval(actor: UserActor) -> requests_api.RequestListItemView | None:
    items, _ = await requests_api.list_requests(actor, statuses=["approval_required"], limit=50)
    return items[0] if items else None


async def _find_open_draft(actor: UserActor, route: str) -> requests_api.RequestListItemView | None:
    items, _ = await requests_api.list_requests(actor, statuses=["draft"], limit=50)
    return next((item for item in items if item.route == route), None)


async def _offer_resume(
    ctx: BotContext, draft: requests_api.RequestListItemView, route: str
) -> None:
    request_id = ids.decode("request", draft.id)
    rows = await buttons.mint_rows(
        ctx,
        [
            [
                ActionSpec(
                    texts.RESUME_CONTINUE,
                    ACTION_RESUME,
                    object_type="request",
                    object_id=request_id,
                    params={"route": route},
                ),
                ActionSpec(
                    texts.RESUME_RESTART,
                    ACTION_RESTART,
                    object_type="request",
                    object_id=request_id,
                    params={"route": route, "expected_version": draft.version},
                ),
            ]
        ],
    )
    await ctx.reply(
        texts.RESUME_DRAFT_FOUND.format(number=draft.request_number), [keyboards.rows(*rows)]
    )


@actions.action(ACTION_RESUME)
async def _resume(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    route = str(claimed.params.get("route", RequestRoute.OWN_SERVICE))
    await resume_draft(ctx, claimed.object_id, route)


async def resume_draft(ctx: BotContext, request_id: uuid.UUID, route: str) -> None:
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    view = await requests_api.get_request(actor, request_id)
    if not isinstance(view, requests_api.RequestCustomerView) or view.status != "draft":
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    await dialogs.enter(
        ctx,
        common.scenario_for(route),
        STEP_SYMPTOMS,
        {
            "route": route,
            "request_id": view.id,
            "request_number": view.request_number,
            "equipment_id": view.equipment.id,
        },
    )


@actions.action(ACTION_RESTART)
async def _restart(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    expected_version = claimed.params.get("expected_version")
    with suppress(DomainError):
        await requests_api.cancel_draft(
            actor,
            claimed.object_id,
            expected_version=int(expected_version) if expected_version is not None else None,
            idem=claimed.idempotency,
        )
    await ctx.reply(texts.RESUME_RESTARTED)
    await start_fresh(ctx, str(claimed.params.get("route", RequestRoute.OWN_SERVICE)))


async def start_fresh(ctx: BotContext, route: str) -> None:
    await dialogs.start(ctx, common.scenario_for(route), route=route)


async def start_with_equipment(
    ctx: BotContext, *, route: str, location_id: str, equipment_id: str
) -> None:
    await dialogs.enter(
        ctx,
        common.scenario_for(route),
        STEP_EQUIPMENT,
        {"route": route, "location_id": location_id, "equipment_page": 0},
        prompt=False,
    )
    await dialogs.feed(ctx, equipment_id)


async def _prompt_location(ctx: BotContext) -> None:
    scope = await ctx.scope()
    assert scope is not None
    items = await common.all_locations(scope)
    if not items:
        await ctx.reply(texts.NO_LOCATIONS)
        await dialogs.cancel(ctx, notify=False)
        return
    page = int(ctx.conversation.data.get("location_page", 0))
    chunk, has_prev, has_next = keyboards.paginate(items, page, common.PAGE_SIZE)
    rows = [[keyboards.dialog_button(loc.name, STEP_LOCATION, loc.id)] for loc in chunk]
    rows.append(keyboards.nav_row(STEP_LOCATION, page, has_prev=has_prev, has_next=has_next))
    rows.append(keyboards.back_cancel_row(STEP_LOCATION, with_back=False))
    await ctx.reply(texts.ASK_LOCATION, [keyboards.rows(*rows)])


async def _handle_location(ctx: BotContext, value: str) -> str | None:
    page = common.page_value(value)
    if page is not None:
        ctx.conversation.data["location_page"] = page
        return STEP_LOCATION
    scope = await ctx.scope()
    assert scope is not None
    found = next((loc for loc in await common.all_locations(scope) if loc.id == value), None)
    if found is None:
        await ctx.reply(texts.ASK_LOCATION)
        return None
    ctx.conversation.data["location_id"] = found.id
    ctx.conversation.data["equipment_page"] = 0
    return STEP_EQUIPMENT


async def _prompt_equipment(ctx: BotContext) -> None:
    scope = await ctx.scope()
    assert scope is not None
    location_id = ids.decode("location", str(ctx.conversation.data["location_id"]))
    items = await common.all_equipment(scope, location_id)
    if not items:
        await ctx.reply(texts.NO_EQUIPMENT)
        await dialogs.cancel(ctx, notify=False)
        return
    page = int(ctx.conversation.data.get("equipment_page", 0))
    chunk, has_prev, has_next = keyboards.paginate(items, page, common.PAGE_SIZE)
    rows = [
        [keyboards.dialog_button(common.equipment_title(eq), STEP_EQUIPMENT, eq.id or "")]
        for eq in chunk
    ]
    rows.append(keyboards.nav_row(STEP_EQUIPMENT, page, has_prev=has_prev, has_next=has_next))
    rows.append(keyboards.back_cancel_row(STEP_EQUIPMENT))
    await ctx.reply(texts.ASK_EQUIPMENT, [keyboards.rows(*rows)])


async def _handle_equipment(ctx: BotContext, value: str) -> str | None:
    page = common.page_value(value)
    if page is not None:
        ctx.conversation.data["equipment_page"] = page
        return STEP_EQUIPMENT
    scope = await ctx.scope()
    assert scope is not None
    location_id = ids.decode("location", str(ctx.conversation.data["location_id"]))
    items = await common.all_equipment(scope, location_id)
    equipment = next((eq for eq in items if eq.id == value), None)
    if equipment is None:
        await ctx.reply(texts.ASK_EQUIPMENT)
        return None

    route = str(ctx.conversation.data.get("route", RequestRoute.OWN_SERVICE))
    equipment_uuid = ids.decode("equipment", value)
    location_view = await catalog.get_location(scope, location_id)
    binding_name = await common.confirmed_service_name(scope, equipment_uuid)

    await ctx.reply(
        texts.EQUIPMENT_CARD.format(
            title=common.equipment_title(equipment),
            location=location_view.name,
            address=location_view.address,
            service=binding_name or texts.BINDING_UNKNOWN,
        )
    )

    if route == RequestRoute.OWN_SERVICE and binding_name is None:
        await ctx.reply(
            texts.NO_CONFIRMED_BINDING,
            [keyboards.rows([keyboards.menu_button(texts.GO_FIND_PROVIDER, "find_provider")])],
        )
        await dialogs.cancel(ctx, notify=False)
        return None

    actor = await ctx.org_actor()
    assert actor is not None
    idem = Idempotency(
        key=f"bot-draft-{ctx.conversation.id.hex}-{ctx.conversation.run}-{value}",
        operation="bot:requests.create_draft",
        body_hash=hash_body({"equipment_id": value, "route": route}),
    )
    result = await requests_api.create_draft(
        actor, equipment_id=equipment_uuid, route=route, idem=idem
    )
    body = result.body
    ctx.conversation.data["request_id"] = body["id"]
    ctx.conversation.data["request_number"] = body["request_number"]
    ctx.conversation.data["request_version"] = body["version"]
    ctx.conversation.data["equipment_id"] = value
    return STEP_SYMPTOMS


async def prompt_symptoms(ctx: BotContext) -> None:
    await ctx.reply(texts.ASK_SYMPTOMS, [keyboards.rows(keyboards.back_cancel_row(STEP_SYMPTOMS))])


async def _handle_symptoms(ctx: BotContext, value: str) -> str | None:
    text = value.strip()
    if not text:
        await ctx.reply(texts.ASK_SYMPTOMS_AGAIN)
        return None
    await common.update_draft(ctx, symptom_description=text[:2000])
    return STEP_ERROR_CODE


async def _prompt_error_code(ctx: BotContext) -> None:
    await ctx.reply(
        texts.ASK_ERROR_CODE,
        [
            keyboards.rows(
                [keyboards.dialog_button(texts.BUTTON_NO_ERROR_CODE, STEP_ERROR_CODE, "skip")],
                keyboards.back_cancel_row(STEP_ERROR_CODE),
            )
        ],
    )


async def _handle_error_code(ctx: BotContext, value: str) -> str | None:
    code = None if value == "skip" else value.strip()[:100] or None
    await common.update_draft(ctx, error_code=code)
    return STEP_URGENCY


_URGENCY_BUTTONS = (
    (Urgency.CRITICAL, texts.URGENCY_CRITICAL),
    (Urgency.URGENT, texts.URGENCY_URGENT),
    (Urgency.NORMAL, texts.URGENCY_NORMAL),
)


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
    await common.update_draft(ctx, urgency=value)
    slots = await common.photo_slots(ctx)
    ctx.conversation.data["photo_slots"] = slots
    ctx.conversation.data["photo_index"] = 0
    return STEP_PHOTOS if slots else STEP_REVIEW


async def prompt_review(ctx: BotContext) -> None:
    data = ctx.conversation.data
    actor = await ctx.org_actor()
    assert actor is not None
    request_id = ids.decode("request", str(data["request_id"]))
    view = await requests_api.get_request(actor, request_id)
    assert isinstance(view, requests_api.RequestCustomerView)

    route = str(data.get("route", RequestRoute.OWN_SERVICE))
    lines = [
        texts.REVIEW_TITLE.format(number=view.request_number),
        texts.REVIEW_RECIPIENT.format(recipient=_recipient_label(actor, route)),
        texts.REVIEW_EQUIPMENT.format(title=common.equipment_title(view.equipment)),
        texts.REVIEW_SYMPTOMS.format(symptoms=view.symptom_description or "—"),
        texts.REVIEW_ERROR_CODE.format(code=view.error_code or "—"),
        texts.REVIEW_URGENCY.format(urgency=texts.URGENCY_LABELS.get(view.urgency, view.urgency)),
        texts.REVIEW_PHOTOS.format(count=len(view.attachments)),
    ]
    if data.get("photos_incomplete"):
        lines.append(
            texts.REVIEW_INCOMPLETE.format(reason=data.get("photos_incomplete_reason", ""))
        )

    rows: list[list[Button]] = []
    if route == RequestRoute.OWN_SERVICE:
        spec = ActionSpec(
            texts.BUTTON_SEND,
            ACTION_SUBMIT_OWN,
            object_type="request",
            object_id=request_id,
            expected_version=view.version,
            params={
                "photos_incomplete": bool(data.get("photos_incomplete")),
                "photos_incomplete_reason": data.get("photos_incomplete_reason"),
            },
        )
        rows.append([await buttons.mint(ctx, spec)])
    elif actor.is_manager:
        rows.append(
            [keyboards.dialog_button(texts.BUTTON_REVIEW_PUBLICATION, STEP_REVIEW, "preview")]
        )
    else:
        spec = ActionSpec(
            texts.APPROVAL_SEND,
            ACTION_SUBMIT_APPROVAL,
            object_type="request",
            object_id=request_id,
            expected_version=view.version,
        )
        rows.append([await buttons.mint(ctx, spec)])
    rows.append(keyboards.back_cancel_row(STEP_REVIEW, with_back=False))
    await ctx.reply("\n".join(lines), [keyboards.rows(*rows)])


def _recipient_label(actor: UserActor, route: str) -> str:
    if route == RequestRoute.OWN_SERVICE:
        return texts.RECIPIENT_OWN_SERVICE
    return texts.RECIPIENT_PUBLICATION if actor.is_manager else texts.RECIPIENT_MANAGER


async def _handle_review(ctx: BotContext, value: str) -> str | None:
    if value == "preview":
        return STEP_PUBLISH_PREVIEW
    await prompt_review(ctx)
    return None


@actions.action(ACTION_SUBMIT_OWN)
async def _submit_own(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    result = await requests_api.submit_to_own_service(
        actor,
        claimed.object_id,
        photos_incomplete=bool(claimed.params.get("photos_incomplete")),
        photos_incomplete_reason=claimed.params.get("photos_incomplete_reason"),
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await dialogs.cancel(ctx, notify=False)
    await ctx.reply(texts.DRAFT_SUBMITTED_OWN.format(number=result.body["request_number"]))
    await menu.send_menu(ctx)


@actions.action(ACTION_SUBMIT_APPROVAL)
async def _submit_approval(ctx: BotContext, claimed: ClaimedAction) -> None:
    if claimed.object_id is None:
        await ctx.reply(texts.ACTION_OUTDATED)
        return
    actor = await ctx.org_actor()
    if actor is None:
        await ctx.reply(texts.NO_ORGANIZATION)
        return
    result = await requests_api.request_approval(
        actor,
        claimed.object_id,
        expected_version=claimed.expected_version,
        idem=claimed.idempotency,
    )
    await dialogs.cancel(ctx, notify=False)
    await ctx.reply(texts.DRAFT_SUBMITTED_APPROVAL.format(number=result.body["request_number"]))
    await menu.send_menu(ctx)


STEPS: tuple[dialogs.Step, ...] = (
    dialogs.Step(STEP_LOCATION, _prompt_location, _handle_location, allow_back=False),
    dialogs.Step(STEP_EQUIPMENT, _prompt_equipment, _handle_equipment),
    dialogs.Step(STEP_SYMPTOMS, prompt_symptoms, _handle_symptoms),
    dialogs.Step(STEP_ERROR_CODE, _prompt_error_code, _handle_error_code),
    dialogs.Step(STEP_URGENCY, _prompt_urgency, _handle_urgency),
)
REVIEW_STEP = dialogs.Step(STEP_REVIEW, prompt_review, _handle_review, allow_back=False)
