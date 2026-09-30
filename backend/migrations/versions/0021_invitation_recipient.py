"""адресат приглашения сотрудника и связь членства с принятым приглашением"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE invitations ADD COLUMN recipient_max_user_id text")
    op.execute("ALTER TABLE invitations ADD COLUMN recipient_name text")
    op.execute(
        """ALTER TABLE memberships ADD COLUMN invitation_id uuid
           CONSTRAINT fk_memberships_invitation_id REFERENCES invitations (id) ON DELETE SET NULL"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE memberships DROP COLUMN invitation_id")
    op.execute("ALTER TABLE invitations DROP COLUMN recipient_name")
    op.execute("ALTER TABLE invitations DROP COLUMN recipient_max_user_id")
