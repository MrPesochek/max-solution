import uuid
from dataclasses import dataclass

from app.core import ids
from app.core.actor import OperatorActor, UserActor
from app.core.pipeline import Idempotency, hash_body
from app.db import session as db_session
from app.db.models import Equipment, Membership, Organization, User
from tests import factories

CUSTOMER_INN = "7707083893"
PROVIDER_INN = "7736050003"
OTHER_INN = "7710137066"


def idem(key: str) -> Idempotency:
    return Idempotency(key=key, operation=key, body_hash=hash_body({"k": key}))


def actor_of(membership: Membership) -> UserActor:
    return UserActor(
        user_id=membership.user_id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


@dataclass(slots=True)
class ProviderFixture:
    organization_id: uuid.UUID
    admin: UserActor
    dispatcher: UserActor
    profile_id: uuid.UUID


@dataclass(slots=True)
class CustomerFixture:
    organization_id: uuid.UUID
    manager: UserActor
    employee: UserActor
    equipment_id: uuid.UUID
    location_id: uuid.UUID


async def make_provider(
    key: str,
    *,
    name: str = "ООО Сервис",
    status: str = "draft",
    accepting: bool = False,
    inn: str | None = PROVIDER_INN,
    with_category: bool = True,
    with_area: bool = True,
    verified: bool = False,
) -> ProviderFixture:
    async with db_session.transaction() as s:
        org = await factories.create_organization(
            s, name=name, customer=False, provider=True, inn=inn
        )
        org.contact_phone = "+70000000000"
        profile = await factories.create_provider_profile(
            s, org, status=status, accepting=accepting
        )
        if with_category:
            await factories.add_provider_category(s, org, await factories.seed_category(s))
        if with_area:
            await factories.add_provider_service_area(s, org, await factories.seed_city(s))
        if verified:
            await factories.verify_organization(s, org)
        admin = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id=f"{key}-admin"),
            org,
            role="provider_admin",
        )
        dispatcher = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id=f"{key}-disp"),
            org,
            role="provider_dispatcher",
        )
        return ProviderFixture(
            organization_id=org.id,
            admin=actor_of(admin),
            dispatcher=actor_of(dispatcher),
            profile_id=profile.id,
        )


async def make_customer(
    key: str,
    *,
    name: str = "ООО Заказчик",
    inn: str | None = CUSTOMER_INN,
    verified: bool = False,
    brand: str | None = "Бренд",
) -> CustomerFixture:
    async with db_session.transaction() as s:
        org = await factories.create_organization(s, name=name, inn=inn)
        location = await factories.create_location(s, org)
        equipment = await factories.create_equipment(s, org, location, brand=brand)
        if verified:
            await factories.verify_organization(s, org)
        manager = await factories.create_membership(
            s, await factories.create_user(s, max_user_id=f"{key}-mgr"), org
        )
        employee = await factories.create_membership(
            s,
            await factories.create_user(s, max_user_id=f"{key}-emp"),
            org,
            role="customer_employee",
            locations=[location],
        )
        return CustomerFixture(
            organization_id=org.id,
            manager=actor_of(manager),
            employee=actor_of(employee),
            equipment_id=equipment.id,
            location_id=location.id,
        )


async def make_operator(key: str) -> OperatorActor:
    async with db_session.transaction() as s:
        user = await factories.create_user(s, max_user_id=key)
        await factories.create_platform_role(s, user)
        return OperatorActor(user_id=user.id)


async def add_equipment(customer: CustomerFixture, *, brand: str | None = "Бренд") -> uuid.UUID:
    async with db_session.transaction() as s:
        org = await s.get(Organization, customer.organization_id)
        assert org is not None
        location = await s.get(Equipment, customer.equipment_id)
        assert location is not None
        equipment = Equipment(
            customer_org_id=org.id,
            location_id=location.location_id,
            equipment_category_id=location.equipment_category_id,
            brand=brand,
        )
        s.add(equipment)
        await s.flush()
        return equipment.id


async def session_token(actor: UserActor) -> str:
    async with db_session.transaction() as s:
        user = await s.get(User, actor.user_id)
        assert user is not None
        return await factories.create_session_token(s, user)


def org_id(actor: UserActor) -> str:
    return ids.encode("organization", actor.organization_id)
