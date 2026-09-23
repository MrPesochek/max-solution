from datetime import datetime

from pydantic import BaseModel

from app.core import ids
from app.db.models import (
    City,
    District,
    EquipmentCategory,
    Organization,
    ProviderBrandRestriction,
    ProviderProfile,
    ProviderServiceArea,
)
from app.infra.config import get_settings
from app.modules.files.api import GalleryItemView
from app.modules.reputation.api import ProfileAppealView, RatingSummaryView
from app.modules.trust.api import (
    CHECK_REPRESENTATIVE,
    CHECK_REQUISITES,
    VerificationBadgeView,
    WarrantyAuthorizationView,
)

SPECIALIZATION_DISCLAIMER = "Со слов исполнителя"


class ProviderCategoryView(BaseModel):
    id: str
    code: str
    name: str


class ProviderServiceAreaView(BaseModel):
    city_id: str
    city_name: str
    district_id: str | None
    district_name: str | None


class ProviderBrandRestrictionView(BaseModel):
    equipment_category_id: str
    brand: str


class ProviderProfileView(BaseModel):
    """Собственный профиль исполнителя: то, что видит его администратор."""

    id: str
    organization_id: str
    name: str
    provider_kind: str
    legal_form: str | None
    inn: str | None
    contact_name: str | None
    representative_position: str | None = None
    contact_phone: str | None
    contact_email: str | None
    status: str
    status_reason: str | None
    accepting_new_requests: bool
    visit_terms: str | None
    visit_price_from_minor: int | None = None
    can_provide_documents: bool
    description: str | None
    specialization_disclaimer: str
    categories: list[ProviderCategoryView]
    service_areas: list[ProviderServiceAreaView]
    brand_restrictions: list[ProviderBrandRestrictionView]
    verification: list[VerificationBadgeView]
    portfolio_max_images: int
    rating: float | None = None
    rating_label: str | None = None
    reviews_count: int = 0
    unique_customers: int = 0
    appeal: ProfileAppealView | None = None
    created_at: datetime
    updated_at: datetime


class ProviderPublicProfileView(BaseModel):
    """Каталожная карточка: раздельные признаки проверки, без единого флага «проверен»."""

    id: str
    name: str
    provider_kind: str
    legal_form: str | None
    categories: list[ProviderCategoryView]
    service_areas: list[ProviderServiceAreaView]
    brand_restrictions: list[ProviderBrandRestrictionView]
    visit_terms: str | None
    visit_price_from_minor: int | None = None
    can_provide_documents: bool
    description: str | None
    specialization_disclaimer: str
    accepting_new_requests: bool
    verification: list[VerificationBadgeView]
    warranty_authorizations: list[WarrantyAuthorizationView]
    rating: float | None = None
    rating_label: str | None = None
    reviews_count: int = 0
    unique_customers: int = 0
    gallery: list[str] = []
    gallery_items: list[GalleryItemView] = []


class ProviderSummaryView(BaseModel):
    """Краткая карточка исполнителя для встраивания в чужие представления (например, оффер)."""

    id: str
    display_name: str
    verification_marks: list[str]


class ProviderCatalogItemView(BaseModel):
    id: str
    name: str
    provider_kind: str
    categories: list[ProviderCategoryView]
    service_areas: list[ProviderServiceAreaView]
    accepting_new_requests: bool
    details_verified: bool
    representative_verified: bool
    rating: float | None = None
    rating_label: str | None = None
    reviews_count: int = 0
    unique_customers: int = 0


def to_category_view(category: EquipmentCategory) -> ProviderCategoryView:
    return ProviderCategoryView(
        id=ids.encode("category", category.id), code=category.code, name=category.name
    )


def to_service_area_view(
    area: ProviderServiceArea, city: City, district: District | None
) -> ProviderServiceAreaView:
    return ProviderServiceAreaView(
        city_id=ids.encode("city", city.id),
        city_name=city.name,
        district_id=ids.encode_opt("district", area.district_id),
        district_name=district.name if district is not None else None,
    )


def to_brand_restriction_view(row: ProviderBrandRestriction) -> ProviderBrandRestrictionView:
    return ProviderBrandRestrictionView(
        equipment_category_id=ids.encode("category", row.equipment_category_id), brand=row.brand
    )


