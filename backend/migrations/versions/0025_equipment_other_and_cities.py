"""Другой тип техники и города для выбора территории.

Revision ID: 0025
Revises: 0024
"""

import json
import uuid

from alembic import op
from sqlalchemy import text

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

NAMESPACE = uuid.UUID("d0f1a1a0-0000-4000-8000-000000000001")
CITIES = {
    "kazan": (
        "Казань",
        "Республика Татарстан",
        [
            "Авиастроительный",
            "Вахитовский",
            "Кировский",
            "Московский",
            "Ново-Савиновский",
            "Приволжский",
            "Советский",
        ],
    ),
    "saint-petersburg": (
        "Санкт-Петербург",
        "Санкт-Петербург",
        [
            "Адмиралтейский",
            "Василеостровский",
            "Выборгский",
            "Калининский",
            "Кировский",
            "Колпинский",
            "Красногвардейский",
            "Красносельский",
            "Кронштадтский",
            "Курортный",
            "Московский",
            "Невский",
            "Петроградский",
            "Петродворцовый",
            "Приморский",
            "Пушкинский",
            "Фрунзенский",
            "Центральный",
        ],
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("""
        INSERT INTO equipment_categories (id, code, name, photo_template)
        VALUES (:id, 'other', 'Техника другого типа', CAST(:template AS jsonb))
        ON CONFLICT (code) DO NOTHING
    """),
        {
            "id": uuid.uuid5(NAMESPACE, "equipment_category:other"),
            "template": json.dumps(
                [
                    {
                        "code": "overview",
                        "label": "Общий вид",
                        "required": True,
                        "visibility_class": "request_private",
                    },
                    {
                        "code": "nameplate",
                        "label": "Шильдик",
                        "required": False,
                        "visibility_class": "request_sensitive",
                    },
                    {
                        "code": "display_error",
                        "label": "Экран / код ошибки",
                        "required": False,
                        "visibility_class": "request_private",
                    },
                ]
            ),
        },
    )
    for code, (name, region, districts) in CITIES.items():
        city_id = uuid.uuid5(NAMESPACE, f"city:{code}")
        bind.execute(
            text("""
            INSERT INTO cities (id, name, region, timezone)
            VALUES (:id, :name, :region, 'Europe/Moscow') ON CONFLICT (id) DO NOTHING
        """),
            {"id": city_id, "name": name, "region": region},
        )
        for district in districts:
            bind.execute(
                text("""
                INSERT INTO districts (id, city_id, name) VALUES (:id, :city, :name)
                ON CONFLICT (city_id, name) DO NOTHING
            """),
                {
                    "id": uuid.uuid5(NAMESPACE, f"district:{code}:{district}"),
                    "city": city_id,
                    "name": district,
                },
            )


def downgrade() -> None:
    pass
