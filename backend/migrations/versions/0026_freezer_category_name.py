"""Название категории: морозильная камера."""

from alembic import op
from sqlalchemy import text

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        text("UPDATE equipment_categories SET name = :name WHERE code = :code"),
        {"name": "Морозильная камера", "code": "split_system_cold_room"},
    )


def downgrade() -> None:
    op.get_bind().execute(
        text("UPDATE equipment_categories SET name = :name WHERE code = :code"),
        {"name": "Сплит-система холодильной камеры", "code": "split_system_cold_room"},
    )
