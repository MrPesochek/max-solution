"""schema_revisions: журнал применённых ревизий для отката образов

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-30

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAIN = [f"{number:04d}" for number in range(1, 25)]


def upgrade() -> None:
    op.execute(
        """CREATE TABLE schema_revisions (
               revision text PRIMARY KEY,
               applied_at timestamptz NOT NULL DEFAULT now()
           )"""
    )
    op.get_bind().execute(
        text(
            "INSERT INTO schema_revisions (revision) VALUES (:revision) "
            "ON CONFLICT (revision) DO NOTHING"
        ),
        [{"revision": item} for item in CHAIN],
    )


def downgrade() -> None:
    op.execute("DROP TABLE schema_revisions")
