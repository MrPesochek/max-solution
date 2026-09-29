import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    City,
    Equipment,
    EquipmentCategory,
    Location,
    Membership,
    Organization,
    User,
)


async def seed_city_id(session: AsyncSession) -> uuid.UUID:
    return (await session.execute(select(City.id).limit(1))).scalar_one()


async def seed_equipment_category_id(session: AsyncSession) -> uuid.UUID:
    return (await session.execute(select(EquipmentCategory.id).limit(1))).scalar_one()


async def make_provider_org(
    session: AsyncSession, inn_normalized: str | None = None
) -> Organization:
    org = Organization(
        is_customer=False,
        is_provider=True,
        legal_name=f"ИП Исполнителев {uuid.uuid4().hex[:6]}",
        display_name="Мастер",
        inn_normalized=inn_normalized,
        details_verification_status="unverified",
        representative_verification_status="unverified",
    )
    session.add(org)
    await session.flush()
    return org


async def make_customer_chain(
    session: AsyncSession,
) -> tuple[Organization, Location, Equipment, Membership]:
    city_id = await seed_city_id(session)
    category_id = await seed_equipment_category_id(session)

    customer_org = Organization(
        is_customer=True,
        is_provider=False,
        legal_name=f"ООО Ромашка {uuid.uuid4().hex[:6]}",
        display_name="Ромашка",
        details_verification_status="unverified",
        representative_verification_status="unverified",
    )
    session.add(customer_org)
    await session.flush()

    location = Location(
        customer_org_id=customer_org.id,
        name="Точка 1",
        city_id=city_id,
        address="ул. Примерная, 1",
        timezone="Europe/Moscow",
    )
    session.add(location)
    await session.flush()

    equipment = Equipment(
        customer_org_id=customer_org.id,
        location_id=location.id,
        equipment_category_id=category_id,
    )
    session.add(equipment)

    user = User(
        max_user_id=f"max-{uuid.uuid4().hex[:12]}", display_name="Сотрудник", bot_available=False
    )
    session.add(user)
    await session.flush()

    membership = Membership(
        user_id=user.id,
        organization_id=customer_org.id,
        role="customer_employee",
        status="active",
    )
    session.add(membership)
    await session.flush()

    return customer_org, location, equipment, membership
