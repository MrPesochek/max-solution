"""durable inbox событий MAX: статусы, аренда, повторы; индексы уборки"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = [
    "ALTER TABLE max_updates ADD COLUMN status text NOT NULL DEFAULT 'received'",
    "ALTER TABLE max_updates ADD COLUMN attempts integer NOT NULL DEFAULT 0",
    "ALTER TABLE max_updates ADD COLUMN lease_until timestamptz",
    "ALTER TABLE max_updates ADD COLUMN next_retry_at timestamptz",
    "ALTER TABLE max_updates ADD COLUMN replies jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE max_updates ADD COLUMN conversation_snapshot jsonb",
    """UPDATE max_updates
       SET status = CASE
               WHEN processed_at IS NOT NULL AND processing_error IS NULL THEN 'processed'
               ELSE 'dead'
           END,
           attempts = 1""",
    """ALTER TABLE max_updates ADD CONSTRAINT ck_max_updates_status
       CHECK (status IN ('received', 'processing', 'processed', 'failed', 'dead'))""",
    "DROP INDEX IF EXISTS ix_max_updates_unprocessed",
    """CREATE INDEX ix_max_updates_pending ON max_updates (status, received_at)
       WHERE status IN ('received', 'processing', 'failed')""",
    """CREATE INDEX ix_max_updates_processed_at ON max_updates (processed_at)
       WHERE status = 'processed'""",
    """CREATE INDEX ix_notifications_finished ON notifications (created_at)
       WHERE state <> 'queued'""",
]

DOWNGRADE = [
    "DROP INDEX ix_notifications_finished",
    "DROP INDEX ix_max_updates_processed_at",
    "DROP INDEX ix_max_updates_pending",
    """CREATE INDEX ix_max_updates_unprocessed ON max_updates (received_at)
       WHERE processed_at IS NULL""",
    "ALTER TABLE max_updates DROP CONSTRAINT ck_max_updates_status",
    "ALTER TABLE max_updates DROP COLUMN conversation_snapshot",
    "ALTER TABLE max_updates DROP COLUMN replies",
    "ALTER TABLE max_updates DROP COLUMN next_retry_at",
    "ALTER TABLE max_updates DROP COLUMN lease_until",
    "ALTER TABLE max_updates DROP COLUMN attempts",
    "ALTER TABLE max_updates DROP COLUMN status",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
