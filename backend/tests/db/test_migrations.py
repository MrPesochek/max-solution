import asyncio
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import BACKEND_DIR, _create_database, _drop_database, _server_url


def _config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _execute(database_url: str, *statements: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def test_downgrade_0011_stops_on_dual_memberships() -> None:
    server_url = _server_url()
    db_name = f"test_mig_{uuid.uuid4().hex[:12]}"
    database_url = f"{server_url}/{db_name}"
    await _create_database(server_url, db_name)
    try:
        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        user_id, org_id = uuid.uuid4(), uuid.uuid4()
        await _execute(
            database_url,
            f"INSERT INTO users (id, max_user_id, display_name) VALUES ('{user_id}', 'm1', 'И')",
            f"INSERT INTO organizations (id, legal_name, display_name, is_customer, is_provider) "
            f"VALUES ('{org_id}', 'ООО', 'О', true, true)",
            f"INSERT INTO memberships (user_id, organization_id, role, status) "
            f"VALUES ('{user_id}', '{org_id}', 'customer_manager', 'active'), "
            f"('{user_id}', '{org_id}', 'provider_admin', 'active')",
        )

        with pytest.raises(Exception, match="downgrade 0011"):
            await asyncio.to_thread(command.downgrade, config, "0010")

        await _execute(database_url, "DELETE FROM memberships WHERE role = 'provider_admin'")
        await asyncio.to_thread(command.downgrade, config, "0010")
        await asyncio.to_thread(command.upgrade, config, "head")
    finally:
        await _drop_database(server_url, db_name)
