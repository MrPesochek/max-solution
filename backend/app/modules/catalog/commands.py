import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.core import ids
from app.core.actor import Actor, UserActor
from app.core.errors import NotFound, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Idempotency, run_command
from app.core.scope import scope_of
from app.core.unset import UNSET, UnsetType
from app.db.models import City, District, Equipment, EquipmentCategory, Location
from app.modules.catalog import policy
from app.modules.catalog.summary import equipment_summaries
from app.modules.catalog.views import to_equipment_view, to_location_view


@dataclass(slots=True)
class LocationCreateData:
    name: str
    city_id: str
    address: str
    district_id: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


@dataclass(slots=True)
class LocationUpdateData:
    name: str | UnsetType | None = UNSET
    city_id: str | UnsetType | None = UNSET
    district_id: str | UnsetType | None = UNSET
    address: str | UnsetType | None = UNSET
    timezone: str | UnsetType | None = UNSET
    contact_name: str | UnsetType | None = UNSET
    contact_phone: str | UnsetType | None = UNSET


@dataclass(slots=True)
class EquipmentCreateData:
    location_id: str
    equipment_category_id: str
    brand: str | None = None
    model: str | None = None
    serial_number: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class EquipmentUpdateData:
    location_id: str | UnsetType | None = UNSET
    equipment_category_id: str | UnsetType | None = UNSET
    brand: str | UnsetType | None = UNSET
    model: str | UnsetType | None = UNSET
    serial_number: str | UnsetType | None = UNSET
    notes: str | UnsetType | None = UNSET


