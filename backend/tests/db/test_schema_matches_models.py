from typing import Any

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.types import TypeEngine

from app.db.base import Base

_PG_DATA_TYPE_TO_BUCKET = {
    "uuid": "uuid",
    "text": "text",
    "boolean": "boolean",
    "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
    "bigint": "bigint",
    "integer": "integer",
    "smallint": "smallint",
    "jsonb": "jsonb",
    "bytea": "bytea",
    "ARRAY": "array",
    "character": "char",
    "date": "date",
    "numeric": "numeric",
    "inet": "inet",
}


def _sa_bucket(col_type: TypeEngine[Any]) -> str:
    if isinstance(col_type, PgUUID):
        return "uuid"
    if isinstance(col_type, ARRAY):
        return "array"
    if isinstance(col_type, JSONB):
        return "jsonb"
    if isinstance(col_type, CHAR):
        return "char"
    if isinstance(col_type, DateTime):
        return "timestamptz" if col_type.timezone else "timestamp"
    if isinstance(col_type, Date):
        return "date"
    if isinstance(col_type, LargeBinary):
        return "bytea"
    if isinstance(col_type, Boolean):
        return "boolean"
    if isinstance(col_type, BigInteger):
        return "bigint"
    if isinstance(col_type, SmallInteger):
        return "smallint"
    if isinstance(col_type, Integer):
        return "integer"
    if isinstance(col_type, Numeric):
        return "numeric"
    if isinstance(col_type, INET):
        return "inet"
    if isinstance(col_type, Text):
        return "text"
    raise AssertionError(f"неизвестный тип колонки в модели: {col_type!r}")


def _pg_bucket(data_type: str) -> str:
    try:
        return _PG_DATA_TYPE_TO_BUCKET[data_type]
    except KeyError:
        raise AssertionError(f"неизвестный data_type в information_schema: {data_type!r}") from None


async def test_schema_matches_models(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name, column_name, is_nullable, data_type, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name NOT IN ('alembic_version', 'schema_revisions')"
            )
        )
        rows = result.all()

    actual_tables: dict[str, dict[str, tuple[str, str, str | None]]] = {}
    for table_name, column_name, is_nullable, data_type, column_default in rows:
        actual_tables.setdefault(table_name, {})[column_name] = (
            is_nullable,
            data_type,
            column_default,
        )

    expected_tables = set(Base.metadata.tables)
    assert set(actual_tables) == expected_tables, (
        f"набор таблиц в БД не совпадает с моделями.\n"
        f"есть в БД, нет в моделях: {sorted(set(actual_tables) - expected_tables)}\n"
        f"есть в моделях, нет в БД: {sorted(expected_tables - set(actual_tables))}"
    )

    for table_name, table in Base.metadata.tables.items():
        actual_columns = actual_tables[table_name]
        expected_column_names = set(table.columns.keys())
        actual_column_names = set(actual_columns)
        assert expected_column_names == actual_column_names, (
            f"таблица {table_name}: колонки не совпадают.\n"
            f"есть в БД, нет в модели: {sorted(actual_column_names - expected_column_names)}\n"
            f"есть в модели, нет в БД: {sorted(expected_column_names - actual_column_names)}"
        )

        for column in table.columns:
            is_nullable, data_type, column_default = actual_columns[column.name]
            actual_nullable = is_nullable == "YES"
            assert column.nullable == actual_nullable, (
                f"{table_name}.{column.name}: nullable в модели={column.nullable}, "
                f"в БД={actual_nullable}"
            )

            expected_bucket = _sa_bucket(column.type)
            actual_bucket = _pg_bucket(data_type)
            assert expected_bucket == actual_bucket, (
                f"{table_name}.{column.name}: тип в модели={expected_bucket} "
                f"({column.type!r}), в БД={actual_bucket} ({data_type!r})"
            )

            has_model_default = column.server_default is not None
            has_db_default = column_default is not None
            assert has_model_default == has_db_default, (
                f"{table_name}.{column.name}: DEFAULT в БД={has_db_default} "
                f"({column_default!r}), server_default в модели={has_model_default} "
                f"({column.server_default!r}) — добавьте server_default=text(...)/func.now() "
                f"в mapped_column, отражающий DEFAULT из SQL-миграции"
            )
