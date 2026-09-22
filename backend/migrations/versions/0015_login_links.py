"""одноразовые ссылки входа в Web App из бота

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE login_links (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id     uuid NOT NULL REFERENCES users (id),
            token_hash  bytea NOT NULL,
            target      text,
            expires_at  timestamptz NOT NULL,
            used_at     timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ux_login_links_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_login_links_target CHECK (target IS NULL OR char_length(target) <= 512)
        )"""
    )
    op.execute("CREATE INDEX ix_login_links_user_id ON login_links (user_id)")
    op.execute("CREATE INDEX ix_login_links_expires_at ON login_links (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE login_links")
