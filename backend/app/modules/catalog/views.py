from dataclasses import asdict
from datetime import date, datetime

from pydantic import BaseModel

from app.core import ids
from app.db.enums import VisibilityClass
from app.db.models import City, District, Equipment, EquipmentCategory, Location
from app.modules.catalog.summary import EquipmentSummary


class DistrictView(BaseModel):
    id: str
    name: str


class CityView(BaseModel):
    id: str
    name: str
    region: str | None
    timezone: str
    districts: list[DistrictView]


class PhotoTemplateSlotView(BaseModel):
    code: str
    label: str
    required: bool
    visibility_class: VisibilityClass


class EquipmentCategoryView(BaseModel):
    id: str
    code: str
    name: str
    photo_template: list[PhotoTemplateSlotView]


class LocationView(BaseModel):
    id: str
    name: str
    city_id: str
    district_id: str | None
    address: str
    timezone: str
    contact_name: str | None
    contact_phone: str | None
    created_at: datetime
    equipment_count: int | None = None


class EquipmentBindingSummaryView(BaseModel):
    id: str
    status: str
    basis: str
    is_contact_only: bool
    provider_name: str | None = None
    valid_until: date | None = None
    guarantor_kind: str | None = None
    guarantor_name: str | None = None
    provider_has_crm: bool = False
    contact_phone: str | None = None
    guarantor_stated_by_provider: bool = False
    warranty_authorization_id: str | None = None


class EquipmentActiveRequestView(BaseModel):
    id: str
    request_number: int
    status: str


class EquipmentView(BaseModel):
    id: str
    location_id: str
    equipment_category_id: str
    brand: str | None
    model: str | None
    serial_number: str | None
    notes: str | None
    created_at: datetime
    category_code: str | None = None
    category_name: str | None = None
    location_name: str | None = None
    binding: EquipmentBindingSummaryView | None = None
    active_request: EquipmentActiveRequestView | None = None
    has_nameplate_photo: bool = False


def to_city_view(city: City, districts: list[District]) -> CityView:
    return CityView(
        id=ids.encode("city", city.id),
        name=city.name,
        region=city.region,
        timezone=city.timezone,
        districts=[DistrictView(id=ids.encode("district", d.id), name=d.name) for d in districts],
    )


def to_category_view(category: EquipmentCategory) -> EquipmentCategoryView:
    return EquipmentCategoryView(
        id=ids.encode("category", category.id),
        code=category.code,
        name=category.name,
        photo_template=category.photo_template,
    )


def to_location_view(location: Location, *, equipment_count: int | None = None) -> LocationView:
    return LocationView(
        id=ids.encode("location", location.id),
        name=location.name,
        city_id=ids.encode("city", location.city_id),
        district_id=ids.encode_opt("district", location.district_id),
        address=location.address,
        timezone=location.timezone,
        contact_name=location.contact_name,
        contact_phone=location.contact_phone,
        created_at=location.created_at,
        equipment_count=equipment_count,
    )


def to_equipment_view(
    equipment: Equipment, summary: EquipmentSummary | None = None
) -> EquipmentView:
    extra = summary or EquipmentSummary()
    return EquipmentView(
        id=ids.encode("equipment", equipment.id),
        location_id=ids.encode("location", equipment.location_id),
        equipment_category_id=ids.encode("category", equipment.equipment_category_id),
        brand=equipment.brand,
        model=equipment.model,
        serial_number=equipment.serial_number,
        notes=equipment.notes,
        created_at=equipment.created_at,
        category_code=extra.category_code,
        category_name=extra.category_name,
        location_name=extra.location_name,
        binding=(
            EquipmentBindingSummaryView(**asdict(extra.binding))
            if extra.binding is not None
            else None
        ),
        active_request=(
            EquipmentActiveRequestView(**asdict(extra.active_request))
            if extra.active_request is not None
            else None
        ),
        has_nameplate_photo=extra.has_nameplate_photo,
    )
