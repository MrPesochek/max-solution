"""аренда доставок, состояния blocked/skipped, last_used_at ключа, публикуемые фото карточки

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = [
    "ALTER TABLE integration_clients ADD COLUMN last_used_at timestamptz",
    "ALTER TABLE webhook_deliveries ADD COLUMN lease_until timestamptz",
    """CREATE UNIQUE INDEX ux_webhook_deliveries_event_subscription
       ON webhook_deliveries (integration_event_id, webhook_subscription_id)""",
    "ALTER TABLE webhook_deliveries DROP CONSTRAINT ck_webhook_deliveries_state",
    """ALTER TABLE webhook_deliveries ADD CONSTRAINT ck_webhook_deliveries_state
       CHECK (state IN ('queued', 'delivered', 'retrying', 'failed', 'blocked'))""",
    "ALTER TABLE notifications ADD COLUMN lease_until timestamptz",
    "ALTER TABLE notifications DROP CONSTRAINT ck_notifications_state",
    """ALTER TABLE notifications ADD CONSTRAINT ck_notifications_state
       CHECK (state IN ('queued', 'sent', 'failed', 'skipped'))""",
    """ALTER TABLE request_public_cards
       ADD COLUMN published_attachment_ids uuid[] NOT NULL DEFAULT '{}'::uuid[]""",
    "ALTER TABLE verification_cases ADD COLUMN is_demo boolean NOT NULL DEFAULT false",
    "ALTER TABLE service_bindings ADD COLUMN claimed_contract_number text",
    "ALTER TABLE service_bindings ADD COLUMN status_reason text",
    "ALTER TABLE invitations ADD COLUMN binding_details jsonb",
]

DOWNGRADE = [
    "ALTER TABLE invitations DROP COLUMN binding_details",
    "ALTER TABLE service_bindings DROP COLUMN status_reason",
    "ALTER TABLE service_bindings DROP COLUMN claimed_contract_number",
    "ALTER TABLE verification_cases DROP COLUMN is_demo",
    "ALTER TABLE request_public_cards DROP COLUMN published_attachment_ids",
    "UPDATE notifications SET state = 'failed' WHERE state = 'skipped'",
    "ALTER TABLE notifications DROP CONSTRAINT ck_notifications_state",
    """ALTER TABLE notifications ADD CONSTRAINT ck_notifications_state
       CHECK (state IN ('queued', 'sent', 'failed'))""",
    "ALTER TABLE notifications DROP COLUMN lease_until",
    "UPDATE webhook_deliveries SET state = 'failed' WHERE state = 'blocked'",
    "ALTER TABLE webhook_deliveries DROP CONSTRAINT ck_webhook_deliveries_state",
    """ALTER TABLE webhook_deliveries ADD CONSTRAINT ck_webhook_deliveries_state
       CHECK (state IN ('queued', 'delivered', 'retrying', 'failed'))""",
    "DROP INDEX ux_webhook_deliveries_event_subscription",
    "ALTER TABLE webhook_deliveries DROP COLUMN lease_until",
    "ALTER TABLE integration_clients DROP COLUMN last_used_at",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
