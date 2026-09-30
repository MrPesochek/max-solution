"""seed directories — пример города с районами, категории холодильного сегмента"""

import json
import uuid
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_NAMESPACE = uuid.UUID("d0f1a1a0-0000-4000-8000-000000000001")


def _seed_id(key: str) -> uuid.UUID:
    return uuid.uuid5(_SEED_NAMESPACE, key)


CITY_ID = _seed_id("city:sample-city")

DISTRICTS = ["Центральный", "Северный", "Южный", "Восточный", "Западный"]

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
    ("commercial_display_fridge", "Холодильная витрина"),
    ("chest_freezer", "Морозильный ларь"),
    ("refrigerator_cabinet", "Холодильный шкаф"),
    ("split_system_cold_room", "Сплит-система холодильной камеры"),
    ("ice_maker", "Льдогенератор"),
]


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        text("INSERT INTO cities (id, name, region, timezone) VALUES (:id, :name, :region, :tz)"),
        {
            "id": CITY_ID,
            "name": "Новоград",
            "region": "Новоградская область",
            "tz": "Europe/Moscow",
        },
    )

    for district_name in DISTRICTS:
        bind.execute(
            text("INSERT INTO districts (id, city_id, name) VALUES (:id, :city_id, :name)"),
            {
                "id": _seed_id(f"district:sample-city:{district_name}"),
                "city_id": CITY_ID,
                "name": district_name,
            },
        )

    for code, name in CATEGORIES:
        bind.execute(
            text(
                "INSERT INTO equipment_categories (id, code, name, photo_template) "
                "VALUES (:id, :code, :name, cast(:photo_template as jsonb))"
            ),
            {
                "id": _seed_id(f"equipment_category:{code}"),
                "code": code,
                "name": name,
                "photo_template": json.dumps(PHOTO_TEMPLATE),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM equipment_categories WHERE code = ANY(:codes)"),
        {"codes": [code for code, _ in CATEGORIES]},
    )
    bind.execute(text("DELETE FROM districts WHERE city_id = :city_id"), {"city_id": CITY_ID})
    bind.execute(text("DELETE FROM cities WHERE id = :id"), {"id": CITY_ID})
