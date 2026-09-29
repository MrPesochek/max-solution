import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db import migrate, schema_revisions
from tests.conftest import BACKEND_DIR, _create_database, _drop_database, _server_url

VERSIONS_DIR = BACKEND_DIR / "migrations" / "versions"
FUTURE_REVISION = "9999"

FUTURE_SCRIPT = '''"""вымышленная ревизия следующей версии кода

Revision ID: {revision}
Revises: {head}

"""

from alembic import op

revision = "{revision}"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE future_feature (id integer PRIMARY KEY)")


def downgrade() -> None:
    op.execute("DROP TABLE future_feature")
'''


def _code_head() -> str:
    (head,) = schema_revisions.head_revisions()
    return head


def _chain(config: Config) -> set[str]:
    return {rev.revision for rev in ScriptDirectory.from_config(config).walk_revisions()}


def _future_config(database_url: str, tmp_path: Path) -> Config:
    """Конфигурация «новой версии»: цепочка кода плюс ревизия-потомок из tmp_path."""
    (tmp_path / f"{FUTURE_REVISION}_future.py").write_text(
        FUTURE_SCRIPT.format(revision=FUTURE_REVISION, head=_code_head()), encoding="utf-8"
    )
    config = schema_revisions.alembic_config(database_url)
    config.set_main_option("version_locations", f"{VERSIONS_DIR}{os.pathsep}{tmp_path}")
    return config


@pytest_asyncio.fixture
async def fresh_db() -> AsyncIterator[tuple[str, AsyncEngine]]:
    server_url = _server_url()
    db_name = f"test_rev_{uuid.uuid4().hex[:12]}"
    database_url = f"{server_url}/{db_name}"
    await _create_database(server_url, db_name)
    engine = create_async_engine(database_url)
    try:
        yield database_url, engine
    finally:
        await engine.dispose()
        await _drop_database(server_url, db_name)


async def _journal(engine: AsyncEngine) -> set[str] | None:
    async with engine.connect() as conn:
        return await schema_revisions._journal(conn)


async def _alembic_version(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return await schema_revisions.applied_revisions(conn)


async def _execute(engine: AsyncEngine, *statements: str) -> None:
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


async def test_upgrade_head_journals_whole_chain(fresh_db: tuple[str, AsyncEngine]) -> None:
    database_url, engine = fresh_db
    config = schema_revisions.alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    assert await _journal(engine) == _chain(config)
    assert await _alembic_version(engine) == {_code_head()}


async def test_downgrade_removes_last_row(
    fresh_db: tuple[str, AsyncEngine], tmp_path: Path
) -> None:
    database_url, engine = fresh_db
    config = _future_config(database_url, tmp_path)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert FUTURE_REVISION in (await _journal(engine) or set())

    await asyncio.to_thread(command.downgrade, config, "-1")
    assert await _journal(engine) == _chain(schema_revisions.alembic_config(database_url))
    assert await _alembic_version(engine) == {_code_head()}

    await asyncio.to_thread(command.downgrade, config, "0023")
    assert await _journal(engine) is None
    await asyncio.to_thread(command.upgrade, config, "head")
    assert await _journal(engine) == _chain(config)


async def test_readiness_ok_on_head(fresh_db: tuple[str, AsyncEngine]) -> None:
    database_url, engine = fresh_db
    await asyncio.to_thread(command.upgrade, schema_revisions.alembic_config(database_url), "head")
    await schema_revisions.check_schema(engine)


async def test_readiness_accepts_schema_newer_than_code(
    fresh_db: tuple[str, AsyncEngine], tmp_path: Path
) -> None:
    """Воспроизведение дефекта: БД поднята следующей версией, образ откатан на прежний.

    Прежняя проверка требовала alembic_version == головам кода и отвечала 503.
    """
    database_url, engine = fresh_db
    await asyncio.to_thread(command.upgrade, _future_config(database_url, tmp_path), "head")

    assert await _alembic_version(engine) == {FUTURE_REVISION}
    assert await _alembic_version(engine) != schema_revisions.head_revisions()
    await schema_revisions.check_schema(engine)


async def test_readiness_rejects_schema_older_than_code(
    fresh_db: tuple[str, AsyncEngine],
) -> None:
    database_url, engine = fresh_db
    await asyncio.to_thread(command.upgrade, schema_revisions.alembic_config(database_url), "head")
    head = _code_head()
    await _execute(
        engine,
        f"DELETE FROM schema_revisions WHERE revision = '{head}'",
        "UPDATE alembic_version SET version_num = '0001'",
    )
    with pytest.raises(schema_revisions.SchemaError, match=schema_revisions.SCHEMA_BEHIND_CODE):
        await schema_revisions.check_schema(engine)


async def test_readiness_without_journal_keeps_previous_message(
    fresh_db: tuple[str, AsyncEngine],
) -> None:
    database_url, engine = fresh_db
    config = schema_revisions.alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, "0023")
    with pytest.raises(schema_revisions.SchemaError, match=schema_revisions.SCHEMA_MISMATCH):
        await schema_revisions.check_schema(engine)


