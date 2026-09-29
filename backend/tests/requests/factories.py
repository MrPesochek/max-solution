import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import IntegrationActor, UserActor
from app.db import session as db_session
from app.db.models import (
    City,
    District,
    Equipment,
    EquipmentCategory,
    IntegrationClient,
    Location,
    Membership,
    MembershipLocation,
    Organization,
    ProviderBrandRestriction,
    ProviderCategory,
    ProviderProfile,
    ProviderServiceArea,
    ServiceBinding,
    User,
)


async def create_user(session: AsyncSession, name: str = "Пользователь") -> User:
    user = User(max_user_id=uuid.uuid4().hex, display_name=name, bot_available=True)
    session.add(user)
    await session.flush()
    return user


async def create_org(
    session: AsyncSession,
    *,
    name: str = "Организация",
    is_customer: bool = False,
    is_provider: bool = False,
) -> Organization:
    org = Organization(
        legal_name=f"ООО «{name}»",
        display_name=name,
        is_customer=is_customer,
        is_provider=is_provider,
    )
    session.add(org)
    await session.flush()
    return org


async def create_membership(
    session: AsyncSession,
    user: User,
    org: Organization,
    role: str,
    *,
    location_ids: tuple[uuid.UUID, ...] = (),
) -> Membership:
    membership = Membership(user_id=user.id, organization_id=org.id, role=role, status="active")
    session.add(membership)
    await session.flush()
    for location_id in location_ids:
        session.add(MembershipLocation(membership_id=membership.id, location_id=location_id))
    await session.flush()
    return membership


async def create_location(
    session: AsyncSession,
    org: Organization,
    *,
    name: str = "Точка",
    district_id: uuid.UUID | None = None,
) -> Location:
    city_id = (await session.execute(select(City.id).limit(1))).scalar_one()
    if district_id is None:
        district_id = (
            await session.execute(select(District.id).where(District.city_id == city_id).limit(1))
        ).scalar_one()
    location = Location(
        customer_org_id=org.id,
        name=name,
        city_id=city_id,
        district_id=district_id,
        address="ул. Примерная, 1",
        contact_name="Дежурный",
        contact_phone="+70000000000",
    )
    session.add(location)
    await session.flush()
    return location


async def create_equipment(
    session: AsyncSession,
    org: Organization,
    location: Location,
    *,
    brand: str = "Полюс",
    category_id: uuid.UUID | None = None,
) -> Equipment:
    if category_id is None:
        category_id = await category_by_index(session, 0)
    equipment = Equipment(
        customer_org_id=org.id,
        location_id=location.id,
        equipment_category_id=category_id,
        brand=brand,
        model="ВХС-1",
        serial_number="SN-0001",
    )
    session.add(equipment)
    await session.flush()
    return equipment


async def category_by_index(session: AsyncSession, index: int) -> uuid.UUID:
    rows = list(
        (
            await session.execute(select(EquipmentCategory.id).order_by(EquipmentCategory.code))
        ).scalars()
    )
    return rows[index]


async def create_provider_matching(
    session: AsyncSession,
    provider_org: Organization,
    *,
    category_id: uuid.UUID,
    city_id: uuid.UUID,
    district_id: uuid.UUID | None = None,
    brands: tuple[str, ...] = (),
) -> None:
    """Специализация, территория и (необязательно) ограничение по брендам."""
    session.add(
        ProviderCategory(provider_org_id=provider_org.id, equipment_category_id=category_id)
    )
    session.add(
        ProviderServiceArea(
            provider_org_id=provider_org.id, city_id=city_id, district_id=district_id
        )
    )
    for brand in brands:
        session.add(
            ProviderBrandRestriction(
                provider_org_id=provider_org.id,
                equipment_category_id=category_id,
                brand=brand,
            )
        )
    await session.flush()


async def create_provider_profile(
    session: AsyncSession, org: Organization, *, status: str = "active"
) -> ProviderProfile:
    profile = ProviderProfile(organization_id=org.id, provider_kind="company", status=status)
    session.add(profile)
    await session.flush()
    return profile


async def create_binding(
    session: AsyncSession,
    equipment: Equipment,
    customer_org: Organization,
    provider_org: Organization,
    created_by: Membership,
    *,
    status: str = "confirmed",
) -> ServiceBinding:
    binding = ServiceBinding(
        equipment_id=equipment.id,
        customer_org_id=customer_org.id,
        provider_org_id=provider_org.id,
        basis="service_contract",
        status=status,
        created_by_membership_id=created_by.id,
    )
    session.add(binding)
    await session.flush()
    return binding


async def create_integration_client(
    session: AsyncSession, org: Organization, *, scopes: tuple[str, ...] = ()
) -> IntegrationClient:
    client = IntegrationClient(
        provider_org_id=org.id,
        name="CRM",
        api_key_hash=uuid.uuid4().bytes,
        api_key_prefix=uuid.uuid4().hex[:8],
        scopes=list(scopes or ("requests:read", "requests:write")),
        status="active",
    )
    session.add(client)
    await session.flush()
    return client


@dataclass(slots=True)
class World:
    """Заказчик с точкой, оборудованием и подтверждённой привязкой к исполнителю."""

    customer_org_id: uuid.UUID
    provider_org_id: uuid.UUID
    location_id: uuid.UUID
    other_location_id: uuid.UUID
    equipment_id: uuid.UUID
    other_equipment_id: uuid.UUID
    binding_id: uuid.UUID | None
    category_id: uuid.UUID
    city_id: uuid.UUID
    district_id: uuid.UUID | None
    manager: UserActor
    employee: UserActor
    other_employee: UserActor
    dispatcher: UserActor
    provider_admin: UserActor
    integration: IntegrationActor
    extra: dict[str, uuid.UUID] = field(default_factory=dict)


