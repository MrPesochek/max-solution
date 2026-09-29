from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories as bot_factories
from tests.requests import factories as req_factories


@dataclass(slots=True)
class BotWorld:
    customer_org_id: uuid.UUID
    provider_org_id: uuid.UUID
    location_id: uuid.UUID
    equipment_id: uuid.UUID
    other_equipment_id: uuid.UUID
    manager_max_id: str
    employee_max_id: str
    dispatcher_max_id: str


MANAGER_ID = 91001
EMPLOYEE_ID = 91002
DISPATCHER_ID = 91003


async def build(
    session: AsyncSession,
    *,
    with_binding: bool = True,
    manager_max_id: int = MANAGER_ID,
    employee_max_id: int = EMPLOYEE_ID,
    dispatcher_max_id: int = DISPATCHER_ID,
    location_timezone: str | None = None,
) -> BotWorld:
    customer = await req_factories.create_org(session, name="Сеть кафе", is_customer=True)
    provider = await req_factories.create_org(session, name="Холод-Сервис", is_provider=True)
    await req_factories.create_provider_profile(session, provider, status="active")

    category_id = await req_factories.category_by_index(session, 0)
    location = await req_factories.create_location(session, customer, name="Кафе на Ленина")
    if location_timezone:
        location.timezone = location_timezone
        await session.flush()
    equipment = await req_factories.create_equipment(
        session, customer, location, category_id=category_id
    )
    other_equipment = await req_factories.create_equipment(
        session, customer, location, category_id=category_id, brand="Другой"
    )
    await req_factories.create_provider_matching(
        session, provider, category_id=category_id, city_id=location.city_id
    )

    manager_user = await bot_factories.create_user(
        session, max_user_id=str(manager_max_id), display_name="Руководитель"
    )
    manager_membership = await bot_factories.create_membership(
        session, manager_user, customer, role="customer_manager"
    )
    employee_user = await bot_factories.create_user(
        session, max_user_id=str(employee_max_id), display_name="Сотрудник"
    )
    await bot_factories.create_membership(
        session, employee_user, customer, role="customer_employee", locations=(location,)
    )
    dispatcher_user = await bot_factories.create_user(
        session, max_user_id=str(dispatcher_max_id), display_name="Диспетчер"
    )
    await bot_factories.create_membership(
        session, dispatcher_user, provider, role="provider_dispatcher"
    )

    if with_binding:
        await req_factories.create_binding(
            session, equipment, customer, provider, manager_membership, status="confirmed"
        )

    return BotWorld(
        customer_org_id=customer.id,
        provider_org_id=provider.id,
        location_id=location.id,
        equipment_id=equipment.id,
        other_equipment_id=other_equipment.id,
        manager_max_id=str(manager_max_id),
        employee_max_id=str(employee_max_id),
        dispatcher_max_id=str(dispatcher_max_id),
    )


def png_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


def image_attachment(url: str) -> dict[str, object]:
    return {"type": "image", "payload": {"photo_id": 1, "token": "tok", "url": url}}
