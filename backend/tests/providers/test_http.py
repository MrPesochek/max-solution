from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core import ids
from app.db import session as db_session
from app.db.models import ProviderRatingAggregate
from app.modules.providers import api as providers
from tests.providers.conftest import auth, idem_header
from tests.support import PROVIDER_INN, idem, make_customer, make_provider, org_id, session_token

pytestmark = pytest.mark.usefixtures("clean_db")


async def _directory_ids(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    cities = (await client.get("/directories/cities", headers=headers)).json()["items"]
    categories = (await client.get("/directories/equipment-categories", headers=headers)).json()[
        "items"
    ]
    return categories[0]["id"], cities[0]["id"]


async def test_provider_profile_lifecycle_over_http(client: AsyncClient) -> None:
    provider = await make_provider("http-prof", with_category=False, with_area=False)
    headers = auth(await session_token(provider.admin), org_id(provider.admin))
    category_id, city_id = await _directory_ids(client, headers)

    current = await client.get("/provider-profile", headers=headers)
    assert current.status_code == 200
    assert current.json()["status"] == "draft"
    assert [b["confirmed"] for b in current.json()["verification"]] == [False, False]

    patched = await client.patch(
        "/provider-profile",
        headers={**headers, **idem_header("p1")},
        json={
            "inn": PROVIDER_INN,
            "contact_phone": "+79990000000",
            "visit_terms": "Выезд в день обращения",
            "can_provide_documents": True,
            "category_ids": [category_id],
            "service_areas": [{"city_id": city_id, "district_ids": []}],
            "brand_restrictions": [{"equipment_category_id": category_id, "brands": ["Бренд"]}],
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["visit_terms"] == "Выезд в день обращения"

    blocked = await client.post(
        "/provider-profile/accepting",
        headers={**headers, **idem_header("p2")},
        json={"accepting": True},
    )
    assert blocked.status_code == 409

    submitted = await client.post(
        "/provider-profile/submit", headers={**headers, **idem_header("p3")}
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_review"

    cases = await client.get("/verification", headers=headers)
    assert cases.status_code == 200
    assert {case["check_kind"] for case in cases.json()} == {"requisites", "representative"}


async def test_catalog_and_public_profile_over_http(client: AsyncClient) -> None:
    provider = await make_provider("http-cat", status="active", accepting=True, verified=True)
    draft = await make_provider("http-cat-draft", inn=None)
    customer = await make_customer("http-cat-c")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))

    catalog = await client.get("/providers", headers=headers)
    assert catalog.status_code == 200
    assert [item["id"] for item in catalog.json()["items"]] == [
        ids.encode("organization", provider.organization_id)
    ]

    public = await client.get(
        f"/providers/{ids.encode('organization', provider.organization_id)}", headers=headers
    )
    assert public.status_code == 200
    body = public.json()
    assert body["rating"] is None
    assert "inn" not in body
    assert len(body["verification"]) == 2

    hidden = await client.get(
        f"/providers/{ids.encode('organization', draft.organization_id)}", headers=headers
    )
    assert hidden.status_code == 404


async def test_customer_has_no_provider_profile_over_http(client: AsyncClient) -> None:
    customer = await make_customer("http-prof-c")
    headers = auth(await session_token(customer.manager), org_id(customer.manager))
    assert (await client.get("/provider-profile", headers=headers)).status_code == 403


async def test_verification_information_over_http(client: AsyncClient) -> None:
    provider = await make_provider("http-ver")
    await providers.submit_for_review(provider.admin, idem=idem("http-ver-1"))
    headers = auth(await session_token(provider.admin), org_id(provider.admin))

    response = await client.post(
        "/verification",
        headers={**headers, **idem_header("v1")},
        json={"note": "телефон приёмной из реестра", "attachment_refs": ["file-1"]},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


async def test_catalog_item_carries_rating_counters_like_public_profile(
    client: AsyncClient,
) -> None:
    provider = await make_provider("http-cat-r", status="active", accepting=True, verified=True)
    customer = await make_customer("http-cat-rc")
    async with db_session.transaction() as session:
        session.add(
            ProviderRatingAggregate(
                provider_org_id=provider.organization_id,
                average_rating=Decimal("4.6"),
                unique_reviewer_orgs_count=4,
                published_reviews_count=7,
            )
        )
    headers = auth(await session_token(customer.manager), org_id(customer.manager))

    item = (await client.get("/providers", headers=headers)).json()["items"][0]
    public = (await client.get(f"/providers/{item['id']}", headers=headers)).json()
    assert (item["rating"], item["reviews_count"], item["unique_customers"]) == (4.6, 7, 4)
    for key in ("rating", "rating_label", "reviews_count", "unique_customers"):
        assert item[key] == public[key]
