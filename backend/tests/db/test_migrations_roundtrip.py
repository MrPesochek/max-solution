import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import _create_database, _drop_database, _server_url
from tests.db.test_migrations import _config, _execute


async def _scalar(database_url: str, statement: str) -> object:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(statement))).scalar_one()
    finally:
        await engine.dispose()


async def test_migrations_roundtrip() -> None:
    server_url = _server_url()
    db_name = f"test_mig_{uuid.uuid4().hex[:12]}"
    database_url = f"{server_url}/{db_name}"
    await _create_database(server_url, db_name)
    try:
        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        codes = "('bar_fridge', 'refrigeration_unit')"
        count_sql = f"SELECT count(*) FROM equipment_categories WHERE code IN {codes}"
        assert await _scalar(database_url, count_sql) == 2

        await asyncio.to_thread(command.downgrade, config, "0017")
        assert await _scalar(database_url, count_sql) == 0
        await asyncio.to_thread(command.downgrade, config, "0016")
        column_sql = (
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assignments' AND column_name = 'en_route_at'"
        )
        assert await _scalar(database_url, column_sql) == 0

        await asyncio.to_thread(command.upgrade, config, "head")
        assert await _scalar(database_url, column_sql) == 1
        assert await _scalar(database_url, count_sql) == 2
    finally:
        await _drop_database(server_url, db_name)


async def test_withdrawn_complaints_survive_downgrade() -> None:
    server_url = _server_url()
    db_name = f"test_mig_{uuid.uuid4().hex[:12]}"
    database_url = f"{server_url}/{db_name}"
    await _create_database(server_url, db_name)
    try:
        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        await _execute(
            database_url,
            "INSERT INTO moderation_cases (subject_type, status, evidence) "
            "VALUES ('review', 'withdrawn', '{}'::jsonb)",
        )
        await asyncio.to_thread(command.downgrade, config, "0016")
        status = await _scalar(database_url, "SELECT status FROM moderation_cases")
        assert status == "rejected"
        await asyncio.to_thread(command.upgrade, config, "head")
    finally:
        await _drop_database(server_url, db_name)


@pytest.mark.parametrize("table", ["equipment"])
async def test_categories_downgrade_refuses_when_used(table: str) -> None:
    server_url = _server_url()
    db_name = f"test_mig_{uuid.uuid4().hex[:12]}"
    database_url = f"{server_url}/{db_name}"
    await _create_database(server_url, db_name)
    try:
        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        org_id, location_id = uuid.uuid4(), uuid.uuid4()
        await _execute(
            database_url,
            f"INSERT INTO organizations (id, legal_name, display_name, is_customer, is_provider) "
            f"VALUES ('{org_id}', 'ООО', 'О', true, false)",
            f"INSERT INTO locations (id, customer_org_id, name, city_id, address, timezone) "
            f"SELECT '{location_id}', '{org_id}', 'Точка', id, 'ул.', timezone FROM cities LIMIT 1",
            f"INSERT INTO {table} (customer_org_id, location_id, equipment_category_id) "
            f"SELECT '{org_id}', '{location_id}', id FROM equipment_categories "
            f"WHERE code = 'bar_fridge'",
        )
        with pytest.raises(Exception, match="downgrade 0018"):
            await asyncio.to_thread(command.downgrade, config, "0017")
    finally:
        await _drop_database(server_url, db_name)
