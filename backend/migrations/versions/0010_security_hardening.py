"""безопасность: секреты вне idempotency_keys, одноразовый initData, префикс токена из хеша

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE idempotency_keys "
        "ADD COLUMN response_secret_redacted boolean NOT NULL DEFAULT false"
    )
    op.execute(
        """UPDATE idempotency_keys
            SET response_secret_redacted = true,
                response_body = (
                    SELECT jsonb_object_agg(
                        e.key,
                        CASE WHEN e.key IN ('key', 'secret', 'token', 'webapp_link', 'bot_link')
                                  AND e.value <> 'null'::jsonb
                             THEN to_jsonb('***'::text) ELSE e.value END
                    )
                    FROM jsonb_each(response_body) AS e
                )
            WHERE response_body IS NOT NULL
              AND jsonb_typeof(response_body) = 'object'
              AND (request_path IN ('POST /integration/api-keys',
                                    'POST /webhook-subscriptions',
                                    'POST /invitations',
                                    'POST /service-binding-invitations')
                   OR request_path LIKE 'POST /integration/api-keys/%/rotate'
                   OR request_path LIKE 'POST /webhook-subscriptions/%/rotate-secret')"""
    )

    op.execute(
        """CREATE TABLE used_init_data (
            digest      bytea PRIMARY KEY,
            expires_at  timestamptz NOT NULL
        )"""
    )
    op.execute("CREATE INDEX ix_used_init_data_expires_at ON used_init_data (expires_at)")

    op.execute("UPDATE invitations SET token_prefix = substr(encode(token_hash, 'hex'), 1, 8)")
    op.execute("UPDATE sessions SET token_prefix = substr(encode(token_hash, 'hex'), 1, 8)")


def downgrade() -> None:
    op.execute("DROP TABLE used_init_data")
    op.execute("ALTER TABLE idempotency_keys DROP COLUMN response_secret_redacted")
