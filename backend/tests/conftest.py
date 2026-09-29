import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.adapters.http.ratelimit import (
    access_request_limiter,
    auth_limiter,
    provider_search_limiter,
)
from app.db import session as db_session_module
from app.db.base import Base
from app.db.models import *  # noqa: F403 — регистрирует все модели в Base.metadata

os.environ.setdefault("APP_ENV", "test")

BACKEND_DIR = Path(__file__).resolve().parent.parent

_REFERENCE_TABLES = {"cities", "districts", "equipment_categories"}


def _server_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_SERVER_URL", "postgresql+asyncpg://repair:repair@127.0.0.1:54329"
    )


async def _create_database(server_url: str, db_name: str) -> None:
    admin_engine = create_async_engine(f"{server_url}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await admin_engine.dispose()


async def _drop_database(server_url: str, db_name: str) -> None:
    admin_engine = create_async_engine(f"{server_url}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    finally:
        await admin_engine.dispose()


def _run_migrations(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def _reset_auth_limiter() -> None:
    auth_limiter.reset()
    provider_search_limiter.reset()
    access_request_limiter.reset()


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Уникальная тестовая БД на сервере из TEST_DATABASE_SERVER_URL, с применёнными миграциями."""
    server_url = _server_url()
    db_name = f"test_{uuid.uuid4().hex[:16]}"
    database_url = f"{server_url}/{db_name}"

    await _create_database(server_url, db_name)
    try:
        await asyncio.to_thread(_run_migrations, database_url)

        engine = create_async_engine(database_url, pool_pre_ping=True)
        db_session_module.configure(engine)
        try:
            yield engine
        finally:
            await db_session_module.dispose()
    finally:
        await _drop_database(server_url, db_name)


@pytest_asyncio.fixture
async def clean_db(db_engine: AsyncEngine) -> AsyncIterator[None]:
    """Очищает все таблицы, кроме справочников, после теста (TRUNCATE ... CASCADE)."""
    yield
    table_names = [name for name in Base.metadata.tables if name not in _REFERENCE_TABLES]
    if not table_names:
        return
    quoted = ", ".join(f'"{name}"' for name in table_names)
    async with db_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine, clean_db: None) -> AsyncIterator[AsyncSession]:
    """Сессия для прямых обращений теста к БД. Приложение открывает свои транзакции
    отдельно, через app.db.session.transaction() — эта сессия с ними не связана."""
    async with db_session_module.get_sessionmaker()() as session:
        yield session
