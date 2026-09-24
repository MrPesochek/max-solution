from __future__ import annotations

import uuid
from typing import Any, Protocol

from app.adapters.bot import updates
from app.adapters.bot.context import BotContext
from app.core import ids
from app.core.scope import AccessScope
from app.db.enums import RequestRoute
from app.modules.catalog import api as catalog
from app.modules.requests import api as requests_api
from app.modules.trust import api as trust

OWN_SERVICE_SCENARIO = "req_own_service"
MARKETPLACE_SCENARIO = "req_marketplace"

STEP_LOCATION = "location"
STEP_EQUIPMENT = "equipment"
STEP_SYMPTOMS = "symptoms"
STEP_ERROR_CODE = "error_code"
STEP_URGENCY = "urgency"
STEP_PHOTOS = "photos"
STEP_PHOTO_REASON = "photo_reason"
STEP_REVIEW = "review"
STEP_PUBLISH_PREVIEW = "publish_preview"
STEP_PUBLISH_DISTRICT = "publish_district"
STEP_SENSITIVE_CONFIRM = "sensitive_confirm"

PAGE_SIZE = 6


def scenario_for(route: str) -> str:
    return OWN_SERVICE_SCENARIO if route == RequestRoute.OWN_SERVICE else MARKETPLACE_SCENARIO


def page_value(value: str) -> int | None:
    """`page=N` из кнопки листания; None — это не листание."""
    if not value.startswith("page="):
        return None
    try:
        return max(int(value[5:] or 0), 0)
    except ValueError:
        return 0


class _HasBrandModel(Protocol):
    brand: str | None
    model: str | None


def equipment_title(eq: _HasBrandModel) -> str:
    parts = [p for p in (eq.brand, eq.model) if p]
    title = " ".join(parts) if parts else "Оборудование"
    return title[:64]


async def all_locations(scope: AccessScope) -> list[catalog.LocationView]:
    items: list[catalog.LocationView] = []
    cursor: uuid.UUID | None = None
    while True:
        page, cursor = await catalog.list_locations(scope, cursor=cursor, limit=100)
        items.extend(page)
        if cursor is None:
            break
    return items


async def all_equipment(scope: AccessScope, location_id: uuid.UUID) -> list[catalog.EquipmentView]:
    items: list[catalog.EquipmentView] = []
    cursor: uuid.UUID | None = None
    while True:
        page, cursor = await catalog.list_equipment(
            scope, location_id=location_id, cursor=cursor, limit=100
        )
        items.extend(page)
        if cursor is None:
            break
    return items


async def confirmed_service_name(scope: AccessScope, equipment_id: uuid.UUID) -> str | None:
    items, _ = await trust.list_bindings(scope, equipment_id=equipment_id, status="confirmed")
    for item in items:
        if isinstance(item, trust.ServiceBindingView) and item.status == "confirmed":
            return item.provider.name
    return None


async def update_draft(ctx: BotContext, **fields: Any) -> None:
    actor = await ctx.org_actor()
    assert actor is not None
    request_id = ids.decode("request", str(ctx.conversation.data["request_id"]))
    idem = updates.event_idempotency(
        "requests.update_draft", {"request_id": str(request_id), **fields}
    )
    result = await requests_api.update_draft(actor, request_id, **fields, idem=idem)
    ctx.conversation.data["request_version"] = result.body["version"]


async def photo_slots(ctx: BotContext) -> list[dict[str, Any]]:
    equipment_public_id = str(ctx.conversation.data["equipment_id"])
    scope = await ctx.scope()
    assert scope is not None
    equipment = await catalog.get_equipment(scope, ids.decode("equipment", equipment_public_id))
    categories = await catalog.list_equipment_categories()
    category = next((c for c in categories if c.id == equipment.equipment_category_id), None)
    if category is None:
        return []
    return [
        {"code": slot.code, "label": slot.label, "required": slot.required}
        for slot in category.photo_template
    ]