def _spy(calls: list[str]) -> Callable[[Config, str], None]:
    original = command.upgrade

    def upgrade(config: Config, revision: str) -> None:
        calls.append(revision)
        original(config, revision)

    return upgrade


async def test_migrate_skips_when_db_is_newer(
    fresh_db: tuple[str, AsyncEngine],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url, engine = fresh_db
    await asyncio.to_thread(command.upgrade, _future_config(database_url, tmp_path), "head")
    code_config = schema_revisions.alembic_config(database_url)

    with pytest.raises(CommandError, match="Can't locate revision"):
        await asyncio.to_thread(command.upgrade, code_config, "head")

    calls: list[str] = []
    monkeypatch.setattr(migrate.command, "upgrade", _spy(calls))
    assert await asyncio.to_thread(migrate.run, code_config) is False
    assert calls == []
    assert migrate.MESSAGE_DB_AHEAD in capsys.readouterr().out
    assert await _alembic_version(engine) == {FUTURE_REVISION}


async def test_migrate_upgrades_when_db_is_older(
    fresh_db: tuple[str, AsyncEngine],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url, engine = fresh_db
    config = schema_revisions.alembic_config(database_url)
    await asyncio.to_thread(command.upgrade, config, "0023")

    calls: list[str] = []
    monkeypatch.setattr(migrate.command, "upgrade", _spy(calls))
    assert await asyncio.to_thread(migrate.run, config) is True
    assert calls == ["head"]
    assert await _journal(engine) == _chain(config)
    await schema_revisions.check_schema(engine)

    assert await asyncio.to_thread(migrate.run, config) is False
    assert calls == ["head"]
    assert migrate.MESSAGE_UP_TO_DATE in capsys.readouterr().out


async def test_migrate_upgrades_empty_database(
    fresh_db: tuple[str, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url, engine = fresh_db
    config = schema_revisions.alembic_config(database_url)
    monkeypatch.setattr(migrate, "build_config", lambda: config)
    assert await asyncio.to_thread(migrate.main, []) == 0
    assert await _journal(engine) == _chain(config)


async def test_pending_lists_only_unapplied_revisions(
    fresh_db: tuple[str, AsyncEngine], tmp_path: Path
) -> None:
    database_url, _ = fresh_db
    config = schema_revisions.alembic_config(database_url)
    revisions = ScriptDirectory.from_config(config)

    assert await asyncio.to_thread(migrate.pending, config) == [
        f"{rev.revision}: {rev.doc}"
        for rev in reversed(list(ScriptDirectory.from_config(config).walk_revisions()))
    ]

    await asyncio.to_thread(command.upgrade, config, "0023")
    listed = await asyncio.to_thread(migrate.pending, config)
    expected = [rev.revision for rev in reversed(list(revisions.iterate_revisions("head", "0023")))]
    assert [line.split(":")[0] for line in listed] == expected

    await asyncio.to_thread(command.upgrade, _future_config(database_url, tmp_path), "head")
    assert await asyncio.to_thread(migrate.pending, config) == []