async def create_location(
    actor: Actor, data: LocationCreateData, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_customer_manager(actor)
    city_id = ids.decode("city", data.city_id)
    district_id = ids.decode("district", data.district_id) if data.district_id else None
    name = data.name.strip()
    address = data.address.strip()
    if not name or not address:
        raise ValidationFailed("Укажите название и адрес точки", field="name")

    async def handler(ctx: CommandContext) -> CommandResult:
        city = await _require_city(ctx, city_id, district_id)
        location = Location(
            customer_org_id=manager.organization_id,
            name=name,
            city_id=city_id,
            district_id=district_id,
            address=address,
            timezone=data.timezone or city.timezone,
            contact_name=data.contact_name,
            contact_phone=data.contact_phone,
        )
        ctx.session.add(location)
        await ctx.session.flush()
        ctx.audit(
            "location.create",
            "location",
            location.id,
            organization_id=manager.organization_id,
        )
        return CommandResult(to_location_view(location).model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


async def update_location(
    actor: Actor, location_public_id: str, data: LocationUpdateData, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_customer_manager(actor)
    location_id = ids.decode("location", location_public_id)
    if data.city_id is None:
        raise ValidationFailed("Город обязателен", field="city_id")
    if data.name is None:
        raise ValidationFailed("Название обязательно", field="name")
    if data.address is None:
        raise ValidationFailed("Адрес обязателен", field="address")
    if data.timezone is None:
        raise ValidationFailed("Часовой пояс обязателен", field="timezone")
    city_id = ids.decode("city", data.city_id) if isinstance(data.city_id, str) else None
    district_id = (
        ids.decode("district", data.district_id) if isinstance(data.district_id, str) else None
    )

    async def handler(ctx: CommandContext) -> CommandResult:
        location = await _own_location(ctx, manager, location_id)
        if city_id is not None or data.district_id is not UNSET:
            target_city = city_id or location.city_id
            target_district = district_id if data.district_id is not UNSET else location.district_id
            await _require_city(ctx, target_city, target_district)
            location.city_id = target_city
            location.district_id = target_district
        if isinstance(data.name, str):
            location.name = data.name.strip()
        if isinstance(data.address, str):
            location.address = data.address.strip()
        if isinstance(data.timezone, str):
            location.timezone = data.timezone
        if not isinstance(data.contact_name, UnsetType):
            location.contact_name = data.contact_name
        if not isinstance(data.contact_phone, UnsetType):
            location.contact_phone = data.contact_phone
        ctx.audit(
            "location.update",
            "location",
            location.id,
            organization_id=manager.organization_id,
        )
        return CommandResult(to_location_view(location).model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def create_equipment(
    actor: Actor, data: EquipmentCreateData, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_customer_manager(actor)
    location_id = ids.decode("location", data.location_id)
    category_id = ids.decode("category", data.equipment_category_id)

    async def handler(ctx: CommandContext) -> CommandResult:
        await _own_location(ctx, manager, location_id)
        await _require_category(ctx, category_id)
        equipment = Equipment(
            customer_org_id=manager.organization_id,
            location_id=location_id,
            equipment_category_id=category_id,
            brand=data.brand,
            model=data.model,
            serial_number=data.serial_number,
            notes=data.notes,
        )
        ctx.session.add(equipment)
        await ctx.session.flush()
        ctx.audit(
            "equipment.create",
            "equipment",
            equipment.id,
            organization_id=manager.organization_id,
        )
        summaries = await equipment_summaries(ctx.session, scope_of(manager), [equipment])
        view = to_equipment_view(equipment, summaries.get(equipment.id))
        return CommandResult(view.model_dump(mode="json"), status=201)

    return await run_command(actor, handler, idempotency=idem)


async def update_equipment(
    actor: Actor, equipment_public_id: str, data: EquipmentUpdateData, *, idem: Idempotency | None
) -> CommandResult:
    manager = policy.require_customer_manager(actor)
    equipment_id = ids.decode("equipment", equipment_public_id)
    if data.location_id is None:
        raise ValidationFailed("Точка обязательна", field="location_id")
    if data.equipment_category_id is None:
        raise ValidationFailed("Категория оборудования обязательна", field="equipment_category_id")
    location_id = (
        ids.decode("location", data.location_id) if isinstance(data.location_id, str) else None
    )
    category_id = (
        ids.decode("category", data.equipment_category_id)
        if isinstance(data.equipment_category_id, str)
        else None
    )

    async def handler(ctx: CommandContext) -> CommandResult:
        equipment = await lock_by_id(ctx.session, Equipment, equipment_id)
        if equipment.customer_org_id != manager.organization_id:
            raise NotFound()
        if location_id is not None:
            await _own_location(ctx, manager, location_id)
            equipment.location_id = location_id
        if category_id is not None:
            await _require_category(ctx, category_id)
            equipment.equipment_category_id = category_id
        if not isinstance(data.brand, UnsetType):
            equipment.brand = data.brand
        if not isinstance(data.model, UnsetType):
            equipment.model = data.model
        if not isinstance(data.serial_number, UnsetType):
            equipment.serial_number = data.serial_number
        if not isinstance(data.notes, UnsetType):
            equipment.notes = data.notes
        ctx.audit(
            "equipment.update",
            "equipment",
            equipment.id,
            organization_id=manager.organization_id,
        )
        await ctx.session.flush()
        summaries = await equipment_summaries(ctx.session, scope_of(manager), [equipment])
        view = to_equipment_view(equipment, summaries.get(equipment.id))
        return CommandResult(view.model_dump(mode="json"))

    return await run_command(actor, handler, idempotency=idem)


async def _own_location(
    ctx: CommandContext, manager: UserActor, location_id: uuid.UUID
) -> Location:
    location = (
        await ctx.session.execute(
            select(Location).where(
                Location.id == location_id,
                Location.customer_org_id == manager.organization_id,
            )
        )
    ).scalar_one_or_none()
    if location is None:
        raise NotFound()
    return location


async def _require_city(
    ctx: CommandContext, city_id: uuid.UUID, district_id: uuid.UUID | None
) -> City:
    city = await ctx.session.get(City, city_id)
    if city is None:
        raise ValidationFailed("Неизвестный город", field="city_id")
    if district_id is not None:
        district = await ctx.session.get(District, district_id)
        if district is None or district.city_id != city.id:
            raise ValidationFailed("Район не принадлежит городу", field="district_id")
    return city


async def _require_category(ctx: CommandContext, category_id: uuid.UUID) -> EquipmentCategory:
    category = await ctx.session.get(EquipmentCategory, category_id)
    if category is None:
        raise ValidationFailed("Неизвестная категория оборудования", field="equipment_category_id")
    return category
