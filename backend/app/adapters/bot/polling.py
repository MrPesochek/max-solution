from __future__ import annotations

import asyncio

import structlog

from app.adapters.bot import runtime as bot_runtime
from app.adapters.bot.updates import DedupMiddleware
from app.infra.config import get_settings
from app.infra.logging import configure_logging

log = structlog.get_logger("bot")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.app_env)
    if settings.app_env != "local":
        raise SystemExit("polling доступен только при app_env=local")
    if settings.max_updates_mode != "polling":
        raise SystemExit("установите max_updates_mode=polling")

    runtime = bot_runtime.build_runtime(settings)
    if runtime is None:
        raise SystemExit("не задан токен бота")
    bot_runtime.set_runtime(runtime)
    runtime.dispatcher.register_outer_middleware(DedupMiddleware())

    await runtime.bot.delete_webhook()
    log.info("bot_polling_started")
    try:
        await runtime.dispatcher.start_polling(runtime.bot)
    finally:
        await bot_runtime.shutdown(runtime)


if __name__ == "__main__":
    asyncio.run(main())
