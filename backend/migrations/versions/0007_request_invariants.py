"""заявки: одна открытая отмена, одно ожидающее предложение выезда и смета на назначение, один активный отклик исполнителя

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """UPDATE visit_proposals p SET status = 'superseded'
           WHERE p.status = 'pending' AND EXISTS (
               SELECT 1 FROM visit_proposals n
               WHERE n.assignment_id = p.assignment_id AND n.status = 'pending'
                 AND n.version > p.version)"""
    )
    op.execute(
        """UPDATE repair_quotes q SET status = 'superseded'
           WHERE q.status = 'pending' AND EXISTS (
               SELECT 1 FROM repair_quotes n
               WHERE n.assignment_id = q.assignment_id AND n.status = 'pending'
                 AND n.version > q.version)"""
    )
    op.execute(
        """UPDATE offers o SET state = 'closed'
           WHERE o.state = 'active' AND EXISTS (
               SELECT 1 FROM offers n
               WHERE n.request_id = o.request_id AND n.provider_org_id = o.provider_org_id
                 AND n.state = 'active' AND n.version > o.version)"""
    )
    op.execute(
        """UPDATE cancellation_requests c
           SET status = 'withdrawn', resolution_kind = 'manual', resolved_at = now()
           WHERE c.status IN ('pending', 'disputed') AND EXISTS (
               SELECT 1 FROM cancellation_requests n
               WHERE n.request_id = c.request_id AND n.status IN ('pending', 'disputed')
                 AND n.id > c.id)"""
    )

    op.execute(
        """CREATE UNIQUE INDEX ux_cancellation_requests_one_open
           ON cancellation_requests (request_id) WHERE status IN ('pending', 'disputed')"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ux_visit_proposals_one_pending
           ON visit_proposals (assignment_id) WHERE status = 'pending'"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ux_repair_quotes_one_pending
           ON repair_quotes (assignment_id) WHERE status = 'pending'"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ux_offers_one_active
           ON offers (request_id, provider_org_id) WHERE state = 'active'"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_offers_one_active")
    op.execute("DROP INDEX IF EXISTS ux_repair_quotes_one_pending")
    op.execute("DROP INDEX IF EXISTS ux_visit_proposals_one_pending")
    op.execute("DROP INDEX IF EXISTS ux_cancellation_requests_one_open")
