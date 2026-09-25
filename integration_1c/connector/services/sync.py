from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from connector import repo
from connector.contract import WebhookEnvelope
from connector.platform_client import PlatformApiError
from connector.services import inbound
from connector.state import AppState
from connector.webhooks import mark_failed

logger = logging.getLogger("onec_connector.sync")

_CURSOR_EXPIRED_CODES = {"CURSOR_EXPIRED", "EXPIRED_CURSOR"}


@dataclass
class ReconcileResult:
    mode: str
    applied: int
    skipped_duplicates: int


async def reconcile(state: AppState) -> ReconcileResult:
    cursor = repo.get_cursor(state.conn)
    try:
        return await _reconcile_from_events(state, cursor)
    except PlatformApiError as exc:
        if exc.code in _CURSOR_EXPIRED_CODES or exc.status_code == 410:
            logger.warning("курсор /events истёк — полная сверка через /requests")
            return await _full_reconciliation(state)
        raise


async def _reconcile_from_events(state: AppState, cursor: str | None) -> ReconcileResult:
    applied = 0
    duplicates = 0
    next_cursor = cursor
    while True:
        page = await state.client.get_events(cursor=next_cursor)
        events = page.get("events", [])
        stopped = False
        for raw in events:
            envelope = WebhookEnvelope.model_validate(raw)
            claim = repo.claim_event(
                state.conn,
                event_id=envelope.event_id,
                delivery_id=None,
                event_type=envelope.type,
                resource_id=envelope.resource_id,
                resource_version=envelope.resource_version,
                payload=raw,
            )
            if claim == "duplicate" or (
                claim == repo.RETRY_DUE and envelope.event_id in state.in_flight_events
            ):
                duplicates += 1
                continue
            try:
                await inbound.handle_event(state, envelope)
            except Exception as exc:
                logger.warning("событие %s из /events не обработано: %s", envelope.event_id, exc)
                mark_failed(state, envelope.event_id, exc)
                stopped = True
                break
            repo.mark_event_processed(state.conn, event_id=envelope.event_id, status="processed")
            applied += 1
        if stopped:
            break
        next_cursor = page.get("next_cursor")
        repo.set_cursor(state.conn, next_cursor)
        if not page.get("has_more") or not next_cursor:
            break
    return ReconcileResult(mode="events", applied=applied, skipped_duplicates=duplicates)


async def _full_reconciliation(state: AppState) -> ReconcileResult:
    applied = 0
    cursor: str | None = None
    while True:
        page = await state.client.list_requests(cursor=cursor)
        for item in page.get("items", []):
            if await _apply_item(state, item):
                applied += 1
        cursor = page.get("next_cursor")
        if not cursor:
            break

    fresh = await state.client.get_events(cursor=None)
    repo.set_cursor(state.conn, fresh.get("next_cursor"))
    return ReconcileResult(mode="full", applied=applied, skipped_duplicates=0)


async def _apply_item(state: AppState, item: dict[str, Any]) -> bool:
    request_id = str(item["id"])
    link = repo.get_link(state.conn, request_id)
    version = int(item.get("version") or 0)
    if link is not None and version <= int(link["applied_version"]):
        return False
    await inbound.handle_request(state, request_id)
    return True
