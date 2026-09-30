"""settings_kv: служебное состояние платформы (отпечаток секрета подписки MAX)"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE settings_kv (
               key text PRIMARY KEY,
               value jsonb NOT NULL DEFAULT '{}'::jsonb,
               updated_at timestamptz NOT NULL DEFAULT now()
           )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE settings_kv")
