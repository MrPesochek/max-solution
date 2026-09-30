from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.adapters.app_api.deps import CurrentSession
from app.adapters.app_api.schemas import Page, page_of
from app.adapters.http.errors import STANDARD_ERROR_RESPONSES
from app.adapters.http.ratelimit import limit_provider_search
from app.core import ids
from app.modules.providers import api as providers
from app.modules.providers.api import ProviderCatalogItemView, ProviderPublicProfileView
from app.modules.reputation import api as reputation
from app.modules.reputation.api import PublicReviewView

router = APIRouter(prefix="/providers", tags=["providers"], responses=STANDARD_ERROR_RESPONSES)


class ProviderCountView(BaseModel):
    count: int


@router.get("", response_model=Page[ProviderCatalogItemView])
async def list_providers(
    session: CurrentSession,
    category_id: str | None = None,
    city_id: str | None = None,
    district_id: str | None = None,
    q: Annotated[
        str | None,
        Query(
            max_length=100,
            description=(
                "Название сервиса (начало слова, от 3 символов) или ИНН целиком. "
                "По части ИНН не ищет; только активные профили."
            ),
        ),
    ] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ProviderCatalogItemView]:
    if q is not None and q.strip():
        limit_provider_search(str(session.session_id))
    items, next_cursor = await providers.list_catalog(
        category_id=ids.decode("category", category_id) if category_id else None,
        city_id=ids.decode("city", city_id) if city_id else None,
        district_id=ids.decode("district", district_id) if district_id else None,
        q=q,
        cursor=ids.decode("organization", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "organization", next_cursor)


@router.get("/count", response_model=ProviderCountView)
async def count_providers(
    session: CurrentSession,
    category_id: str | None = None,
    city_id: str | None = None,
    district_id: str | None = None,
) -> ProviderCountView:
    count = await providers.count_catalog(
        category_id=ids.decode("category", category_id) if category_id else None,
        city_id=ids.decode("city", city_id) if city_id else None,
        district_id=ids.decode("district", district_id) if district_id else None,
    )
    return ProviderCountView(count=count)


@router.get("/{provider_id}", response_model=ProviderPublicProfileView)
async def get_provider(session: CurrentSession, provider_id: str) -> ProviderPublicProfileView:
    return await providers.get_public_profile(ids.decode("organization", provider_id))


@router.get("/{provider_id}/reviews", response_model=Page[PublicReviewView])
async def list_provider_reviews(
    session: CurrentSession,
    provider_id: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[PublicReviewView]:
    items, next_cursor = await reputation.list_published_reviews(
        ids.decode("organization", provider_id),
        cursor=ids.decode("review", cursor) if cursor else None,
        limit=limit,
    )
    return page_of(items, "review", next_cursor)
