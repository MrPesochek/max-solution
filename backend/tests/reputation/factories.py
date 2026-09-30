import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.core.actor import IntegrationActor, UserActor
from app.db import session as db_session
from app.db.models import City, Organization
from tests.requests import factories as req_factories
from tests.requests.factories import World


@dataclass(slots=True)
class SharedProvider:
    organization_id: uuid.UUID
    category_id: uuid.UUID
    dispatcher: UserActor
    provider_admin: UserActor
    integration: IntegrationActor


async def build_shared_provider(*, category_index: int = 0) -> SharedProvider:
    async with db_session.transaction() as session:
        provider = await req_factories.create_org(session, name="Общий сервис", is_provider=True)
        await req_factories.create_provider_profile(session, provider, status="active")
        category_id = await req_factories.category_by_index(session, category_index)
        city_id = (await session.execute(select(City.id).limit(1))).scalar_one()
        await req_factories.create_provider_matching(
            session, provider, category_id=category_id, city_id=city_id
        )

        dispatcher_user = await req_factories.create_user(session, "Общий диспетчер")
        dispatcher_membership = await req_factories.create_membership(
            session, dispatcher_user, provider, "provider_dispatcher"
        )
        admin_user = await req_factories.create_user(session, "Общий администратор")
        admin_membership = await req_factories.create_membership(
            session, admin_user, provider, "provider_admin"
        )
        client = await req_factories.create_integration_client(session, provider)

        return SharedProvider(
            organization_id=provider.id,
            category_id=category_id,
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
                scopes=frozenset({"reviews:read", "reviews:write"}),
            ),
        )


async def add_customer_world(shared: SharedProvider, *, name: str, verified: bool = True) -> World:
    async with db_session.transaction() as session:
        customer = await req_factories.create_org(session, name=name, is_customer=True)
        location = await req_factories.create_location(session, customer, name=f"{name}: точка")
        equipment = await req_factories.create_equipment(
            session, customer, location, category_id=shared.category_id
        )
        manager_user = await req_factories.create_user(session, f"{name}: руководитель")
        manager_membership = await req_factories.create_membership(
            session, manager_user, customer, "customer_manager"
        )
        employee_user = await req_factories.create_user(session, f"{name}: сотрудник")
        employee_membership = await req_factories.create_membership(
            session,
            employee_user,
            customer,
            "customer_employee",
            location_ids=(location.id,),
        )
        provider_org = await session.get(Organization, shared.organization_id)
        assert provider_org is not None
        binding = await req_factories.create_binding(
            session, equipment, customer, provider_org, manager_membership, status="confirmed"
        )
        if verified:
            customer.representative_verification_status = "verified"
        await session.flush()

        manager = UserActor(
            user_id=manager_user.id,
            membership_id=manager_membership.id,
            organization_id=customer.id,
            role="customer_manager",
        )
        employee = UserActor(
            user_id=employee_user.id,
            membership_id=employee_membership.id,
            organization_id=customer.id,
            role="customer_employee",
            location_ids=frozenset({location.id}),
        )
        return World(
            customer_org_id=customer.id,
            provider_org_id=shared.organization_id,
            location_id=location.id,
            other_location_id=location.id,
            equipment_id=equipment.id,
            other_equipment_id=equipment.id,
            binding_id=binding.id,
            category_id=shared.category_id,
            city_id=location.city_id,
            district_id=location.district_id,
            manager=manager,
            employee=employee,
            other_employee=manager,
            dispatcher=shared.dispatcher,
            provider_admin=shared.provider_admin,
            integration=shared.integration,
        )


async def verify_customer(world: World) -> None:
    async with db_session.transaction() as session:
        org = await session.get(Organization, world.customer_org_id)
        assert org is not None
        org.representative_verification_status = "verified"
        await session.flush()
