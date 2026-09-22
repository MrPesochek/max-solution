"""категории оборудования под итоговый макет

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-29

"""

import json
import uuid
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_NAMESPACE = uuid.UUID("d0f1a1a0-0000-4000-8000-000000000001")

PHOTO_TEMPLATE = [
    {
        "code": "overview",
        "label": "Общий вид",
        "required": True,
        "visibility_class": "request_private",
    },
    {
        "code": "nameplate",
        "label": "Шильдик",
        "required": True,
        "visibility_class": "request_sensitive",
    },
    {
        "code": "display_error",
        "label": "Экран / код ошибки",
        "required": False,
        "visibility_class": "request_private",
    },
]

CATEGORIES = [
    ("bar_fridge", "Барный холодильник"),
    ("refrigeration_unit", "Холодильный агрегат"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for code, name in CATEGORIES:
        bind.execute(
            text(
                "INSERT INTO equipment_categories (id, code, name, photo_template) "
                "VALUES (:id, :code, :name, cast(:photo_template as jsonb)) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "id": uuid.uuid5(_SEED_NAMESPACE, f"equipment_category:{code}"),
                "code": code,
                "name": name,
                "photo_template": json.dumps(PHOTO_TEMPLATE),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, _ in CATEGORIES]
    category_ids = "(SELECT id FROM equipment_categories WHERE code = ANY(:codes))"
    for table in ("equipment", "request_public_cards", "warranty_authorizations"):
        used = bind.execute(
            text(f"SELECT count(*) FROM {table} WHERE equipment_category_id IN {category_ids}"),  # noqa: S608
            {"codes": codes},
        ).scalar_one()
        if used:
            raise RuntimeError(
                f"downgrade 0018: категории используются в {table}, смените категорию "
                "или удалите записи"
            )
    for table in ("provider_brand_restrictions", "provider_categories"):
        bind.execute(
            text(f"DELETE FROM {table} WHERE equipment_category_id IN {category_ids}"),  # noqa: S608
            {"codes": codes},
        )
    bind.execute(
        text("DELETE FROM equipment_categories WHERE code = ANY(:codes)"), {"codes": codes}
    )
