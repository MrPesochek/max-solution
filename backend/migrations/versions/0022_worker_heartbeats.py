"""worker_heartbeats: heartbeat фоновых циклов для healthcheck и /ops/status

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-30

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE worker_heartbeats (
               loop_name text PRIMARY KEY,
               stale_after_seconds integer NOT NULL CHECK (stale_after_seconds > 0),
               registered_at timestamptz NOT NULL DEFAULT now(),
               last_success_at timestamptz,
               last_processed integer,
               last_error_at timestamptz,
               last_error text,
               consecutive_failures integer NOT NULL DEFAULT 0
                   CHECK (consecutive_failures >= 0),
               updated_at timestamptz NOT NULL DEFAULT now()
           )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE worker_heartbeats")
