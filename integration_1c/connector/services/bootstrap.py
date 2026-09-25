from __future__ import annotations

import asyncio
import logging

from connector import repo
from connector.contract import SUBSCRIBED_EVENTS
from connector.platform_client import PlatformApiError, PlatformUnreachableError
from connector.state import AppState

logger = logging.getLogger("onec_connector.bootstrap")


def subscribed_events() -> list[str]:
    return sorted(SUBSCRIBED_EVENTS)


async def ensure_subscription(state: AppState) -> bool:
    """Возвращает True, если подписка есть/только что создана."""
    if not state.settings.platform_api_key:
        logger.info("API-ключ платформы не задан — bootstrap подписки пропущен")
        return False

    webhook_url = state.settings.public_base_url.rstrip("/") + "/webhooks/platform"
    existing = repo.get_subscription(state.conn)
    stale_id: str | None = None
    if existing is not None and existing["subscription_id"]:
        stale_id = await _stale_subscription(state, str(existing["subscription_id"]))
        if stale_id is None:
            return True
        logger.info("типы событий подписки %s устарели, подписка пересоздаётся", stale_id)

    try:
        response = await state.client.create_webhook_subscription(
            url=webhook_url, events=subscribed_events()
        )
    except PlatformUnreachableError:
        logger.warning("платформа недоступна при bootstrap подписки, повтор в фоне")
        return False
    except Exception:
        logger.exception("не удалось создать подписку на вебхуки")
        return False

    repo.save_subscription(
        state.conn,
        subscription_id=str(response["id"]),
        secret=str(response["secret"]),
        url=str(response.get("url", webhook_url)),
        status=str(response.get("status", "active")),
    )
    logger.info("подписка на вебхуки создана: %s", response.get("id"))
    if stale_id is not None and stale_id != str(response["id"]):
        try:
            await state.client.delete_webhook_subscription(stale_id)
        except (PlatformApiError, PlatformUnreachableError):
            logger.warning("прежняя подписка %s не удалена", stale_id)
    return True


async def _stale_subscription(state: AppState, subscription_id: str) -> str | None:
    """Id сохранённой подписки, если её типы событий разошлись с `SUBSCRIBED_EVENTS`.

    Сбой сверки не мешает работе: подписка остаётся прежней до следующего старта.
    """
    try:
        listing = await state.client.list_webhook_subscriptions()
    except (PlatformApiError, PlatformUnreachableError):
        logger.warning("не удалось сверить типы событий подписки %s", subscription_id)
        return None
    for item in listing.get("items", []):
        if str(item.get("id")) == subscription_id:
            return None if set(item.get("events") or []) == SUBSCRIBED_EVENTS else subscription_id
    return subscription_id


async def bootstrap_retry_loop(state: AppState) -> None:
    while True:
        try:
            if await ensure_subscription(state):
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("сбой попытки bootstrap подписки")
        await asyncio.sleep(state.settings.bootstrap_retry_seconds)
