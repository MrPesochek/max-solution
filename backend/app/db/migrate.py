import argparse
import asyncio
import sys

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import schema_revisions
from app.infra.config import get_settings

MESSAGE_DB_AHEAD = "БД новее кода, миграции не требуются"
MESSAGE_UP_TO_DATE = "схема БД на голове кода, миграции не требуются"


def build_config() -> Config:
    return schema_revisions.alembic_config(get_settings().database_url)


async def _state(database_url: str, heads: set[str]) -> tuple[bool, set[str]]:
    """(головы кода применены, содержимое alembic_version); пустая БД — (False, set())."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            exists = await connection.execute(text("SELECT to_regclass('alembic_version')"))
            if exists.scalar() is None:
                return False, set()
            applied = await schema_revisions.heads_applied(connection, heads)
            current = await schema_revisions.applied_revisions(connection)
    finally:
        await engine.dispose()
    return applied, current


def _database_url(config: Config) -> str:
    database_url = config.get_main_option("sqlalchemy.url")
    if not database_url:
        raise RuntimeError("в конфигурации Alembic не задан sqlalchemy.url")
    return database_url


def _load_state(config: Config, heads: set[str]) -> tuple[bool, set[str]]:
    return asyncio.run(_state(_database_url(config), heads))


def run(config: Config) -> bool:
    """Доводит схему до головы кода. Возвращает True, если миграции запускались."""
    heads = schema_revisions.head_revisions(config)
    applied, current = _load_state(config, heads)
    if applied:
        print(MESSAGE_UP_TO_DATE if current == heads else MESSAGE_DB_AHEAD)
        return False
    command.upgrade(config, "head")
    return True


def pending(config: Config) -> list[str]:
    """Строки «ревизия: описание» для миграций, которые применил бы run()."""
    heads = schema_revisions.head_revisions(config)
    applied, current = _load_state(config, heads)
    if applied:
        return []
    script = ScriptDirectory.from_config(config)
    lower = next(iter(current)) if len(current) == 1 else None
    revisions = list(script.iterate_revisions("heads", lower, inclusive=False))
    return [
        f"{rev.revision}: {rev.doc}" for rev in reversed(revisions) if rev.revision not in current
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="миграции схемы с учётом отката образов")
    parser.add_argument(
        "--pending", action="store_true", help="только напечатать ревизии, которые будут применены"
    )
    args = parser.parse_args(argv)
    config = build_config()
    if args.pending:
        for line in pending(config):
            print(line)
        return 0
    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
