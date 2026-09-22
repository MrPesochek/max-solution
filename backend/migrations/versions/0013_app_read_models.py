"""отказ заказчика от приглашения на привязку, отметки прочтения переписки

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE invitations DROP CONSTRAINT ck_invitations_status")
    op.execute(
        "ALTER TABLE invitations ADD CONSTRAINT ck_invitations_status "
        "CHECK (status IN ('pending', 'accepted', 'revoked', 'expired', 'declined'))"
    )
    op.execute("ALTER TABLE invitations ADD COLUMN declined_at timestamptz")
    op.execute("ALTER TABLE invitations ADD COLUMN declined_by_user_id uuid REFERENCES users (id)")
    op.execute("ALTER TABLE invitations ADD COLUMN decline_reason text")

    op.execute(
        """CREATE TABLE message_reads (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            request_id uuid NOT NULL REFERENCES repair_requests (id),
            membership_id uuid NOT NULL REFERENCES memberships (id),
            last_read_message_id uuid REFERENCES messages (id),
            last_read_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ux_message_reads_request_membership UNIQUE (request_id, membership_id)
        )"""
    )
    op.execute("CREATE INDEX ix_message_reads_membership_id ON message_reads (membership_id)")


def downgrade() -> None:
    op.execute("DROP TABLE message_reads")
    op.execute("ALTER TABLE invitations DROP COLUMN decline_reason")
    op.execute("ALTER TABLE invitations DROP COLUMN declined_by_user_id")
    op.execute("ALTER TABLE invitations DROP COLUMN declined_at")
    op.execute("UPDATE invitations SET status = 'revoked' WHERE status = 'declined'")
    op.execute("ALTER TABLE invitations DROP CONSTRAINT ck_invitations_status")
    op.execute(
        "ALTER TABLE invitations ADD CONSTRAINT ck_invitations_status "
        "CHECK (status IN ('pending', 'accepted', 'revoked', 'expired'))"
    )