def to_profile_view(
    profile: ProviderProfile,
    org: Organization,
    *,
    categories: list[ProviderCategoryView],
    service_areas: list[ProviderServiceAreaView],
    brand_restrictions: list[ProviderBrandRestrictionView],
    verification: list[VerificationBadgeView],
    rating: RatingSummaryView | None = None,
    appeal: ProfileAppealView | None = None,
) -> ProviderProfileView:
    return ProviderProfileView(
        id=ids.encode("provider_profile", profile.id),
        organization_id=ids.encode("organization", org.id),
        name=org.display_name,
        provider_kind=profile.provider_kind,
        legal_form=org.legal_form,
        inn=org.inn_normalized,
        contact_name=org.contact_name,
        representative_position=org.representative_position,
        contact_phone=org.contact_phone,
        contact_email=org.contact_email,
        status=profile.status,
        status_reason=profile.status_reason,
        accepting_new_requests=profile.accepting_new_requests,
        visit_terms=profile.visit_terms,
        visit_price_from_minor=profile.visit_price_from_minor,
        can_provide_documents=profile.can_provide_documents,
        description=profile.description,
        specialization_disclaimer=SPECIALIZATION_DISCLAIMER,
        categories=categories,
        service_areas=service_areas,
        brand_restrictions=brand_restrictions,
        verification=verification,
        portfolio_max_images=get_settings().portfolio_max_images,
        rating=rating.average if rating is not None else None,
        rating_label=rating.label if rating is not None else None,
        reviews_count=rating.published_reviews_count if rating is not None else 0,
        unique_customers=rating.unique_customers if rating is not None else 0,
        appeal=appeal,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def to_public_profile_view(
    profile: ProviderProfile,
    org: Organization,
    *,
    categories: list[ProviderCategoryView],
    service_areas: list[ProviderServiceAreaView],
    brand_restrictions: list[ProviderBrandRestrictionView],
    verification: list[VerificationBadgeView],
    warranty_authorizations: list[WarrantyAuthorizationView],
    rating: float | None = None,
    rating_label: str | None = None,
    reviews_count: int = 0,
    unique_customers: int = 0,
    gallery: list[str] | None = None,
    gallery_items: list[GalleryItemView] | None = None,
) -> ProviderPublicProfileView:
    return ProviderPublicProfileView(
        id=ids.encode("organization", org.id),
        name=org.display_name,
        provider_kind=profile.provider_kind,
        legal_form=org.legal_form,
        categories=categories,
        service_areas=service_areas,
        brand_restrictions=brand_restrictions,
        visit_terms=profile.visit_terms,
        visit_price_from_minor=profile.visit_price_from_minor,
        can_provide_documents=profile.can_provide_documents,
        description=profile.description,
        specialization_disclaimer=SPECIALIZATION_DISCLAIMER,
        accepting_new_requests=profile.accepting_new_requests,
        verification=verification,
        warranty_authorizations=warranty_authorizations,
        rating=rating,
        rating_label=rating_label,
        reviews_count=reviews_count,
        unique_customers=unique_customers,
        gallery=gallery or [],
        gallery_items=gallery_items or [],
    )


def to_catalog_item_view(
    profile: ProviderProfile,
    org: Organization,
    *,
    categories: list[ProviderCategoryView],
    service_areas: list[ProviderServiceAreaView],
    details_verified: bool,
    representative_verified: bool,
    rating: float | None = None,
    rating_label: str | None = None,
    reviews_count: int = 0,
    unique_customers: int = 0,
) -> ProviderCatalogItemView:
    return ProviderCatalogItemView(
        id=ids.encode("organization", org.id),
        name=org.display_name,
        provider_kind=profile.provider_kind,
        categories=categories,
        service_areas=service_areas,
        accepting_new_requests=profile.accepting_new_requests,
        details_verified=details_verified,
        representative_verified=representative_verified,
        rating=rating,
        rating_label=rating_label,
        reviews_count=reviews_count,
        unique_customers=unique_customers,
    )


def to_provider_summary_view(org: Organization, checks: set[str]) -> ProviderSummaryView:
    """`checks` — действующие признаки из trust (с учётом срока проверки)."""
    marks = [kind for kind in (CHECK_REQUISITES, CHECK_REPRESENTATIVE) if kind in checks]
    return ProviderSummaryView(
        id=ids.encode("organization", org.id),
        display_name=org.display_name,
        verification_marks=marks,
    )