async def build_world(
    *,
    binding_status: str | None = "confirmed",
    provider_status: str = "active",
    category_index: int = 0,
    provider_matches: bool = True,
    provider_brands: tuple[str, ...] = (),
) -> World:
    async with db_session.transaction() as session:
        customer = await create_org(session, name="Сеть кафе", is_customer=True)
        provider = await create_org(session, name="Холод-Сервис", is_provider=True)
        await create_provider_profile(session, provider, status=provider_status)

        category_id = await category_by_index(session, category_index)
        location = await create_location(session, customer, name="Кафе на Ленина")
        other_location = await create_location(session, customer, name="Кафе на Мира")
        equipment = await create_equipment(session, customer, location, category_id=category_id)
        other_equipment = await create_equipment(
            session, customer, other_location, category_id=category_id
        )
        if provider_matches:
            await create_provider_matching(
                session,
                provider,
                category_id=category_id,
                city_id=location.city_id,
                brands=provider_brands,
            )

        manager_user = await create_user(session, "Руководитель")
        manager_membership = await create_membership(
            session, manager_user, customer, "customer_manager"
        )
        employee_user = await create_user(session, "Сотрудник")
        employee_membership = await create_membership(
            session, employee_user, customer, "customer_employee", location_ids=(location.id,)
        )
        other_employee_user = await create_user(session, "Сотрудник другой точки")
        other_employee_membership = await create_membership(
            session,
            other_employee_user,
            customer,
            "customer_employee",
            location_ids=(other_location.id,),
        )

        dispatcher_user = await create_user(session, "Диспетчер")
        dispatcher_membership = await create_membership(
            session, dispatcher_user, provider, "provider_dispatcher"
        )
        admin_user = await create_user(session, "Администратор исполнителя")
        admin_membership = await create_membership(session, admin_user, provider, "provider_admin")
        client = await create_integration_client(session, provider)

        binding_id: uuid.UUID | None = None
        if binding_status is not None:
            binding = await create_binding(
                session,
                equipment,
                customer,
                provider,
                manager_membership,
                status=binding_status,
            )
            binding_id = binding.id

        return World(
            customer_org_id=customer.id,
            provider_org_id=provider.id,
            location_id=location.id,
            other_location_id=other_location.id,
            equipment_id=equipment.id,
            other_equipment_id=other_equipment.id,
            binding_id=binding_id,
            category_id=category_id,
            city_id=location.city_id,
            district_id=location.district_id,
            manager=UserActor(
                user_id=manager_user.id,
                membership_id=manager_membership.id,
                organization_id=customer.id,
                role="customer_manager",
            ),
            employee=UserActor(
                user_id=employee_user.id,
                membership_id=employee_membership.id,
                organization_id=customer.id,
                role="customer_employee",
                location_ids=frozenset({location.id}),
            ),
            other_employee=UserActor(
                user_id=other_employee_user.id,
                membership_id=other_employee_membership.id,
                organization_id=customer.id,
                role="customer_employee",
                location_ids=frozenset({other_location.id}),
            ),
            dispatcher=UserActor(
                user_id=dispatcher_user.id,
                membership_id=dispatcher_membership.id,
                organization_id=provider.id,
                role="provider_dispatcher",
            ),
            provider_admin=UserActor(
                user_id=admin_user.id,
                membership_id=admin_membership.id,
                organization_id=provider.id,
                role="provider_admin",
            ),
            integration=IntegrationActor(
                integration_client_id=client.id,
                organization_id=provider.id,
                scopes=frozenset({"requests:read", "requests:write"}),
            ),
        )


async def build_foreign_world() -> World:
    """Вторая пара «заказчик — исполнитель»: другая категория, подбор их не сводит."""
    return await build_world(category_index=1)


async def build_rival_provider(world: World) -> World:
    """Второй исполнитель с тем же профилем подбора, что и основной."""
    async with db_session.transaction() as session:
        provider = await create_org(session, name="Сервис-Плюс", is_provider=True)
        await create_provider_profile(session, provider)
        await create_provider_matching(
            session,
            provider,
            category_id=world.category_id,
            city_id=world.city_id,
        )
        dispatcher_user = await create_user(session, "Диспетчер конкурента")
        dispatcher_membership = await create_membership(
            session, dispatcher_user, provider, "provider_dispatcher"
        )
        client = await create_integration_client(
            session, provider, scopes=("marketplace:read", "marketplace:write")
        )
        rival = replace_provider(world, provider.id)
        rival.dispatcher = UserActor(
            user_id=dispatcher_user.id,
            membership_id=dispatcher_membership.id,
            organization_id=provider.id,
            role="provider_dispatcher",
        )
        rival.provider_admin = rival.dispatcher
        rival.integration = IntegrationActor(
            integration_client_id=client.id,
            organization_id=provider.id,
            scopes=frozenset({"marketplace:read", "marketplace:write"}),
        )
        return rival


def replace_provider(world: World, provider_org_id: uuid.UUID) -> World:
    return World(
        customer_org_id=world.customer_org_id,
        provider_org_id=provider_org_id,
        location_id=world.location_id,
        other_location_id=world.other_location_id,
        equipment_id=world.equipment_id,
        other_equipment_id=world.other_equipment_id,
        binding_id=world.binding_id,
        category_id=world.category_id,
        city_id=world.city_id,
        district_id=world.district_id,
        manager=world.manager,
        employee=world.employee,
        other_employee=world.other_employee,
        dispatcher=world.dispatcher,
        provider_admin=world.provider_admin,
        integration=world.integration,
    )
