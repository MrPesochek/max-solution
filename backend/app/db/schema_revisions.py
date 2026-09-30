from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext, MigrationInfo
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

SCHEMA_MISMATCH = "схема БД не соответствует последней миграции"
SCHEMA_BEHIND_CODE = "схема БД старше кода, выполните миграции"


class SchemaError(RuntimeError):
    pass


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def head_revisions(config: Config | None = None) -> set[str]:
    return set(ScriptDirectory.from_config(config or alembic_config()).get_heads())


def _journal_exists(connection: Connection) -> bool:
    return connection.execute(text("SELECT to_regclass('schema_revisions')")).scalar() is not None


def record_step(
    ctx: MigrationContext, step: MigrationInfo, heads: set[str], run_args: dict[str, Any]
) -> None:
    if step.is_stamp or ctx.as_sql or ctx.connection is None:
        return
    connection = ctx.connection
    if not _journal_exists(connection):
        return
    if step.is_upgrade:
        for revision in step.destination_revision_ids:
            connection.execute(
                text(
                    "INSERT INTO schema_revisions (revision) VALUES (:revision) "
                    "ON CONFLICT (revision) DO NOTHING"
                ),
                {"revision": revision},
            )
    else:
        for revision in step.source_revision_ids:
            connection.execute(
                text("DELETE FROM schema_revisions WHERE revision = :revision"),
                {"revision": revision},
            )


async def applied_revisions(connection: AsyncConnection) -> set[str]:
    result = await connection.execute(text("SELECT version_num FROM alembic_version"))
    return set(result.scalars())


async def _journal(connection: AsyncConnection) -> set[str] | None:
    exists = (await connection.execute(text("SELECT to_regclass('schema_revisions')"))).scalar()
    if exists is None:
        return None
    result = await connection.execute(text("SELECT revision FROM schema_revisions"))
    return set(result.scalars())


async def heads_applied(connection: AsyncConnection, heads: set[str]) -> bool:
    if await applied_revisions(connection) == heads:
        return True
    journal = await _journal(connection)
    return journal is not None and heads <= journal


async def check_schema(engine: AsyncEngine, heads: set[str] | None = None) -> None:
    heads = heads if heads is not None else head_revisions()
    async with engine.connect() as connection:
        applied = await applied_revisions(connection)
        if applied == heads:
            return
        journal = await _journal(connection)
    if journal is None:
        raise SchemaError(SCHEMA_MISMATCH)
    if not heads <= journal:
        raise SchemaError(SCHEMA_BEHIND_CODE)
