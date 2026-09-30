"""окно поиска, связь заявок, неполные фото, напоминание, архив точек и оборудования"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = [
    "ALTER TABLE repair_requests ADD COLUMN search_expires_at timestamptz",
    "ALTER TABLE repair_requests ADD COLUMN parent_request_id uuid REFERENCES repair_requests (id)",
    "ALTER TABLE repair_requests ADD COLUMN photos_incomplete boolean NOT NULL DEFAULT false",
    "ALTER TABLE repair_requests ADD COLUMN photos_incomplete_reason text",
    """ALTER TABLE repair_requests ADD CONSTRAINT ck_repair_requests_photos_incomplete_reason
       CHECK (NOT photos_incomplete OR photos_incomplete_reason IS NOT NULL)""",
    """CREATE INDEX ix_repair_requests_search_expires_at ON repair_requests (search_expires_at)
       WHERE status = 'searching'""",
    "CREATE INDEX ix_repair_requests_parent_request_id ON repair_requests (parent_request_id)",
    "ALTER TABLE assignments ADD COLUMN reminded_at timestamptz",
    "ALTER TABLE locations ADD COLUMN archived_at timestamptz",
    "ALTER TABLE equipment ADD COLUMN archived_at timestamptz",
]

DOWNGRADE = [
    "ALTER TABLE equipment DROP COLUMN archived_at",
    "ALTER TABLE locations DROP COLUMN archived_at",
    "ALTER TABLE assignments DROP COLUMN reminded_at",
    "DROP INDEX ix_repair_requests_parent_request_id",
    "DROP INDEX ix_repair_requests_search_expires_at",
    "ALTER TABLE repair_requests DROP CONSTRAINT ck_repair_requests_photos_incomplete_reason",
    "ALTER TABLE repair_requests DROP COLUMN photos_incomplete_reason",
    "ALTER TABLE repair_requests DROP COLUMN photos_incomplete",
    "ALTER TABLE repair_requests DROP COLUMN parent_request_id",
    "ALTER TABLE repair_requests DROP COLUMN search_expires_at",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
