import argparse
import asyncio
import sys

import structlog

from app.core.actor import Actor, SystemActor
from app.core.errors import DomainError
from app.db import session as db_session
from app.infra.config import get_settings
from app.infra.logging import configure_logging
from app.modules.identity import api as identity
from app.modules.trust import api as trust

log = structlog.get_logger("operator.cli")

CLI_ACTOR_NAME = "operator_cli"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="operator-cli", description="Операторские операции")
    sub = parser.add_subparsers(dest="command", required=True)

    grant = sub.add_parser("grant-operator", help="Выдать платформенную роль оператора")
    grant.add_argument("--max-user-id", required=True)

    revoke = sub.add_parser("revoke-operator", help="Отозвать платформенную роль оператора")
    revoke.add_argument("--max-user-id", required=True)

    for name, help_text in (
        ("suspend-provider", "Заблокировать профиль исполнителя"),
        ("reinstate-provider", "Восстановить профиль исполнителя"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--organization-id", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument(
            "--as-operator",
            help="MAX-идентификатор оператора, от имени которого выполняется операция",
        )

    link = sub.add_parser(
        "issue-login-link",
        help="Одноразовая ссылка входа демо-пользователю (для проверяющих, только demo-стенд)",
    )
    link.add_argument(
        "--user-key",
        required=True,
        action="append",
        dest="user_keys",
        help="Ключ демо-пользователя (employee, provider_admin, ...); можно повторять",
    )
    link.add_argument(
        "--ttl-minutes",
        type=int,
        help="Срок жизни ссылки в минутах (по умолчанию LOGIN_LINK_TTL_SECONDS, не больше 7 суток)",
    )
    return parser


async def _actor(max_user_id: str | None) -> Actor:
    if max_user_id:
        return await identity.operator_actor_by_max_user_id(max_user_id)
    return SystemActor(CLI_ACTOR_NAME)


async def run(args: argparse.Namespace) -> None:
    actor: Actor = SystemActor(CLI_ACTOR_NAME)
    if args.command == "grant-operator":
        await identity.grant_operator(actor, args.max_user_id, idem=None)
        log.info("operator_granted", max_user_id=args.max_user_id)
    elif args.command == "revoke-operator":
        await identity.revoke_operator(actor, args.max_user_id, idem=None)
        log.info("operator_revoked", max_user_id=args.max_user_id)
    elif args.command == "suspend-provider":
        actor = await _actor(args.as_operator)
        await trust.suspend_provider(actor, args.organization_id, args.reason, idem=None)
        log.info("provider_suspended", organization_id=args.organization_id)
    elif args.command == "reinstate-provider":
        actor = await _actor(args.as_operator)
        await trust.reinstate_provider(actor, args.organization_id, args.reason, idem=None)
        log.info("provider_reinstated", organization_id=args.organization_id)
    elif args.command == "issue-login-link":
        ttl = args.ttl_minutes * 60 if args.ttl_minutes is not None else None
        for user_key in args.user_keys:
            issued = await identity.issue_demo_login_link(actor, user_key, ttl_seconds=ttl)
            print(f"{login_link_env_name(user_key)}={issued.url}")


def login_link_env_name(user_key: str) -> str:
    return f"LOGIN_LINK_{user_key.strip().upper()}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(get_settings().app_env)
    if args.command == "issue-login-link":
        structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    try:
        asyncio.run(_run_and_dispose(args))
    except DomainError as exc:
        log.error("command_failed", code=exc.code, message=exc.message)
        return 1
    return 0


async def _run_and_dispose(args: argparse.Namespace) -> None:
    try:
        await run(args)
    finally:
        await db_session.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
