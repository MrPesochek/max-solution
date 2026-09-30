"""адресат и параметры действия кнопки бота"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE bot_actions ADD COLUMN recipient_user_id uuid REFERENCES users (id)")
    op.execute("ALTER TABLE bot_actions ADD COLUMN params jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("CREATE INDEX ix_bot_actions_recipient_user_id ON bot_actions (recipient_user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_bot_actions_recipient_user_id")
    op.execute("ALTER TABLE bot_actions DROP COLUMN params")
    op.execute("ALTER TABLE bot_actions DROP COLUMN recipient_user_id")
