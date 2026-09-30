"""переписка общего канала привязана к назначению"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN assignment_id uuid REFERENCES assignments (id)")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT ck_messages_thread_assignment "
        "CHECK (thread_provider_org_id IS NULL OR assignment_id IS NULL)"
    )
    op.execute("CREATE INDEX ix_messages_assignment_id ON messages (assignment_id)")

    op.execute(
        """WITH picked AS (
            SELECT m.id AS message_id,
                   (
                       SELECT a.id
                       FROM assignments a
                       WHERE a.request_id = m.request_id
                         AND a.created_at <= m.created_at
                         AND (
                             m.author_kind NOT IN ('provider_membership', 'integration_client')
                             OR a.provider_org_id = COALESCE(
                                 (SELECT ms.organization_id FROM memberships ms
                                  WHERE ms.id = m.author_membership_id),
                                 (SELECT ic.provider_org_id FROM integration_clients ic
                                  WHERE ic.id = m.author_integration_client_id)
                             )
                         )
                       ORDER BY a.created_at DESC, a.id DESC
                       LIMIT 1
                   ) AS assignment_id
            FROM messages m
            WHERE m.thread_provider_org_id IS NULL
        )
        UPDATE messages
        SET assignment_id = a.id
        FROM picked p
        JOIN assignments a ON a.id = p.assignment_id
        WHERE messages.id = p.message_id
          AND (
              a.state IN ('pending', 'accepted', 'completed')
              OR a.updated_at >= messages.created_at
          )"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN assignment_id")
