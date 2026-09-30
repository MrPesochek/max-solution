from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import ValidationError

from connector import repo, security
from connector.contract import WebhookEnvelope
from connector.services import inbound
from connector.state import AppState

logger = logging.getLogger("onec_connector.webhooks")

router = APIRouter()

MAX_WEBHOOK_BODY_BYTES = 256 * 1024


@router.post("/webhooks/platform")
async def receive_platform_webhook(request: Request) -> Response:
    state: AppState = request.app.state.connector

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        _log_rejected(state, request.headers.get("X-Event-ID"), None, None, "body_too_large")
        raise HTTPException(status_code=413, detail="тело события слишком большое")
    raw_body = await _read_limited(request)
    if raw_body is None:
        _log_rejected(state, request.headers.get("X-Event-ID"), None, None, "body_too_large")
        raise HTTPException(status_code=413, detail="тело события слишком большое")
    event_id = request.headers.get("X-Event-ID")
    delivery_id = request.headers.get("X-Delivery-ID")
    timestamp_header = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    subscription = repo.get_subscription(state.conn)
    if subscription is None or not subscription["secret"]:
        _log_rejected(state, event_id, delivery_id, None, "no_subscription")
        raise HTTPException(status_code=401, detail="подписка не настроена")

    if not signature or not timestamp_header:
        _log_rejected(state, event_id, delivery_id, None, "missing_signature_headers")
        raise HTTPException(status_code=401, detail="отсутствуют заголовки подписи")

    try:
        timestamp = int(timestamp_header)
    except ValueError as exc:
        _log_rejected(state, event_id, delivery_id, None, "bad_timestamp")
        raise HTTPException(status_code=401, detail="некорректный X-Timestamp") from exc

    valid = security.verify_webhook_signature(
        str(subscription["secret"]),
        timestamp,
        raw_body,
        signature,
        max_age_seconds=state.settings.webhook_signature_max_age_seconds,
    )
    if not valid:
        _log_rejected(state, event_id, delivery_id, None, "invalid_signature")
        raise HTTPException(status_code=401, detail="неверная подпись")

    try:
        payload = json.loads(raw_body)
        envelope = WebhookEnvelope.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        _log_rejected(state, event_id, delivery_id, None, "bad_payload")
        raise HTTPException(status_code=400, detail="некорректное тело события") from exc

    claim = repo.claim_event(
        state.conn,
        event_id=envelope.event_id,
        delivery_id=delivery_id,
        event_type=envelope.type,
        resource_id=envelope.resource_id,
        resource_version=envelope.resource_version,
        payload=payload,
    )
    repo.log_delivery(
        state.conn,
        event_id=envelope.event_id,
        delivery_id=delivery_id,
        event_type=envelope.type,
        signature_valid=True,
        outcome="accepted" if claim == "new" else claim,
    )

    if claim != "duplicate":
        schedule_processing(state, envelope)

    return Response(status_code=200)


async def _read_limited(request: Request) -> bytes | None:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _log_rejected(
    state: AppState,
    event_id: str | None,
    delivery_id: str | None,
    event_type: str | None,
    outcome: str,
) -> None:
    repo.log_delivery(
        state.conn,
        event_id=event_id or "unknown",
        delivery_id=delivery_id,
        event_type=event_type,
        signature_valid=False,
        outcome=outcome,
    )


def schedule_processing(state: AppState, envelope: WebhookEnvelope) -> asyncio.Task[None] | None:
    if envelope.event_id in state.in_flight_events:
        return None
    state.in_flight_events.add(envelope.event_id)
    task = asyncio.create_task(_process_with_retries(state, envelope))
    state.background_tasks.add(task)
    task.add_done_callback(state.background_tasks.discard)
    task.add_done_callback(lambda _: state.in_flight_events.discard(envelope.event_id))
    return task


async def _process_with_retries(state: AppState, envelope: WebhookEnvelope) -> None:
    attempts = max(1, state.settings.background_retry_attempts)
    for attempt in range(1, attempts + 1):
        try:
            await inbound.handle_event(state, envelope)
            repo.mark_event_processed(state.conn, event_id=envelope.event_id, status="processed")
            return
        except Exception as exc:
            logger.warning(
                "обработка события %s (попытка %s/%s) не удалась: %s",
                envelope.event_id,
                attempt,
                attempts,
                exc,
            )
            if attempt == attempts:
                mark_failed(state, envelope.event_id, exc)
                return
            delay = state.settings.background_retry_base_delay_seconds * (2 ** (attempt - 1))
            await asyncio.sleep(delay)


def mark_failed(state: AppState, event_id: str, exc: Exception) -> None:
    settings = state.settings
    status = repo.mark_event_failed(
        state.conn,
        event_id=event_id,
        error=str(exc),
        max_attempts=settings.event_retry_max_rounds,
        base_delay_seconds=settings.event_retry_base_delay_seconds,
        max_delay_seconds=settings.event_retry_max_delay_seconds,
    )
    if status == "dead":
        logger.error("событие %s не обработано, попытки исчерпаны: %s", event_id, exc)


async def drain_background_tasks(state: AppState, timeout_seconds: float = 5.0) -> None:
    try:
        async with asyncio.timeout(timeout_seconds):
            while state.background_tasks:
                pending = list(state.background_tasks)
                await asyncio.gather(*pending, return_exceptions=True)
    except TimeoutError:
        logger.warning("drain_background_tasks: тайм-аут ожидания")
