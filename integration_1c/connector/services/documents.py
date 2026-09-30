from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from connector import repo
from connector.onec_client import is_empty_ref
from connector.onec_directory import format_onec_datetime
from connector.platform_client import VersionConflictError
from connector.profile import FieldRef
from connector.state import AppState

logger = logging.getLogger("onec_connector.documents")

STATUS_LABELS = {
    "awaiting_provider": "ожидает ответа сервиса",
    "awaiting_assignment_confirmation": "ожидает подтверждения назначения",
    "accepted": "принята, выезд не согласован",
    "scheduled": "выезд согласован",
    "in_progress": "работы начаты",
    "completion_reported": "работы завершены, ждём подтверждения заказчика",
    "closed": "закрыта",
    "cancellation_pending": "заказчик просит отменить",
    "cancelled": "отменена",
    "action_required": "назначение снято",
}
URGENCY_LABELS = {"normal": "обычная", "urgent": "срочная", "critical": "критичная"}


def template_context(card: dict[str, Any], *, number: str = "") -> dict[str, str]:
    equipment = card.get("equipment") or {}
    location = card.get("location") or {}
    title = " ".join(
        str(part)
        for part in (equipment.get("category_name"), equipment.get("brand"), equipment.get("model"))
        if part
    )
    if equipment.get("serial_number"):
        title += f", S/N {equipment['serial_number']}"
    contact = ", ".join(
        str(part) for part in (location.get("contact_name"), location.get("contact_phone")) if part
    )
    status = str(card.get("status") or "")
    urgency = str(card.get("urgency") or "normal")
    return {
        "request_id": str(card.get("id") or ""),
        "request_number": str(card.get("request_number") or ""),
        "number": number,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "urgency": urgency,
        "urgency_label": URGENCY_LABELS.get(urgency, urgency),
        "urgent": "true" if urgency != "normal" else "false",
        "symptom_description": str(card.get("symptom_description") or ""),
        "error_code_suffix": f" (код ошибки {card['error_code']})"
        if card.get("error_code")
        else "",
        "equipment_title": title,
        "location_name": str(location.get("name") or ""),
        "address": str(location.get("address") or ""),
        "address_suffix": f", {location['address']}" if location.get("address") else "",
        "contact": contact,
    }


def _mapped_values(state: AppState, card: dict[str, Any], *, creating: bool) -> dict[FieldRef, str]:
    context = template_context(card)
    values: dict[FieldRef, str] = {}
    for mapping in state.profile.document.fields:
        if mapping.when == "create" and not creating:
            continue
        values[mapping.target] = mapping.template.format(**context).strip()
    return values


async def _counterparty(state: AppState, card: dict[str, Any]) -> str | None:
    mapping = state.profile.document.counterparty
    if mapping is None:
        return None
    location = card.get("location") or {}
    name = str(location.get("name") or "").strip()
    if not card.get("contacts_disclosed") or not name:
        name = mapping.placeholder
    inn = (
        (card.get("customer") or {}).get("inn") if isinstance(card.get("customer"), dict) else None
    )
    return await state.directory.counterparty_key(name=name, inn=inn)


async def create_document(state: AppState, card: dict[str, Any]) -> dict[str, Any]:
    profile = state.profile
    entity = profile.document.entity
    request_id = str(card["id"])
    body = await state.directory.build_patch(None, _mapped_values(state, card, creating=True))
    body[profile.document.date_field] = format_onec_datetime(datetime.now(UTC), profile)
    initial_state = await state.directory.initial_state_value()
    if initial_state is not None:
        body[profile.state.attribute] = initial_state
    counterparty = await _counterparty(state, card)
    if counterparty is not None and profile.document.counterparty is not None:
        body[profile.document.counterparty.field] = counterparty
    doc = await state.onec.create(entity, body)
    ref_key = str(doc["Ref_Key"])
    number = str(doc.get(profile.document.number_field) or "").strip()
    repo.create_link(
        state.conn,
        request_id=request_id,
        ref_key=ref_key,
        doc_number=number,
        card=card,
        data_version=None,
    )
    logger.info("заявка %s -> %s %s (%s)", request_id, entity, number, ref_key)
    if profile.document.post_after_create:
        await state.onec.post_document(entity, ref_key)
    if number:
        external_id = _external_id(number, doc.get(profile.document.date_field))
        repo.set_setting(state.conn, f"external_id:{request_id}", external_id)
    return await ensure_external_reference(state, request_id, card)


async def ensure_external_reference(
    state: AppState, request_id: str, card: dict[str, Any]
) -> dict[str, Any]:
    external_id = repo.get_setting(state.conn, f"external_id:{request_id}")
    if not external_id or repo.get_setting(state.conn, f"external_id_sent:{request_id}"):
        return card
    try:
        updated = await state.client.set_external_reference(
            request_id, external_id, expected_version=int(card["version"])
        )
    except VersionConflictError:
        card = await state.client.get_request(request_id)
        updated = await state.client.set_external_reference(
            request_id, external_id, expected_version=int(card["version"])
        )
    repo.set_setting(state.conn, f"external_id_sent:{request_id}", "1")
    if "status" in updated:
        card = updated
        repo.update_link_card(state.conn, request_id, card)
    return card


async def update_document(
    state: AppState, ref_key: str, card: dict[str, Any], *, with_messages: bool
) -> dict[str, Any] | None:
    profile = state.profile
    entity = profile.document.entity
    doc = await state.onec.get(entity, ref_key)
    if doc is None:
        return None
    values = _mapped_values(state, card, creating=False)
    if with_messages and profile.messages.inbound is not None:
        values[profile.messages.inbound] = await _customer_messages(state, str(card["id"]))
    body = await state.directory.build_patch(doc, values)

    counterparty_mapping = profile.document.counterparty
    if counterparty_mapping is not None and card.get("contacts_disclosed"):
        current = doc.get(counterparty_mapping.field)
        placeholder = await state.directory.counterparty_key(
            name=counterparty_mapping.placeholder, inn=None
        )
        if is_empty_ref(current) or current == placeholder:
            key = await _counterparty(state, card)
            if key is not None and key != current:
                body[counterparty_mapping.field] = key

    status = card.get("status")
    inbound_state = profile.state.inbound.get(str(status))
    if inbound_state is not None:
        value = await state.directory.state_value(inbound_state)
        if doc.get(profile.state.attribute) != value:
            body[profile.state.attribute] = value
    if body:
        return await state.onec.update(entity, ref_key, body)
    return doc


async def _customer_messages(state: AppState, request_id: str) -> str:
    page = await state.client.list_messages(request_id)
    items = [m for m in page.get("items", []) if m.get("author_kind") != "integration_client"]
    items = items[-state.profile.messages.inbound_limit :]
    lines = []
    for item in items:
        created = str(item.get("created_at") or "")[:16].replace("T", " ")
        lines.append(f"{created}: {str(item.get('body') or '').strip()}")
    return "\n".join(lines)


def _external_id(number: str, date_value: Any) -> str:
    text = str(date_value or "")
    if len(text) >= 10 and not text.startswith("0001"):
        return f"{number} от {text[8:10]}.{text[5:7]}.{text[0:4]}"
    return number
