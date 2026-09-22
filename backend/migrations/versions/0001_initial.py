"""initial schema — 47 таблиц (docs/architecture/schema-draft.sql)

Revision ID: 0001
Revises:
Create Date: 2026-09-19

"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"


def upgrade() -> None:
    sql_script = SQL_PATH.read_text(encoding="utf-8")
    connection = op.get_bind()
    raw_connection = connection.connection.driver_connection
    await_only(raw_connection.execute(sql_script))


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
