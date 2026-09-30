import re
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, false, func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.scope import AccessScope
from app.db import session as db_session
from app.db.enums import ProviderProfileStatus
from app.db.models import (
    City,
    District,
    EquipmentCategory,
    Organization,
    ProviderBrandRestriction,
    ProviderCategory,
    ProviderProfile,
    ProviderServiceArea,
)
from app.modules.files import api as files
from app.modules.identity.api import normalize_inn
from app.modules.providers.views import (
    ProviderBrandRestrictionView,
    ProviderCatalogItemView,
    ProviderCategoryView,
    ProviderProfileView,
    ProviderPublicProfileView,
    ProviderServiceAreaView,
    ProviderSummaryView,
    to_brand_restriction_view,
    to_catalog_item_view,
    to_category_view,
    to_profile_view,
    to_provider_summary_view,
    to_public_profile_view,
    to_service_area_view,
)
from app.modules.reputation import api as reputation
from app.modules.trust.api import (
    CHECK_REPRESENTATIVE,
    CHECK_REQUISITES,
    active_checks,
    verification_badges,
    warranty_badges,
)

DEFAULT_LIMIT = 50


def _paginate[T](
    rows: list[T], limit: int, key: Callable[[T], uuid.UUID]
) -> tuple[list[T], uuid.UUID | None]:
    if len(rows) <= limit:
        return rows, None
    page = rows[:limit]
    return page, key(page[-1])


