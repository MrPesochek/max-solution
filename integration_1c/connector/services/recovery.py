from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from connector import repo
from connector.contract import WebhookEnvelope
from connector.services import sync
from connector.state import AppState
from connector.webhooks import schedule_processing

logger = logging.getLogger("onec_connector.recovery")


def resume_unprocessed(state: AppState) -> int:
    """Ставит в обработку события `received`, которые сейчас никто не обрабатывает."""
    scheduled = 0
    for payload in repo.list_unprocessed_events(state.conn):
        try:
            envelope = WebhookEnvelope.model_validate(payload)
        except ValidationError:
            logger.warning("сохранённое событие не разобрано, пропущено")
            continue
        if schedule_processing(state, envelope) is not None:
            scheduled += 1
    if scheduled:
        logger.info("дообработка событий после сбоя: %s", scheduled)
    return scheduled


async def recover_once(state: AppState) -> int:
    scheduled = resume_unprocessed(state)
    if not state.settings.platform_api_key:
        return scheduled
    try:
        await sync.reconcile(state)
    except Exception:
        logger.warning("сверка через /events не удалась, повтор позже", exc_info=True)
    return scheduled


async def recovery_loop(state: AppState) -> None:
    while True:
        try:
            await recover_once(state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("сбой цикла дообработки событий")
        await asyncio.sleep(state.settings.recovery_interval_seconds)
