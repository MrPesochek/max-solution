from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass

import structlog
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db_session
from app.db.models import WebhookSubscription
from app.infra.config import get_settings
from app.infra.crypto import SecretBox, SecretBoxError

log = structlog.get_logger(__name__)

__all__ = [
    "KeyCheck",
    "KeyMismatchError",
    "check_stored_secrets",
    "key_fingerprint",
    "main",
    "rotate_stored_secrets",
    "verify_on_startup",
]


def key_fingerprint(key: str) -> str:
    """Несекретный отпечаток ключа для журналов и описи резервной копии."""
    return hashlib.sha256(key.strip().encode("ascii")).hexdigest()[:12]


def _keys(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True, slots=True)
class KeyCheck:
    total: int
    unreadable: int
    stale: int


async def check_stored_secrets(session: AsyncSession, key: str) -> KeyCheck:
    """Пробует расшифровать все сохранённые секреты подписок заданными ключами."""
    keys = _keys(key)
    box = SecretBox(key)
    primary = SecretBox(keys[0])
    rows = (await session.execute(select(WebhookSubscription.secret_encrypted))).scalars()
    total = unreadable = stale = 0
    for token in rows:
        total += 1
        try:
            box.decrypt(token)
        except SecretBoxError:
            unreadable += 1
            continue
        if len(keys) > 1:
            try:
                primary.decrypt(token)
            except SecretBoxError:
                stale += 1
    return KeyCheck(total=total, unreadable=unreadable, stale=stale)


async def rotate_stored_secrets(session: AsyncSession, key: str) -> int:
    """Перешифровывает все секреты подписок первым ключом; возвращает число строк.

    Нерасшифровываемый секрет прерывает ротацию целиком: частично перешифрованная
    таблица с неизвестным ключом хуже исходной.
    """
    box = SecretBox(key)
    subscriptions = (
        (await session.execute(select(WebhookSubscription).with_for_update())).scalars().all()
    )
    for subscription in subscriptions:
        subscription.secret_encrypted = box.rotate(subscription.secret_encrypted)
    await session.flush()
    return len(subscriptions)


class KeyMismatchError(RuntimeError):
    pass


async def verify_on_startup() -> None:
    """Проверка при старте api: ключ подходит к сохранённым секретам.

    Нет подписок — проверять нечего, ключ может быть и не задан. Секреты есть, а ключ
    их не читает — старт прерывается с понятной причиной: иначе все доставки молча
    перестанут подписываться. Недоступная БД старт не прерывает: это забота readyz.
    """
    key = get_settings().secrets_encryption_key
    try:
        async with db_session.transaction() as session:
            first = (
                await session.execute(select(WebhookSubscription.secret_encrypted).limit(1))
            ).scalar_one_or_none()
    except Exception as exc:
        log.warning("secrets_key_check_skipped", reason=type(exc).__name__)
        return
    if first is None:
        return
    try:
        SecretBox(key).decrypt(first)
    except SecretBoxError as exc:
        raise KeyMismatchError(
            "SECRETS_ENCRYPTION_KEY не подходит к секретам подписок в БД "
            f"({exc}). Верните ключ из резервной копии (см. app/infra/crypto_keys.py) "
            "или добавьте его в SECRETS_ENCRYPTION_KEY через запятую"
        ) from exc


async def _run(command: str, *, strict: bool) -> int:
    key = get_settings().secrets_encryption_key
    if command == "generate":
        new_key = Fernet.generate_key().decode("ascii")
        print(new_key)
        print(f"отпечаток: {key_fingerprint(new_key)}", file=sys.stderr)
        return 0
    try:
        keys = _keys(key)
        SecretBox(key)
    except SecretBoxError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    if command == "fingerprint":
        for index, item in enumerate(keys):
            role = "шифрует" if index == 0 else "только расшифровывает"
            print(f"{key_fingerprint(item)}  {role}")
        return 0
    try:
        async with db_session.transaction() as session:
            if command == "rotate":
                count = await rotate_stored_secrets(session, key)
                print(f"перешифровано секретов: {count}, ключ {key_fingerprint(keys[0])}")
                return 0
            result = await check_stored_secrets(session, key)
    except SecretBoxError as exc:
        print(f"ошибка: {exc}; ротация отменена, данные не изменены", file=sys.stderr)
        return 1
    finally:
        await db_session.dispose()
    print(
        f"секретов: {result.total}, не расшифровано: {result.unreadable}, "
        f"ждут ротации: {result.stale}"
    )
    if result.unreadable or (strict and result.stale):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.infra.crypto_keys",
        description="Ключ шифрования секретов подписок: проверка, ротация, отпечаток",
    )
    parser.add_argument("command", choices=["check", "rotate", "fingerprint", "generate"])
    parser.add_argument(
        "--strict", action="store_true", help="check: ошибка, если секреты ждут ротации"
    )
    args = parser.parse_args(argv)

    return asyncio.run(_run(args.command, strict=args.strict))


if __name__ == "__main__":
    raise SystemExit(main())
