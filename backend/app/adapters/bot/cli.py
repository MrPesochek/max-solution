from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from app.adapters.bot import runtime as bot_runtime
from app.adapters.bot import webhook_secret
from app.db import session as db_session
from app.infra.config import get_settings
from app.infra.logging import configure_logging

log = structlog.get_logger("bot.cli")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_OUT_OF_SYNC = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot-cli", description="Обслуживание бота MAX")
    sub = parser.add_subparsers(dest="command", required=True)
    rotate = sub.add_parser(
        "rotate-webhook-secret",
        help="Переподписать вебхук MAX на текущий MAX_WEBHOOK_SECRET",
    )
    rotate.add_argument(
        "--check",
        action="store_true",
        help="Только проверить: код 2 — подписка не на текущем секрете или её нет",
    )
    return parser


async def check(runtime: bot_runtime.BotRuntime) -> int:
    response = await runtime.bot.get_subscriptions()
    present = any(item.url == runtime.webhook_url for item in response.subscriptions)
    state = await webhook_secret.load_state()
    in_sync = present and state.matches(
        runtime.webhook_url, webhook_secret.fingerprint(runtime.secret)
    )
    print(f"адрес подписки: {runtime.webhook_url}")
    print(f"подписка в MAX: {'есть' if present else 'нет'}")
    if state.secret_fp is None:
        print("отпечаток секрета: не сохранён")
    else:
        print(f"секрет подписки совпадает с MAX_WEBHOOK_SECRET: {'да' if in_sync else 'нет'}")
    if state.subscribed_at is not None:
        print(f"последняя подписка: {state.subscribed_at.isoformat()}")
    if state.rotation_started_at is not None:
        print(f"ротация начата: {state.rotation_started_at.isoformat()}")
    print("переподписка не нужна" if in_sync else "нужна переподписка: rotate-webhook-secret")
    return EXIT_OK if in_sync else EXIT_OUT_OF_SYNC


async def run(args: argparse.Namespace) -> int:
    runtime = bot_runtime.subscription_runtime()
    if runtime is None or runtime.mode != "webhook":
        print("бот не в режиме webhook (MAX_UPDATES_MODE, MAX_BOT_TOKEN)", file=sys.stderr)
        return EXIT_FAILED
    if not runtime.secret:
        print("MAX_WEBHOOK_SECRET не задан", file=sys.stderr)
        return EXIT_FAILED
    try:
        if args.check:
            return await check(runtime)
        await bot_runtime.ensure_subscription(runtime, force=True)
        print(f"вебхук {runtime.webhook_url} переподписан на текущий MAX_WEBHOOK_SECRET")
        return EXIT_OK
    finally:
        await runtime.bot.close_session()


async def _run_and_dispose(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await db_session.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(get_settings().app_env)
    try:
        return asyncio.run(_run_and_dispose(args))
    except bot_runtime.SubscriptionError as exc:
        log.error("command_failed", command=args.command, reason=type(exc).__name__)
        print(f"не удалось: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except Exception as exc:
        log.error("command_failed", command=args.command, reason=type(exc).__name__)
        print(f"не удалось: {type(exc).__name__}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
