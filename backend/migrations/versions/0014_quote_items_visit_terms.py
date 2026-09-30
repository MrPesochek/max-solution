"""позиции сметы, условия выезда «от», должность представителя"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE repair_quotes ADD COLUMN items jsonb")
    op.execute(
        "ALTER TABLE repair_quotes ADD CONSTRAINT ck_repair_quotes_items "
        "CHECK (items IS NULL OR jsonb_typeof(items) = 'array')"
    )
    op.execute("ALTER TABLE provider_profiles ADD COLUMN visit_price_from_minor bigint")
    op.execute(
        "ALTER TABLE provider_profiles ADD CONSTRAINT ck_provider_profiles_visit_price_from "
        "CHECK (visit_price_from_minor IS NULL OR visit_price_from_minor >= 0)"
    )
    op.execute("ALTER TABLE organizations ADD COLUMN representative_position text")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN representative_position")
    op.execute(
        "ALTER TABLE provider_profiles DROP CONSTRAINT ck_provider_profiles_visit_price_from"
    )
    op.execute("ALTER TABLE provider_profiles DROP COLUMN visit_price_from_minor")
    op.execute("ALTER TABLE repair_quotes DROP CONSTRAINT ck_repair_quotes_items")
    op.execute("ALTER TABLE repair_quotes DROP COLUMN items")
