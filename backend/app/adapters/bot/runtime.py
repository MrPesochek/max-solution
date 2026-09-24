from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import structlog
from maxapi import Bot, Dispatcher

from app.adapters.bot import updates, webhook_secret
from app.adapters.bot.handlers import build_router
from app.infra.config import Settings, get_settings
from app.infra.max.throttle import MaxThrottle
from app.infra.max.transport import MaxapiTransport

log = structlog.get_logger("bot")

WEBHOOK_PATH = "/max/webhook"


@dataclass(slots=True)
class BotRuntime:
    bot: Bot
    dispatcher: Dispatcher
    transport: MaxapiTransport
    mode: str
    webhook_url: str
    secret: str
    previous_secret: str = ""


_runtime: BotRuntime | None = None
_subscription_runtime: BotRuntime | None = None


def get_runtime() -> BotRuntime | None:
    return _runtime


def set_runtime(runtime: BotRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def webhook_url(settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}{WEBHOOK_PATH}"


def build_runtime(settings: Settings | None = None) -> BotRuntime | None:
    """Готовит бота по настройкам. None — режим `off` или не задан токен."""
    settings = settings or get_settings()
    if settings.max_updates_mode == "off":
        return None
    if not settings.max_bot_token:
        log.warning("bot_disabled", reason="no_token", mode=settings.max_updates_mode)
        return None
    if settings.max_updates_mode == "polling" and settings.app_env != "local":
        raise RuntimeError("polling допустим только при app_env=local")

    bot = Bot(token=settings.max_bot_token, auto_requests=False)
    bot.set_api_url(settings.max_api_base_url)
    transport = MaxapiTransport(
        bot,
        throttle=MaxThrottle(
            per_chat_rps=settings.max_per_chat_rps, global_rps=settings.max_global_rps
        ),
    )
    dispatcher = Dispatcher(router_id="max")
    dispatcher.include_routers(build_router(transport))
    dispatcher.errors()(updates.capture_error)

    if settings.max_updates_mode == "webhook" and not settings.max_webhook_secret:
        if settings.app_env == "prod":
            raise RuntimeError("MAX_WEBHOOK_SECRET обязателен при MAX_UPDATES_MODE=webhook")
        log.warning("bot_webhook_without_secret", effect="requests_rejected")

    return BotRuntime(
        bot=bot,
        dispatcher=dispatcher,
        transport=transport,
        mode=settings.max_updates_mode,
        webhook_url=webhook_url(settings),
        secret=settings.max_webhook_secret,
        previous_secret=settings.max_webhook_secret_previous,
    )


class SubscriptionError(RuntimeError):
    """MAX ответил на подписку или отписку неуспехом."""


def _check_result(result: object, operation: str) -> None:
    if getattr(result, "success", True) is False:
        message = getattr(result, "message", None)
        raise SubscriptionError(f"MAX отклонил {operation}: {message or 'без пояснения'}")


def subscription_runtime() -> BotRuntime | None:
    """Runtime для проверки подписки: приложения (api) или собранный по настройкам (worker)."""
    global _subscription_runtime
    runtime = get_runtime()
    if runtime is not None:
        return runtime
    if _subscription_runtime is None:
        _subscription_runtime = build_runtime()
    return _subscription_runtime


async def ensure_subscription(runtime: BotRuntime | None = None, *, force: bool = False) -> bool:
    """Идемпотентно подписывает бота на наш webhook. True — подписка создана заново.

    Совпадения адреса мало: MAX не показывает секрет подписки, поэтому сверяется и
    отпечаток секрета, с которым мы подписались (`webhook_secret`). Не совпал или
    его нет — переподписка на тот же адрес с текущим секретом. `force` —
    переподписаться в любом случае (CLI).
    """
    runtime = runtime or subscription_runtime()
    if runtime is None or runtime.mode != "webhook":
        return False
    secret_fp = webhook_secret.fingerprint(runtime.secret)
    await webhook_secret.mark_rotation_started(runtime.webhook_url, secret_fp)

    async with webhook_secret.subscription_lock() as session:
        state = await webhook_secret.load_state(session)
        response = await runtime.bot.get_subscriptions()
        for item in response.subscriptions:
            if item.url != runtime.webhook_url and urlsplit(item.url).path == WEBHOOK_PATH:
                await runtime.bot.unsubscribe_webhook(url=item.url)
                log.info("bot_webhook_stale_removed")
        present = any(item.url == runtime.webhook_url for item in response.subscriptions)
        if present and not force and state.matches(runtime.webhook_url, secret_fp):
            return False

        if present:
            _check_result(await runtime.bot.unsubscribe_webhook(url=runtime.webhook_url), "отписку")
        _check_result(
            await runtime.bot.subscribe_webhook(
                url=runtime.webhook_url, secret=runtime.secret or None
            ),
            "подписку",
        )
        await webhook_secret.save_subscribed(session, state, runtime.webhook_url, secret_fp)

    if not present:
        reason = "new"
    elif state.secret_fp is None:
        reason = "no_fingerprint"
    elif state.secret_fp != secret_fp:
        reason = "secret_changed"
    else:
        reason = "forced" if force else "url_changed"
    log.info("bot_webhook_subscribed", reason=reason)
    return True


async def start(runtime: BotRuntime | None = None) -> None:
    """Старт приложения: подготовка диспетчера и восстановление подписки.

    Недоступность MAX на старте не мешает приложению подняться: обработчики
    остаются рабочими, подписку позже восстановит worker.
    """
    runtime = runtime or get_runtime()
    if runtime is None:
        return
    try:
        await runtime.dispatcher.startup(runtime.bot)
    except Exception as exc:
        log.warning("bot_startup_degraded", reason=type(exc).__name__)
    try:
        await ensure_subscription(runtime)
    except Exception as exc:
        log.warning("bot_subscription_failed", reason=type(exc).__name__)


async def shutdown(runtime: BotRuntime | None = None) -> None:
    runtime = runtime or get_runtime()
    if runtime is None:
        return
    await runtime.transport.aclose()
