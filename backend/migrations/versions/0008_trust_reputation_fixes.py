"""привязки и отзывы: перечень оборудования в приглашении, лимиты запросов и жалоб"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE service_bindings ADD COLUMN invitation_item_index integer")
    op.execute(
        """ALTER TABLE service_bindings ADD CONSTRAINT ck_service_bindings_invitation_item
           CHECK (invitation_item_index IS NULL
                  OR (invitation_item_index >= 0 AND source_invitation_id IS NOT NULL))"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ux_service_bindings_invitation_item
           ON service_bindings (source_invitation_id, invitation_item_index)
           WHERE invitation_item_index IS NOT NULL"""
    )

    op.execute(
        """UPDATE invitations
           SET binding_details = binding_details || jsonb_build_object(
               'equipment_items',
               COALESCE(
                   (SELECT jsonb_agg(jsonb_build_object(
                               'description', d, 'serial_number', NULL, 'model', NULL))
                    FROM jsonb_array_elements_text(
                        COALESCE(binding_details -> 'equipment_descriptions', '[]'::jsonb)) AS d),
                   '[]'::jsonb))
           WHERE kind = 'service_binding'
             AND binding_details IS NOT NULL
             AND NOT binding_details ? 'equipment_items'"""
    )
    op.execute(
        """UPDATE invitations
           SET status = 'revoked', revoked_at = now()
           WHERE kind = 'service_binding'
             AND status = 'pending'
             AND jsonb_array_length(COALESCE(binding_details -> 'equipment_items', '[]'::jsonb))
                 = 0"""
    )

    op.execute(
        """CREATE INDEX ix_audit_entries_binding_request
           ON audit_entries ((details ->> 'provider_org_id'), occurred_at)
           WHERE action = 'service_binding.request'"""
    )
    op.execute(
        """CREATE INDEX ix_audit_entries_complaint
           ON audit_entries (actor_user_id, occurred_at)
           WHERE action = 'complaint.create'"""
    )
    op.execute(
        """CREATE INDEX ix_verification_cases_expires_at
           ON verification_cases (expires_at)
           WHERE decision = 'approved' AND expires_at IS NOT NULL"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_verification_cases_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_audit_entries_complaint")
    op.execute("DROP INDEX IF EXISTS ix_audit_entries_binding_request")
    op.execute(
        """UPDATE invitations SET binding_details = binding_details - 'equipment_items'
           WHERE kind = 'service_binding' AND binding_details IS NOT NULL"""
    )
    op.execute("DROP INDEX IF EXISTS ux_service_bindings_invitation_item")
    op.execute(
        "ALTER TABLE service_bindings DROP CONSTRAINT IF EXISTS ck_service_bindings_invitation_item"
    )
    op.execute("ALTER TABLE service_bindings DROP COLUMN IF EXISTS invitation_item_index")
