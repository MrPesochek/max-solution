"""интеграция: постоянный счётчик ленты событий"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE integration_feed_counters (
            organization_id uuid PRIMARY KEY REFERENCES organizations (id),
            last_seq bigint NOT NULL DEFAULT 0,
            CONSTRAINT ck_integration_feed_counters_last_seq CHECK (last_seq >= 0)
        )"""
    )
    op.execute(
        """INSERT INTO integration_feed_counters (organization_id, last_seq)
           SELECT recipient_org_id, max(feed_seq)
           FROM integration_events
           WHERE feed_seq IS NOT NULL
           GROUP BY recipient_org_id"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE integration_feed_counters")
