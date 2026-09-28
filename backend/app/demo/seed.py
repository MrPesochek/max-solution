"""Создание демо-данных. --refresh обновляет заявки, --reset удаляет демо-данные."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import OperatorActor, UserActor
from app.core.clock import utcnow
from app.db import session as db_session
from app.db.enums import (
    BindingBasis,
    BindingStatus,
    MembershipRole,
    MembershipStatus,
    ProviderKind,
    ProviderProfileStatus,
    VerificationDecision,
)
from app.db.models import (
    Attachment,
    City,
    District,
    Equipment,
    EquipmentCategory,
    IntegrationClient,
    Invitation,
    Location,
    Membership,
    MembershipLocation,
    Organization,
    PlatformRole,
    ProviderCategory,
    ProviderProfile,
    ProviderServiceArea,
    RepairRequest,
    ServiceBinding,
    ServiceContract,
    User,
    VerificationCase,
)
from app.demo import scenarios
from app.infra.config import get_settings
from app.infra.crypto import generate_token, hash_token, token_prefix
from app.modules.files import api as files
from app.modules.identity.sessions import DEMO_USER_KEYS as DEMO_USER_KEYS
from app.modules.identity.sessions import DEMO_USER_PREFIX
from app.modules.integration.keys import issue_api_key, parse_api_key

log = structlog.get_logger(__name__)

_ALLOWED_ENVIRONMENTS = ("local", "demo")

_PUBLISHED_CONNECTOR_KEY_PREFIX = "01120116af3a"

_NAMESPACE = uuid.UUID("2f2a9a4a-8b3e-4d63-9b8e-6a6f1a1c9d00")


def _id(key: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, key)


def _max_user_id(user_key: str) -> str:
    return f"{DEMO_USER_PREFIX}{user_key}"


CUSTOMER_INN = "7707083893"
PROVIDER_INN = "7736050003"
EXT_PROVIDER_1_INN = "7710137066"

ORG_CUSTOMER = _id("org:customer")
ORG_PROVIDER = _id("org:provider")
ORG_EXT1 = _id("org:ext1")
ORG_EXT2 = _id("org:ext2")
ORG_OUTSIDER = _id("org:outsider")
ORG_PENDING = _id("org:pending")
ORG_DUAL = _id("org:dual")
ORG_BAKERY = _id("org:bakery")
ORG_EXT3 = _id("org:ext3")
ORG_EXT4 = _id("org:ext4")
DEMO_ORG_IDS = (
    ORG_CUSTOMER,
    ORG_PROVIDER,
    ORG_EXT1,
    ORG_EXT2,
    ORG_OUTSIDER,
    ORG_PENDING,
    ORG_DUAL,
    ORG_BAKERY,
    ORG_EXT3,
    ORG_EXT4,
)

_EXTERNAL_KEYS = ("ext_provider_1", "ext_provider_2", "ext_provider_3", "ext_provider_4")


class DemoSeedNotAllowed(RuntimeError):
    """Сид/сброс демо-данных запрошен вне local/demo окружения."""


def _ensure_environment_allowed() -> None:
    env = get_settings().app_env
    if env not in _ALLOWED_ENVIRONMENTS:
        raise DemoSeedNotAllowed(
            f"Демо-данные недоступны в окружении {env!r}: "
            f"разрешено только {', '.join(_ALLOWED_ENVIRONMENTS)}. "
            "Проверьте переменную APP_ENV."
        )


@dataclass(slots=True)
class SeedReport:
    organizations: int = 0
    users: int = 0
    requests_created: int = 0
    portfolio_images: int = 0
    integration_client_created: bool = False
    connector_api_key_generated: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Reference:
    city: City
    districts: dict[str, District]
    categories: dict[str, EquipmentCategory]


async def _load_reference(session: AsyncSession) -> _Reference:
    city = (await session.execute(select(City).where(City.name == "Новоград"))).scalar_one()
    districts = {
        row.name: row
        for row in (
            await session.execute(select(District).where(District.city_id == city.id))
        ).scalars()
    }
    categories = {
        row.code: row for row in (await session.execute(select(EquipmentCategory))).scalars()
    }
    return _Reference(city=city, districts=districts, categories=categories)


async def _ensure[M](
    session: AsyncSession, model: type[M], id_: uuid.UUID, /, **fields: Any
) -> tuple[M, bool]:
    """Строка с детерминированным id: находит существующую либо создаёт новую."""
    obj = await session.get(model, id_)
    if obj is not None:
        return obj, False
    created = model(id=id_, **fields)  # type: ignore[call-arg]
    session.add(created)
    await session.flush()
    return created, True


def _actor_of(membership: Membership) -> UserActor:
    return UserActor(
        user_id=membership.user_id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


_CUSTOMER_EQUIPMENT: tuple[tuple[str, int, str, str, str, str, bool], ...] = (
    (
        "equipment_1",
        1,
        "commercial_display_fridge",
        "Carboma",
        "F16-08 VM",
        "Витрина холодильная у кассы (демо)",
        True,
    ),
    ("equipment_2", 1, "chest_freezer", "Polair", "SF140-S", "Ларь морозильный (демо)", True),
    ("equipment_3", 1, "ice_maker", "Scotsman", "AC 46", "Льдогенератор бара (демо)", False),
    ("equipment_4", 2, "refrigerator_cabinet", "Бриз", "ШХ-0,7", "Шкаф холодильный (демо)", True),
    (
        "equipment_5",
        2,
        "split_system_cold_room",
        "Термо-Люкс",
        "SCN 214",
        "Сплит-система камеры (демо)",
        False,
    ),
    (
        "equipment_6",
        2,
        "commercial_display_fridge",
        "FrostLine",
        "Mini 1200",
        "Витрина десертная (демо)",
        True,
    ),
    (
        "equipment_7",
        1,
        "refrigerator_cabinet",
        "Polair",
        "CM107-S",
        "Холодильный стол на кухне (демо)",
        True,
    ),
    (
        "equipment_8",
        1,
        "commercial_display_fridge",
        "Ариада",
        "Veneto VS-UN",
        "Витрина в зале (демо)",
        True,
    ),
    (
        "equipment_9",
        1,
        "split_system_cold_room",
        "Intercold",
        "MCM 218",
        "Холодильная камера склада (демо)",
        False,
    ),
    ("equipment_10", 2, "chest_freezer", "Сугроб", "200", "Ларь для мороженого (демо)", True),
    ("equipment_11", 2, "ice_maker", "IceCraft", "IC-25", "Льдогенератор бара (демо)", True),
    (
        "equipment_12",
        1,
        "refrigerator_cabinet",
        "Бирюса",
        "520 DN",
        "Шкаф для молока (демо)",
        True,
    ),
    ("equipment_13", 1, "chest_freezer", "Frostor", "F 500 S", "Ларь на складе (демо)", False),
)
BOUND_EQUIPMENT_KEYS = tuple(key for key, *_, bound in _CUSTOMER_EQUIPMENT if bound)


async def _ensure_equipment(session: AsyncSession, id_: uuid.UUID, **fields: Any) -> uuid.UUID:
    """Как `_ensure`, но подтягивает бренд, модель и заметку к текущему плану —
    стенды, поднятые раньше, получают те же названия, что и новые."""
    row, created = await _ensure(session, Equipment, id_, **fields)
    if not created:
        for name in ("brand", "model", "notes"):
            setattr(row, name, fields[name])
        await session.flush()
    return row.id


@dataclass(slots=True)
class CustomerFixture:
    organization_id: uuid.UUID
    location_1_id: uuid.UUID
    location_2_id: uuid.UUID
    equipment: dict[str, uuid.UUID]
    manager_membership_id: uuid.UUID
    employee_membership_id: uuid.UUID
    manager_user_id: uuid.UUID
    employee_user_id: uuid.UUID


async def _seed_customer(
    session: AsyncSession, ref: _Reference, report: SeedReport
) -> CustomerFixture:
    org, created = await _ensure(
        session,
        Organization,
        ORG_CUSTOMER,
        is_customer=True,
        is_provider=False,
        legal_name="ООО «Зерно» (демонстрационные данные)",
        display_name="Демо: Кофейня «Зерно»",
        legal_form="ooo",
        inn_raw=CUSTOMER_INN,
        inn_normalized=CUSTOMER_INN,
        contact_name="Демо Заказчик",
        contact_phone="+70000000001",
        details_verification_status="verified",
        details_verified_at=utcnow(),
        representative_verification_status="verified",
        representative_verified_at=utcnow(),
    )
    if created:
        report.organizations += 1

    loc1, _ = await _ensure(
        session,
        Location,
        _id("location:customer:1"),
        customer_org_id=org.id,
        name="Демо: Кофейня на Центральной",
        city_id=ref.city.id,
        district_id=ref.districts["Центральный"].id,
        address="г. Новоград, ул. Центральная, 10",
        timezone=ref.city.timezone,
        contact_name="Демо Управляющий точкой №1",
        contact_phone="+70000000011",
    )
    loc2, _ = await _ensure(
        session,
        Location,
        _id("location:customer:2"),
        customer_org_id=org.id,
        name="Демо: Кофейня на Южной",
        city_id=ref.city.id,
        district_id=ref.districts["Южный"].id,
        address="г. Новоград, ул. Южная, 24",
        timezone=ref.city.timezone,
        contact_name="Демо Управляющий точкой №2",
        contact_phone="+70000000012",
    )

    locations = {1: loc1.id, 2: loc2.id}
    equipment: dict[str, uuid.UUID] = {}
    for key, location_no, category_code, brand, model, note, _bound in _CUSTOMER_EQUIPMENT:
        equipment[key] = await _ensure_equipment(
            session,
            _id(f"equipment:customer:{key}"),
            customer_org_id=org.id,
            location_id=locations[location_no],
            equipment_category_id=ref.categories[category_code].id,
            brand=brand,
            model=model,
            notes=note,
        )

    manager_user, was_created = await _ensure(
        session,
        User,
        _id("user:manager"),
        max_user_id=_max_user_id("manager"),
        display_name="Демо: Руководитель заказчика",
    )
    if was_created:
        report.users += 1
    employee_user, was_created = await _ensure(
        session,
        User,
        _id("user:employee"),
        max_user_id=_max_user_id("employee"),
        display_name="Демо: Сотрудник точки №1",
    )
    if was_created:
        report.users += 1

    manager_membership, _ = await _ensure(
        session,
        Membership,
        _id("membership:customer:manager"),
        user_id=manager_user.id,
        organization_id=org.id,
        role=MembershipRole.CUSTOMER_MANAGER.value,
        status=MembershipStatus.ACTIVE.value,
    )
    employee_membership, employee_created = await _ensure(
        session,
        Membership,
        _id("membership:customer:employee"),
        user_id=employee_user.id,
        organization_id=org.id,
        role=MembershipRole.CUSTOMER_EMPLOYEE.value,
        status=MembershipStatus.ACTIVE.value,
    )
    if employee_created:
        session.add(
            MembershipLocation(
                id=_id("membership_location:employee:1"),
                membership_id=employee_membership.id,
                location_id=loc1.id,
            )
        )
        await session.flush()

    invitation_id = _id("invitation:customer:expired")
    if await session.get(Invitation, invitation_id) is None:
        token = generate_token()
        session.add(
            Invitation(
                id=invitation_id,
                kind="membership",
                organization_id=org.id,
                created_by_membership_id=manager_membership.id,
                role=MembershipRole.CUSTOMER_EMPLOYEE.value,
                location_ids=[loc1.id],
                token_hash=hash_token(token),
                token_prefix=token_prefix(token),
                status="pending",
                expires_at=utcnow() - timedelta(days=1),
            )
        )
        await session.flush()

    return CustomerFixture(
        organization_id=org.id,
        location_1_id=loc1.id,
        location_2_id=loc2.id,
        equipment=equipment,
        manager_membership_id=manager_membership.id,
        employee_membership_id=employee_membership.id,
        manager_user_id=manager_user.id,
        employee_user_id=employee_user.id,
    )


async def _ensure_categories(
    session: AsyncSession,
    ref: _Reference,
    provider_org_id: uuid.UUID,
    key: str,
    codes: tuple[str, ...],
) -> None:
    for code in codes:
        await _ensure(
            session,
            ProviderCategory,
            _id(f"provider_category:{key}:{code}"),
            provider_org_id=provider_org_id,
            equipment_category_id=ref.categories[code].id,
        )


async def _ensure_binding(
    session: AsyncSession,
    key: str,
    *,
    equipment_id: uuid.UUID,
    customer_org_id: uuid.UUID,
    provider_org_id: uuid.UUID,
    contract_id: uuid.UUID,
    created_by_membership_id: uuid.UUID,
) -> None:
    await _ensure(
        session,
        ServiceBinding,
        _id(f"service_binding:{key}"),
        equipment_id=equipment_id,
        customer_org_id=customer_org_id,
        provider_org_id=provider_org_id,
        contract_id=contract_id,
        basis=BindingBasis.SERVICE_CONTRACT.value,
        status=BindingStatus.CONFIRMED.value,
        customer_confirmed_at=utcnow(),
        provider_confirmed_at=utcnow(),
        created_by_membership_id=created_by_membership_id,
    )


@dataclass(slots=True)
class ProviderFixture:
    organization_id: uuid.UUID
    admin_membership_id: uuid.UUID
    dispatcher_membership_id: uuid.UUID


async def _seed_connected_provider(
    session: AsyncSession, ref: _Reference, customer: CustomerFixture, report: SeedReport
) -> ProviderFixture:
    org, created = await _ensure(
        session,
        Organization,
        ORG_PROVIDER,
        is_customer=False,
        is_provider=True,
        legal_name="ООО «Холод-Мастер» (демонстрационные данные)",
        display_name="Демо: Сервис «Холод-Мастер»",
        legal_form="ooo",
        inn_raw=PROVIDER_INN,
        inn_normalized=PROVIDER_INN,
        contact_name="Демо Администратор сервиса",
        contact_phone="+70000000002",
        details_verification_status="verified",
        details_verified_at=utcnow(),
        representative_verification_status="verified",
        representative_verified_at=utcnow(),
    )
    if created:
        report.organizations += 1

    _profile, profile_created = await _ensure(
        session,
        ProviderProfile,
        _id("provider_profile:provider"),
        organization_id=org.id,
        provider_kind=ProviderKind.COMPANY.value,
        status=ProviderProfileStatus.ACTIVE.value,
        accepting_new_requests=True,
        can_provide_documents=True,
        description="Демо: подключённая сервисная компания со своим договором на обслуживание.",
    )
    await _ensure_categories(session, ref, org.id, "provider", tuple(ref.categories))
    if profile_created:
        session.add(
            ProviderServiceArea(
                id=_id("provider_service_area:provider:city"),
                provider_org_id=org.id,
                city_id=ref.city.id,
                district_id=None,
            )
        )
        session.add(
            VerificationCase(
                id=_id("verification_case:provider:requisites"),
                organization_id=org.id,
                subject_type="organization_details",
                check_kind="requisites",
                decision=VerificationDecision.APPROVED.value,
                source="демонстрационные данные",
                is_demo=True,
                checked_at=utcnow(),
            )
        )
        session.add(
            VerificationCase(
                id=_id("verification_case:provider:representative"),
                organization_id=org.id,
                subject_type="representative",
                check_kind="representative",
                decision=VerificationDecision.APPROVED.value,
                source="демонстрационные данные",
                is_demo=True,
                checked_at=utcnow(),
            )
        )
        await session.flush()

    admin_user, was_created = await _ensure(
        session,
        User,
        _id("user:provider_admin"),
        max_user_id=_max_user_id("provider_admin"),
        display_name="Демо: Администратор сервиса",
    )
    if was_created:
        report.users += 1
    dispatcher_user, was_created = await _ensure(
        session,
        User,
        _id("user:provider_dispatcher"),
        max_user_id=_max_user_id("provider_dispatcher"),
        display_name="Демо: Диспетчер сервиса",
    )
    if was_created:
        report.users += 1

    admin_membership, _ = await _ensure(
        session,
        Membership,
        _id("membership:provider:admin"),
        user_id=admin_user.id,
        organization_id=org.id,
        role=MembershipRole.PROVIDER_ADMIN.value,
        status=MembershipStatus.ACTIVE.value,
    )
    dispatcher_membership, _ = await _ensure(
        session,
        Membership,
        _id("membership:provider:dispatcher"),
        user_id=dispatcher_user.id,
        organization_id=org.id,
        role=MembershipRole.PROVIDER_DISPATCHER.value,
        status=MembershipStatus.ACTIVE.value,
    )

    contract, _ = await _ensure(
        session,
        ServiceContract,
        _id("service_contract:provider:customer"),
        provider_org_id=org.id,
        customer_org_id=customer.organization_id,
        contract_number="Д-2026/001",
        basis=BindingBasis.SERVICE_CONTRACT.value,
        created_by_membership_id=customer.manager_membership_id,
    )

    for key in BOUND_EQUIPMENT_KEYS:
        await _ensure_binding(
            session,
            key,
            equipment_id=customer.equipment[key],
            customer_org_id=customer.organization_id,
            provider_org_id=org.id,
            contract_id=contract.id,
            created_by_membership_id=customer.manager_membership_id,
        )

    return ProviderFixture(
        organization_id=org.id,
        admin_membership_id=admin_membership.id,
        dispatcher_membership_id=dispatcher_membership.id,
    )


async def _seed_external_provider(
    session: AsyncSession,
    ref: _Reference,
    *,
    org_id: uuid.UUID,
    user_key: str,
    legal_name: str,
    display_name: str,
    provider_kind: str,
    inn: str | None,
    category_codes: tuple[str, ...],
    district_name: str | None,
    report: SeedReport,
) -> uuid.UUID:
    """Внешний (не подключённый по договору) исполнитель для сценария поиска."""
    org, created = await _ensure(
        session,
        Organization,
        org_id,
        is_customer=False,
        is_provider=True,
        legal_name=legal_name,
        display_name=display_name,
        legal_form="ooo" if provider_kind == ProviderKind.COMPANY.value else "ip",
        inn_raw=inn,
        inn_normalized=inn,
        contact_phone="+70000000003",
        details_verification_status="verified",
        details_verified_at=utcnow(),
        representative_verification_status="verified",
        representative_verified_at=utcnow(),
    )
    if created:
        report.organizations += 1

    _profile, profile_created = await _ensure(
        session,
        ProviderProfile,
        _id(f"provider_profile:{user_key}"),
        organization_id=org.id,
        provider_kind=provider_kind,
        status=ProviderProfileStatus.ACTIVE.value,
        accepting_new_requests=True,
        description=f"Демо: внешний исполнитель ({display_name}).",
    )
    await _ensure_categories(session, ref, org.id, user_key, category_codes)
    if profile_created:
        district = ref.districts[district_name] if district_name else None
        session.add(
            ProviderServiceArea(
                id=_id(f"provider_service_area:{user_key}"),
                provider_org_id=org.id,
                city_id=ref.city.id,
                district_id=district.id if district else None,
            )
        )
        session.add(
            VerificationCase(
                id=_id(f"verification_case:{user_key}:requisites"),
                organization_id=org.id,
                subject_type="organization_details",
                check_kind="requisites",
                decision=VerificationDecision.APPROVED.value,
                source="демонстрационные данные",
                is_demo=True,
                checked_at=utcnow(),
            )
        )
        await session.flush()

    user, was_created = await _ensure(
        session,
        User,
        _id(f"user:{user_key}"),
        max_user_id=_max_user_id(user_key),
        display_name=f"Демо: {display_name}",
    )
    if was_created:
        report.users += 1

    await _ensure(
        session,
        Membership,
        _id(f"membership:{user_key}:admin"),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.PROVIDER_ADMIN.value,
        status=MembershipStatus.ACTIVE.value,
    )
    return org.id


async def _seed_outsider(session: AsyncSession, ref: _Reference, report: SeedReport) -> None:
    """Отдельная организация-заказчик — для проверки запрета межорганизационного доступа (A19)."""
    org, created = await _ensure(
        session,
        Organization,
        ORG_OUTSIDER,
        is_customer=True,
        is_provider=False,
        legal_name="ООО «Чужая компания» (демонстрационные данные)",
        display_name="Демо: ООО «Чужая компания»",
        legal_form="ooo",
        details_verification_status="verified",
        details_verified_at=utcnow(),
        representative_verification_status="verified",
        representative_verified_at=utcnow(),
    )
    if created:
        report.organizations += 1

    location, _ = await _ensure(
        session,
        Location,
        _id("location:outsider:1"),
        customer_org_id=org.id,
        name="Демо: Точка чужой организации",
        city_id=ref.city.id,
        district_id=ref.districts["Восточный"].id,
        address="г. Новоград, ул. Восточная, 5",
        timezone=ref.city.timezone,
    )
    await _ensure(
        session,
        Equipment,
        _id("equipment:outsider:1"),
        customer_org_id=org.id,
        location_id=location.id,
        equipment_category_id=ref.categories["refrigerator_cabinet"].id,
        brand="Бриз",
        notes="Шкаф холодильный (демо, чужая организация)",
    )

    user, was_created = await _ensure(
        session,
        User,
        _id("user:outsider_manager"),
        max_user_id=_max_user_id("outsider_manager"),
        display_name="Демо: Руководитель чужой организации",
    )
    if was_created:
        report.users += 1
    await _ensure(
        session,
        Membership,
        _id("membership:outsider:manager"),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.CUSTOMER_MANAGER.value,
        status=MembershipStatus.ACTIVE.value,
    )


@dataclass(slots=True)
class BakeryFixture:
    manager_membership_id: uuid.UUID
    equipment: dict[str, uuid.UUID]


async def _seed_bakery(
    session: AsyncSession, ref: _Reference, provider: ProviderFixture, report: SeedReport
) -> BakeryFixture:
    """Второй заказчик подключённого сервиса — со своим договором, для входящих исполнителя."""
    org, created = await _ensure(
        session,
        Organization,
        ORG_BAKERY,
        is_customer=True,
        is_provider=False,
        legal_name="ООО «Мука» (демонстрационные данные)",
        display_name="Демо: Пекарня «Мука»",
        legal_form="ooo",
        contact_name="Демо Руководитель пекарни",
        contact_phone="+70000000081",
        details_verification_status="verified",
        details_verified_at=utcnow(),
        representative_verification_status="verified",
        representative_verified_at=utcnow(),
    )
    if created:
        report.organizations += 1

    location, _ = await _ensure(
        session,
        Location,
        _id("location:bakery:1"),
        customer_org_id=org.id,
        name="Демо: Пекарня на Северной",
        city_id=ref.city.id,
        district_id=ref.districts["Северный"].id,
        address="г. Новоград, ул. Северная, 3",
        timezone=ref.city.timezone,
        contact_name="Демо Технолог пекарни",
        contact_phone="+70000000082",
    )
    equipment_id = await _ensure_equipment(
        session,
        _id("equipment:bakery:bakery_1"),
        customer_org_id=org.id,
        location_id=location.id,
        equipment_category_id=ref.categories["split_system_cold_room"].id,
        brand="Polair",
        model="KM 102",
        notes="Холодильная камера для теста (демо)",
    )

    user, was_created = await _ensure(
        session,
        User,
        _id("user:bakery_manager"),
        max_user_id=_max_user_id("bakery_manager"),
        display_name="Демо: Руководитель пекарни",
    )
    if was_created:
        report.users += 1
    membership, _ = await _ensure(
        session,
        Membership,
        _id("membership:bakery:manager"),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.CUSTOMER_MANAGER.value,
        status=MembershipStatus.ACTIVE.value,
    )
    contract, _ = await _ensure(
        session,
        ServiceContract,
        _id("service_contract:provider:bakery"),
        provider_org_id=provider.organization_id,
        customer_org_id=org.id,
        contract_number="Д-2026/014",
        basis=BindingBasis.SERVICE_CONTRACT.value,
        created_by_membership_id=membership.id,
    )
    await _ensure_binding(
        session,
        "bakery_1",
        equipment_id=equipment_id,
        customer_org_id=org.id,
        provider_org_id=provider.organization_id,
        contract_id=contract.id,
        created_by_membership_id=membership.id,
    )
    return BakeryFixture(manager_membership_id=membership.id, equipment={"bakery_1": equipment_id})


async def _seed_pending_provider(
    session: AsyncSession, ref: _Reference, report: SeedReport
) -> None:
    """Неподтверждённый представитель: профиль в очереди проверки (`pending_review`)."""
    org, created = await _ensure(
        session,
        Organization,
        ORG_PENDING,
        is_customer=False,
        is_provider=True,
        legal_name="ИП Кузнецов (демонстрационные данные)",
        display_name="Демо: ИП Кузнецов (заявка на подключение)",
        legal_form="ip",
    )
    if created:
        report.organizations += 1

    _profile, profile_created = await _ensure(
        session,
        ProviderProfile,
        _id("provider_profile:pending"),
        organization_id=org.id,
        provider_kind=ProviderKind.INDEPENDENT_SPECIALIST.value,
        status=ProviderProfileStatus.PENDING_REVIEW.value,
        accepting_new_requests=False,
        description="Демо: самостоятельная регистрация, представитель ещё не подтверждён.",
    )
    if profile_created:
        session.add(
            ProviderCategory(
                id=_id("provider_category:pending:refrigerator_cabinet"),
                provider_org_id=org.id,
                equipment_category_id=ref.categories["refrigerator_cabinet"].id,
            )
        )
        session.add(
            VerificationCase(
                id=_id("verification_case:pending:requisites"),
                organization_id=org.id,
                subject_type="organization_details",
                check_kind="requisites",
                decision=VerificationDecision.PENDING.value,
                is_demo=True,
            )
        )
        session.add(
            VerificationCase(
                id=_id("verification_case:pending:representative"),
                organization_id=org.id,
                subject_type="representative",
                check_kind="representative",
                decision=VerificationDecision.PENDING.value,
                is_demo=True,
            )
        )
        await session.flush()

    user, was_created = await _ensure(
        session,
        User,
        _id("user:pending_admin"),
        max_user_id=_max_user_id("pending_provider_admin"),
        display_name="Демо: ИП Кузнецов",
    )
    if was_created:
        report.users += 1
    await _ensure(
        session,
        Membership,
        _id("membership:pending:admin"),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.PROVIDER_ADMIN.value,
        status=MembershipStatus.ACTIVE.value,
    )


async def _seed_dual_organization(
    session: AsyncSession, ref: _Reference, report: SeedReport
) -> None:
    """Организация и заказчик, и исполнитель (ТЗ 3): у руководителя два членства —
    по одному на сторону, контексты переключаются выбором членства."""
    org, created = await _ensure(
        session,
        Organization,
        ORG_DUAL,
        is_customer=True,
        is_provider=True,
        legal_name="ООО «Двойной контур» (демонстрационные данные)",
        display_name="Демо: ООО «Двойной контур»",
        legal_form="ooo",
        contact_name="Демо Руководитель двойной организации",
        contact_phone="+70000000071",
    )
    if created:
        report.organizations += 1

    await _ensure(
        session,
        Location,
        _id("location:dual:1"),
        customer_org_id=org.id,
        name="Демо: Столовая «Двойного контура»",
        city_id=ref.city.id,
        district_id=ref.districts["Центральный"].id,
        address="г. Новоград, ул. Центральная, 71",
        timezone=ref.city.timezone,
    )
    await _ensure(
        session,
        ProviderProfile,
        _id("provider_profile:dual"),
        organization_id=org.id,
        provider_kind=ProviderKind.COMPANY.value,
        status=ProviderProfileStatus.DRAFT.value,
        accepting_new_requests=False,
        can_provide_documents=False,
        description="Демо: исполнитель внутри организации-заказчика, профиль не отправлен.",
    )

    user, was_created = await _ensure(
        session,
        User,
        _id("user:dual_manager"),
        max_user_id=_max_user_id("dual_manager"),
        display_name="Демо: Руководитель двойной организации",
    )
    if was_created:
        report.users += 1
    await _ensure(
        session,
        Membership,
        _id("membership:dual:customer"),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.CUSTOMER_MANAGER.value,
        status=MembershipStatus.ACTIVE.value,
    )
    await _ensure(
        session,
        Membership,
        _id("membership:dual:provider"),
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.PROVIDER_ADMIN.value,
        status=MembershipStatus.ACTIVE.value,
    )


async def _seed_operator(session: AsyncSession, report: SeedReport) -> uuid.UUID:
    user, was_created = await _ensure(
        session,
        User,
        _id("user:operator"),
        max_user_id=_max_user_id("operator"),
        display_name="Демо: Оператор платформы",
    )
    if was_created:
        report.users += 1
    await _ensure(
        session,
        PlatformRole,
        _id("platform_role:operator"),
        user_id=user.id,
        role="operator",
        granted_at=utcnow(),
    )
    return user.id


def _connector_api_key(report: SeedReport) -> str | None:
    """Ключ коннектора 1С: `CONNECTOR_API_KEY`, иначе файл `CONNECTOR_API_KEY_FILE`.

    Файла ещё нет — первый запуск сида выпускает новый ключ и кладёт его туда
    (compose.demo.yaml: том `demo-secrets`, оттуда же его читает коннектор). Так у
    каждого стенда свой ключ, а в репозитории — только код генерации.
    """
    raw_key = os.environ.get("CONNECTOR_API_KEY", "").strip()
    if raw_key:
        return raw_key
    key_file = os.environ.get("CONNECTOR_API_KEY_FILE", "").strip()
    if not key_file:
        return None
    path = Path(key_file)
    if path.is_file():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    issued = issue_api_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(issued.raw + "\n", encoding="utf-8")
    tmp.chmod(0o644)
    tmp.replace(path)
    report.connector_api_key_generated = True
    log.info("demo_connector_key_generated", path=str(path), prefix=issued.prefix)
    return issued.raw


async def _seed_integration_client(
    session: AsyncSession, provider: ProviderFixture, report: SeedReport
) -> None:
    """Интеграционный клиент коннектора 1С (ключ — `_connector_api_key`).

    Ключ действителен только в demo-окружении (проверка `APP_ENV` — на входе в
    скрипт, окружение ключа — `env_matches`). Если ключа нет или он не соответствует
    формату `rk_<env>_<prefix>_<secret>` (`app/modules/integration/keys.py`), клиент не
    создаётся — остальной сид не прерывается, чтобы стенд поднимался и без него.
    Отозванный администратором клиент сид не трогает: повторный запуск не должен
    отменять отзыв ключа.
    """
    raw_key = _connector_api_key(report)
    if raw_key is None:
        report.notes.append(
            "CONNECTOR_API_KEY и CONNECTOR_API_KEY_FILE не заданы — интеграционный клиент "
            "коннектора 1С не создан."
        )
        return
    parsed = parse_api_key(raw_key)
    if parsed is None:
        report.notes.append(
            "CONNECTOR_API_KEY не соответствует формату rk_<env>_<prefix>_<secret> — "
            "интеграционный клиент коннектора 1С не создан."
        )
        return
    if parsed.prefix == _PUBLISHED_CONNECTOR_KEY_PREFIX:
        report.notes.append(
            "CONNECTOR_API_KEY совпадает с ключом, опубликованным в репозитории, — "
            "интеграционный клиент коннектора 1С не создан. Очистите CONNECTOR_API_KEY: "
            "сид выпустит собственный ключ."
        )
        return

    client_id = _id("integration_client:provider:demo_crm")
    existing = await session.get(IntegrationClient, client_id)
    if existing is not None:
        if existing.status != "active" or existing.revoked_at is not None:
            report.notes.append(
                "Интеграционный клиент коннектора 1С отозван — сид его не восстанавливает."
            )
            return
        existing.name = "Демо: коннектор 1С"
        existing.api_key_hash = hash_token(raw_key)
        existing.api_key_prefix = parsed.prefix
        await session.flush()
        return

    session.add(
        IntegrationClient(
            id=client_id,
            provider_org_id=provider.organization_id,
            name="Демо: коннектор 1С",
            api_key_hash=hash_token(raw_key),
            api_key_prefix=parsed.prefix,
            scopes=["requests:read", "requests:write", "webhooks:manage", "events:read"],
            status="active",
            created_by_membership_id=provider.admin_membership_id,
        )
    )
    await session.flush()
    report.integration_client_created = True


_PORTFOLIO: dict[str, tuple[tuple[str, tuple[int, int, int]], ...]] = {
    "provider": (
        ("Carboma F16 - compressor", (38, 92, 140)),
        ("Polair CM107 - cold room", (46, 125, 90)),
        ("Ariada R1400 - display", (150, 84, 40)),
    ),
    "ext_provider_1": (
        ("Split system - service", (92, 60, 140)),
        ("Display fridge - repair", (120, 120, 50)),
    ),
}


async def _seed_portfolio(operator_user_id: uuid.UUID) -> int:
    """Опубликованные фото галереи: тот же путь, что у живой загрузки — карантин,
    обработка, решение модератора. Повторный запуск не добавляет фото к уже имеющимся."""
    owners = {
        "provider": ("membership:provider:admin", "provider_profile:provider"),
        "ext_provider_1": ("membership:ext_provider_1:admin", "provider_profile:ext_provider_1"),
    }
    uploads: list[tuple[UserActor, tuple[tuple[str, tuple[int, int, int]], ...]]] = []
    async with db_session.get_sessionmaker()() as session:
        for key, (membership_key, profile_key) in owners.items():
            existing = (
                await session.execute(
                    select(Attachment.id)
                    .where(Attachment.provider_profile_id == _id(profile_key))
                    .limit(1)
                )
            ).scalar_one_or_none()
            membership = await session.get(Membership, _id(membership_key))
            if existing is None and membership is not None:
                uploads.append((_actor_of(membership), _PORTFOLIO[key]))
    if not uploads:
        return 0

    attachment_ids: list[uuid.UUID] = []
    for actor, items in uploads:
        for caption, color in items:
            result = await files.submit_portfolio_image(
                actor,
                filename_hint="portfolio.jpg",
                content_type_hint="image/jpeg",
                stream=scenarios.one_chunk(scenarios.jpeg(caption, color)),
            )
            attachment_id = ids.decode("attachment", result.body["id"])
            await files.set_portfolio_caption(actor, attachment_id, f"Пример работы: {caption}")
            attachment_ids.append(attachment_id)
    while await files.process_images(utcnow()):
        pass
    operator = OperatorActor(user_id=operator_user_id)
    for attachment_id in attachment_ids:
        await files.approve_attachment(operator, attachment_id)
    return len(attachment_ids)


async def _seed_requests(
    customer: CustomerFixture,
    provider: ProviderFixture,
    bakery: BakeryFixture,
    operator_user_id: uuid.UUID,
    timezone: str,
) -> int:
    """Демо-сценарии заявок (`app/demo/scenarios.py`) — один раз на чистый стенд."""
    async with db_session.get_sessionmaker()() as session:
        already = (
            await session.execute(
                select(RepairRequest.id)
                .where(RepairRequest.customer_org_id == customer.organization_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if already is not None:
            return 0
        memberships = {
            row.id: row
            for row in (
                await session.execute(
                    select(Membership).where(
                        Membership.id.in_(
                            [
                                customer.manager_membership_id,
                                bakery.manager_membership_id,
                                provider.admin_membership_id,
                                provider.dispatcher_membership_id,
                                *(_id(f"membership:{key}:admin") for key in _EXTERNAL_KEYS),
                            ]
                        )
                    )
                )
            ).scalars()
        }
        employee_user_id = (
            await session.execute(
                select(Membership.user_id).where(Membership.id == customer.employee_membership_id)
            )
        ).scalar_one()

    cast = scenarios.Cast(
        manager=_actor_of(memberships[customer.manager_membership_id]),
        employee=UserActor(
            user_id=employee_user_id,
            membership_id=customer.employee_membership_id,
            organization_id=customer.organization_id,
            role=MembershipRole.CUSTOMER_EMPLOYEE.value,
            location_ids=frozenset({customer.location_1_id}),
        ),
        bakery_manager=_actor_of(memberships[bakery.manager_membership_id]),
        provider_admin=_actor_of(memberships[provider.admin_membership_id]),
        provider_dispatcher=_actor_of(memberships[provider.dispatcher_membership_id]),
        ext={key: _actor_of(memberships[_id(f"membership:{key}:admin")]) for key in _EXTERNAL_KEYS},
        operator=OperatorActor(user_id=operator_user_id),
        equipment={**customer.equipment, **bakery.equipment},
        timezone=timezone,
    )
    return await scenarios.create_all(cast)


_SCENARIO_RESET_STATEMENTS: tuple[str, ...] = (
    "DELETE FROM attachment_variants WHERE attachment_id IN "
    "(SELECT id FROM attachments WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs)))",
    "UPDATE attachments SET moderation_case_id = NULL WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM moderation_cases WHERE attachment_id IN "
    "(SELECT id FROM attachments WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))) "
    "OR review_id IN (SELECT id FROM reviews WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))) "
    "OR assignment_id IN (SELECT id FROM assignments WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs)))",
    "DELETE FROM attachments WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM review_replies WHERE review_id IN "
    "(SELECT id FROM reviews WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs)))",
    "DELETE FROM review_versions WHERE review_id IN "
    "(SELECT id FROM reviews WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs)))",
    "DELETE FROM reviews WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM message_reads WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM messages WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM visit_proposals WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM repair_quotes WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM cancellation_requests WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM assignments WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM offers WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM request_events WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM request_public_cards WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM external_references WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM notifications WHERE request_id IN "
    "(SELECT id FROM repair_requests WHERE customer_org_id = ANY(:orgs))",
    "DELETE FROM repair_requests WHERE customer_org_id = ANY(:orgs)",
    "DELETE FROM provider_rating_aggregates WHERE provider_org_id = ANY(:orgs)",
)

_RESET_STATEMENTS: tuple[str, ...] = (
    *_SCENARIO_RESET_STATEMENTS,
    "DELETE FROM attachment_variants WHERE attachment_id IN (SELECT id FROM attachments "
    "WHERE provider_profile_id IN "
    "(SELECT id FROM provider_profiles WHERE organization_id = ANY(:orgs)))",
    "UPDATE attachments SET moderation_case_id = NULL WHERE provider_profile_id IN "
    "(SELECT id FROM provider_profiles WHERE organization_id = ANY(:orgs))",
    "DELETE FROM moderation_cases WHERE attachment_id IN (SELECT id FROM attachments "
    "WHERE provider_profile_id IN "
    "(SELECT id FROM provider_profiles WHERE organization_id = ANY(:orgs)))",
    "DELETE FROM attachments WHERE provider_profile_id IN "
    "(SELECT id FROM provider_profiles WHERE organization_id = ANY(:orgs))",
    "DELETE FROM review_replies WHERE review_id IN "
    "(SELECT id FROM reviews WHERE customer_org_id = ANY(:orgs) OR provider_org_id = ANY(:orgs))",
    "DELETE FROM review_versions WHERE review_id IN "
    "(SELECT id FROM reviews WHERE customer_org_id = ANY(:orgs) OR provider_org_id = ANY(:orgs))",
    "DELETE FROM moderation_cases WHERE review_id IN "
    "(SELECT id FROM reviews WHERE customer_org_id = ANY(:orgs) OR provider_org_id = ANY(:orgs)) "
    "OR provider_profile_id IN "
    "(SELECT id FROM provider_profiles WHERE organization_id = ANY(:orgs))",
    "DELETE FROM reviews WHERE customer_org_id = ANY(:orgs) OR provider_org_id = ANY(:orgs)",
    "DELETE FROM message_reads "
    "WHERE membership_id IN (SELECT id FROM memberships WHERE organization_id = ANY(:orgs))",
    "DELETE FROM notifications WHERE organization_id = ANY(:orgs) "
    "OR recipient_user_id IN (SELECT id FROM users WHERE max_user_id LIKE :user_prefix)",
    "DELETE FROM webhook_deliveries WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM webhook_subscriptions WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM integration_events WHERE recipient_org_id = ANY(:orgs)",
    "DELETE FROM integration_clients WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM service_bindings "
    "WHERE customer_org_id = ANY(:orgs) OR provider_org_id = ANY(:orgs)",
    "DELETE FROM service_contracts "
    "WHERE customer_org_id = ANY(:orgs) OR provider_org_id = ANY(:orgs)",
    "DELETE FROM verification_cases WHERE organization_id = ANY(:orgs)",
    "DELETE FROM warranty_authorizations WHERE authorized_provider_org_id = ANY(:orgs)",
    "DELETE FROM provider_brand_restrictions WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM provider_service_areas WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM provider_categories WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM provider_profiles WHERE organization_id = ANY(:orgs)",
    "DELETE FROM membership_locations WHERE membership_id IN "
    "(SELECT id FROM memberships WHERE organization_id = ANY(:orgs))",
    "DELETE FROM equipment WHERE customer_org_id = ANY(:orgs)",
    "DELETE FROM locations WHERE customer_org_id = ANY(:orgs)",
    "DELETE FROM invitations WHERE organization_id = ANY(:orgs)",
    "DELETE FROM audit_entries WHERE organization_id = ANY(:orgs) "
    "OR actor_user_id IN (SELECT id FROM users WHERE max_user_id LIKE :user_prefix)",
    "DELETE FROM sessions WHERE user_id IN "
    "(SELECT id FROM users WHERE max_user_id LIKE :user_prefix)",
    "DELETE FROM platform_roles WHERE user_id IN "
    "(SELECT id FROM users WHERE max_user_id LIKE :user_prefix)",
    "DELETE FROM memberships WHERE organization_id = ANY(:orgs)",
    "DELETE FROM users WHERE max_user_id LIKE :user_prefix",
    "DELETE FROM provider_rating_aggregates WHERE provider_org_id = ANY(:orgs)",
    "DELETE FROM organizations WHERE id = ANY(:orgs)",
)


def _reset_params() -> dict[str, object]:
    return {"orgs": list(DEMO_ORG_IDS), "user_prefix": f"{DEMO_USER_PREFIX}%"}


async def reset_scenarios() -> None:
    """Удаляет только заявки демо-заказчиков; организации, пользователи и справочники остаются."""
    _ensure_environment_allowed()
    async with db_session.transaction() as session:
        for statement in _SCENARIO_RESET_STATEMENTS:
            await session.execute(text(statement), _reset_params())
    log.info("demo_seed_scenarios_reset")


async def refresh() -> SeedReport:
    """Пересоздаёт демо-сценарии со свежими сроками — после простоя стенда."""
    await reset_scenarios()
    return await run()


async def reset() -> None:
    _ensure_environment_allowed()
    async with db_session.transaction() as session:
        for statement in _RESET_STATEMENTS:
            await session.execute(text(statement), _reset_params())
    log.info("demo_seed_reset", organizations=len(DEMO_ORG_IDS))


async def run() -> SeedReport:
    _ensure_environment_allowed()
    report = SeedReport()

    async with db_session.transaction() as session:
        ref = await _load_reference(session)
        customer = await _seed_customer(session, ref, report)
        provider = await _seed_connected_provider(session, ref, customer, report)
        await _seed_external_provider(
            session,
            ref,
            org_id=ORG_EXT1,
            user_key="ext_provider_1",
            legal_name="ИП Соколов (демонстрационные данные)",
            display_name="ИП Соколов (холодильный сервис)",
            provider_kind=ProviderKind.INDEPENDENT_SPECIALIST.value,
            inn=EXT_PROVIDER_1_INN,
            category_codes=("commercial_display_fridge", "split_system_cold_room"),
            district_name="Южный",
            report=report,
        )
        await _seed_external_provider(
            session,
            ref,
            org_id=ORG_EXT2,
            user_key="ext_provider_2",
            legal_name="ООО «ТехХолод Сервис» (демонстрационные данные)",
            display_name="ООО «ТехХолод Сервис»",
            provider_kind=ProviderKind.COMPANY.value,
            inn=None,
            category_codes=("commercial_display_fridge", "split_system_cold_room", "ice_maker"),
            district_name="Центральный",
            report=report,
        )
        await _seed_external_provider(
            session,
            ref,
            org_id=ORG_EXT3,
            user_key="ext_provider_3",
            legal_name="ИП Малов И. С. (демонстрационные данные)",
            display_name="Игорь Малов",
            provider_kind=ProviderKind.INDEPENDENT_SPECIALIST.value,
            inn=None,
            category_codes=(
                "commercial_display_fridge",
                "refrigerator_cabinet",
                "split_system_cold_room",
                "ice_maker",
            ),
            district_name=None,
            report=report,
        )
        await _seed_external_provider(
            session,
            ref,
            org_id=ORG_EXT4,
            user_key="ext_provider_4",
            legal_name="ООО «Северный холод» (демонстрационные данные)",
            display_name="ООО «Северный холод»",
            provider_kind=ProviderKind.COMPANY.value,
            inn=None,
            category_codes=("commercial_display_fridge", "refrigerator_cabinet", "ice_maker"),
            district_name=None,
            report=report,
        )
        bakery = await _seed_bakery(session, ref, provider, report)
        await _seed_outsider(session, ref, report)
        await _seed_pending_provider(session, ref, report)
        await _seed_dual_organization(session, ref, report)
        operator_user_id = await _seed_operator(session, report)
        await _seed_integration_client(session, provider, report)

    report.requests_created = await _seed_requests(
        customer, provider, bakery, operator_user_id, ref.city.timezone
    )
    report.portfolio_images = await _seed_portfolio(operator_user_id)
    log.info(
        "demo_seed_done",
        organizations_created=report.organizations,
        users_created=report.users,
        requests_created=report.requests_created,
        integration_client_created=report.integration_client_created,
    )
    for note in report.notes:
        log.warning("demo_seed_note", note=note)
    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reset", action="store_true", help="удалить демо-данные вместо наполнения")
    mode.add_argument(
        "--refresh",
        action="store_true",
        help="пересоздать демо-заявки со свежими сроками (остальные демо-данные не трогаются)",
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> SeedReport | None:
    """Один event loop на весь запуск: движок БД открывается и закрывается в нём же."""
    try:
        if args.reset:
            await reset()
            return None
        if args.refresh:
            return await refresh()
        return await run()
    finally:
        await db_session.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = asyncio.run(_main_async(args))
    except DemoSeedNotAllowed as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    if args.reset:
        print("Демо-данные удалены.")
    else:
        assert report is not None
        print(
            "Демо-данные готовы: "
            f"организаций создано {report.organizations}, "
            f"пользователей создано {report.users}, "
            f"заявок создано {report.requests_created}."
        )
        for note in report.notes:
            print(f"Предупреждение: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
