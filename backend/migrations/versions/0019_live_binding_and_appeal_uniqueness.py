"""уникальность живой привязки и открытого обжалования, напоминание по отмене"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """WITH ranked AS (
               SELECT id,
                      row_number() OVER (
                          PARTITION BY equipment_id, provider_org_id
                          ORDER BY (status = 'confirmed') DESC, created_at, id
                      ) AS position
               FROM service_bindings
               WHERE provider_org_id IS NOT NULL
                 AND status IN ('pending', 'confirmed')
           )
           UPDATE service_bindings AS b
           SET status = 'revoked', updated_at = now()
           FROM ranked
           WHERE b.id = ranked.id AND ranked.position > 1"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ux_service_bindings_live_equipment_provider
           ON service_bindings (equipment_id, provider_org_id)
           WHERE status IN ('pending', 'confirmed')"""
    )

    op.execute(
        """WITH ranked AS (
               SELECT id,
                      row_number() OVER (
                          PARTITION BY review_id, filer_org_id ORDER BY created_at, id
                      ) AS position
               FROM moderation_cases
               WHERE subject_type = 'review'
                 AND status = 'pending'
                 AND evidence ->> 'kind' = 'appeal'
           )
           UPDATE moderation_cases AS c
           SET status = 'withdrawn', appeal_status = 'resolved',
               appeal_resolved_at = now(), updated_at = now()
           FROM ranked
           WHERE c.id = ranked.id AND ranked.position > 1"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ux_moderation_cases_open_review_appeal
           ON moderation_cases (review_id, filer_org_id)
           WHERE subject_type = 'review'
             AND status = 'pending'
             AND evidence ->> 'kind' = 'appeal'"""
    )

    op.execute("ALTER TABLE cancellation_requests ADD COLUMN reminded_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE cancellation_requests DROP COLUMN IF EXISTS reminded_at")
    op.execute("DROP INDEX IF EXISTS ux_moderation_cases_open_review_appeal")
    op.execute("DROP INDEX IF EXISTS ux_service_bindings_live_equipment_provider")
