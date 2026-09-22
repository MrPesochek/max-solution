"""Понятные названия техники в общем справочнике."""

from alembic import op
from sqlalchemy import text

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

NAMES = {
    "refrigerator_cabinet": ("Холодильный шкаф", "Холодильник"),
    "bar_fridge": ("Барный холодильник", "Холодильник для напитков"),
    "refrigeration_unit": ("Холодильный агрегат", "Холодильный блок"),
}


def _rename(index: int) -> None:
    for code, names in NAMES.items():
        op.get_bind().execute(
            text("UPDATE equipment_categories SET name = :name WHERE code = :code"),
            {"name": names[index], "code": code},
        )


def upgrade() -> None:
    _rename(1)


def downgrade() -> None:
    _rename(0)