async def _categories(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[ProviderCategoryView]:
    rows = list(
        (
            await session.execute(
                select(EquipmentCategory)
                .join(
                    ProviderCategory,
                    ProviderCategory.equipment_category_id == EquipmentCategory.id,
                )
                .where(ProviderCategory.provider_org_id == organization_id)
                .order_by(EquipmentCategory.name)
            )
        ).scalars()
    )
    return [to_category_view(row) for row in rows]


async def _service_areas(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[ProviderServiceAreaView]:
    rows = list(
        (
            await session.execute(
                select(ProviderServiceArea, City, District)
                .join(City, City.id == ProviderServiceArea.city_id)
                .outerjoin(District, District.id == ProviderServiceArea.district_id)
                .where(ProviderServiceArea.provider_org_id == organization_id)
                .order_by(City.name, ProviderServiceArea.id)
            )
        ).all()
    )
    return [to_service_area_view(area, city, district) for area, city, district in rows]


async def _brand_restrictions(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[ProviderBrandRestrictionView]:
    rows = list(
        (
            await session.execute(
                select(ProviderBrandRestriction)
                .where(ProviderBrandRestriction.provider_org_id == organization_id)
                .order_by(ProviderBrandRestriction.brand)
            )
        ).scalars()
    )
    return [to_brand_restriction_view(row) for row in rows]


async def build_profile_view(
    session: AsyncSession, profile: ProviderProfile, org: Organization
) -> ProviderProfileView:
    await session.flush()
    if inspect(profile).expired_attributes:
        await session.refresh(profile)
    return to_profile_view(
        profile,
        org,
        categories=await _categories(session, org.id),
        service_areas=await _service_areas(session, org.id),
        brand_restrictions=await _brand_restrictions(session, org.id),
        verification=await verification_badges(session, org.id),
        rating=await reputation.get_rating_summary(session, org.id),
        appeal=await reputation.get_profile_appeal(session, profile.id),
    )


async def get_own_profile(scope: AccessScope) -> ProviderProfileView:
    if scope.side != "provider":
        raise Forbidden()
    async with db_session.transaction() as session:
        profile = (
            await session.execute(
                select(ProviderProfile).where(
                    ProviderProfile.organization_id == scope.organization_id
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound()
        org = await session.get(Organization, scope.organization_id)
        assert org is not None
        return await build_profile_view(session, profile, org)


async def get_public_profile(provider_org_id: uuid.UUID) -> ProviderPublicProfileView:
    async with db_session.transaction() as session:
        profile = (
            await session.execute(
                select(ProviderProfile).where(
                    ProviderProfile.organization_id == provider_org_id,
                    ProviderProfile.status == ProviderProfileStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound()
        org = await session.get(Organization, provider_org_id)
        assert org is not None
        rating = await reputation.get_rating_summary(session, org.id)
        return to_public_profile_view(
            profile,
            org,
            categories=await _categories(session, org.id),
            service_areas=await _service_areas(session, org.id),
            brand_restrictions=await _brand_restrictions(session, org.id),
            verification=await verification_badges(session, org.id),
            warranty_authorizations=await warranty_badges(session, org.id),
            rating=rating.average,
            rating_label=rating.label,
            reviews_count=rating.published_reviews_count,
            unique_customers=rating.unique_customers,
            gallery=await files.public_gallery(session, org.id),
            gallery_items=await files.public_gallery_items(session, org.id),
        )


MIN_SEARCH_LENGTH = 3
_INN_LENGTHS = (10, 12)


def _search_condition(q: str) -> ColumnElement[bool]:
    value = q.strip()
    digits = normalize_inn(value)
    if digits and digits == value.replace(" ", ""):
        if len(digits) not in _INN_LENGTHS:
            return false()
        return Organization.inn_normalized == digits
    if len(value) < MIN_SEARCH_LENGTH:
        raise ValidationFailed(
            f"Введите не меньше {MIN_SEARCH_LENGTH} символов названия или ИНН целиком",
            field="q",
        )
    words = _PUNCTUATION.sub(" ", value.lower()).split()
    if not words:
        return false()
    escaped = " ".join(words).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"% {escaped}%"
    return or_(*(_normalized_name(column).like(pattern, escape="\\") for column in _NAME_COLUMNS))


_PUNCTUATION = re.compile(r"[«»\"'.,()/–—-]+")
_SQL_PUNCTUATION = "[«»\"'.,()/–—-]+"
_NAME_COLUMNS = (Organization.display_name, Organization.legal_name)


def _normalized_name(column: Any) -> ColumnElement[str]:
    return " " + func.regexp_replace(func.lower(column), _SQL_PUNCTUATION, " ", "g")


async def count_catalog(
    *,
    category_id: uuid.UUID | None = None,
    city_id: uuid.UUID | None = None,
    district_id: uuid.UUID | None = None,
) -> int:
    async with db_session.transaction() as session:
        stmt = select(func.count(ProviderProfile.id)).where(
            ProviderProfile.status == ProviderProfileStatus.ACTIVE,
            ProviderProfile.accepting_new_requests.is_(True),
        )
        stmt = _apply_filters(stmt, category_id, city_id, district_id)
        return int((await session.execute(stmt)).scalar_one())


async def list_catalog(
    *,
    category_id: uuid.UUID | None = None,
    city_id: uuid.UUID | None = None,
    district_id: uuid.UUID | None = None,
    q: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[ProviderCatalogItemView], uuid.UUID | None]:
    condition = _search_condition(q) if q is not None and q.strip() else None
    async with db_session.transaction() as session:
        stmt = (
            select(ProviderProfile, Organization)
            .join(Organization, Organization.id == ProviderProfile.organization_id)
            .where(ProviderProfile.status == ProviderProfileStatus.ACTIVE)
            .order_by(ProviderProfile.organization_id)
            .limit(limit + 1)
        )
        stmt = _apply_filters(stmt, category_id, city_id, district_id)
        if condition is not None:
            stmt = stmt.where(condition)
        if cursor is not None:
            stmt = stmt.where(ProviderProfile.organization_id > cursor)
        rows = list((await session.execute(stmt)).all())
        page, next_cursor = _paginate(rows, limit, lambda row: row[1].id)
        ratings = await reputation.get_rating_summaries(session, [org.id for _, org in page])
        checks = await active_checks(session, [org.id for _, org in page])
        items = []
        for profile, org in page:
            rating = ratings[org.id]
            items.append(
                to_catalog_item_view(
                    profile,
                    org,
                    categories=await _categories(session, org.id),
                    service_areas=await _service_areas(session, org.id),
                    details_verified=CHECK_REQUISITES in checks.get(org.id, set()),
                    representative_verified=CHECK_REPRESENTATIVE in checks.get(org.id, set()),
                    rating=rating.average,
                    rating_label=rating.label,
                    reviews_count=rating.published_reviews_count,
                    unique_customers=rating.unique_customers,
                )
            )
        return items, next_cursor


async def get_provider_summaries(
    session: AsyncSession, provider_org_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ProviderSummaryView]:
    if not provider_org_ids:
        return {}
    rows = list(
        (
            await session.execute(select(Organization).where(Organization.id.in_(provider_org_ids)))
        ).scalars()
    )
    checks = await active_checks(session, [org.id for org in rows])
    return {org.id: to_provider_summary_view(org, checks.get(org.id, set())) for org in rows}


def _apply_filters[T: tuple[Any, ...]](
    stmt: Select[T],
    category_id: uuid.UUID | None,
    city_id: uuid.UUID | None,
    district_id: uuid.UUID | None,
) -> Select[T]:
    if category_id is not None:
        stmt = stmt.where(
            select(ProviderCategory.id)
            .where(
                ProviderCategory.provider_org_id == ProviderProfile.organization_id,
                ProviderCategory.equipment_category_id == category_id,
            )
            .exists()
        )
    if city_id is not None:
        area_filter = and_(
            ProviderServiceArea.provider_org_id == ProviderProfile.organization_id,
            ProviderServiceArea.city_id == city_id,
            _territory_condition(district_id),
        )
        stmt = stmt.where(select(ProviderServiceArea.id).where(area_filter).exists())
    return stmt


def _territory_condition(district_id: uuid.UUID | None) -> ColumnElement[bool]:
    whole_city = ProviderServiceArea.district_id.is_(None)
    if district_id is None:
        return whole_city
    return or_(whole_city, ProviderServiceArea.district_id == district_id)


async def find_matching_providers(
    category_id: uuid.UUID,
    city_id: uuid.UUID,
    district_id: uuid.UUID | None = None,
    brand: str | None = None,
    *,
    session: AsyncSession | None = None,
) -> list[uuid.UUID]:
    if session is not None:
        return await _find_matching(session, category_id, city_id, district_id, brand)
    async with db_session.transaction() as own:
        return await _find_matching(own, category_id, city_id, district_id, brand)


async def _find_matching(
    session: AsyncSession,
    category_id: uuid.UUID,
    city_id: uuid.UUID,
    district_id: uuid.UUID | None,
    brand: str | None,
) -> list[uuid.UUID]:
    stmt = (
        select(ProviderProfile.organization_id)
        .where(
            ProviderProfile.status == ProviderProfileStatus.ACTIVE,
            ProviderProfile.accepting_new_requests.is_(True),
        )
        .order_by(ProviderProfile.organization_id)
    )
    stmt = _apply_filters(stmt, category_id, city_id, district_id)
    candidates = list((await session.execute(stmt)).scalars())
    if not candidates:
        return []
    restrictions: dict[uuid.UUID, set[str]] = {}
    for provider_org_id, restricted_brand in (
        await session.execute(
            select(ProviderBrandRestriction.provider_org_id, ProviderBrandRestriction.brand).where(
                ProviderBrandRestriction.provider_org_id.in_(candidates),
                ProviderBrandRestriction.equipment_category_id == category_id,
            )
        )
    ).all():
        restrictions.setdefault(provider_org_id, set()).add(restricted_brand.strip().casefold())
    normalized = (brand or "").strip().casefold()
    return [
        org_id
        for org_id in candidates
        if org_id not in restrictions or normalized in restrictions[org_id]
    ]


async def list_profiles_for_operator(
    actor: Actor,
    *,
    status: str | None = None,
    cursor: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[ProviderProfileView], uuid.UUID | None]:
    from app.modules.trust.api import require_operator

    require_operator(actor)
    async with db_session.transaction() as session:
        stmt = (
            select(ProviderProfile, Organization)
            .join(Organization, Organization.id == ProviderProfile.organization_id)
            .order_by(ProviderProfile.id)
            .limit(limit + 1)
        )
        if status is not None:
            stmt = stmt.where(ProviderProfile.status == status)
        if cursor is not None:
            stmt = stmt.where(ProviderProfile.id > cursor)
        rows = list((await session.execute(stmt)).all())
        page, next_cursor = _paginate(rows, limit, lambda row: row[0].id)
        return [await build_profile_view(session, p, o) for p, o in page], next_cursor
